"""
Веб-интерфейс для ассистента разработчика ZORA.
FastAPI приложение с поддержкой истории диалогов, управления агентами и виджетов.
"""

import logging
import os
import sys
import asyncio
import json
import threading
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

# Импортируем реестр агентов для эндпоинта /api/system/graph
try:
    from core.agent_registry import AGENT_REGISTRY
    AGENT_REGISTRY_AVAILABLE = True
except Exception as e:
    AGENT_REGISTRY = {}
    AGENT_REGISTRY_AVAILABLE = False
    logger.warning(f"⚠️ Реестр агентов не загружен: {e}")


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
    """Редирект на новый дашборд v2 (React)."""
    from starlette.responses import RedirectResponse
    return RedirectResponse(url="/dashboard/v2")

# Раздача статики React-дашборда v2
dashboard_v2_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "dashboard_v2", "dist")
if os.path.exists(dashboard_v2_dir):
    app.mount("/dashboard/assets", StaticFiles(directory=os.path.join(dashboard_v2_dir, "assets")), name="dashboard_v2_assets")

    @app.get("/dashboard/v2", response_class=HTMLResponse)
    async def dashboard_v2_page():
        """Дашборд v2 (React)."""
        index_path = os.path.join(dashboard_v2_dir, "index.html")
        if not os.path.exists(index_path):
            return HTMLResponse(content="<h1>Ошибка: dashboard v2 не собран</h1>", status_code=404)
        with open(index_path, "r", encoding="utf-8") as f:
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
    """API endpoint для отправки запроса с поддержкой истории диалога."""
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
        cpu_count_physical = psutil.cpu_count(logical=False) or psutil.cpu_count()
        cpu_count_logical = psutil.cpu_count(logical=True)
        cpu_count = cpu_count_logical  # для обратной совместимости
        cpu_freq = psutil.cpu_freq()
        cpu_freq_current = cpu_freq.current / 1000 if cpu_freq else 0
        
        # Получаем имя CPU (читаемое)
        cpu_name = "—"
        try:
            import cpuinfo
            cpu_info_data = cpuinfo.get_cpu_info()
            cpu_name = cpu_info_data.get('brand_raw', '—')
        except ImportError:
            try:
                import subprocess
                result = subprocess.run(
                    ['wmic', 'cpu', 'get', 'name'],
                    capture_output=True, text=True, timeout=5
                )
                if result.returncode == 0:
                    lines = result.stdout.strip().split('\n')
                    if len(lines) >= 2:
                        cpu_name = lines[1].strip()
            except:
                import platform
                cpu_name = platform.processor() or "—"
        except:
            import platform
            cpu_name = platform.processor() or "—"
        
        # Получаем температуру CPU
        cpu_temp = ""
        try:
            from monitoring.system_monitor import get_cpu_temperature
            cpu_temp_val = get_cpu_temperature()
            if cpu_temp_val is not None:
                cpu_temp = f"{cpu_temp_val:.0f}"
        except:
            pass
        
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
        
        # GPU — сначала nvidia-smi, затем fallback на gpu_monitor
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
            # Fallback на gpu_monitor
            try:
                from monitoring.gpu_monitor import get_gpu_info
                gpu_info = get_gpu_info()
                if gpu_info.get('gpu_available'):
                    gpu_percent = gpu_info.get('gpu_percent', 0)
                    gpu_memory_used = gpu_info.get('gpu_memory_used', 0) / 1024
                    gpu_memory_total = gpu_info.get('gpu_memory_total', 0) / 1024
                    gpu_name = gpu_info.get('gpu_name', '')
                    gpu_temp = str(gpu_info.get('gpu_temperature', ''))
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
                "cpu_count_physical": cpu_count_physical,
                "cpu_count_logical": cpu_count_logical,
                "cpu_freq_current": cpu_freq_current,
                "cpu_name": cpu_name,
                "cpu_temp": cpu_temp,
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
            from agents.parser_agent import ParserAgent
            async def _index_in_background():
                try:
                    agent = ParserAgent()
                    result = agent.index_single_file(path)
                    if result.get("success"):
                        logger.info(f"Файл проиндексирован: {path}")
                    else:
                        logger.warning(f"Не удалось проиндексировать файл {path}: {result.get('message', '')}")
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
            from agents.parser_agent import ParserAgent
            agent = ParserAgent()
            result = agent.index_single_file(file_path)
            chunks_count = result.get("data", {}).get("chunks", 0)
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
        def run_indexing():
            try:
                from agents.parser_agent import ParserAgent
                agent = ParserAgent()
                result = agent.index_files(full_path, recursive=recursive, clean=clean)
                if result.get("success"):
                    logger.info(f"Индексация завершена: {path}")
                else:
                    logger.error(f"Ошибка индексации: {result.get('message', '')}")
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
    """API endpoint для потоковой отправки запроса (Server-Sent Events)."""
    data = await request.json()
    query = data.get("query", "").strip()
    interface = data.get("interface", "dev")

    if not query:
        raise HTTPException(status_code=400, detail="Не указан запрос")

    if not ORCHESTRATOR_AVAILABLE or _orchestrator is None:
        raise HTTPException(status_code=503, detail="Оркестратор недоступен")

    async def event_generator():
        try:
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
    """Запускает переиндексацию памяти через ParserAgent."""
    try:
        import os
        if path is None:
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            index_path = project_root
        else:
            index_path = path
        
        logger.info(f"Запуск переиндексации: mode={mode}, path={index_path}")
        
        from agents.parser_agent import ParserAgent
        agent = ParserAgent()
        
        if mode == "full":
            if clean_old and MEMORY_AVAILABLE and _memory:
                try:
                    _memory.clear()
                    logger.info("Память очищена перед полной переиндексацией")
                except Exception as e:
                    logger.error(f"Ошибка очистки памяти: {e}")
            result = agent.index_files(index_path, recursive=True, clean=True)
        else:
            result = agent.index_files(index_path, recursive=True, clean=False)
        
        if result.get("success"):
            return {
                "success": True,
                "message": f"Переиндексация завершена (mode={mode}, path={index_path})",
                "stats": result.get("data", {})
            }
        else:
            return {
                "success": False,
                "error": result.get("message", "Неизвестная ошибка")
            }
    except Exception as e:
        logger.error(f"Ошибка запуска переиндексации: {e}")
        return {"success": False, "error": str(e)}

