"""
Агент-парсер для обработки документов и данных.
Заменяет кнопку "Парсить ИТС 1С" в интерфейсе мониторинга.
"""

import logging
import os
from typing import Dict, Any, List, Optional
from datetime import datetime

from agents.base import BaseAgent
from core.roles import AgentRole, get_system_prompt

logger = logging.getLogger(__name__)


class ParserAgent(BaseAgent):
    """Агент для парсинга документов и данных."""
    
    def __init__(self):
        super().__init__(AgentRole.DEFAULT.value)
        self.name = "parser"
        self.description = "Агент для парсинга документов и данных"
        self.version = "1.0"
        self.current_task = None
        self.parsing_results = []
        
    def parse_its_docs(self, docs_path: str = None) -> Dict[str, Any]:
        """
        Парсит документацию ИТС 1С.
        
        Args:
            docs_path: Путь к документации ИТС 1С.
                Если None, использует стандартный путь.
        
        Returns:
            Результаты парсинга.
        """
        self.current_task = "Парсинг документации ИТС 1С"
        
        try:
            # Проверяем наличие модуля парсера
            try:
                from parsers.its_parser import parse_its_docs as parse_its
            except ImportError:
                logger.warning("Модуль parsers.its_parser не найден")
                return {
                    "success": False,
                    "message": "Модуль парсера ИТС не установлен",
                    "task": self.current_task
                }
            
            # Если путь не указан, используем стандартный
            if docs_path is None:
                # Пытаемся найти документацию в стандартных местах
                possible_paths = [
                    "C:\\Program Files\\1Cv8\\",
                    "C:\\Program Files (x86)\\1Cv8\\",
                    "D:\\1C\\",
                    os.path.expanduser("~\\Documents\\1C\\")
                ]
                
                for path in possible_paths:
                    if os.path.exists(path):
                        docs_path = path
                        break
                
                if docs_path is None:
                    docs_path = "."
            
            logger.info(f"Начинаем парсинг ИТС из: {docs_path}")
            
            # Вызываем парсер
            result = parse_its(docs_path)
            
            self.parsing_results.append({
                "timestamp": datetime.now().isoformat(),
                "type": "its_docs",
                "path": docs_path,
                "result": result
            })
            
            return {
                "success": True,
                "message": f"Парсинг ИТС завершен. Обработано: {result.get('processed', 0)} файлов",
                "data": result,
                "task": self.current_task
            }
            
        except Exception as e:
            logger.error(f"Ошибка парсинга ИТС: {e}")
            return {
                "success": False,
                "message": f"Ошибка парсинга ИТС: {str(e)}",
                "task": self.current_task
            }
    
    def process_request(self, request: str) -> Dict[str, Any]:
        """
        Обрабатывает запрос пользователя.
        
        Args:
            request: Текстовый запрос пользователя.
        
        Returns:
            Ответ агента.
        """
        self.current_task = f"Обработка запроса: {request[:50]}..."
        
        # Простой анализ запроса
        request_lower = request.lower()
        
        if "парс" in request_lower or "its" in request_lower or "1с" in request_lower:
            result = self.parse_its_docs()
            return {
                "success": result.get("success", True),
                "message": result.get("message", ""),
                "data": result.get("data", {}),
                "task": self.current_task
            }
        
        else:
            return {
                "success": True,
                "message": "Я агент-парсер. Могу помочь только с парсингом ИТС 1С. Для индексации проекта, анализа кода, запуска тестов или проверки Git статуса обратитесь к ассистенту разработчика.",
                "task": self.current_task
            }
    
    def _process_specific(self, query: str, context: str) -> Dict[str, Any]:
        """
        Обрабатывает запрос пользователя (реализация абстрактного метода).
        
        Args:
            query: Пользовательский запрос
            context: Извлечённый контекст
            
        Returns:
            Результат обработки
        """
        self.logger.info(f"Обработка запроса парсера: {query}")
        
        # Используем существующую логику обработки запросов
        result = self.process_request(query)
        
        # Форматируем результат в соответствии с ожидаемым форматом
        return {
            "success": result.get("success", True),
            "result": result.get("message", ""),
            "data": result.get("data", {}),
            "task": result.get("task", ""),
            "agent": self.agent_name
        }
    
    def get_status(self) -> Dict[str, Any]:
        """Возвращает статус агента."""
        return {
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "current_task": self.current_task,
            "parsing_results_count": len(self.parsing_results),
            "last_parsing": self.parsing_results[-1]["timestamp"] if self.parsing_results else None,
            "status": "running" if self.current_task else "idle"
        }


def test_parser():
    """Тестирование агента-парсера."""
    parser = ParserAgent()
    
    print("Тест агента-парсера:")
    print(f"Имя: {parser.name}")
    print(f"Описание: {parser.description}")
    
    # Тест обработки запроса
    print("\n1. Тест обработки запроса:")
    response = parser.process_request("Парси ИТС 1С")
    print(f"   Успех: {response.get('success')}")
    print(f"   Сообщение: {response.get('message')}")
    
    # Тест статуса
    print("\n2. Статус агента:")
    status = parser.get_status()
    print(f"   Текущая задача: {status.get('current_task')}")
    print(f"   Состояние: {status.get('status')}")
    
    print("\nТест завершён.")


if __name__ == "__main__":
    test_parser()