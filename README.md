# ZORA — Zootopia Operational Resource Assistant

Многоагентная RAG-система на локальных LLM для автоматизации бизнес-процессов с оркестрацией на LangGraph, векторной памятью Qdrant и оценкой качества ответов (Faithfulness).

## 🏗️ Архитектура

```
ZORA/
├── agents/                    # Специализированные агенты (10 шт.)
│   ├── base.py               # Базовый класс BaseAgent
│   ├── accountant.py         # Бухгалтер (1С, проводки, НДС)
│   ├── developer_assistant.py # Ria — ассистент разработчика (исполнитель)
│   ├── economist.py          # Экономист (юнит-экономика, себестоимость)
│   ├── inspector.py          # Инспектор качества ответов
│   ├── logistician.py        # Логист (маршруты, топливо, Платон)
│   ├── operator_1c_local.py  # Оператор 1С (фоновый мониторинг)
│   ├── parser_agent.py       # Парсер-интегратор данных
│   ├── purchaser.py          # Закупщик (остатки, заказы)
│   ├── sales_consultant.py   # Консультант по продажам
│   ├── smm.py                # SMM (соцсети)
│   ├── support.py            # Клиентская поддержка
│   └── website.py            # Управление сайтом
├── collectors/               # Сборщики данных
│   ├── base.py               # Базовый класс коллектора
│   ├── its_collector.py      # Сборщик ИТС (1С)
│   ├── onec_collector_universal.py # Универсальный сборщик 1С
│   └── ukorona_collector.py  # Сборщик ukorona.ru
├── connectors/               # Коннекторы к внешним API
│   ├── deepseek_v4_client.py # DeepSeek V4 Flash/Pro
│   ├── llm_client_distributed.py # Распределённый LLM клиент
│   ├── ollama_client.py      # Клиент Ollama
│   ├── embedding_client.py   # Клиент эмбеддингов
│   ├── vision_client.py      # Vision (анализ изображений)
│   ├── onec_rest.py          # REST API 1С
│   ├── telegram_handler.py   # Обработчик Telegram
│   └── tokenizer_utils.py    # Утилиты токенизации
├── core/                     # Ядро системы
│   ├── orchestrator.py       # Оркестратор на LangGraph
│   ├── agent_registry.py     # Реестр агентов (автообнаружение)
│   ├── model_selector.py     # Выбор модели (DeepSeek/Ollama)
│   ├── roles.py              # Системные промпты агентов
│   ├── chat_history.py       # История чатов (PostgreSQL)
│   └── scheduler.py          # Планировщик фоновых задач
├── memory/                   # Векторная память
│   ├── qdrant_memory.py      # Клиент Qdrant (store/search/hybrid)
│   ├── qdrant_memory_old.py  # Предыдущая версия (backup)
│   ├── feedback_analyzer.py  # Анализ обратной связи
│   ├── lesson_saver.py       # Сохранение уроков
│   ├── router_learner.py     # Обучение маршрутизации
│   └── versioning.py         # Версионирование данных
├── tools/                    # Инструменты
│   ├── rag_evaluator.py      # Оценка RAG (Hit Rate, Precision, Recall)
│   ├── faithfulness_evaluator.py # LLM-судья (оценка галлюцинаций)
│   ├── rag_dataset_generator.py # Генерация тестовых датасетов
│   ├── browser.py            # Браузерная автоматизация
│   ├── code_analyzer.py      # Анализ кода
│   ├── desktop_automation.py # Автоматизация рабочего стола
│   ├── email_sender.py       # Отправка email
│   ├── file_ops.py           # Файловые операции
│   ├── git_tools.py          # Git операции
│   ├── model_trainer.py      # Тренировка моделей
│   ├── shell.py / terminal.py # Shell/терминал
│   ├── test_runner.py        # Запуск тестов
│   ├── weather.py            # Погода
│   └── cleanup_duplicates.py # Очистка дубликатов
├── interfaces/               # Интерфейсы
│   ├── web.py                # FastAPI веб-сервер (порт 8002)
│   ├── templates/            # HTML шаблоны
│   │   ├── modern_chat.html  # Современный чат
│   │   └── user_chat.html    # Классический чат
│   └── static/               # Статические файлы
├── monitoring/               # Мониторинг
│   ├── dashboard.py          # FastAPI дашборд
│   ├── system_monitor.py     # Мониторинг системы
│   ├── gpu_monitor.py        # Мониторинг GPU
│   └── templates/            # Шаблоны дашборда
├── parsers/                  # Парсеры
│   └── its_parser.py         # Парсер ИТС
├── workflows/                # Бизнес-воркфлоу
│   └── escalation.py         # Эскалация к большим моделям
├── data/                     # Данные
│   ├── rag_test_set.json     # Тестовый набор RAG
│   ├── rag_metrics.json      # Метрики RAG
│   ├── faithfulness_samples/ # Примеры оценки faithfulness
│   ├── dialogues/            # История диалогов
│   └── prompts/              # Пользовательские промпты
├── docs/                     # Документация
├── zora_launcher.py          # Точка входа (запуск системы)
├── run_rag_evaluation.py     # CLI для оценки RAG
└── docker-compose.yml        # Qdrant + PostgreSQL
```

## 🚀 Возможности