@app.get("/api/memory/stats")
async def get_memory_stats():
    """Возвращает количество векторов в Qdrant."""
    try:
        if not MEMORY_AVAILABLE or not _memory:
            return {"success": False, "vector_count": None, "error": "Память недоступна"}
        
        # Получаем реальное количество точек
        try:
            collection_info = _memory.client.get_collection(_memory.collection_name)
            return {"success": True, "vector_count": collection_info.points_count}
        except Exception as e:
            logger.warning(f"Не удалось получить количество векторов: {e}")
            return {"success": False, "vector_count": None, "error": str(e)}
    except Exception as e:
        logger.error(f"Ошибка получения статистики памяти: {e}")
        return {"success": False, "vector_count": None, "error": str(e)}

@app.post("/api/memory/cleanup")
async def cleanup_memory(days: int = 30):
    """Очищает старые записи из памяти (старше указанного количества дней)."""
    try:
        if not MEMORY_AVAILABLE or not _memory:
            return {"success": False, "error": "Память недоступна"}
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
    """Обрабатывает обратную связь от пользователя."""
    try:
        data = await request.json()
        rating = data.get("rating", "").lower()
        query = data.get("query", "")
        assistant_response = data.get("assistant_response", "")
        agent = data.get("agent", "ria")
        
        logger.info(f"Получена обратная связь: rating={rating}, agent={agent}")
        
        if rating in ["useful", "good", "positive", "👍", "like"]:
            if not MEMORY_AVAILABLE or not _memory:
                return {"success": False, "error": "Память недоступна для сохранения"}
            
            if query and assistant_response:
                text = f"Вопрос: {query}\nОтвет: {assistant_response}"
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

