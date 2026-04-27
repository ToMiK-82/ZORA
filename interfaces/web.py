"""
Веб-интерфейс для ассистента разработчика ZORA.
FastAPI приложение с поддержкой истории диалогов.
"""

import logging
import os
import sys
import asyncio
import json
from datetime import datetime
from fastapi import FastAPI, Request, HTTPException, UploadFile, File, Form
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
import shutil
import uuid

# Добавляем путь к проекту
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logger = logging.getLogger(__name__)

app = FastAPI(title="ZORA Assistant Web Interface", version="1.0.0")

# Настраиваем CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Создаем директории для шаблонов и статических файлов
templates_dir = os.path.join(os.path.dirname(__file__), "templates")
static_dir = os.path.join(os.path.dirname(__file__), "static")

os.makedirs(templates_dir, exist_ok=True)
os.makedirs(static_dir, exist_ok=True)

# Настраиваем шаблоны и статические файлы
templates = Jinja2Templates(directory=templates_dir)
app.mount("/static", StaticFiles(directory=static_dir), name="static")

# Маршрут для favicon.ico
@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    """Возвращает favicon.ico"""
    from fastapi.responses import FileResponse
    favicon_path = os.path.join(os.path.dirname(__file__), "..", "static", "favicon.ico")
    if os.path.exists(favicon_path):
        return FileResponse(favicon_path)
    # Если favicon не найден, возвращаем 404
    raise HTTPException(status_code=404, detail="Favicon not found")

# Глобальная переменная для выбора провайдера LLM
current_provider = "ollama"  # по умолчанию

# Импортируем оркестратор и память
try:
    from core.orchestrator import orchestrator
    _orchestrator = orchestrator
    ORCHESTRATOR_AVAILABLE = True
    logger.info("✅ LangGraph оркестратор ZORA загружен для веб-интерфейса")
except Exception as e:
    ORCHESTRATOR_AVAILABLE = False
    _orchestrator = None
    logger.warning(f"⚠️ Оркестратор не загружен: {e}")

try:
    from memory.qdrant_memory import memory as _memory
    MEMORY_AVAILABLE = True
    logger.info("✅ Векторная память Qdrant загружена")
except Exception as e:
    MEMORY_AVAILABLE = False
    _memory = None
    logger.warning(f"⚠️ Память не загружена: {e}")

try:
    from connectors.telegram_handler import telegram_handler
    TELEGRAM_HANDLER_AVAILABLE = True
    logger.info("✅ Telegram обработчик загружен для веб-интерфейса")
except ImportError as e:
    TELEGRAM_HANDLER_AVAILABLE = False
    logger.warning(f"⚠️ Telegram обработчик не найден: {e}")

# HTML эндпоинты
@app.get("/", response_class=HTMLResponse)
async def home():
    with open(os.path.join(templates_dir, "modern_chat.html"), "r", encoding="utf-8") as f:
        html_content = f.read()
    return HTMLResponse(content=html_content)

@app.get("/chat", response_class=HTMLResponse)
async def chat():
    with open(os.path.join(templates_dir, "user_chat.html"), "r", encoding="utf-8") as f:
        html_content = f.read()
    return HTMLResponse(content=html_content)

@app.get("/ide", response_class=HTMLResponse)
async def ide():
    return HTMLResponse(content="<h1>IDE интерфейс удалён. Используйте <a href='/modern'>modern chat</a> или <a href='/chat'>user chat</a>.</h1>", status_code=404)