### 🤖 Специализированные агенты
- **Ria (Developer Assistant)**: универсальный исполнитель, генерация ответов с RAG
- **Бухгалтер**: 1С, проводки, НДС, учётная политика
- **Экономист**: юнит-экономика, себестоимость, рентабельность
- **Логист**: маршруты, топливо, системы "Платон" и "Автодор"
- **Закупщик**: прогнозирование остатков, формирование заказов
- **Консультант по продажам**: анализ продаж, ценообразование
- **SMM**: контент для соцсетей, планирование публикаций
- **Поддержка**: обработка обращений, база знаний
- **Сайт**: аналитика, SEO, мониторинг
- **Парсер**: интеграция данных из внешних источников
- **Инспектор**: контроль качества ответов
- **Оператор 1С**: фоновый мониторинг 1С

### 🧠 Технологический стек
- **LangGraph**: оркестрация агентов, графы выполнения
- **Qdrant**: векторная память (гибридный поиск: dense + sparse)
- **DeepSeek V4 Flash/Pro**: основной облачный LLM провайдер
- **Ollama**: локальные LLM (Llama 3.2, Qwen 3, BGE-M3)
- **PostgreSQL**: история чатов
- **FastAPI**: REST API + WebSocket
- **Docker**: контейнеризация Qdrant и PostgreSQL

### 📊 RAG оценка
- **Hit Rate, Precision, Recall, MRR** — метрики поиска
- **Faithfulness (LLM-судья)** — оценка галлюцинаций через отдельную модель (llama3.2)
- **Генерация датасетов** — автоматическая из документов в Qdrant
- **CI-режим** — автоматическая проверка качества при деплое

## ⚡ Быстрый старт

### 1. Установка зависимостей
```bash
# Создание виртуального окружения
python -m venv venv
venv\Scripts\activate  # Windows

# Установка зависимостей
pip install -r requirements.txt
```

### 2. Запуск инфраструктуры (Docker)
```bash
docker-compose up -d
```

Сервисы будут доступны:
- **Qdrant**: http://localhost:6333
- **PostgreSQL**: localhost:5432

### 3. Настройка .env
```bash
cp .env.example .env
# Отредактируйте .env под своё окружение
```

### 4. Запуск ZORA
```bash
python zora_launcher.py
```

Веб-интерфейс: http://localhost:8002/modern
Дашборд: http://localhost:8002/dashboard

## 🔧 Конфигурация

### Основные переменные .env

```ini
# === LLM провайдеры ===
DEEPSEEK_API_KEY=sk-...           # API ключ DeepSeek
DEEPSEEK_MODEL_FLASH=deepseek-v4-flash
DEEPSEEK_MODEL_PRO=deepseek-v4-pro
DEEPSEEK_LEGACY_MODE=false
DEEPSEEK_DEFAULT_REASONING=flash

# === Ollama (локальные модели) ===
OLLAMA_HOST=http://localhost:11434
OLLAMA_EXECUTOR_MODEL=llama3.2:latest
OLLAMA_VISION_MODEL=qwen3-vl:4b
EMBED_MODEL=mxbai-embed-large

# === LLM-судья (Faithfulness) ===
FAITHFULNESS_JUDGE_MODEL=llama3.2:latest

# === Базы данных ===
QDRANT_HOST=localhost
QDRANT_PORT=6333
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=zora
POSTGRES_USER=postgres
POSTGRES_PASSWORD=your_password

# === Telegram ===
TELEGRAM_BOT_TOKEN=your_token
```

## 📊 Оценка RAG

### Запуск оценки
```bash
# Базовая оценка (Hit Rate)
python run_rag_evaluation.py

# С оценкой faithfulness (выборка 50 вопросов)
python run_rag_evaluation.py --evaluate-faithfulness --faithfulness-sample-size 50

# CI-режим (25 вопросов, exit code 1 если faithfulness < 4.0)
python run_rag_evaluation.py --ci

# Просмотр последних метрик
python run_rag_evaluation.py --show-last
```

### Результаты
Метрики сохраняются в `data/rag_metrics.json`:
- `hit_rate`: точность поиска по K
- `faithfulness_mean`: средняя верность ответов (1-5)
- `faithfulness_samples`: примеры с question, answer, score, reasoning

## 🔌 API Endpoints

| Метод | Путь | Описание |
|-------|------|----------|
| POST | `/ask` | Задать вопрос агенту |
| GET | `/api/agents` | Список агентов |
| GET | `/api/rag/metrics` | Метрики RAG |
| GET | `/api/rag/evaluate` | Запустить оценку RAG |
| GET | `/api/health` | Проверка здоровья |
| GET | `/api/zora_status` | Статус системы |
| GET | `/dashboard` | Дашборд мониторинга |
| GET | `/modern` | Современный чат |
| WS | `/ws/{chat_id}` | WebSocket чат |

## 📈 Дорожная карта

### Реализовано
- [x] Многоагентная архитектура на LangGraph
- [x] Гибридный поиск (dense + sparse) в Qdrant
- [x] RAG оценка (Hit Rate, Precision, Recall, MRR)
- [x] Faithfulness оценка (LLM-судья)
- [x] Генерация тестовых датасетов из документов
- [x] CI-режим для автоматической проверки качества
- [x] Веб-интерфейс с историей чатов (PostgreSQL)
- [x] Telegram интеграция
- [x] Сборщики данных (ukorona.ru, 1С, ИТС)
- [x] Мониторинг системы и GPU

### В разработке
- [ ] Автоматическое обновление документов по расписанию
- [ ] A/B тестирование моделей
- [ ] Экспорт метрик в Grafana

## 👥 Контакты

- **Автор**: Denis
- **GitHub**: [ToMiK-82](https://github.com/ToMiK-82)
- **Проект**: https://github.com/ToMiK-82/ZORA

---

**ZORA** — ваш интеллектуальный партнёр в бизнесе. Автоматизируйте рутину, фокусируйтесь на стратегии!