@app.get("/api/system/graph")
async def system_graph():
    """Возвращает граф компонентов системы для дашборда v2."""
    import asyncio
    import subprocess
    import httpx

    nodes = []
    edges = []

    async def check_qdrant():
        """Проверяет Qdrant и возвращает статус и количество векторов."""
        try:
            from monitoring.system_monitor import get_qdrant_vectors_count
            vectors = get_qdrant_vectors_count()
            # Проверяем HTTP — жив ли Qdrant
            async with httpx.AsyncClient(timeout=3) as client:
                r = await client.get("http://localhost:6333/collections")
                if r.status_code == 200:
                    return "healthy", max(vectors, 0)
        except httpx.TimeoutException:
            return "degraded", 0
        except:
            pass
        return "down", 0


    async def check_ollama():
        """Проверяет Ollama и возвращает статус и количество моделей."""
        try:
            async with httpx.AsyncClient(timeout=3) as client:
                r = await client.get("http://localhost:11434/api/tags")
                if r.status_code == 200:
                    models = r.json().get("models", [])
                    return "healthy", len(models)
        except httpx.TimeoutException:
            return "degraded", 0
        except:
            pass
        return "down", 0

    async def check_postgres():
        """Проверяет PostgreSQL."""
        try:
            import asyncpg
            conn = await asyncpg.connect(
                host=os.getenv("POSTGRES_HOST", "localhost"),
                port=int(os.getenv("POSTGRES_PORT", "5432")),
                database=os.getenv("POSTGRES_DB", "zora"),
                user=os.getenv("POSTGRES_USER", "zora"),
                password=os.getenv("POSTGRES_PASSWORD", "zora"),
                timeout=2
            )
            await conn.close()
            return "healthy"
        except ImportError:
            logger.warning("PostgreSQL: asyncpg не установлен")
            return "degraded"
        except asyncpg.exceptions.InvalidPasswordError:
            logger.warning("PostgreSQL: неверный пароль")
            return "degraded"
        except (asyncio.TimeoutError, Exception):
            logger.warning("PostgreSQL check failed (timeout or error)")
            return "degraded"

    # Запускаем все проверки параллельно
    qdrant_task = asyncio.create_task(check_qdrant())
    ollama_task = asyncio.create_task(check_ollama())
    pg_task = asyncio.create_task(check_postgres())

    # 1. Orchestrator
    orch_status = "healthy" if ORCHESTRATOR_AVAILABLE else "down"
    nodes.append({
        "id": "orchestrator",
        "label": "Оркестратор",
        "type": "service",
        "status": orch_status,
        "metrics": {"agents": len(AGENT_REGISTRY) if ORCHESTRATOR_AVAILABLE else 0}
    })

    # 2. Qdrant
    qdrant_status, qdrant_vectors = await qdrant_task
    nodes.append({
        "id": "qdrant",
        "label": "Qdrant",
        "type": "database",
        "status": qdrant_status,
        "metrics": {"vectors": qdrant_vectors}
    })

    # 3. Ollama
    ollama_status, ollama_models = await ollama_task
    nodes.append({
        "id": "ollama",
        "label": "Ollama",
        "type": "service",
        "status": ollama_status,
        "metrics": {"models": ollama_models}
    })

    # 4. DeepSeek API
    deepseek_key = os.getenv("DEEPSEEK_API_KEY", "")
    deepseek_status = "healthy" if deepseek_key else "down"
    nodes.append({
        "id": "deepseek",
        "label": "DeepSeek",
        "type": "external",
        "status": deepseek_status,
        "metrics": {"api_key": len(deepseek_key) if deepseek_key else 0}
    })

    # 5. PostgreSQL
    pg_status = await pg_task
    nodes.append({
        "id": "postgres",
        "label": "PostgreSQL",
        "type": "database",
        "status": pg_status,
        "metrics": {}
    })

    # 6. Web UI (сам сервер — всегда healthy)
    nodes.append({
        "id": "web_ui",
        "label": "Web UI",
        "type": "service",
        "status": "healthy",
        "metrics": {"port": 8002}
    })

    # 7. Docker
    docker_status = "down"
    try:
        r = await asyncio.get_event_loop().run_in_executor(
            None, lambda: subprocess.run(["docker", "info"], capture_output=True, text=True, timeout=3)
        )
        docker_status = "healthy" if r.returncode == 0 else "down"
    except:
        pass
    nodes.append({
        "id": "docker",
        "label": "Docker",
        "type": "service",
        "status": docker_status,
        "metrics": {}
    })

    # 8. 1C OData
    onec_status = "degraded"
    onec_url = os.getenv("ONEC_ODATA_URL", "")
    onec_user = os.getenv("ONEC_ODATA_USER", "")
    onec_pass = os.getenv("ONEC_ODATA_PASSWORD", "")
    if onec_url and onec_user and onec_pass:
        try:
            auth = httpx.BasicAuth(onec_user, onec_pass)
            async with httpx.AsyncClient(timeout=3) as client:
                r = await client.get(onec_url, auth=auth)
                onec_status = "healthy" if 200 <= r.status_code < 300 else "degraded"
        except:
            onec_status = "degraded"
    nodes.append({
        "id": "1c_odata",
        "label": "1C OData",
        "type": "external",
        "status": onec_status,
        "metrics": {"url": len(onec_url) if onec_url else 0}
    })

    # 9. Telegram Bot
    telegram_status = "healthy" if TELEGRAM_HANDLER_AVAILABLE else "down"
    nodes.append({
        "id": "telegram_bot",
        "label": "Telegram Bot",
        "type": "service",
        "status": telegram_status,
        "metrics": {}
    })

    # Позиции для сетки 3×3
    initial_positions = {
        "orchestrator": {"x": 250, "y": 0},
        "deepseek": {"x": 500, "y": 0},
        "docker": {"x": 0, "y": 0},
        "qdrant": {"x": 0, "y": 150},
        "ollama": {"x": 250, "y": 150},
        "1c_odata": {"x": 500, "y": 150},
        "postgres": {"x": 0, "y": 300},
        "web_ui": {"x": 250, "y": 300},
        "telegram_bot": {"x": 500, "y": 300},
    }
    for node in nodes:
        pos = initial_positions.get(node["id"])
        if pos:
            node["position"] = pos

    # Рёбра графа (связи между компонентами)
    edges = [
        {"source": "orchestrator", "target": "qdrant", "label": "векторный поиск"},
        {"source": "orchestrator", "target": "ollama", "label": "LLM"},
        {"source": "orchestrator", "target": "deepseek", "label": "LLM API"},
        {"source": "orchestrator", "target": "postgres", "label": "история"},
        {"source": "web_ui", "target": "orchestrator", "label": "API"},
        {"source": "docker", "target": "qdrant", "label": "контейнер"},
        {"source": "orchestrator", "target": "1c_odata", "label": "данные 1С"},
        {"source": "orchestrator", "target": "telegram_bot", "label": "уведомления"},
    ]

    return {"nodes": nodes, "edges": edges}

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
# Эндпоинты для Дашборда v2 (React)
# ======================================================================