@app.post("/ask")
async def ask(request: Request):
    """
    API endpoint для отправки запроса с поддержкой истории диалога.
    """
    data = await request.json()
    query = data.get("query", "").strip()
    history = data.get("history", [])  # список {role, content}
    interface = data.get("interface", "dev")

    if not query:
        raise HTTPException(status_code=400, detail="Не указан запрос")

    # Добавляем историю к запросу (последние 10 сообщений)
    if history and isinstance(history, list):
        history_str = "\n".join([f"{msg.get('role', 'unknown')}: {msg.get('content', '')}" for msg in history[-10:]])
        query = f"История диалога:\n{history_str}\n\nТекущий запрос: {query}"

    try:
        if not ORCHESTRATOR_AVAILABLE or _orchestrator is None:
            raise HTTPException(status_code=503, detail="Оркестратор недоступен")

        result = await asyncio.wait_for(
            asyncio.to_thread(_orchestrator.process, query, interface),
            timeout=600.0
        )

        if not result.get("success", False):
            raise HTTPException(status_code=500, detail=result.get("error", "Неизвестная ошибка"))

        answer = result.get("result", "Нет ответа")
        used_agent = result.get("agent", "developer")

        # Сохраняем диалог в векторную память
        if MEMORY_AVAILABLE and _memory is not None:
            try:
                _memory.store(
                    text=f"User: {query}\nAssistant: {answer}",
                    metadata={
                        "type": "dialogue",
                        "query": query,
                        "agent": used_agent,
                        "timestamp": datetime.now().isoformat()
                    }
                )
            except Exception as e:
                logger.warning(f"Не удалось сохранить диалог в память: {e}")

        # Сохраняем в lessons
        try:
            from memory.lesson_saver import save_lesson
            save_lesson(
                query=query,
                response=answer,
                result=answer,
                agent=used_agent
            )
        except Exception as e:
            logger.warning(f"Не удалось сохранить урок: {e}")

        return {
            "success": True,
            "result": answer,
            "agent": used_agent,
            "query": query
        }
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Таймаут обработки запроса (180 секунд)")
    except Exception as e:
        logger.error(f"Ошибка в веб-интерфейсе: {e}")
        raise HTTPException(status_code=500, detail=f"Ошибка обработки: {str(e)}")

@app.get("/status")
async def status():
    return {
        "status": "running",
        "version": "1.0.0",
        "orchestrator_available": ORCHESTRATOR_AVAILABLE,
        "telegram_handler_available": TELEGRAM_HANDLER_AVAILABLE,
        "endpoints": {
            "GET /": "Главная страница",
            "POST /ask": "Отправка запроса ассистенту",
            "GET /status": "Статус системы",
            "GET /health": "Проверка здоровья"
        }
    }

@app.get("/health")
async def health():
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}

@app.get("/api/agents")
async def list_agents():
    if not ORCHESTRATOR_AVAILABLE:
        return {"agents": [], "error": "Оркестратор недоступен"}
    agents = ["economist", "monitor", "purchaser", "accountant", "logistician",
              "sales_manager", "support", "smm", "website", "reporter", "developer"]
    return {"agents": agents, "count": len(agents), "developer_assistant_available": "developer" in agents}

@app.get("/api/files")
async def list_files(path: str = ""):
    try:
        from tools.file_ops import list_directory
        if not path:
            path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        result = list_directory(path)
        files = []
        for line in result.split('\n'):
            line = line.strip()
            if not line:
                continue
            if line.endswith('/'):
                file_type = "directory"
                name = line.rstrip('/')
            else:
                file_type = "file"
                name = line
            full_path = os.path.join(path, name) if path != '.' else name
            files.append({"name": name, "path": full_path, "type": file_type})
        return {"success": True, "files": files, "current_path": path, "count": len(files)}
    except Exception as e:
        logger.error(f"Ошибка получения списка файлов: {e}")
        return {"success": False, "error": str(e), "files": []}

@app.get("/api/file")
async def get_file(path: str):
    try:
        from tools.file_ops import read_file
        if not path:
            raise HTTPException(status_code=400, detail="Не указан путь к файлу")
        content = read_file(path)
        return {"success": True, "content": content, "path": path}
    except Exception as e:
        logger.error(f"Ошибка чтения файла: {e}")
        return {"success": False, "error": str(e), "content": ""}

@app.post("/api/file")
async def save_file(request: Request):
    try:
        from tools.file_ops import write_file
        data = await request.json()
        path = data.get("path", "").strip()
        content = data.get("content", "")
        if not path:
            raise HTTPException(status_code=400, detail="Не указан путь к файлу")
        result = write_file(path, content)
        # фоновая индексация
        try:
            from memory.indexer import index_file
            async def _index_in_background():
                try:
                    chunks_count = index_file(path)
                    logger.info(f"Файл проиндексирован: {path} ({chunks_count} чанков)")
                except Exception as e:
                    logger.error(f"Ошибка индексации файла {path}: {e}")
            asyncio.create_task(_index_in_background())
        except Exception as e:
            logger.warning(f"Ошибка индексации: {e}")
        return {"success": True, "message": result, "path": path}
    except Exception as e:
        logger.error(f"Ошибка сохранения файла: {e}")
        return {"success": False, "error": str(e)}

