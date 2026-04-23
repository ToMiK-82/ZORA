"""
Эскалация сложных задач к большим моделям (Claude, GPT).
"""

import logging
from typing import Dict, Any, Optional
from enum import Enum


class EscalationLevel(Enum):
    """Уровни эскалации."""
    LOCAL = "local"  # Локальные модели Ollama
    CLOUDE_SMALL = "claude_small"  # Claude Haiku
    CLOUDE_MEDIUM = "claude_medium"  # Claude Sonnet
    CLOUDE_LARGE = "claude_large"  # Claude Opus
    GPT_SMALL = "gpt_small"  # GPT-3.5
    GPT_LARGE = "gpt_large"  # GPT-4


class EscalationWorkflow:
    """Workflow для эскалации сложных задач к более мощным моделям."""

    def __init__(self):
        self.logger = logging.getLogger("zora.workflow.escalation")
        # Настройки эскалации
        self.escalation_thresholds = {
            "complexity": 0.7,  # Порог сложности для эскалации
            "confidence": 0.3,  # Порог уверенности для эскалации
            "retry_count": 2,   # Количество попыток перед эскалацией
        }

    def _assess_complexity(self, query: str, context: str) -> float:
        """
        Оценивает сложность запроса.

        Args:
            query: Пользовательский запрос
            context: Контекст из памяти

        Returns:
            Оценка сложности от 0 до 1
        """
        # Простая эвристика: длина запроса + наличие ключевых слов сложности
        complexity = 0.0
        
        # Учитываем длину запроса
        query_length = len(query)
        if query_length > 500:
            complexity += 0.3
        elif query_length > 200:
            complexity += 0.2
        elif query_length > 100:
            complexity += 0.1
        
        # Ключевые слова сложных задач
        complex_keywords = [
            "анализ", "прогноз", "стратегия", "оптимизация", 
            "рекомендация", "сравнение", "оценка", "планирование",
            "отчёт", "статистика", "тренд", "законодательство"
        ]
        
        query_lower = query.lower()
        for keyword in complex_keywords:
            if keyword in query_lower:
                complexity += 0.1
        
        # Ограничиваем максимум 1.0
        return min(complexity, 1.0)

    def _assess_confidence(self, local_response: str) -> float:
        """
        Оценивает уверенность в локальном ответе.

        Args:
            local_response: Ответ локальной модели

        Returns:
            Оценка уверенности от 0 до 1
        """
        # Простая эвристика: наличие маркеров неуверенности
        uncertainty_markers = [
            "не знаю", "не уверен", "не могу", "затрудняюсь",
            "возможно", "наверное", "скорее всего", "предполагаю",
            "извините", "простите", "к сожалению"
        ]
        
        confidence = 1.0
        response_lower = local_response.lower()
        
        for marker in uncertainty_markers:
            if marker in response_lower:
                confidence -= 0.2
        
        # Ограничиваем минимум 0.0
        return max(confidence, 0.0)

    def _determine_escalation_level(self, complexity: float, confidence: float) -> EscalationLevel:
        """
        Определяет уровень эскалации на основе сложности и уверенности.

        Args:
            complexity: Оценка сложности
            confidence: Оценка уверенности

        Returns:
            Уровень эскалации
        """
        if complexity < 0.3 and confidence > 0.7:
            return EscalationLevel.LOCAL
        
        if complexity < 0.5 and confidence > 0.5:
            return EscalationLevel.CLOUDE_SMALL
        
        if complexity < 0.7 or confidence < 0.5:
            return EscalationLevel.CLOUDE_MEDIUM
        
        if complexity >= 0.7 and confidence < 0.3:
            return EscalationLevel.CLOUDE_LARGE
        
        # По умолчанию
        return EscalationLevel.CLOUDE_MEDIUM

    def _call_external_model(self, query: str, context: str, level: EscalationLevel) -> str:
        """
        Вызывает внешнюю модель в зависимости от уровня эскалации.

        Args:
            query: Пользовательский запрос
            context: Контекст из памяти
            level: Уровень эскалации

        Returns:
            Ответ внешней модели
        """
        self.logger.info(f"Эскалация к {level.value} для запроса: {query[:100]}...")
        
        # Заглушки для внешних моделей
        model_responses = {
            EscalationLevel.CLOUDE_SMALL: (
                "Claude Haiku: Это упрощённый ответ на ваш запрос. "
                "Для более детального анализа рекомендуется использовать более мощную модель."
            ),
            EscalationLevel.CLOUDE_MEDIUM: (
                "Claude Sonnet: Проанализировав ваш запрос, могу предложить следующее. "
                "Учитывая предоставленный контекст, рекомендуется провести дополнительный анализ данных."
            ),
            EscalationLevel.CLOUDE_LARGE: (
                "Claude Opus: На основе глубокого анализа вашего запроса и предоставленного контекста, "
                "могу предложить комплексное решение. Рекомендую рассмотреть следующие стратегические шаги..."
            ),
            EscalationLevel.GPT_SMALL: (
                "GPT-3.5: Основываясь на вашем запросе, могу предложить следующее решение. "
                "Однако для более точного анализа потребуются дополнительные данные."
            ),
            EscalationLevel.GPT_LARGE: (
                "GPT-4: Проведя всесторонний анализ, выявляю ключевые аспекты вашего запроса. "
                "Предлагаю многоуровневое решение, учитывающее все нюансы поставленной задачи."
            ),
        }
        
        return model_responses.get(level, "Локальная модель: " + query)

    def process(self, query: str, context: str, local_response: str) -> Dict[str, Any]:
        """
        Обрабатывает эскалацию запроса.

        Args:
            query: Пользовательский запрос
            context: Контекст из памяти
            local_response: Ответ локальной модели

        Returns:
            Результат эскалации
        """
        self.logger.info(f"Оценка необходимости эскалации для запроса: {query[:100]}...")
        
        # Оцениваем сложность и уверенность
        complexity = self._assess_complexity(query, context)
        confidence = self._assess_confidence(local_response)
        
        self.logger.info(f"Сложность: {complexity:.2f}, Уверенность: {confidence:.2f}")
        
        # Определяем уровень эскалации
        escalation_level = self._determine_escalation_level(complexity, confidence)
        
        if escalation_level == EscalationLevel.LOCAL:
            self.logger.info("Эскалация не требуется, используем локальный ответ")
            return {
                "escalated": False,
                "level": "local",
                "response": local_response,
                "complexity": complexity,
                "confidence": confidence
            }
        
        # Вызываем внешнюю модель
        external_response = self._call_external_model(query, context, escalation_level)
        
        self.logger.info(f"Эскалация выполнена на уровень {escalation_level.value}")
        
        return {
            "escalated": True,
            "level": escalation_level.value,
            "local_response": local_response,
            "external_response": external_response,
            "complexity": complexity,
            "confidence": confidence,
            "combined_response": f"{external_response}\n\n[Основано на локальном анализе: {local_response[:200]}...]"
        }

    def should_escalate(self, query: str, context: str, local_response: str) -> bool:
        """
        Определяет, требуется ли эскалация.

        Args:
            query: Пользовательский запрос
            context: Контекст из памяти
            local_response: Ответ локальной модели

        Returns:
            True если требуется эскалация, False если нет
        """
        complexity = self._assess_complexity(query, context)
        confidence = self._assess_confidence(local_response)
        
        return (complexity > self.escalation_thresholds["complexity"] or 
                confidence < self.escalation_thresholds["confidence"])


# Глобальный экземпляр workflow
escalation_workflow = EscalationWorkflow()