@app.get("/api/filesystem/graph")
async def filesystem_graph():
    """Возвращает граф файловой системы для дашборда v2 с 4 статусами."""
    try:
        import os
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        nodes = []
        edges = []

        # Пытаемся получить информацию о проиндексированных файлах из Qdrant
        indexed_files = {}  # rel_path -> {chunks_count, last_indexed, used_by_agents}
        try:
            if MEMORY_AVAILABLE and _memory is not None:
                # Получаем все точки из Qdrant (с пагинацией)
                from qdrant_client import models
                all_points = []
                next_offset = None
                while True:
                    result = _memory.client.scroll(
                        collection_name=_memory.collection_name,
                        limit=1000,
                        offset=next_offset,
                        with_payload=True,
                    )
                    points, next_offset = result
                    for p in points:
                        payload = p.payload or {}
                        source_path = payload.get("source_path") or payload.get("path", "")
                        if source_path:
                            rel = os.path.relpath(source_path, project_root) if os.path.isabs(source_path) else source_path
                            if rel not in indexed_files:
                                indexed_files[rel] = {
                                    "chunks_count": 0,
                                    "last_indexed": None,
                                    "used_by_agents": set(),
                                }
                            indexed_files[rel]["chunks_count"] += 1
                            ts = payload.get("timestamp") or payload.get("indexed_at")
                            if ts:
                                try:
                                    if isinstance(ts, (int, float)):
                                        ts_dt = datetime.fromtimestamp(ts)
                                    else:
                                        ts_dt = datetime.fromisoformat(str(ts))
                                    if indexed_files[rel]["last_indexed"] is None or ts_dt > indexed_files[rel]["last_indexed"]:
                                        indexed_files[rel]["last_indexed"] = ts_dt
                                except:
                                    pass
                            # Кто использовал этот чанк
                            agent = payload.get("agent") or payload.get("used_by")
                            if agent:
                                indexed_files[rel]["used_by_agents"].add(str(agent))
                    if next_offset is None:
                        break
        except Exception as e:
            logger.warning(f"Не удалось получить данные из Qdrant: {e}")

        # Собираем .py файлы
        for root, dirs, files in os.walk(project_root):
            # Пропускаем скрытые и виртуальные окружения
            dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ('__pycache__', 'node_modules', 'venv', '.venv', 'dist', 'build')]
            for f in files:
                if f.endswith('.py'):
                    full_path = os.path.join(root, f)
                    rel_path = os.path.relpath(full_path, project_root)
                    size_kb = os.path.getsize(full_path) / 1024
                    last_mod_ts = os.path.getmtime(full_path)
                    last_mod_dt = datetime.fromtimestamp(last_mod_ts)

                    # Определяем статус на основе данных из Qdrant
                    file_info = indexed_files.get(rel_path)
                    if file_info:
                        chunks_count = file_info["chunks_count"]
                        last_indexed = file_info["last_indexed"]
                        used_by = list(file_info["used_by_agents"])

                        # Проверяем stale: файл изменён после последней индексации
                        if last_indexed and last_mod_dt > last_indexed:
                            status = "stale"
                        elif len(used_by) > 0:
                            status = "indexed_used"
                        else:
                            status = "indexed_unused"
                    else:
                        # Файл не найден в Qdrant
                        status = "not_indexed"
                        chunks_count = 0
                        used_by = []
                        last_indexed = None

                    nodes.append({
                        "id": rel_path,
                        "label": f,
                        "type": "file",
                        "size_kb": round(size_kb, 1),
                        "last_modified": last_mod_dt.isoformat(),
                        "status": status,
                        "chunks_count": chunks_count,
                        "used_by_agents": used_by,
                        "last_indexed": last_indexed.isoformat() if last_indexed else None,
                        "dependencies": [],
                    })
                    if len(nodes) > 200:
                        break
            if len(nodes) > 200:
                break

        return {"nodes": nodes, "edges": edges}
    except Exception as e:
        logger.error(f"Ошибка получения графа файлов: {e}")
        return {"nodes": [], "edges": []}


@app.get("/api/datapipeline")
async def data_pipeline():
    """Возвращает статус конвейера данных для дашборда v2."""
    try:
        sources = [
            {
                "name": "1C OData",
                "status": "idle",
                "throughput_chunks_per_hour": 0,
                "queue_size": 0,
                "last_run": datetime.now().isoformat(),
                "error_rate": 0,
            },
            {
                "name": "ITS Parser",
                "status": "idle",
                "throughput_chunks_per_hour": 0,
                "queue_size": 0,
                "last_run": datetime.now().isoformat(),
                "error_rate": 0,
            },
            {
                "name": "File Indexer",
                "status": "idle",
                "throughput_chunks_per_hour": 0,
                "queue_size": 0,
                "last_run": datetime.now().isoformat(),
                "error_rate": 0,
            },
        ]
        # Пытаемся получить реальные статусы из парсера
        try:
            agent = _get_parser_agent()
            progress = agent.get_progress()
            if progress and progress.get("is_running"):
                sources[1]["status"] = "active"
        except:
            pass
        return {"sources": sources}
    except Exception as e:
        logger.error(f"Ошибка получения конвейера данных: {e}")
        return {"sources": []}