@app.delete("/api/file")
async def delete_file(path: str):
    try:
        if not os.path.exists(path):
            return {"success": False, "error": f"Файл {path} не существует"}
        os.remove(path)
        if MEMORY_AVAILABLE and _memory is not None:
            _memory.delete_by_filter({"path": path})
        return {"success": True, "message": f"Файл {path} удалён"}
    except Exception as e:
        logger.error(f"Ошибка удаления файла: {e}")
        return {"success": False, "error": str(e)}

@app.post("/api/command")
async def execute_command(request: Request):
    try:
        from tools.shell import run_command
        data = await request.json()
        command = data.get("command", "").strip()
        if not command:
            raise HTTPException(status_code=400, detail="Не указана команда")
        dangerous = ["rm -rf", "format", "del", "shutdown", "reboot"]
        if any(d in command.lower() for d in dangerous):
            return {"success": False, "error": "Команда заблокирована", "output": ""}
        output = run_command(command)
        return {"success": True, "output": output, "command": command}
    except Exception as e:
        logger.error(f"Ошибка выполнения команды: {e}")
        return {"success": False, "error": str(e), "output": ""}

@app.get("/api/lessons")
async def get_lessons(query: str = "", limit: int = 10, agent: str = ""):
    try:
        from memory.lesson_saver import search_lessons
        lessons = search_lessons(query=query, limit=limit, agent=agent if agent else None)
        return {"success": True, "lessons": lessons, "count": len(lessons), "query": query, "agent": agent}
    except Exception as e:
        logger.error(f"Ошибка получения уроков: {e}")
        return {"success": False, "error": str(e), "lessons": []}

@app.post("/api/lessons")
async def save_lesson(request: Request):
    try:
        from memory.lesson_saver import save_lesson as save_lesson_func
        data = await request.json()
        query = data.get("query", "").strip()
        response = data.get("response", "").strip()
        result = data.get("result", "").strip()
        agent = data.get("agent", "developer_assistant").strip()
        if not query or not response:
            raise HTTPException(status_code=400, detail="Не указаны обязательные поля: query, response")
        lesson_id = save_lesson_func(query=query, response=response, result=result, agent=agent)
        return {"success": True, "lesson_id": lesson_id, "message": "Урок успешно сохранён"}
    except Exception as e:
        logger.error(f"Ошибка сохранения урока: {e}")
        return {"success": False, "error": str(e)}

@app.get("/api/lessons/analyze")
async def analyze_lessons():
    try:
        from memory.lesson_saver import analyze_lessons_for_improvements
        report = analyze_lessons_for_improvements()
        return {"success": True, "report": report}
    except Exception as e:
        logger.error(f"Ошибка анализа уроков: {e}")
        return {"success": False, "error": str(e), "report": ""}

@app.post("/api/upload")
async def upload_file(file: UploadFile = File(...)):
    try:
        uploads_dir = os.path.join(os.path.dirname(__file__), "uploads")
        os.makedirs(uploads_dir, exist_ok=True)
        ext = os.path.splitext(file.filename)[1]
        unique_filename = f"{uuid.uuid4().hex}{ext}"
        file_path = os.path.join(uploads_dir, unique_filename)
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        original_name = file.filename
        try:
            from memory.indexer import index_file
            chunks_count = index_file(file_path, metadata={"original_name": original_name})
        except Exception as e:
            logger.warning(f"Индексация не выполнена: {e}")
            chunks_count = 0
        return {"success": True, "message": f"Файл '{original_name}' загружен", "original_name": original_name, "saved_path": file_path, "chunks_count": chunks_count}
    except Exception as e:
        logger.error(f"Ошибка загрузки файла: {e}")
        return {"success": False, "error": str(e)}

