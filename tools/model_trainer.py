"""
Инструменты для обучения и fine-tuning моделей Ollama.
"""

import json
import os
import logging
from typing import Dict, List, Any, Optional
import subprocess
import tempfile

logger = logging.getLogger(__name__)


class ModelTrainer:
    """Класс для обучения и fine-tuning моделей Ollama."""
    
    def __init__(self, ollama_host: str = "http://localhost:11434"):
        self.ollama_host = ollama_host
        self.training_data_dir = "training_data"
        os.makedirs(self.training_data_dir, exist_ok=True)
    
    def prepare_training_data(self, conversations: List[Dict[str, str]], 
                             dataset_name: str = "zora_conversations") -> str:
        """
        Подготавливает данные для обучения в формате JSONL.
        
        Args:
            conversations: Список диалогов в формате [{"role": "user/assistant", "content": "текст"}]
            dataset_name: Имя датасета
        
        Returns:
            Путь к файлу с данными
        """
        data_file = os.path.join(self.training_data_dir, f"{dataset_name}.jsonl")
        
        with open(data_file, 'w', encoding='utf-8') as f:
            for conv in conversations:
                # Форматируем в формат для fine-tuning
                formatted = {
                    "messages": conv if isinstance(conv, list) else [conv]
                }
                f.write(json.dumps(formatted, ensure_ascii=False) + '\n')
        
        logger.info(f"Подготовлены данные для обучения: {data_file} ({len(conversations)} примеров)")
        return data_file
    
    def collect_conversations_from_memory(self, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Собирает диалоги из памяти для обучения.
        
        Args:
            limit: Максимальное количество диалогов
        
        Returns:
            Список диалогов
        """
        try:
            from memory import memory
        except ImportError:
            logger.warning("Память недоступна для сбора данных")
            return []
        
        conversations = []
        try:
            # Ищем диалоги в памяти
            results = memory.search(query="диалог разговор пользователь ассистент", limit=limit*2)
            
            for result in results:
                text = result.get("text", "")
                metadata = result.get("metadata", {})
                
                # Пытаемся извлечь структурированный диалог
                if "user:" in text.lower() and "assistant:" in text.lower():
                    lines = text.split('\n')
                    messages = []
                    
                    for line in lines:
                        line = line.strip()
                        if line.lower().startswith("user:"):
                            messages.append({"role": "user", "content": line[5:].strip()})
                        elif line.lower().startswith("assistant:"):
                            messages.append({"role": "assistant", "content": line[10:].strip()})
                        elif line.lower().startswith("ассистент:"):
                            messages.append({"role": "assistant", "content": line[10:].strip()})
                        elif line.lower().startswith("пользователь:"):
                            messages.append({"role": "user", "content": line[13:].strip()})
                    
                    if len(messages) >= 2:  # Минимум один обмен репликами
                        conversations.append(messages)
        
        except Exception as e:
            logger.error(f"Ошибка при сборе диалогов из памяти: {e}")
        
        return conversations[:limit]
    
    def create_modelfile(self, base_model: str = "llama3.2:latest",
                        dataset_path: str = None,
                        model_name: str = "zora-finetuned") -> str:
        """
        Создает Modelfile для fine-tuning.
        
        Args:
            base_model: Базовая модель Ollama
            dataset_path: Путь к датасету
            model_name: Имя новой модели
        
        Returns:
            Путь к Modelfile
        """
        modelfile_content = f"""FROM {base_model}

# Системный промпт для ассистента ZORA
SYSTEM \"\"\"Ты — Ria, интеллектуальный ассистент системы ZORA. 
Твоя задача — помогать пользователям с вопросами о разработке, анализе кода и автоматизации.
Будь полезным, точным и кратким в ответах.
Отвечай на русском языке.\"\"\"

# Параметры модели
PARAMETER temperature 0.7
PARAMETER top_p 0.9
PARAMETER top_k 40
"""
        
        if dataset_path and os.path.exists(dataset_path):
            modelfile_content += f"\n# Данные для fine-tuning\nTEMPLATE {dataset_path}\n"
        
        modelfile_path = os.path.join(self.training_data_dir, f"{model_name}.Modelfile")
        with open(modelfile_path, 'w', encoding='utf-8') as f:
            f.write(modelfile_content)
        
        return modelfile_path
    
    def train_model(self, base_model: str = "llama3.2:latest",
                   dataset_path: Optional[str] = None,
                   model_name: str = "zora-finetuned",
                   epochs: int = 3) -> Dict[str, Any]:
        """
        Запускает fine-tuning модели Ollama.
        
        Args:
            base_model: Базовая модель
            dataset_path: Путь к датасету (опционально)
            model_name: Имя новой модели
            epochs: Количество эпох
        
        Returns:
            Результаты обучения
        """
        try:
            # Создаем Modelfile
            modelfile_path = self.create_modelfile(base_model, dataset_path, model_name)
            
            # Команда для создания модели
            cmd = ["ollama", "create", model_name, "-f", modelfile_path]
            
            logger.info(f"Запуск обучения модели: {' '.join(cmd)}")
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=3600  # 1 час таймаут
            )
            
            if result.returncode == 0:
                logger.info(f"Модель {model_name} успешно создана")
                return {
                    "success": True,
                    "model_name": model_name,
                    "output": result.stdout,
                    "base_model": base_model
                }
            else:
                logger.error(f"Ошибка создания модели: {result.stderr}")
                return {
                    "success": False,
                    "error": result.stderr,
                    "output": result.stdout
                }
                
        except subprocess.TimeoutExpired:
            logger.error("Таймаут обучения модели (1 час)")
            return {
                "success": False,
                "error": "Таймаут обучения модели"
            }
        except Exception as e:
            logger.error(f"Ошибка обучения модели: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    def evaluate_model(self, model_name: str, test_questions: List[str] = None) -> Dict[str, Any]:
        """
        Оценивает качество обученной модели.
        
        Args:
            model_name: Имя модели для оценки
            test_questions: Список тестовых вопросов
        
        Returns:
            Результаты оценки
        """
        if test_questions is None:
            test_questions = [
                "Привет! Как дела?",
                "Что такое ZORA?",
                "Помоги мне проанализировать код",
                "Как проверить доступ в интернет?",
                "Расскажи о возможностях ассистента"
            ]
        
        try:
            import requests
            import time
            
            results = []
            for question in test_questions:
                try:
                    response = requests.post(
                        f"{self.ollama_host}/api/generate",
                        json={
                            "model": model_name,
                            "prompt": question,
                            "stream": False
                        },
                        timeout=30
                    )
                    
                    if response.status_code == 200:
                        answer = response.json().get("response", "")
                        results.append({
                            "question": question,
                            "answer": answer,
                            "success": True,
                            "length": len(answer)
                        })
                    else:
                        results.append({
                            "question": question,
                            "error": f"HTTP {response.status_code}",
                            "success": False
                        })
                    
                    time.sleep(1)  # Задержка между запросами
                    
                except Exception as e:
                    results.append({
                        "question": question,
                        "error": str(e),
                        "success": False
                    })
            
            # Анализируем результаты
            successful = sum(1 for r in results if r.get("success", False))
            total = len(results)
            
            return {
                "success": True,
                "model": model_name,
                "total_questions": total,
                "successful_answers": successful,
                "success_rate": successful / total if total > 0 else 0,
                "results": results
            }
            
        except Exception as e:
            logger.error(f"Ошибка оценки модели: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    def get_available_models(self) -> List[str]:
        """
        Получает список доступных моделей Ollama.
        Также проверяет модели из конфигурации ZORA.
        
        Returns:
            Список имен моделей
        """
        try:
            import requests
            
            # Получаем модели из Ollama
            response = requests.get(f"{self.ollama_host}/api/tags", timeout=10)
            ollama_models = []
            
            if response.status_code == 200:
                models_data = response.json()
                ollama_models = [model["name"] for model in models_data.get("models", [])]
                logger.info(f"Найдено моделей в Ollama: {len(ollama_models)}")
            else:
                logger.warning(f"Не удалось получить список моделей из Ollama: HTTP {response.status_code}")
            
            # Получаем модели из конфигурации ZORA
            config_models = []
            try:
                from config.distributed_models import (
                    CHAT_MODEL_WEAK, 
                    CHAT_MODEL_STRONG, 
                    CHAT_MODEL_STRONG_LOCAL,
                    EMBED_MODEL
                )
                
                config_models = [
                    CHAT_MODEL_WEAK,
                    CHAT_MODEL_STRONG,
                    CHAT_MODEL_STRONG_LOCAL,
                    EMBED_MODEL
                ]
                
                # Фильтруем None значения
                config_models = [model for model in config_models if model]
                logger.info(f"Модели из конфигурации ZORA: {config_models}")
                
            except ImportError as e:
                logger.warning(f"Не удалось импортировать конфигурацию моделей: {e}")
            except Exception as e:
                logger.warning(f"Ошибка получения моделей из конфигурации: {e}")
            
            # Объединяем списки, убираем дубликаты
            all_models = list(set(ollama_models + config_models))
            
            # Проверяем, какие модели из конфигурации не найдены в Ollama
            missing_models = [model for model in config_models if model not in ollama_models]
            if missing_models:
                logger.warning(f"Модели из конфигурации не найдены в Ollama: {missing_models}")
                logger.warning(f"Для загрузки моделей используйте: ollama pull <model_name>")
            
            return all_models
                
        except Exception as e:
            logger.error(f"Ошибка получения списка моделей: {e}")
            return []
    
    def delete_model(self, model_name: str) -> Dict[str, Any]:
        """
        Удаляет модель Ollama.
        
        Args:
            model_name: Имя модели для удаления
        
        Returns:
            Результат удаления
        """
        try:
            cmd = ["ollama", "rm", model_name]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            
            if result.returncode == 0:
                return {"success": True, "message": f"Модель {model_name} удалена"}
            else:
                return {"success": False, "error": result.stderr}
                
        except Exception as e:
            return {"success": False, "error": str(e)}


def train_zora_assistant(use_memory_data: bool = True, 
                        custom_conversations: List[Dict] = None) -> Dict[str, Any]:
    """
    Основная функция для обучения ассистента ZORA.
    
    Args:
        use_memory_data: Использовать данные из памяти
        custom_conversations: Пользовательские диалоги для обучения
    
    Returns:
        Результаты обучения
    """
    trainer = ModelTrainer()
    
    # Собираем данные для обучения
    conversations = []
    
    if use_memory_data:
        memory_conversations = trainer.collect_conversations_from_memory(limit=50)
        conversations.extend(memory_conversations)
        logger.info(f"Собрано {len(memory_conversations)} диалогов из памяти")
    
    if custom_conversations:
        conversations.extend(custom_conversations)
        logger.info(f"Добавлено {len(custom_conversations)} пользовательских диалогов")
    
    if not conversations:
        logger.warning("Нет данных для обучения")
        return {
            "success": False,
            "error": "Нет данных для обучения"
        }
    
    # Подготавливаем данные
    dataset_path = trainer.prepare_training_data(conversations, "zora_training")
    
    # Обучаем модель
    result = trainer.train_model(
        base_model="llama3.2:latest",
        dataset_path=dataset_path,
        model_name="zora-assistant",
        epochs=3
    )
    
    if result.get("success"):
        # Оцениваем модель
        evaluation = trainer.evaluate_model("zora-assistant")
        result["evaluation"] = evaluation
    
    return result


if __name__ == "__main__":
    # Пример использования
    import logging
    logging.basicConfig(level=logging.INFO)
    
    print("🔄 Запуск обучения ассистента ZORA...")
    
    # Тестовые диалоги
    test_conversations = [
        [
            {"role": "user", "content": "Привет! Как дела?"},
            {"role": "assistant", "content": "Привет! У меня всё отлично, готов помочь вам с вопросами о ZORA и разработке!"}
        ],
        [
            {"role": "user", "content": "Что такое ZORA?"},
            {"role": "assistant", "content": "ZORA — это интеллектуальная система с агентами для автоматизации задач разработки, анализа кода и помощи программистам."}
        ]
    ]
    
    result = train_zora_assistant(
        use_memory_data=False,  # Не использовать память для теста
        custom_conversations=test_conversations
    )
    
    if result.get("success"):
        print("✅ Обучение завершено успешно!")
        print(f"📊 Модель: {result.get('model_name')}")
        if "evaluation" in result:
            eval_result = result["evaluation"]
            print(f"📈 Оценка: {eval_result.get('success_rate', 0)*100:.1f}% успешных ответов")
    else:
        print(f"❌ Ошибка обучения: {result.get('error', 'Неизвестная ошибка')}")