@app.get("/api/metrics")
async def metrics_history(limit: int = 100):
    """Возвращает историю метрик для графиков дашборда v2."""
    try:
        import psutil
        # Генерируем тестовые данные на основе текущих метрик
        import random
        now = datetime.now()
        metrics_list = []
        for i in range(min(limit, 60)):
            ts = now.timestamp() - (limit - i) * 60
            metrics_list.append({
                "timestamp": datetime.fromtimestamp(ts).isoformat(),
                "cpu_percent": psutil.cpu_percent(interval=None) + random.uniform(-5, 5),
                "memory_percent": psutil.virtual_memory().percent + random.uniform(-3, 3),
                "disk_percent": psutil.disk_usage('/').percent,
            })
        return {"metrics": metrics_list}
    except Exception as e:
        logger.error(f"Ошибка получения истории метрик: {e}")
        return {"metrics": []}


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
async def run_rag_evaluation(
    evaluate_faithfulness: bool = False,
    faithfulness_sample_size: int = 50,
    ci: bool = False
):
    """
    Запускает оценку RAG в фоне через Inspector.

    Query-параметры:
        evaluate_faithfulness (bool): Оценивать faithfulness (по умолч. false).
        faithfulness_sample_size (int): Размер выборки для faithfulness (по умолч. 50).
        ci (bool): CI-режим (маленькая выборка + проверка порога, по умолч. false).
    """
    try:
        from agents.inspector import get_inspector
        inspector = get_inspector()
        result = inspector.run_rag_evaluation_async(
            evaluate_faithfulness=evaluate_faithfulness,
            faithfulness_sample_size=faithfulness_sample_size if evaluate_faithfulness else None,
            ci=ci
        )
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

# ======================================================================
# Эндпоинты для графа агентов и статуса конкретного агента
# ======================================================================

@app.get("/api/knowledge_graph")
async def knowledge_graph():
    """Возвращает граф связей агентов с файлами (звёздная система)."""
    try:
        nodes = []
        edges = []
        seen_agents = set()
        seen_files = set()

        # Получаем данные из Qdrant
        if MEMORY_AVAILABLE and _memory is not None:
            from qdrant_client import models
            all_points = []
            next_offset = None
            while True:
                result = _memory.client.scroll(
                    collection_name=_memory.collection_name,
                    limit=1000,
                    offset=next_offset,
                    with_payload=True,
                )
                points, next_offset = result
                for p in points:
                    payload = p.payload or {}
                    agent = payload.get("agent") or payload.get("used_by")
                    source_path = payload.get("source_path") or payload.get("path", "")
                    if agent and source_path:
                        agent_id = f"agent:{agent}"
                        file_id = f"file:{source_path}"
                        if agent_id not in seen_agents:
                            seen_agents.add(agent_id)
                            nodes.append({
                                "id": agent_id,
                                "label": str(agent),
                                "type": "agent",
                            })
                        if file_id not in seen_files:
                            seen_files.add(file_id)
                            nodes.append({
                                "id": file_id,
                                "label": str(source_path).split("/").pop() or str(source_path),
                                "type": "file",
                            })
                        edges.append({
                            "source": agent_id,
                            "target": file_id,
                            "type": "uses",
                        })
                        # Обратная связь: файл используется агентом
                        edges.append({
                            "source": file_id,
                            "target": agent_id,
                            "type": "used_by",
                        })
                if next_offset is None:
                    break

        return {"nodes": nodes, "edges": edges}
    except Exception as e:
        logger.error(f"Ошибка получения knowledge graph: {e}")
        return {"nodes": [], "edges": []}