@app.post("/api/train")
async def train_assistant(request: Request):
    try:
        data = await request.json()
        path = data.get("path", "").strip()
        recursive = data.get("recursive", False)
        clean = data.get("clean", False)
        if not path:
            raise HTTPException(status_code=400, detail="Не указан путь")
        full_path = os.path.abspath(path)
        if not os.path.exists(full_path):
            raise HTTPException(status_code=404, detail=f"Путь не существует: {path}")
        import threading
        import subprocess
        import sys
        def run_indexing():
            try:
                script_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "scripts", "index_project.py")
                cmd = [sys.executable, script_path, "--path", full_path]
                if recursive:
                    cmd.append("--recursive")
                if clean:
                    cmd.append("--clean")
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
                if result.returncode == 0:
                    logger.info(f"Индексация завершена: {path}")
                else:
                    logger.error(f"Ошибка индексации: {result.stderr}")
            except Exception as e:
                logger.error(f"Ошибка в процессе индексации: {e}")
        thread = threading.Thread(target=run_indexing, daemon=True)
        thread.start()
        return {"success": True, "message": f"Индексация запущена для пути: {path}", "path": path, "recursive": recursive, "clean": clean}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Ошибка запуска обучения: {e}")
        return {"success": False, "error": str(e), "message": "Не удалось запустить индексацию"}

@app.get("/api/status")
async def api_status():
    return {
        "success": True,
        "status": "running",
        "orchestrator_available": ORCHESTRATOR_AVAILABLE,
        "memory_available": MEMORY_AVAILABLE,
        "telegram_handler_available": TELEGRAM_HANDLER_AVAILABLE,
        "current_provider": current_provider,
        "endpoints": {}
    }

@app.post("/api/set_provider")
async def set_provider(request: Request):
    global current_provider
    try:
        data = await request.json()
        provider = data.get("provider", "").strip().lower()
        if provider not in ["ollama", "deepseek"]:
            raise HTTPException(status_code=400, detail="Неподдерживаемый провайдер")
        current_provider = provider
        return {"success": True, "message": f"Провайдер изменён на {provider}", "provider": provider}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Ошибка переключения провайдера: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/feedback")
async def save_feedback(request: Request):
    try:
        data = await request.json()
        data["timestamp"] = datetime.now().isoformat()
        feedback_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
        os.makedirs(feedback_dir, exist_ok=True)
        feedback_file = os.path.join(feedback_dir, "feedback.json")
        try:
            with open(feedback_file, "r", encoding="utf-8") as f:
                feedbacks = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            feedbacks = []
        feedbacks.append(data)
        with open(feedback_file, "w", encoding="utf-8") as f:
            json.dump(feedbacks, f, ensure_ascii=False, indent=2)
        # Если полезный отзыв – сохраняем как урок
        if data.get("rating") == "useful":
            try:
                query = data.get("query", "")
                assistant_response = data.get("assistant_response", "")
                agent_name = data.get("agent", "unknown")
                if query and assistant_response and MEMORY_AVAILABLE and _memory:
                    lesson_text = f"User: {query}\nAssistant: {assistant_response}"
                    _memory.store(
                        text=lesson_text,
                        metadata={
                            "type": "lesson",
                            "agent": agent_name,
                            "rating": "useful",
                            "timestamp": data["timestamp"],
                            "source": "feedback"
                        }
                    )
            except Exception as e:
                logger.error(f"Ошибка сохранения урока из feedback: {e}")
        return {"success": True, "message": "Спасибо за обратную связь!"}
    except Exception as e:
        logger.error(f"Ошибка сохранения feedback: {e}")
        return {"success": False, "error": str(e)}

@app.get("/user", response_class=HTMLResponse)
async def user_chat():
    template_path = os.path.join(templates_dir, "user_chat.html")
    if not os.path.exists(template_path):
        return HTMLResponse(content="<h1>Ошибка: user_chat.html не найден</h1>", status_code=404)
    with open(template_path, "r", encoding="utf-8") as f:
        html_content = f.read()
    return HTMLResponse(content=html_content)

