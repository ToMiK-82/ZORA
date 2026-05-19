# Todo List

## Этап 1: TraceHandler → WebSocket (бэкенд)
- [ ] Подписать websocket_telemetry на trace_handler.subscribe()
- [ ] Отправлять execution_trace, trace_step, trace_completed через WS

## Этап 2: WebSocket фронтенд — обработка execution_trace
- [ ] Добавить тип WsExecutionTrace в types.ts
- [ ] Добавить обработку execution_trace в websocketProvider.tsx

## Этап 3: AgentExecutionGraph — живые трейсы + кастомные узлы
- [ ] Использовать execution_trace из WS для обновления рёбер
- [ ] Кастомные узлы: разные формы для оркестратора, агентов, пользователя, разработчика
- [ ] Фильтр "Только активные" + история за час

## Этап 4: FileSystemGraph — 4 статуса
- [ ] Доработать /api/filesystem/graph: stale, indexed_used, indexed_unused, not_indexed
- [ ] Сравнение дат last_modified vs last_indexed
- [ ] Проверка использования чанков агентами

## Этап 5: SystemHealthGraph — degraded
- [ ] Добавить статус degraded при таймаутах

## Этап 6: Звёздная система (агенты ↔ файлы)
- [ ] Логирование agent→chunk в memory.search()
- [ ] Эндпоинт /api/knowledge_graph
- [ ] Фронтенд: файлы-узлы на графе агентов
