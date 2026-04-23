"""
Модуль самоконтроля (Reflection) для проверки успешности выполненных агентом действий.

Принцип работы:
После выполнения каждого действия (клик, ввод текста, запуск команды) агент должен проверить его успешность.
Для этого используется ReflectionChecker, который выбирает подходящую модель для проверки и возвращает результат.
"""

import os
import logging
import base64
from typing import Dict, Optional
from enum import Enum

from core.model_selector import get_selector
from connectors.llm_client_distributed import generate_sync

logger = logging.getLogger("ZORA.ReflectionChecker")

class ReflectionType(Enum):
    """Типы проверок самоконтроля"""
    VISUAL = "visual"      # Визуальная проверка (скриншоты до/после)
    TEXT = "text"          # Текстовая проверка (анализ вывода)
    CODE = "code"          # Проверка выполнения кода

class ReflectionChecker:
    """Класс для проверки успешности действий агентов"""
    
    def __init__(self):
        self.selector = get_selector()
        self.confidence_threshold = float(os.getenv("REFLECTION_CONFIDENCE_THRESHOLD", "0.7"))
        self.max_retries = int(os.getenv("REFLECTION_MAX_RETRIES", "3"))
        self.visual_timeout = int(os.getenv("REFLECTION_VISUAL_TIMEOUT", "30"))
        
        logger.info(f"Инициализация ReflectionChecker с порогом уверенности {self.confidence_threshold}")
    
    def check_visual(self, screenshot_before: bytes, screenshot_after: bytes, 
                    expected_description: str) -> Dict[str, any]:
        """
        Проверяет успешность визуального действия (клик, ввод текста).
        
        Args:
            screenshot_before: Скриншот до действия (bytes)
            screenshot_after: Скриншот после действия (bytes)
            expected_description: Описание ожидаемого результата
            
        Returns:
            Словарь с результатом проверки: {'success': bool, 'reason': str, 'confidence': float}
        """
        try:
            # Кодируем изображения в base64
            before_b64 = base64.b64encode(screenshot_before).decode('utf-8')
            after_b64 = base64.b64encode(screenshot_after).decode('utf-8')
            
            # Выбираем модель для зрения
            model_info = self.selector.select_vision()
            if model_info["provider"] is None:
                logger.error("Vision модель недоступна для визуальной проверки")
                return {
                    "success": False,
                    "reason": "Vision модель недоступна",
                    "confidence": 0.0
                }
            
            # Формируем промпт для vision-модели
            prompt = f"""
            Сравни два скриншота: до и после действия.
            
            Ожидаемый результат: {expected_description}
            
            Проанализируй изменения и определи:
            1. Успешно ли выполнено действие?
            2. Появился ли ожидаемый элемент/изменение?
            3. Есть ли ошибки или неожиданные изменения?
            
            Ответь в формате JSON:
            {{
                "success": true/false,
                "reason": "краткое объяснение",
                "confidence": 0.0-1.0
            }}
            """
            
            # Для vision-моделей нужно специальное форматирование
            if model_info["provider"] == "ollama":
                # Ollama vision модели принимают изображения через промпт
                vision_prompt = f"data:image/png;base64,{before_b64}\ndata:image/png;base64,{after_b64}\n{prompt}"
                response = generate_sync(
                    prompt=vision_prompt,
                    task_type="vision",
                    temperature=0.1,
                    system_prompt="Ты эксперт по анализу скриншотов. Анализируй изменения на изображениях."
                )
            else:
                # Для других провайдеров (если будут поддерживать vision)
                response = generate_sync(
                    prompt=prompt,
                    task_type="vision",
                    temperature=0.1,
                    system_prompt="Ты эксперт по анализу скриншотов. Анализируй изменения на изображениях."
                )
            
            # Парсим ответ
            import json
            try:
                # Ищем JSON в ответе
                import re
                json_match = re.search(r'\{.*\}', response, re.DOTALL)
                if json_match:
                    result = json.loads(json_match.group())
                else:
                    # Если не нашли JSON, анализируем текстовый ответ
                    result = self._parse_text_response(response)
                
                # Проверяем уверенность
                confidence = result.get("confidence", 0.0)
                if confidence < self.confidence_threshold:
                    logger.warning(f"Низкая уверенность визуальной проверки: {confidence}")
                    result["success"] = False
                    result["reason"] = f"Низкая уверенность ({confidence})"
                
                logger.info(f"Визуальная проверка: успех={result['success']}, уверенность={confidence}")
                return result
                
            except json.JSONDecodeError:
                logger.error(f"Ошибка парсинга JSON ответа: {response}")
                return {
                    "success": False,
                    "reason": "Ошибка анализа ответа модели",
                    "confidence": 0.0
                }
                
        except Exception as e:
            logger.error(f"Ошибка визуальной проверки: {e}")
            return {
                "success": False,
                "reason": f"Ошибка проверки: {str(e)}",
                "confidence": 0.0
            }
    
    def check_text(self, text_output: str, expected_pattern: str) -> Dict[str, any]:
        """
        Проверяет текстовый вывод на наличие ожидаемых признаков успеха.
        
        Args:
            text_output: Текстовый вывод для анализа
            expected_pattern: Описание ожидаемого результата или паттерн
            
        Returns:
            Словарь с результатом проверки
        """
        try:
            # Выбираем модель для текстового анализа
            model_info = self.selector.select_planner("Анализ текстового вывода")
            
            # Формируем промпт
            prompt = f"""
            Проанализируй текстовый вывод и определи, успешно ли выполнено действие.
            
            Текстовый вывод:
            ```
            {text_output}
            ```
            
            Ожидаемый результат: {expected_pattern}
            
            Проанализируй и определи:
            1. Содержит ли вывод признаки успеха?
            2. Есть ли ошибки или предупреждения?
            3. Соответствует ли вывод ожидаемому результату?
            
            Ответь в формате JSON:
            {{
                "success": true/false,
                "reason": "краткое объяснение",
                "confidence": 0.0-1.0,
                "errors_found": ["список ошибок, если есть"],
                "success_indicators": ["список признаков успеха, если есть"]
            }}
            """
            
            response = generate_sync(
                prompt=prompt,
                task_type="planner",
                temperature=0.1,
                system_prompt="Ты эксперт по анализу текстовых выводов. Определяй успешность выполнения действий."
            )
            
            # Парсим ответ
            import json
            try:
                import re
                json_match = re.search(r'\{.*\}', response, re.DOTALL)
                if json_match:
                    result = json.loads(json_match.group())
                else:
                    result = self._parse_text_response(response)
                
                # Проверяем уверенность
                confidence = result.get("confidence", 0.0)
                if confidence < self.confidence_threshold:
                    logger.warning(f"Низкая уверенность текстовой проверки: {confidence}")
                    result["success"] = False
                    result["reason"] = f"Низкая уверенность ({confidence})"
                
                logger.info(f"Текстовая проверка: успех={result['success']}, уверенность={confidence}")
                return result
                
            except json.JSONDecodeError:
                logger.error(f"Ошибка парсинга JSON ответа: {response}")
                return {
                    "success": False,
                    "reason": "Ошибка анализа ответа модели",
                    "confidence": 0.0
                }
                
        except Exception as e:
            logger.error(f"Ошибка текстовой проверки: {e}")
            return {
                "success": False,
                "reason": f"Ошибка проверки: {str(e)}",
                "confidence": 0.0
            }
    
    def check_code_execution(self, stdout: str, stderr: str) -> Dict[str, any]:
        """
        Определяет, успешно ли выполнился код.
        
        Args:
            stdout: Стандартный вывод
            stderr: Стандартный вывод ошибок
            
        Returns:
            Словарь с результатом проверки
        """
        try:
            # Выбираем модель для анализа кода
            model_info = self.selector.select_coder()
            
            # Формируем промпт
            prompt = f"""
            Проанализируй вывод выполнения кода и определи, успешно ли он выполнился.
            
            Стандартный вывод (stdout):
            ```
            {stdout}
            ```
            
            Вывод ошибок (stderr):
            ```
            {stderr}
            ```
            
            Проанализируй и определи:
            1. Успешно ли выполнился код?
            2. Есть ли ошибки компиляции или выполнения?
            3. Получен ли ожидаемый результат?
            
            Ответь в формате JSON:
            {{
                "success": true/false,
                "reason": "краткое объяснение",
                "confidence": 0.0-1.0,
                "error_type": "тип ошибки, если есть",
                "suggestions": ["предложения по исправлению, если есть"]
            }}
            """
            
            response = generate_sync(
                prompt=prompt,
                task_type="coder",
                temperature=0.1,
                system_prompt="Ты эксперт по анализу выполнения кода. Определяй успешность выполнения программ."
            )
            
            # Парсим ответ
            import json
            try:
                import re
                json_match = re.search(r'\{.*\}', response, re.DOTALL)
                if json_match:
                    result = json.loads(json_match.group())
                else:
                    result = self._parse_text_response(response)
                
                # Проверяем уверенность
                confidence = result.get("confidence", 0.0)
                if confidence < self.confidence_threshold:
                    logger.warning(f"Низкая уверенность проверки кода: {confidence}")
                    result["success"] = False
                    result["reason"] = f"Низкая уверенность ({confidence})"
                
                logger.info(f"Проверка выполнения кода: успех={result['success']}, уверенность={confidence}")
                return result
                
            except json.JSONDecodeError:
                logger.error(f"Ошибка парсинга JSON ответа: {response}")
                return {
                    "success": False,
                    "reason": "Ошибка анализа ответа модели",
                    "confidence": 0.0
                }
                
        except Exception as e:
            logger.error(f"Ошибка проверки выполнения кода: {e}")
            return {
                "success": False,
                "reason": f"Ошибка проверки: {str(e)}",
                "confidence": 0.0
            }
    
    def _parse_text_response(self, response: str) -> Dict[str, any]:
        """
        Парсит текстовый ответ модели в структурированный формат.
        
        Args:
            response: Текстовый ответ модели
            
        Returns:
            Словарь с результатом
        """
        response_lower = response.lower()
        
        # Определяем успешность по ключевым словам
        success_keywords = ["успех", "успешно", "да", "true", "yes", "ок", "готово", "выполнено"]
        failure_keywords = ["ошибка", "неудача", "нет", "false", "no", "провал", "сбой"]
        
        success_count = sum(1 for kw in success_keywords if kw in response_lower)
        failure_count = sum(1 for kw in failure_keywords if kw in response_lower)
        
        success = success_count > failure_count
        confidence = 0.7 if success_count > 0 else 0.3
        
        return {
            "success": success,
            "reason": response[:200],  # Первые 200 символов как причина
            "confidence": confidence
        }
    
    def check_with_retry(self, check_type: ReflectionType, *args, **kwargs) -> Dict[str, any]:
        """
        Выполняет проверку с повторными попытками.
        
        Args:
            check_type: Тип проверки
            *args, **kwargs: Аргументы для проверки
            
        Returns:
            Результат проверки после всех попыток
        """
        for attempt in range(self.max_retries):
            logger.info(f"Попытка проверки {attempt + 1}/{self.max_retries}")
            
            if check_type == ReflectionType.VISUAL:
                result = self.check_visual(*args, **kwargs)
            elif check_type == ReflectionType.TEXT:
                result = self.check_text(*args, **kwargs)
            elif check_type == ReflectionType.CODE:
                result = self.check_code_execution(*args, **kwargs)
            else:
                raise ValueError(f"Неизвестный тип проверки: {check_type}")
            
            if result.get("success", False):
                logger.info(f"Проверка успешна на попытке {attempt + 1}")
                return result
            
            logger.warning(f"Проверка неуспешна на попытке {attempt + 1}: {result.get('reason', '')}")
            
            # Если это не последняя попытка, ждём перед следующей
            if attempt < self.max_retries - 1:
                import time
                time.sleep(1)  # Ждём 1 секунду перед следующей попыткой
        
        logger.error(f"Все {self.max_retries} попыток проверки неуспешны")
        return {
            "success": False,
            "reason": f"Все {self.max_retries} попыток проверки неуспешны",
            "confidence": 0.0
        }


# Создаём глобальный экземпляр ReflectionChecker
_checker = None

def get_reflection_checker() -> ReflectionChecker:
    """Возвращает глобальный экземпляр ReflectionChecker"""
    global _checker
    if _checker is None:
        _checker = ReflectionChecker()
    return _checker