@app.get("/modern", response_class=HTMLResponse)
async def modern_chat():
    template_path = os.path.join(templates_dir, "modern_chat.html")
    if not os.path.exists(template_path):
        return HTMLResponse(content="<h1>Ошибка: modern_chat.html не найден</h1>", status_code=404)
    with open(template_path, "r", encoding="utf-8") as f:
        html_content = f.read()
    return HTMLResponse(content=html_content)

@app.post("/ask_stream")
async def ask_stream(request: Request):
    """
    API endpoint для потоковой отправки запроса (Server-Sent Events).
    """
    data = await request.json()
    query = data.get("query", "").strip()
    interface = data.get("interface", "dev")

    if not query:
        raise HTTPException(status_code=400, detail="Не указан запрос")

    if not ORCHESTRATOR_AVAILABLE or _orchestrator is None:
        raise HTTPException(status_code=503, detail="Оркестратор недоступен")

    async def event_generator():
        try:
            # Имитация потоковой передачи - разбиваем ответ на части
            # В реальности нужно интегрировать с LLM, поддерживающим стриминг
            result = await asyncio.wait_for(
                asyncio.to_thread(_orchestrator.process, query, interface),
                timeout=180.0
            )
            
            if not result.get("success", False):
                yield f"data: {{\"error\": \"{result.get('error', 'Неизвестная ошибка')}\"}}\n\n"
                return
            
            answer = result.get("result", "Нет ответа")
            used_agent = result.get("agent", "developer")
            
            # Отправляем метаданные
            yield f"data: {{\"type\": \"metadata\", \"agent\": \"{used_agent}\"}}\n\n"
            
            # Разбиваем ответ на слова и отправляем по частям
            words = answer.split()
            for i, word in enumerate(words):
                # Имитация задержки
                await asyncio.sleep(0.05)
                yield f"data: {{\"type\": \"chunk\", \"chunk\": \"{word} \", \"index\": {i}}}\n\n"
            
            # Отправляем завершающий сигнал
            yield f"data: {{\"type\": \"complete\", \"total_chunks\": {len(words)}}}\n\n"
            
        except asyncio.TimeoutError:
            yield f"data: {{\"error\": \"Таймаут обработки запроса (180 секунд)\"}}\n\n"
        except Exception as e:
            logger.error(f"Ошибка в стриминге: {e}")
            yield f"data: {{\"error\": \"{str(e)}\"}}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )

# Эндпоинты для переиндексации и управления памятью
@app.post("/api/reindex")
async def reindex(mode: str = "incremental", path: str = None, clean_old: bool = False):
    """
    Запускает переиндексацию памяти.
    
    Параметры:
    - mode: "full" (полная очистка и индексация), "incremental" (инкрементальная, по умолчанию)
    - path: путь для индексации (если None, используется текущая директория проекта)
    - clean_old: очищать старые версии (только для mode="full")
    """
    try:
        import subprocess
        import sys
        import os
        
        # Определяем путь для индексации
        if path is None:
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            index_path = project_root
        else:
            index_path = path
        
        # Формируем команду для индексатора
        cmd = [sys.executable, "memory/indexer.py", "--path", index_path, "--recursive"]
        
        if mode == "full":
            cmd.append("--clean")
            if clean_old and MEMORY_AVAILABLE and _memory:
                try:
                    _memory.clear()
                    logger.info("Память очищена перед полной переиндексацией")
                except Exception as e:
                    logger.error(f"Ошибка очистки памяти: {e}")
        
        # Запускаем индексацию в фоне
        logger.info(f"Запуск переиндексации: mode={mode}, path={index_path}")
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        )
        
        # Не ждём завершения, возвращаем ответ сразу
        return {
            "success": True,
            "message": f"Переиндексация запущена (mode={mode}, path={index_path})",
            "pid": process.pid
        }
        
    except Exception as e:
        logger.error(f"Ошибка запуска переиндексации: {e}")
        return {"success": False, "error": str(e)}

