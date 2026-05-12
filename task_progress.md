# Todo List

- [x] **Задача A: Последовательное выполнение задач в планировщике**
  - [x] Добавить `index_project` в `run_scheduled_tasks`
  - [x] Убедиться, что `start_background_scheduler` не вызывает задачи сразу
  - [x] Добавить `start_operation`/`finish_operation` в `_scheduler_loop`

- [x] **Задача B: Удаление дублирующихся фоновых задач**
  - [x] Удалить `schedule_background_tasks` из `core/orchestrator.py`
  - [x] Исправить `/api/train` и `/api/reindex` в `web.py`

- [x] **Задача C: Исправление виджетов дашборда**
  - [x] C1: Виджет RAG — обработка отсутствия метрик, отображение векторов
  - [x] C2: Виджет CPU — температура, корректные ядра

- [x] **Задача D: Финальная проверка индексации**
  - [x] Удалить `memory/indexer.py`
  - [x] Проверить, что все функции перенесены в ParserAgent