@app.get("/api/agents/graph")
async def agents_graph(history: str = ""):
    """Возвращает граф агентов с активными трассами для дашборда v2.
    
    Query-параметры:
        history (str): "1h" или "today" — подгрузить исторические трассы за период.
    """
    try:
        from core.agent_registry import get_all_agents_info
        
        # Получаем информацию о всех агентах
        agents_info = get_all_agents_info()
        if isinstance(agents_info, list):
            agents_dict = {a.get("role", ""): a for a in agents_info}
        else:
            agents_dict = agents_info
        nodes = []
        
        # Узел оркестратора
        nodes.append({
            "id": "orchestrator",
            "label": "Оркестратор",
            "type": "orchestrator",
            "status": "healthy" if ORCHESTRATOR_AVAILABLE else "down",
            "metrics": {"active_traces": 0, "total_agents": len(agents_dict)}
        })
        
        # Узел User
        nodes.append({
            "id": "user",
            "label": "Пользователь",
            "type": "user",
            "status": "healthy",
            "metrics": {}
        })
        
        # Узел Ассистент (Ria)
        nodes.append({
            "id": "developer",
            "label": "Ассистент",
            "type": "developer",
            "status": "healthy" if ORCHESTRATOR_AVAILABLE else "down",
            "metrics": {}
        })

        # Узлы агентов

        for role, info in agents_dict.items():
            agent_status = "idle"
            current_task = None
            if _orchestrator:
                try:
                    status_data = _orchestrator.get_agent_status(role)
                    agent_status = status_data.get("status", "idle")
                    current_task = status_data.get("current_task")
                except Exception:
                    pass  # остаётся idle
            
            nodes.append({
                "id": role,
                "label": info.get("display_name", role),
                "type": "agent",
                "status": agent_status,
                "current_task": current_task,
                "description": info.get("description", ""),
            })
        
        # Рёбра
        edges = [
            {"source": "user", "target": "developer", "label": "запрос"},
            {"source": "developer", "target": "orchestrator", "label": "API"},
        ]
        edges += [{"source": "orchestrator", "target": role, "label": ""} for role in agents_dict.keys()]
        
        # Трассы: пытаемся получить из trace_handler, если он есть
        active_traces = []
        recent_traces = []
        try:
            from core.orchestrator import trace_handler
            if trace_handler and hasattr(trace_handler, 'get_active_traces'):
                active_traces = trace_handler.get_active_traces()
                recent_traces = trace_handler.get_recent_traces(10)
        except Exception:
            pass  # трассировка ещё не настроена
        
        # Форматируем активные трассы
        traces_list = []
        for t in active_traces:
            traces_list.append({
                "run_id": t["run_id"],
                "query": t.get("query", "")[:100],
                "steps": [s["agent"] for s in t.get("steps", [])],
                "started_at": t.get("started_at", ""),
            })
        
        # Фильтрация recent_traces по параметру history
        if history:
            now_ts = datetime.now().timestamp() * 1000
            cutoff = now_ts - (3600_000 if history == "1h" else 86400_000)
            recent_traces = [
                t for t in recent_traces
                if t.get("started_at", 0) >= cutoff
            ]
        
        return {
            "nodes": nodes,
            "edges": edges,
            "active_traces": traces_list,
            "recent_traces": recent_traces,
        }
    except Exception as e:
        logger.error(f"Ошибка получения графа агентов: {e}")
        return {"nodes": [], "edges": [], "active_traces": [], "recent_traces": []}

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
        
        discover_agents()
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

@app.get("/api/parsing/status")
async def parsing_status():
    """Статус парсинга с прогрессом (использует синглтон парсера)."""
    try:
        agent = _get_parser_agent()
        progress = agent.get_progress()
        last_result = agent.get_last_parsing_result()
        return {
            "success": True,
            "data": {
                "progress": progress,
                "last_result": last_result
            }
        }
    except Exception as e:
        logger.error(f"Ошибка получения статуса парсинга: {e}")
        return {"success": False, "error": str(e), "data": {}}

@app.get("/api/widgets/parsing")
async def widget_parsing():
    """Статус парсинга (парсер) — для дашборда (использует синглтон парсера)."""
    try:
        agent = _get_parser_agent()
        progress = agent.get_progress()
        last_result = agent.get_last_parsing_result()
        data = {
            "progress": progress,
            "last_result": last_result
        }
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

# Глобальный синглтон парсера для сохранения состояния прогресса между вызовами
_parser_agent_instance = None
_parser_agent_lock = threading.Lock()

def _get_parser_agent():
    """Возвращает синглтон ParserAgent."""
    global _parser_agent_instance
    if _parser_agent_instance is None:
        with _parser_agent_lock:
            if _parser_agent_instance is None:
                from agents.parser_agent import ParserAgent
                _parser_agent_instance = ParserAgent()
    return _parser_agent_instance

# ======================================================================
# ДОБАВЛЕННЫЕ ЭНДПОИНТЫ УПРАВЛЕНИЯ ФОНОВЫМИ АГЕНТАМИ И ЛОГАМИ
# ======================================================================

@app.post("/api/agent/parser/start")
async def start_parser_background():
    """Запускает парсер: запускает планировщик (если не запущен) и выполняет все задачи немедленно."""
    try:
        agent = _get_parser_agent()
        agent.start_background_scheduler()
        def _run_tasks():
            try:
                agent.run_all_once()
            except Exception as e:
                logger.error(f"Ошибка в run_all_once: {e}")
        thread = threading.Thread(target=_run_tasks, daemon=True)
        thread.start()
        return {"success": True, "message": "Парсер запущен", "status": "running"}
    except Exception as e:
        logger.error(f"Ошибка запуска парсера: {e}")
        return {"success": False, "error": str(e)}

