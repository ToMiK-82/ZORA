"""
Агент для управления сайтом и веб-контентом.
Использует промпт из core.roles.py и интеграцию с LLM.
"""

from typing import Dict, Any
from agents.base import BaseAgent
from core.roles import AgentRole, get_system_prompt
from connectors.llm_client_distributed import generate_sync as generate
try:
    from memory import memory
    MEMORY_AVAILABLE = True
except ImportError:
    MEMORY_AVAILABLE = False
    memory = None


class Website(BaseAgent):
    """Агент для управления сайтом."""

    def __init__(self):
        super().__init__(AgentRole.WEBSITE.value)
        # Получаем системный промпт из централизованного модуля
        self.system_prompt = get_system_prompt(AgentRole.WEBSITE)

    def _process_specific(self, query: str, context: str) -> Dict[str, Any]:
        """
        Обрабатывает запросы по сайту с использованием LLM.

        Args:
            query: Пользовательский запрос
            context: Извлечённый контекст (может быть пустым, если не передан)

        Returns:
            Результат работы агента
        """
        if query is None:
            query = ""
        # Используем переданный контекст (уже извлечённый оркестратором)
        
        # Формируем полный промпт с системным промптом, контекстом и запросом
        full_prompt = f"""{self.system_prompt}

Контекст из памяти системы:
{context if context else "Контекст не найден"}

Запрос пользователя: {query}

Пожалуйста, предоставь рекомендации по управлению сайтом, контенту и SEO.
Если в контексте есть данные, используй их для анализа.
Если данных недостаточно, укажи, какие дополнительные данные нужны.
"""
        
        try:
            # Вызываем LLM через распределённую систему
            response = generate(full_prompt)  # model=None по умолчанию
            
            # Если ответ содержит ошибку, возвращаем сообщение об ошибке
            if isinstance(response, dict) and "error" in response:
                return {
                    "success": False,
                    "result": f"Ошибка LLM: {response['error']}",
                    "agent": self.agent_name,
                    "context_used": bool(context)
                }
            
            # Преобразуем ответ в строку, если это необходимо
            if isinstance(response, dict):
                result_text = response.get("text", str(response))
            else:
                result_text = str(response)
            
            return {
                "success": True,
                "result": result_text,
                "agent": self.agent_name,
                "context_used": bool(context),
                "system_prompt_used": True
            }
            
        except Exception as e:
            # В случае ошибки возвращаем сообщение с информацией об ошибке
            return {
                "success": False,
                "result": f"Ошибка при обработке запроса по сайту: {str(e)}",
                "agent": self.agent_name,
                "context_used": bool(context),
                "error": str(e)
            }
    
    def _retrieve_context(self, query: str, limit: int = 5) -> str:
        try:
            from memory import memory
            results = memory.search(query=query, limit=limit * 2)
            if not results:
                return ""
            # Группировка по файлам
            grouped = {}
            for r in results:
                path = r.get("path", "unknown")
                grouped.setdefault(path, []).append(r)
            context_parts = []
            for path, chunks in list(grouped.items())[:limit]:
                context_parts.append(f"\n📁 Файл: {path}")
                for i, chunk in enumerate(chunks[:3], 1):
                    text = chunk.get("text", "")
                    score = chunk.get("score", 0)
                    if len(text) > 500:
                        text = text[:500] + "..."
                    context_parts.append(f"  [{i}] Сходство: {score:.2f}")
                    context_parts.append(f"     {text}")
                    context_parts.append("")
            context = "\n".join(context_parts)
            if context:
                context = "📚 РЕЛЕВАНТНЫЙ КОНТЕКСТ ИЗ ПАМЯТИ:\n" + context
                context += "\n\n💡 ИНСТРУКЦИЯ: Используй эту информацию для ответа. Если находишь релевантные фрагменты, цитируй их и указывай из какого файла они взяты."
            return context
        except Exception as e:
            self.logger.error(f"Ошибка при извлечении контекста: {e}")
            return ""