@app.get("/api/memory/stats")
async def get_memory_stats():
    """Возвращает статистику по памяти."""
    try:
        if not MEMORY_AVAILABLE or not _memory:
            return {"success": False, "error": "Память недоступна"}
        
        # Получаем базовую статистику
        stats = {
            "available": True,
            "provider": "Qdrant",
            "collection": "zora_memory"
        }
        
        # Пытаемся получить более детальную статистику
        try:
            # Здесь можно добавить вызов методов памяти для получения статистики
            # Например: stats["total_vectors"] = _memory.get_vector_count()
            stats["message"] = "Память доступна, детальная статистика требует реализации"
        except Exception as e:
            stats["message"] = f"Базовая статистика: {str(e)}"
        
        return {"success": True, "stats": stats}
        
    except Exception as e:
        logger.error(f"Ошибка получения статистики памяти: {e}")
        return {"success": False, "error": str(e)}

@app.post("/api/memory/cleanup")
async def cleanup_memory(days: int = 30):
    """Очищает старые записи из памяти (старше указанного количества дней)."""
    try:
        if not MEMORY_AVAILABLE or not _memory:
            return {"success": False, "error": "Память недоступна"}
        
        # Здесь можно добавить логику очистки старых записей
        # Например: cleaned_count = _memory.cleanup_old_entries(days)
        
        return {
            "success": True,
            "message": f"Очистка памяти (старше {days} дней) требует реализации",
            "note": "Функция очистки старых версий будет реализована в системе версионирования"
        }
        
    except Exception as e:
        logger.error(f"Ошибка очистки памяти: {e}")
        return {"success": False, "error": str(e)}

@app.post("/api/confirm")
async def confirm_action(request: Request):
    """Подтверждение критического действия от Ria."""
    try:
        data = await request.json()
        plan = data.get("plan", [])
        confirm = data.get("confirm", False)
        
        if not confirm:
            return {"success": True, "result": "❌ Действие отменено пользователем"}
        
        if not plan:
            return {"success": False, "error": "Не указан план для выполнения"}
        
        # Выполняем план через DeveloperAssistant
        from agents.developer_assistant import DeveloperAssistant
        assistant = DeveloperAssistant()
        results = assistant._execute_plan(plan)
        
        return {"success": True, "result": "\n".join(results)}
    except Exception as e:
        logger.error(f"Ошибка подтверждения действия: {e}")
        return {"success": False, "error": str(e)}

@app.post("/api/feedback")
async def handle_feedback(request: Request):
    """
    Обрабатывает обратную связь от пользователя.
    Сохраняет полезные диалоги в память для использования в RAG.
    """
    try:
        data = await request.json()
        rating = data.get("rating", "").lower()
        query = data.get("query", "")
        assistant_response = data.get("assistant_response", "")
        agent = data.get("agent", "ria")
        
        logger.info(f"Получена обратная связь: rating={rating}, agent={agent}")
        
        # Сохраняем только полезные ответы
        if rating in ["useful", "good", "positive", "👍", "like"]:
            if not MEMORY_AVAILABLE or not _memory:
                return {"success": False, "error": "Память недоступна для сохранения"}
            
            if query and assistant_response:
                # Формируем текст для сохранения
                text = f"Вопрос: {query}\nОтвет: {assistant_response}"
                
                # Сохраняем в память
                try:
                    _memory.store(
                        text=text,
                        metadata={
                            "type": "good_example",
                            "agent": agent,
                            "rating": rating,
                            "timestamp": datetime.now().isoformat(),
                            "source": "user_feedback"
                        }
                    )
                    logger.info(f"Сохранен полезный диалог в память: {len(text)} символов")
                    
                    return {
                        "success": True,
                        "message": "Полезный диалог сохранен в память",
                        "saved": True
                    }
                except Exception as e:
                    logger.error(f"Ошибка сохранения в память: {e}")
                    return {"success": False, "error": f"Ошибка сохранения: {str(e)}"}
            else:
                return {"success": False, "error": "Отсутствует запрос или ответ"}
        else:
            # Для негативной или нейтральной обратной связи просто логируем
            logger.info(f"Обратная связь не сохранена (рейтинг: {rating})")
            return {
                "success": True,
                "message": "Обратная связь получена",
                "saved": False
            }
            
    except Exception as e:
        logger.error(f"Ошибка обработки обратной связи: {e}")
        return {"success": False, "error": str(e)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8002)