@app.post("/api/agent/parser/stop")
async def stop_parser_background():
    """Останавливает фоновый планировщик парсера."""
    try:
        agent = _get_parser_agent()
        agent.stop_background_scheduler()
        return {"success": True, "message": "Фоновый парсер остановлен"}
    except Exception as e:
        logger.error(f"Ошибка остановки парсера: {e}")
        return {"success": False, "error": str(e)}

@app.post("/api/index_file")
async def index_single_file(file_path: str):
    """Запускает индексацию одного файла."""
    try:
        if not os.path.exists(file_path):
            return {"success": False, "error": "Файл не найден"}
        from agents.parser_agent import ParserAgent
        agent = ParserAgent()
        result = agent.index_single_file(file_path)
        return {"success": True, "message": f"Индексация запущена для {file_path}", "result": result}
    except Exception as e:
        logger.error(f"Ошибка индексации файла: {e}")
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
        return {"success": True, "message": "Оператор 1С запущен (заглушка)"}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/api/agent/operator_1c/stop")
async def stop_operator_1c():
    """Останавливает оператора 1С (заглушка)."""
    return {"success": True, "message": "Оператор 1С остановлен (заглушка)"}

@app.get("/api/agent/{role}/logs")
async def get_agent_logs(role: str, limit: int = 50):
    """Возвращает последние логи агента."""
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
# WebSocket для дашборда v2 (телеметрия в реальном времени)
# ======================================================================

from fastapi import WebSocket, WebSocketDisconnect

@app.websocket("/ws/telemetry")
async def websocket_telemetry(websocket: WebSocket):
    """
    WebSocket-эндпоинт для потоковой передачи телеметрии дашборду v2.
    Отправляет обновления ресурсов, статусов агентов, алертов и трейсов выполнения.
    """
    await websocket.accept()
    logger.info("WebSocket /ws/telemetry: клиент подключён")

    # Подписка на события трассировки от TraceHandler
    from core.orchestrator import trace_handler

    async def trace_callback(event: str, data: dict):
        """Отправляет события трассировки клиенту."""
        try:
            msg = {
                "type": "execution_trace",
                "event": event,
                "data": data,
            }
            await websocket.send_json(msg)
        except Exception:
            pass  # Если клиент отключился — игнорируем

    trace_handler.subscribe(trace_callback)

    try:
        while True:
            try:
                # 1. Системные ресурсы
                import psutil
                import subprocess

                cpu_percent = psutil.cpu_percent(interval=0.3)
                mem = psutil.virtual_memory()
                disk = psutil.disk_usage('/')

                # GPU
                gpu_percent = 0
                gpu_memory_used = 0
                gpu_memory_total = 0
                try:
                    result = subprocess.run(
                        ['nvidia-smi', '--query-gpu=utilization.gpu,memory.used,memory.total', '--format=csv,noheader,nounits'],
                        capture_output=True, text=True, timeout=3
                    )
                    if result.returncode == 0:
                        parts = result.stdout.strip().split(',')
                        if len(parts) >= 3:
                            gpu_percent = float(parts[0].strip())
                            gpu_memory_used = float(parts[1].strip()) / 1024
                            gpu_memory_total = float(parts[2].strip()) / 1024
                except:
                    pass

                resources_msg = {
                    "type": "system_resources",
                    "data": {
                        "cpu_percent": cpu_percent,
                        "memory_percent": mem.percent,
                        "memory_used_gb": round(mem.used / (1024**3), 1),
                        "memory_total_gb": round(mem.total / (1024**3), 1),
                        "disk_percent": disk.percent,
                        "disk_used_gb": round(disk.used / (1024**3), 1),
                        "disk_total_gb": round(disk.total / (1024**3), 1),
                        "gpu_percent": gpu_percent,
                        "gpu_memory_used_gb": round(gpu_memory_used, 1),
                        "gpu_memory_total_gb": round(gpu_memory_total, 1),
                    }
                }
                await websocket.send_json(resources_msg)

                # 2. Статусы агентов
                try:
                    from core.agent_registry import get_all_agents_info
                    agents_info = get_all_agents_info()
                    for agent_info in agents_info:
                        role = agent_info.get("role", "")
                        state = "idle"
                        if ORCHESTRATOR_AVAILABLE and _orchestrator is not None:
                            try:
                                status = _orchestrator.get_agent_status(role)
                                if status:
                                    state = status.get("status", "idle")
                            except:
                                pass
                        agent_msg = {
                            "type": "agent_status",
                            "data": {
                                "agent": role,
                                "state": state,
                                "display_name": agent_info.get("display_name", role),
                            }
                        }
                        await websocket.send_json(agent_msg)
                except:
                    pass

                # 3. Алерты (проверка здоровья)
                alerts = []
                if mem.percent > 90:
                    alerts.append({
                        "severity": "critical",
                        "message": f"Критическая загрузка RAM: {mem.percent}%",
                        "timestamp": datetime.now().isoformat()
                    })
                elif mem.percent > 80:
                    alerts.append({
                        "severity": "warning",
                        "message": f"Высокая загрузка RAM: {mem.percent}%",
                        "timestamp": datetime.now().isoformat()
                    })
                if disk.percent > 90:
                    alerts.append({
                        "severity": "critical",
                        "message": f"Критическая заполненность диска: {disk.percent}%",
                        "timestamp": datetime.now().isoformat()
                    })
                if cpu_percent > 90:
                    alerts.append({
                        "severity": "warning",
                        "message": f"Высокая загрузка CPU: {cpu_percent}%",
                        "timestamp": datetime.now().isoformat()
                    })
                # Алерты по падениям сервисов
                try:
                    import httpx
                    async with httpx.AsyncClient(timeout=5.0) as client:
                        r = await client.get("http://localhost:11434/api/tags")
                        if r.status_code != 200:
                            alerts.append({
                                "severity": "error",
                                "message": "Ollama недоступен",
                                "timestamp": datetime.now().isoformat()
                            })
                except httpx.ConnectError:
                    alerts.append({
                        "severity": "error",
                        "message": "Ollama недоступен",
                        "timestamp": datetime.now().isoformat()
                    })
                except Exception as e:
                    logger.warning(f"Ollama check failed: {e}")
                if not MEMORY_AVAILABLE:
                    alerts.append({
                        "severity": "error",
                        "message": "Qdrant (память) недоступен",
                        "timestamp": datetime.now().isoformat()
                    })
                # Алерты по ошибкам агентов (из трекера статусов)
                try:
                    from core.orchestrator import agent_status_tracker
                    for role, status in agent_status_tracker.get_all_statuses().items():
                        if status.get("status") == "error":
                            alerts.append({
                                "severity": "error",
                                "message": f"Агент {role}: {status.get('current_task', 'ошибка')}",
                                "timestamp": datetime.now().isoformat()
                            })
                except:
                    pass
                for alert in alerts:
                    await websocket.send_json({
                        "type": "alert",
                        "data": alert
                    })

                # Ожидание перед следующим обновлением
                await asyncio.sleep(2)

            except WebSocketDisconnect:
                raise
            except Exception as e:
                logger.error(f"WebSocket ошибка при отправке: {e}")
                await asyncio.sleep(5)

    except WebSocketDisconnect:
        logger.info("WebSocket /ws/telemetry: клиент отключён")
    except Exception as e:
        logger.error(f"WebSocket /ws/telemetry ошибка: {e}")
    finally:
        try:
            await websocket.close()
        except:
            pass


