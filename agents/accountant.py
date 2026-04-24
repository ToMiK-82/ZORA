"""
Агент-бухгалтер для работы с 1С, проводками и налоговой отчётностью.
Создан согласно заданию с новым системным промптом.
"""

import logging
from typing import Dict, Any
from agents.base import BaseAgent
from connectors.llm_client_distributed import generate as llm_generate
try:
    from memory import memory
    MEMORY_AVAILABLE = True
except ImportError:
    MEMORY_AVAILABLE = False
    memory = None

logger = logging.getLogger(__name__)

class Accountant(BaseAgent):
    """Агент-бухгалтер для помощи пользователям в работе с 1С и бухгалтерскими документами."""
    
    def __init__(self):
        super().__init__("accountant")
        self.logger = logging.getLogger("zora.agent.accountant")
    
    def _process_specific(self, query: str, context: str) -> Dict[str, Any]:
        """
        Обработка бухгалтерских запросов.
        
        Args:
            query: Пользовательский запрос
            context: Извлечённый контекст из памяти (может быть пустым, если не передан)
            
        Returns:
            Словарь с результатом работы агента
        """
        if query is None:
            query = ""
        # Используем переданный контекст (уже извлечённый оркестратором)
        
        self.logger.info(f"Обработка бухгалтерского запроса: {query}")
        
        # Формируем промпт с системным промптом и контекстом
        prompt = self._build_accountant_prompt(query, context)
        
        # Получаем ответ от LLM
        try:
            response = llm_generate(prompt)  # model=None по умолчанию
            
            if isinstance(response, dict) and "error" in response:
                return {
                    "success": False,
                    "result": f"Ошибка LLM: {response['error']}",
                    "agent": self.agent_name,
                    "context_used": bool(context)
                }
            
            # Парсим ответ LLM
            result_text = response.get("text", str(response)) if isinstance(response, dict) else str(response)
            
            return {
                "success": True,
                "result": result_text,
                "agent": self.agent_name,
                "context_used": bool(context)
            }
            
        except Exception as e:
            self.logger.error(f"Ошибка при обработке запроса бухгалтером: {e}")
            return {
                "success": False,
                "result": f"Ошибка при обработке запроса бухгалтером: {str(e)}",
                "agent": self.agent_name,
                "context_used": bool(context),
                "error": str(e)
            }
    
    def _build_accountant_prompt(self, query: str, context: str) -> str:
        """Формирует промпт для бухгалтера."""
        system_prompt = (
            "Ты — главный бухгалтер. Твоя задача — помогать пользователям (сотрудникам компании) "
            "в работе с 1С и бухгалтерскими документами. Ты получаешь запрос и фрагменты из базы знаний "
            "(инструкции, регламенты). Твоя задача: используя эти фрагменты, дать чёткий, пошаговый ответ "
            "на естественном языке. Игнорируй любые технические детали (названия функций, SQL-запросы, "
            "примеры кода), если они не нужны для ответа. Если во фрагментах нет нужной информации, "
            "скажи об этом честно и предложи обратиться к разработчику."
        )
        
        return f"""{system_prompt}

Контекст из памяти (инструкции, регламенты, документация):
{context if context else "Контекст отсутствует. Документация ещё не проиндексирована или память пуста."}

Запрос пользователя: {query}

Ответ (чёткий, пошаговый, на естественном языке, без технических деталей если они не нужны):"""
    
    def _retrieve_context(self, query: str, limit: int = 5) -> str:
        """
        Извлекает релевантный контекст из памяти без фильтров.
        Использует только базовый поиск по тексту запроса.
        """
        try:
            # Выполняем поиск без фильтров
            results = memory.search(
                query=query,
                limit=limit * 2  # Берем больше результатов для группировки
            )
            
            if not results:
                return ""
            
            # Группируем результаты по файлам
            grouped_results = {}
            for result in results:
                path = result.get("path", "unknown")
                if path not in grouped_results:
                    grouped_results[path] = []
                grouped_results[path].append(result)
            
            # Формируем контекст с группировкой по файлам
            context_parts = []
            for file_path, file_results in list(grouped_results.items())[:limit]:  # Ограничиваем количество файлов
                context_parts.append(f"\n📁 Файл: {file_path}")
                
                for i, result in enumerate(file_results[:3], 1):  # Берем до 3 чанков из каждого файла
                    text = result.get("text", "")
                    score = result.get("score", 0)
                    
                    # Обрезаем слишком длинный текст
                    if len(text) > 500:
                        text = text[:500] + "..."
                    
                    context_parts.append(f"  [{i}] Сходство: {score:.2f}")
                    context_parts.append(f"     {text}")
                    context_parts.append("")
            
            context = "\n".join(context_parts)
            
            # Добавляем инструкцию по использованию контекста
            if context:
                context = "📚 РЕЛЕВАНТНЫЙ КОНТЕКСТ ИЗ ПАМЯТИ:\n" + context
                context += "\n\n💡 ИНСТРУКЦИЯ: Используй эту информацию для ответа. Если находишь релевантные фрагменты, цитируй их и указывай из какого файла они взяты."
            
            return context
            
        except Exception as e:
            self.logger.error(f"Ошибка при извлечении контекста: {e}")
            # Возвращаем базовый поиск без фильтров
            return super()._retrieve_context(query, limit)