"""
Веб-интерфейс для ассистента разработчика ZORA.
FastAPI приложение с поддержкой истории диалогов, управления агентами и виджетов.
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

# Импорт модуля истории чатов
from core.chat_history import (
    init_db, get_chats, create_chat, update_chat_name, delete_chat,
    get_messages, add_message, delete_messages
)

# Добавляем путь к проекту
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logger = logging.getLogger(__name__)

app = FastAPI(title="ZORA Assistant Web Interface", version="1.0.0")

# Инициализация БД при старте
@app.on_event("startup")
async def startup_event():
    """Инициализирует таблицы истории чатов при запуске."""
    try:
        await init_db()
        logger.info("✅ История чатов инициализирована (PostgreSQL)")
    except Exception as e:
        logger.warning(f"⚠️ История чатов недоступна: {e}")
        logger.warning("⚠️ Система будет работать без сохранения истории диалогов")

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

# ======================================================================
# ТРИ ОСНОВНЫХ HTML-ЭНДПОИНТА
# ======================================================================

@app.get("/modern", response_class=HTMLResponse)
async def modern_chat():
    """Чат разработчика (Ria IDE)."""
    template_path = os.path.join(templates_dir, "modern_chat.html")
    if not os.path.exists(template_path):
        return HTMLResponse(content="<h1>Ошибка: modern_chat.html не найден</h1>", status_code=404)
    with open(template_path, "r", encoding="utf-8") as f:
        html_content = f.read()
    return HTMLResponse(content=html_content)

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page():
    """Дашборд мониторинга (управление агентами, метрики, логи)."""
    dashboard_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "monitoring", "templates", "dashboard.html")
    if not os.path.exists(dashboard_path):
        return HTMLResponse(content="<h1>Ошибка: dashboard.html не найден</h1>", status_code=404)
    with open(dashboard_path, "r", encoding="utf-8") as f:
        html_content = f.read()
    return HTMLResponse(content=html_content)

@app.get("/user", response_class=HTMLResponse)
async def user_chat():
    """Чат пользователя (с виджетами справа)."""
    template_path = os.path.join(templates_dir, "user_chat.html")
    if not os.path.exists(template_path):
        return HTMLResponse(content="<h1>Ошибка: user_chat.html не найден</h1>", status_code=404)
    with open(template_path, "r", encoding="utf-8") as f:
        html_content = f.read()
    return HTMLResponse(content=html_content)

@app.get("/")
async def root_redirect():
    """Перенаправляет / на /modern."""
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/modern", status_code=307)

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
        reasoning = result.get("reasoning")
        mode = result.get("mode")
        pending_plan = result.get("pending_plan")

        response = {
            "success": True,
            "result": answer,
            "agent": used_agent,
            "query": query,
            "reasoning": reasoning
        }
        if mode:
            response["mode"] = mode
        if pending_plan:
            response["pending_plan"] = pending_plan
        return response
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Таймаут обработки запроса (600 секунд)")
    except Exception as e:
        logger.error(f"Ошибка в веб-интерфейсе: {e}")
        raise HTTPException(status_code=500, detail=f"Ошибка обработки: {str(e)}")

@app.get("/status")
async def status():
    # Проверяем доступность сервисов
    ollama_available = False
    qdrant_available = MEMORY_AVAILABLE
    postgres_available = False
    deepseek_available = False
    
    # Проверка Ollama
    try:
        import httpx
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get("http://localhost:11434/api/tags")
            ollama_available = r.status_code == 200
    except:
        ollama_available = False
    
    # Проверка PostgreSQL
    try:
        from core.chat_history import get_pool
        pool = await get_pool()
        if pool:
            async with pool.acquire() as conn:
                await conn.execute("SELECT 1")
                postgres_available = True
    except:
        postgres_available = False
    
    # Проверка DeepSeek V4
    try:
        from connectors.deepseek_v4_client import get_v4_client
        v4 = get_v4_client()
        deepseek_available = v4.is_available()
    except:
        deepseek_available = False
    
    return {
        "status": "running",
        "version": "1.0.0",
        "orchestrator_available": ORCHESTRATOR_AVAILABLE,
        "telegram_handler_available": TELEGRAM_HANDLER_AVAILABLE,
        "memory_available": MEMORY_AVAILABLE,
        "ollama_available": ollama_available,
        "qdrant_available": qdrant_available,
        "postgres_available": postgres_available,
        "deepseek_available": deepseek_available,
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

# ======================================================================
# Эндпоинты для дашборда мониторинга
# ======================================================================

@app.get("/api/health")
async def api_health():
    """Возвращает системную информацию для дашборда."""
    try:
        import psutil
        import subprocess
        
        # CPU
        cpu_percent = psutil.cpu_percent(interval=0.5)
        cpu_count = psutil.cpu_count()
        cpu_count_logical = psutil.cpu_count(logical=True)
        cpu_freq = psutil.cpu_freq()
        cpu_freq_current = cpu_freq.current / 1000 if cpu_freq else 0
        
        # RAM
        mem = psutil.virtual_memory()
        memory_percent = mem.percent
        memory_total = mem.total / (1024**3)
        memory_free = mem.available / (1024**3)
        
        # Disk
        disk = psutil.disk_usage('/')
        disk_percent = disk.percent
        disk_total = disk.total / (1024**3)
        disk_used = disk.used / (1024**3)
        
        # GPU
        gpu_percent = 0
        gpu_memory_used = 0
        gpu_memory_total = 0
        gpu_name = ""
        gpu_temp = ""
        try:
            result = subprocess.run(
                ['nvidia-smi', '--query-gpu=utilization.gpu,memory.used,memory.total,name,temperature.gpu', '--format=csv,noheader,nounits'],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                parts = result.stdout.strip().split(',')
                if len(parts) >= 5:
                    gpu_percent = float(parts[0].strip())
                    gpu_memory_used = float(parts[1].strip()) / 1024
                    gpu_memory_total = float(parts[2].strip()) / 1024
                    gpu_name = parts[3].strip()
                    gpu_temp = parts[4].strip()
        except:
            pass
        
        # Health score
        health_score = 100
        issues = []
        if memory_percent > 90:
            health_score -= 20
            issues.append("Критическая загрузка RAM")
        if disk_percent > 90:
            health_score -= 20
            issues.append("Критическая заполненность диска")
        if cpu_percent > 90:
            health_score -= 10
            issues.append("Высокая загрузка CPU")
        
        return {
            "system": {
                "cpu_percent": cpu_percent,
                "cpu_count": cpu_count,
                "cpu_count_logical": cpu_count_logical,
                "cpu_freq_current": cpu_freq_current,
                "cpu_name": gpu_name or "—",
                "cpu_temp": "",
                "gpu_percent": gpu_percent,
                "gpu_name": gpu_name,
                "gpu_memory_used": gpu_memory_used,
                "gpu_memory_total": gpu_memory_total,
                "gpu_temp": gpu_temp,
                "memory_percent": memory_percent,
                "memory_total": memory_total,
                "memory_free": memory_free,
                "disk_percent": disk_percent,
                "disk_total": disk_total,
                "disk_used": disk_used,
                "disk_name": "C:",
                "disk_temp": ""
            },
            "health_score": max(0, health_score),
            "issues": issues,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"Ошибка получения health: {e}")
        return {"system": {}, "health_score": 0, "issues": [str(e)]}

@app.get("/api/zora_status")
async def api_zora_status():
    """Возвращает статус компонентов ZORA для дашборда."""
    try:
        # Проверка компонентов
        components = {
            "core": ORCHESTRATOR_AVAILABLE,
            "web": True,
            "agents": ORCHESTRATOR_AVAILABLE,
            "orchestrator": ORCHESTRATOR_AVAILABLE,
            "docker": False,
            "ollama": False,
            "qdrant": MEMORY_AVAILABLE
        }
        
        # Проверка Ollama
        try:
            import httpx
            async with httpx.AsyncClient(timeout=2.0) as client:
                r = await client.get("http://localhost:11434/api/tags")
                components["ollama"] = r.status_code == 200
        except:
            pass
        
        # Проверка Docker
        try:
            import subprocess
            result = subprocess.run(['docker', 'info'], capture_output=True, text=True, timeout=3)
            components["docker"] = result.returncode == 0
        except:
            pass
        
        working = sum(1 for v in components.values() if v)
        total = len(components)
        
        status = "running" if working == total else ("partial" if working > 0 else "stopped")
        
        return {
            "success": True,
            "status": status,
            "message": f"Работает {working} из {total} компонентов",
            "components": components,
            "working_components": working,
            "total_components": total,
            "qdrant_vectors": "—",
            "uptime": datetime.now().strftime("%H:%M")
        }
    except Exception as e:
        logger.error(f"Ошибка получения статуса ZORA: {e}")
        return {"success": False, "error": str(e)}

@app.get("/api/agents")
async def list_agents():
    """Возвращает список агентов с детальной информацией для дашборда."""
    try:
        # Используем динамический реестр агентов
        try:
            from core.agent_registry import get_all_agents_info, AGENT_REGISTRY
            agents_info_list = get_all_agents_info()
        except ImportError:
            agents_info_list = []
        
        agents_info = {}
        for agent_info in agents_info_list:
            role_value = agent_info.get("role", "")
            agents_info[role_value] = {
                "state": "idle",
                "display_name": agent_info.get("display_name", role_value),
                "description": agent_info.get("description", ""),
                "tools": agent_info.get("tools", []),
                "current_task": None,
                "task_progress": 0,
                "last_activity": None,
                "errors_count": 0
            }
        
        # Если оркестратор доступен, пытаемся получить реальные статусы
        if ORCHESTRATOR_AVAILABLE and _orchestrator is not None:
            try:
                for role_value in agents_info:
                    status = _orchestrator.get_agent_status(role_value)
                    if status and status.get("status") != "unknown":
                        agents_info[role_value].update({
                            "state": status.get("status", "idle"),
                            "current_task": status.get("current_task"),
                            "last_activity": status.get("last_activity"),
                        })
                    else:
                        # Создаём агента, чтобы он появился в оркестраторе
                        _orchestrator._get_or_create_agent(role_value)
            except Exception as e:
                logger.warning(f"Не удалось получить статусы агентов: {e}")
        
        available = sum(1 for a in agents_info.values() if a.get("state") not in ("unavailable",))
        
        return {
            "success": True,
            "agents": agents_info,
            "available_agents": available,
            "total_agents": len(agents_info)
        }
    except Exception as e:
        logger.error(f"Ошибка получения списка агентов: {e}")
        return {"success": False, "error": str(e), "agents": {}, "available_agents": 0, "total_agents": 0}

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
        # Проверяем только начало команды, чтобы не блокировать python -c "del x"
        dangerous_prefixes = ["rm -rf", "format ", "shutdown", "reboot", "del ", "rd ", "rmdir "]
        cmd_lower = command.lower().strip()
        if any(cmd_lower.startswith(d) for d in dangerous_prefixes):
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

@app.post("/api/search")
async def search_history(request: Request):
    """Поиск по истории диалогов в Qdrant."""
    data = await request.json()
    query = data.get("query", "").strip()
    limit = data.get("limit", 10)
    
    if not query:
        return {"success": False, "error": "Пустой запрос", "results": []}
    
    try:
        if not MEMORY_AVAILABLE or not _memory:
            return {"success": False, "error": "Память недоступна", "results": []}
        
        results = _memory.search(query=query, limit=limit)
        formatted = []
        for r in results:
            formatted.append({
                "text": r.get("text", ""),
                "score": r.get("score", 0),
                "metadata": r.get("metadata", {})
            })
        return {"success": True, "results": formatted, "query": query}
    except Exception as e:
        logger.error(f"Ошибка поиска: {e}")
        return {"success": False, "error": str(e), "results": []}

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
        
        # Добавляем хэш плана в confirmed_plans, чтобы при повторном вызове
        # (через оркестратор) план выполнился без повторного запроса подтверждения
        import json as _json
        plan_hash = _json.dumps(plan, sort_keys=True)
        assistant.confirmed_plans.add(plan_hash)
        
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

# ========== Эндпоинты для истории чатов (PostgreSQL) ==========

@app.get("/api/chats")
async def api_get_chats(user_id: str = "default"):
    """Возвращает список чатов пользователя."""
    try:
        chats = await get_chats(user_id)
        return {"success": True, "chats": chats}
    except Exception as e:
        logger.error(f"Ошибка получения чатов: {e}")
        return {"success": False, "error": str(e), "chats": []}

@app.post("/api/chats")
async def api_create_chat(request: Request):
    """Создаёт новый чат."""
    try:
        data = await request.json()
        chat_id = data.get("chat_id") or f"chat_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        name = data.get("name", "Новый чат")
        user_id = data.get("user_id", "default")
        await create_chat(chat_id, name, user_id)
        return {"success": True, "chat_id": chat_id}
    except Exception as e:
        logger.error(f"Ошибка создания чата: {e}")
        return {"success": False, "error": str(e)}

@app.delete("/api/chats/{chat_id}")
async def api_delete_chat(chat_id: str):
    """Удаляет чат."""
    try:
        await delete_chat(chat_id)
        return {"success": True}
    except Exception as e:
        logger.error(f"Ошибка удаления чата: {e}")
        return {"success": False, "error": str(e)}

@app.put("/api/chats/{chat_id}")
async def api_update_chat(chat_id: str, request: Request):
    """Обновляет название чата."""
    try:
        data = await request.json()
        name = data.get("name")
        if name:
            await update_chat_name(chat_id, name)
        return {"success": True}
    except Exception as e:
        logger.error(f"Ошибка обновления чата: {e}")
        return {"success": False, "error": str(e)}

@app.get("/api/chats/{chat_id}/messages")
async def api_get_messages(chat_id: str, limit: int = 50):
    """Возвращает сообщения чата."""
    try:
        messages = await get_messages(chat_id, limit)
        return {"success": True, "messages": messages}
    except Exception as e:
        logger.error(f"Ошибка получения сообщений: {e}")
        return {"success": False, "error": str(e), "messages": []}

@app.post("/api/chats/{chat_id}/messages")
async def api_add_message(chat_id: str, request: Request):
    """Добавляет сообщение в чат."""
    try:
        data = await request.json()
        message_id = data.get("message_id") or f"msg_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        role = data.get("role", "user")
        content = data.get("content", "")
        agent = data.get("agent")
        await add_message(chat_id, message_id, role, content, agent)
        return {"success": True}
    except Exception as e:
        logger.error(f"Ошибка добавления сообщения: {e}")
        return {"success": False, "error": str(e)}

@app.delete("/api/chats/{chat_id}/messages")
async def api_delete_messages(chat_id: str):
    """Удаляет все сообщения чата."""
    try:
        await delete_messages(chat_id)
        return {"success": True}
    except Exception as e:
        logger.error(f"Ошибка удаления сообщений: {e}")
        return {"success": False, "error": str(e)}

@app.get("/api/system/stats")
async def system_stats():
    """Возвращает статистику использования памяти и VRAM."""
    try:
        import psutil
        import subprocess
        
        # RAM
        ram = psutil.virtual_memory()
        
        # VRAM (для NVIDIA GPU через nvidia-smi)
        vram_used = 0
        vram_total = 0
        try:
            result = subprocess.run(
                ['nvidia-smi', '--query-gpu=memory.used,memory.total', '--format=csv,noheader,nounits'],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                parts = result.stdout.strip().split(',')
                if len(parts) == 2:
                    vram_used = int(parts[0].strip())
                    vram_total = int(parts[1].strip())
        except:
            pass
        
        return {
            "ram_percent": ram.percent,
            "ram_used": ram.used // (1024**2),
            "ram_total": ram.total // (1024**2),
            "vram_percent": (vram_used / vram_total * 100) if vram_total else 0,
            "vram_used": vram_used,
            "vram_total": vram_total
        }
    except Exception as e:
        logger.error(f"Ошибка получения статистики: {e}")
        return {"ram_percent": 0, "vram_percent": 0}

# ======================================================================
# Эндпоинты Инспектора (Supervisor)
# ======================================================================

@app.get("/api/inspector/stats/{agent_name}")
async def inspector_stats(agent_name: str):
    """Статистика работы агента."""
    try:
        from agents.inspector import get_inspector
        inspector = get_inspector()
        stats = inspector.get_agent_stats(agent_name)
        return {"success": True, "stats": stats}
    except Exception as e:
        logger.error(f"Ошибка получения статистики инспектора: {e}")
        return {"success": False, "error": str(e)}

@app.post("/api/inspector/analyze/{agent_name}")
async def inspector_analyze(agent_name: str):
    """Анализ ошибок агента."""
    try:
        from agents.inspector import get_inspector
        inspector = get_inspector()
        report = inspector.analyze_errors(agent_name)
        return {"success": True, "report": report}
    except Exception as e:
        logger.error(f"Ошибка анализа инспектора: {e}")
        return {"success": False, "error": str(e)}

@app.post("/api/inspector/tests/{agent_name}")
async def inspector_run_tests(agent_name: str):
    """Запуск тестов агента."""
    try:
        from agents.inspector import get_inspector
        inspector = get_inspector()
        results = inspector.run_tests(agent_name)
        return {"success": True, "results": results}
    except Exception as e:
        logger.error(f"Ошибка запуска тестов: {e}")
        return {"success": False, "error": str(e)}

@app.post("/api/inspector/suggest/{agent_name}")
async def inspector_suggest(agent_name: str):
    """Предложение улучшения промпта."""
    try:
        from agents.inspector import get_inspector
        inspector = get_inspector()
        suggestion = inspector.suggest_prompt_improvement(agent_name)
        return {"success": True, "suggestion": suggestion}
    except Exception as e:
        logger.error(f"Ошибка генерации предложения: {e}")
        return {"success": False, "error": str(e)}

@app.post("/api/inspector/learn")
async def inspector_learn():
    """Запускает цикл обучения инспектора."""
    try:
        from agents.inspector import get_inspector
        inspector = get_inspector()
        result = inspector.run_learning_cycle()
        return {"success": True, "result": result}
    except Exception as e:
        logger.error(f"Ошибка цикла обучения: {e}")
        return {"success": False, "error": str(e)}

@app.post("/api/inspector/abtest")
async def inspector_abtest():
    """Запускает A/B тестирование промптов."""
    try:
        from agents.inspector import get_inspector
        inspector = get_inspector()
        result = inspector.run_ab_tests()
        return {"success": True, "results": result}
    except Exception as e:
        logger.error(f"Ошибка A/B теста: {e}")
        return {"success": False, "error": str(e)}

@app.post("/api/inspector/apply")
async def inspector_apply():
    """Применяет улучшения промптов."""
    try:
        from agents.inspector import get_inspector
        inspector = get_inspector()
        result = inspector.apply_improvements(confirmed_only=True)
        return {"success": True, "applied": result}
    except Exception as e:
        logger.error(f"Ошибка применения улучшений: {e}")
        return {"success": False, "error": str(e)}

@app.post("/api/inspector/autofix")
async def inspector_autofix():
    """Автоматическое исправление промптов при повторяющихся ошибках."""
    try:
        from agents.inspector import get_inspector
        inspector = get_inspector()
        result = inspector.auto_fix_prompts()
        return {"success": True, "fixed": result}
    except Exception as e:
        logger.error(f"Ошибка автоисправления: {e}")
        return {"success": False, "error": str(e)}

# ======================================================================
# Эндпоинты RAG Evaluation
# ======================================================================

@app.get("/api/rag/metrics")
async def get_rag_metrics():
    """Возвращает последние метрики RAG через Inspector."""
    try:
        from agents.inspector import get_inspector
        inspector = get_inspector()
        return inspector.get_rag_metrics()
    except Exception as e:
        logger.error(f"Ошибка получения метрик RAG: {e}")
        return {"success": False, "error": str(e)}

@app.post("/api/rag/evaluate")
async def run_rag_evaluation():
    """Запускает оценку RAG в фоне через Inspector."""
    try:
        from agents.inspector import get_inspector
        inspector = get_inspector()
        result = inspector.run_rag_evaluation_async()
        return result
    except Exception as e:
        logger.error(f"Ошибка запуска оценки RAG: {e}")
        return {"success": False, "error": str(e)}

@app.post("/api/rag/generate_dataset")
async def generate_rag_dataset():
    """Генерирует тестовый датасет для RAG из чанков в Qdrant."""
    try:
        from agents.inspector import get_inspector
        inspector = get_inspector()
        result = inspector.run_dataset_generation_async()
        return result
    except Exception as e:
        logger.error(f"Ошибка запуска генерации датасета: {e}")
        return {"success": False, "error": str(e)}

@app.get("/api/rag/dataset_stats")
async def rag_dataset_stats():
    """Возвращает статистику по тестовому датасету RAG."""
    try:
        from agents.inspector import get_inspector
        inspector = get_inspector()
        return inspector.get_dataset_stats()
    except Exception as e:
        logger.error(f"Ошибка получения статистики датасета: {e}")
        return {"success": False, "error": str(e)}


# ======================================================================
# Эндпоинты Vision (qwen3-vl:4b)
# ======================================================================

@app.post("/api/vision/check")
async def vision_check(request: Request):
    """Проверяет скриншот через vision-модель."""
    try:
        data = await request.json()
        image_path = data.get("image_path")
        task = data.get("task", "Что изображено на скриншоте?")

        if not image_path:
            return {"success": False, "error": "Не указан путь к изображению"}

        from connectors.vision_client import vision_client
        result = vision_client.analyze_screenshot(image_path, task)
        return result
    except Exception as e:
        logger.error(f"Ошибка vision-проверки: {e}")
        return {"success": False, "error": str(e)}

@app.post("/api/vision/capture")
async def vision_capture():
    """Делает скриншот и проверяет его."""
    try:
        from agents.inspector import get_inspector
        inspector = get_inspector()
        result = inspector.capture_and_check()
        return {"success": True, "result": result}
    except Exception as e:
        logger.error(f"Ошибка захвата экрана: {e}")
        return {"success": False, "error": str(e)}

# ======================================================================
# Эндпоинты для дубликатов и сиротских файлов
# ======================================================================

@app.get("/api/duplicates/find")
async def duplicates_find():
    """Находит дубликаты файлов."""
    try:
        from tools.cleanup_duplicates import get_duplicate_report
        report = get_duplicate_report()
        return {"success": True, "report": report}
    except Exception as e:
        logger.error(f"Ошибка поиска дубликатов: {e}")
        return {"success": False, "error": str(e)}

@app.post("/api/duplicates/cleanup")
async def duplicates_cleanup():
    """Удаляет дубликаты файлов."""
    try:
        from tools.cleanup_duplicates import remove_duplicates
        result = remove_duplicates()
        return {"success": True, "result": result}
    except Exception as e:
        logger.error(f"Ошибка удаления дубликатов: {e}")
        return {"success": False, "error": str(e)}

@app.get("/api/orphans/find")
async def orphans_find():
    """Находит сиротские файлы (не импортируемые нигде)."""
    try:
        from tools.cleanup_duplicates import find_orphan_files
        report = find_orphan_files()
        return {"success": True, "report": report}
    except Exception as e:
        logger.error(f"Ошибка поиска сиротских файлов: {e}")
        return {"success": False, "error": str(e)}

# ======================================================================
# Эндпоинты планировщика
# ======================================================================

@app.get("/api/scheduler/status")
async def scheduler_status():
    """Статус планировщика фоновых задач."""
    try:
        from core.scheduler import scheduler
        return {"success": True, "status": scheduler.get_status()}
    except Exception as e:
        logger.error(f"Ошибка получения статуса планировщика: {e}")
        return {"success": False, "error": str(e)}

@app.post("/api/scheduler/start")
async def scheduler_start():
    """Запускает планировщик."""
    try:
        from core.scheduler import scheduler
        scheduler.start()
        return {"success": True, "message": "Планировщик запущен"}
    except Exception as e:
        logger.error(f"Ошибка запуска планировщика: {e}")
        return {"success": False, "error": str(e)}

@app.post("/api/scheduler/stop")
async def scheduler_stop():
    """Останавливает планировщик."""
    try:
        from core.scheduler import scheduler
        await scheduler.stop()
        return {"success": True, "message": "Планировщик остановлен"}
    except Exception as e:
        logger.error(f"Ошибка остановки планировщика: {e}")
        return {"success": False, "error": str(e)}

@app.post("/api/scheduler/run/{task_name}")
async def scheduler_run_task(task_name: str):
    """Запускает задачу немедленно."""
    try:
        from core.scheduler import scheduler
        result = scheduler.run_now(task_name)
        return {"success": True, "result": result}
    except Exception as e:
        logger.error(f"Ошибка запуска задачи: {e}")
        return {"success": False, "error": str(e)}

# ======================================================================
# 2.1 Эндпоинт для получения reasoning
# ======================================================================
@app.get("/api/reasoning/{chat_id}")
async def get_reasoning(chat_id: str):
    """Возвращает последние рассуждения Ria для чата."""
    try:
        from memory import memory
        results = memory.search(query="РАССУЖДЕНИЯ", limit=5, types=["dialogue_fragment"])
        reasoning_list = []
        for r in results:
            text = r.get("text", "")
            if "РАССУЖДЕНИЯ" in text:
                reasoning_list.append({
                    "text": text[:500],
                    "timestamp": r.get("metadata", {}).get("timestamp")
                })
        return {"success": True, "reasoning": reasoning_list}
    except Exception as e:
        return {"success": False, "error": str(e)}

# ======================================================================
# Эндпоинты для инструментов разработки (анализ кода, тесты, git)
# ======================================================================

@app.post("/api/analyze_code")
async def api_analyze_code():
    """Анализирует код проекта."""
    try:
        from tools.code_analyzer import analyze_project
        result = analyze_project()
        return {"success": True, "result": result}
    except ImportError:
        logger.warning("Модуль code_analyzer не найден")
        return {"success": False, "error": "Модуль не реализован", "message": "Анализатор кода временно недоступен"}
    except Exception as e:
        logger.error(f"Ошибка анализа кода: {e}")
        return {"success": False, "error": str(e)}

@app.post("/api/run_tests")
async def api_run_tests():
    """Запускает тесты проекта."""
    try:
        from tools.test_runner import run_all_tests
        result = run_all_tests()
        return {"success": True, "result": result}
    except ImportError:
        logger.warning("Модуль test_runner не найден")
        return {"success": False, "error": "Модуль не реализован", "message": "Тесты временно недоступны"}
    except Exception as e:
        logger.error(f"Ошибка запуска тестов: {e}")
        return {"success": False, "error": str(e)}

@app.get("/api/git_status")
async def api_git_status():
    """Возвращает статус Git репозитория."""
    try:
        from tools.git_tools import get_git_status
        result = get_git_status()
        return {"success": True, "output": result}
    except ImportError:
        logger.warning("Модуль git_tools не найден")
        return {"success": False, "error": "Модуль не реализован", "output": "Git инструменты временно недоступны"}
    except Exception as e:
        logger.error(f"Ошибка получения Git статуса: {e}")
        return {"success": False, "error": str(e)}

# (Страница управления агентами удалена — функционал перенесён в /dashboard)

# ======================================================================
# Эндпоинт для получения статуса конкретного агента
# ======================================================================

@app.get("/api/agents/{agent_name}")
async def get_agent_status(agent_name: str):
    """Возвращает статус конкретного агента."""
    try:
        from core.agent_registry import get_agent_info
        agent_info = get_agent_info(agent_name)
        if not agent_info:
            return {"success": False, "error": f"Агент '{agent_name}' не найден"}
        
        result = {
            "success": True,
            "agent": agent_info,
            "state": "idle",
            "current_task": None,
            "last_activity": None
        }
        
        # Если оркестратор доступен, пытаемся получить реальный статус
        if ORCHESTRATOR_AVAILABLE and _orchestrator is not None:
            try:
                status = _orchestrator.get_agent_status(agent_name)
                if status and status.get("status") != "unknown":
                    result.update({
                        "state": status.get("status", "idle"),
                        "current_task": status.get("current_task"),
                        "last_activity": status.get("last_activity"),
                    })
                else:
                    # Создаём агента, чтобы он появился в оркестраторе
                    _orchestrator._get_or_create_agent(agent_name)
            except Exception as e:
                logger.warning(f"Не удалось получить статус агента {agent_name}: {e}")
        
        return result
    except Exception as e:
        logger.error(f"Ошибка получения статуса агента {agent_name}: {e}")
        return {"success": False, "error": str(e)}

# ======================================================================
# Эндпоинты для редактирования системных промптов
# ======================================================================

@app.get("/api/agent/{role}/prompt")
async def get_agent_prompt(role: str):
    """Возвращает текущий системный промпт агента."""
    try:
        from core.roles import get_system_prompt
        prompt = get_system_prompt(role)
        return {"success": True, "role": role, "prompt": prompt}
    except Exception as e:
        logger.error(f"Ошибка получения промпта для {role}: {e}")
        return {"success": False, "error": str(e)}

@app.post("/api/agent/{role}/prompt")
async def save_agent_prompt(role: str, request: Request):
    """Сохраняет кастомный системный промпт агента."""
    try:
        data = await request.json()
        prompt = data.get("prompt", "").strip()
        if not prompt:
            return {"success": False, "error": "Промпт не может быть пустым"}
        
        from core.roles import save_custom_prompt
        result = save_custom_prompt(role, prompt)
        if result:
            return {"success": True, "message": f"Промпт для {role} сохранён"}
        else:
            return {"success": False, "error": "Ошибка сохранения промпта"}
    except Exception as e:
        logger.error(f"Ошибка сохранения промпта для {role}: {e}")
        return {"success": False, "error": str(e)}

@app.post("/api/agents/reload")
async def reload_agents():
    """Перезагружает реестр агентов и пересоздаёт оркестратор."""
    global _orchestrator, ORCHESTRATOR_AVAILABLE
    try:
        from core.agent_registry import discover_agents, AGENT_REGISTRY
        from core.orchestrator import ZoraOrchestrator
        
        # Переоткрываем реестр
        discover_agents()
        
        # Создаём новый оркестратор
        _orchestrator = ZoraOrchestrator()
        ORCHESTRATOR_AVAILABLE = True
        
        logger.info("✅ Агенты перезагружены")
        return {"success": True, "message": "Агенты перезагружены", "count": len(AGENT_REGISTRY)}
    except Exception as e:
        logger.error(f"Ошибка перезагрузки агентов: {e}")
        return {"success": False, "error": str(e)}

# ======================================================================
# Эндпоинты для виджетов дашборда (данные от агентов)
# ======================================================================

@app.get("/api/widgets/balances")
async def widget_balances():
    """Балансы счетов (логист)."""
    try:
        from agents.logistician import Logistician
        agent = Logistician()
        data = agent.get_balances()
        return {"success": True, "data": data}
    except Exception as e:
        logger.error(f"Ошибка получения балансов: {e}")
        return {"success": False, "error": str(e), "data": {}}

@app.get("/api/widgets/orders")
async def widget_orders():
    """Статистика заказов (менеджер по продажам)."""
    try:
        from agents.sales_consultant import SalesConsultant
        agent = SalesConsultant()
        data = agent.get_order_stats()
        return {"success": True, "data": data}
    except Exception as e:
        logger.error(f"Ошибка получения статистики заказов: {e}")
        return {"success": False, "error": str(e), "data": {}}

@app.get("/api/widgets/parsing")
async def widget_parsing():
    """Статус парсинга (парсер)."""
    try:
        from agents.parser_agent import ParserAgent
        agent = ParserAgent()
        data = agent.get_last_parsing_result()
        return {"success": True, "data": data}
    except Exception as e:
        logger.error(f"Ошибка получения статуса парсинга: {e}")
        return {"success": False, "error": str(e), "data": {}}

@app.get("/api/widgets/finance")
async def widget_finance():
    """Финансовая статистика (экономист)."""
    try:
        from agents.economist import Economist
        agent = Economist()
        data = agent.get_financial_stats()
        return {"success": True, "data": data}
    except Exception as e:
        logger.error(f"Ошибка получения финансовой статистики: {e}")
        return {"success": False, "error": str(e), "data": {}}

@app.get("/api/widgets/bank")
async def widget_bank():
    """Банковские счета (бухгалтер)."""
    try:
        from agents.accountant import Accountant
        agent = Accountant()
        data = agent.get_bank_balances()
        return {"success": True, "data": data}
    except Exception as e:
        logger.error(f"Ошибка получения банковских счетов: {e}")
        return {"success": False, "error": str(e), "data": {}}

@app.get("/api/widgets/purchases")
async def widget_purchases():
    """Статистика закупок (менеджер по закупкам)."""
    try:
        from agents.purchaser import Purchaser
        agent = Purchaser()
        data = agent.get_purchase_stats()
        return {"success": True, "data": data}
    except Exception as e:
        logger.error(f"Ошибка получения статистики закупок: {e}")
        return {"success": False, "error": str(e), "data": {}}

# ======================================================================
# ДОБАВЛЕННЫЕ ЭНДПОИНТЫ УПРАВЛЕНИЯ ФОНОВЫМИ АГЕНТАМИ И ЛОГАМИ
# ======================================================================

@app.post("/api/agent/parser/start")
async def start_parser_background():
    """Запускает фоновый планировщик парсера."""
    try:
        from agents.parser_agent import ParserAgent
        agent = ParserAgent()
        agent.start_background_scheduler()
        return {"success": True, "message": "Фоновый парсер запущен"}
    except Exception as e:
        logger.error(f"Ошибка запуска парсера: {e}")
        return {"success": False, "error": str(e)}

@app.post("/api/agent/parser/stop")
async def stop_parser_background():
    """Останавливает фоновый планировщик парсера."""
    try:
        from agents.parser_agent import ParserAgent
        agent = ParserAgent()
        agent.stop_background_scheduler()
        return {"success": True, "message": "Фоновый парсер остановлен"}
    except Exception as e:
        logger.error(f"Ошибка остановки парсера: {e}")
        return {"success": False, "error": str(e)}

@app.post("/api/agent/parser/task/{task_name}")
async def run_parser_task(task_name: str):
    """Ручной запуск конкретной задачи парсера."""
    try:
        from agents.parser_agent import ParserAgent
        agent = ParserAgent()
        if task_name == "parse_its":
            res = agent.parse_its_docs()
        elif task_name == "fetch_1c":
            res = agent.fetch_1c_rest_data()
        elif task_name == "parse_suppliers":
            res = agent.parse_supplier_sites()
        else:
            return {"success": False, "error": "Неизвестная задача"}
        return {"success": res.get("success", False), "message": res.get("message", "")}
    except Exception as e:
        logger.error(f"Ошибка запуска задачи парсера: {e}")
        return {"success": False, "error": str(e)}

@app.post("/api/agent/operator_1c/start")
async def start_operator_1c():
    """Запускает фонового оператора 1С (заглушка)."""
    try:
        # реальная реализация может быть добавлена позже, пока заглушка
        return {"success": True, "message": "Оператор 1С запущен (заглушка)"}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/api/agent/operator_1c/stop")
async def stop_operator_1c():
    """Останавливает оператора 1С (заглушка)."""
    return {"success": True, "message": "Оператор 1С остановлен (заглушка)"}

@app.get("/api/agent/{role}/logs")
async def get_agent_logs(role: str, limit: int = 50):
    """
    Возвращает последние логи агента.
    Для парсера читает data/parsing_log.json, для остальных — logs/zora.log.
    """
    try:
        if role in ("parser", "parser_agent"):
            log_path = "data/parsing_log.json"
            if os.path.exists(log_path):
                with open(log_path, "r", encoding="utf-8") as f:
                    log_data = json.load(f)
                logs = "\n".join([str(entry) for entry in log_data[-limit:]])
                return {"success": True, "logs": logs}
            else:
                return {"success": True, "logs": "Лог парсинга пока пуст"}
        else:
            log_file = "logs/zora.log"
            if os.path.exists(log_file):
                with open(log_file, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                    return {"success": True, "logs": "".join(lines[-limit:])}
            else:
                return {"success": True, "logs": "Лог-файл не найден"}
    except Exception as e:
        logger.error(f"Ошибка получения логов для {role}: {e}")
        return {"success": False, "error": str(e)}

# ======================================================================
# Запуск
# ======================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8002)