# ======================================================================
# Эндпоинт для оценки RAG через Opik
# ======================================================================

@app.post("/api/rag/evaluate_opik")
async def evaluate_rag_opik():
    """Запускает оценку RAG и логирует результаты в Opik."""
    try:
        import opik
        import json
        
        # Загружаем тестовый датасет
        dataset_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "rag_test_set.json")
        if not os.path.exists(dataset_path):
            return {"success": False, "error": "Файл data/rag_test_set.json не найден"}
        
        with open(dataset_path, "r", encoding="utf-8") as f:
            dataset = json.load(f)
        
        @opik.track
        def run_rag_query(query):
            # Вызываем реальный RAG-пайплайн
            if MEMORY_AVAILABLE and _memory:
                result = _memory.hybrid_search(query, limit=5)
                return result
            return []
        
        results_summary = []
        for item in dataset:
            query = item.get("query", "")
            expected_chunk_id = item.get("chunk_id", "")
            if not query:
                continue
            
            retrieved = run_rag_query(query)
            retrieved_chunk_ids = [r.get("chunk_id", "") for r in retrieved]
            
            # Логируем в Opik
            try:
                opik.log_rag_evaluation(
                    query=query,
                    retrieved_chunks=retrieved_chunk_ids,
                    expected_chunks=[expected_chunk_id]
                )
            except Exception as opik_err:
                logger.warning(f"Opik logging warning: {opik_err}")
            
            results_summary.append({
                "query": query[:50],
                "expected_chunk_id": expected_chunk_id,
                "retrieved_count": len(retrieved),
                "retrieved_chunk_ids": retrieved_chunk_ids[:3]
            })
        
        return {
            "success": True,
            "message": f"Оценка запущена для {len(results_summary)} запросов, результаты доступны в Opik",
            "results": results_summary
        }
    except Exception as e:
        logger.error(f"Ошибка оценки RAG через Opik: {e}")
        return {"success": False, "error": str(e)}


@app.post("/api/rag/evaluate_laminar")
async def evaluate_rag_laminar():
    """Запускает оценку RAG и отправляет результаты в Laminar."""
    try:
        from tools.rag_eval_laminar import run_rag_evaluation
        run_rag_evaluation()
        return {"success": True, "message": "Оценка RAG запущена, результаты доступны в Laminar"}
    except Exception as e:
        logger.error(f"Ошибка оценки RAG через Laminar: {e}")
        return {"success": False, "error": str(e)}


# ======================================================================
# Запуск
# ======================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8002)
