#!/usr/bin/env python3
"""
ЕДИНЫЙ ФАЙЛ ЗАПУСКА ZORA (АСИНХРОННАЯ ВЕРСИЯ С ПЛАНИРОВЩИКОМ)
Объединяет все компоненты системы с автоматической проверкой и запуском зависимостей,
а также управляет фоновыми агентами по расписанию.
"""

import os
import sys
import logging
import socket
import subprocess
import time
import threading
import requests
import webbrowser
import asyncio
import io
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime

# Загрузка переменных окружения из .env файла
# Сначала удаляем OLLAMA_HOST из os.environ, чтобы системная переменная не переопределила .env
os.environ.pop("OLLAMA_HOST", None)
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))
# Принудительно устанавливаем OLLAMA_HOST из .env (если он там есть)
_env_ollama = None
with open(os.path.join(os.path.dirname(__file__), '.env'), 'r', encoding='utf-8') as _f:
    for _line in _f:
        _line = _line.strip()
        if _line.startswith('OLLAMA_HOST='):
            _env_ollama = _line.split('=', 1)[1].strip().strip('"').strip("'")
            break
if _env_ollama:
    os.environ["OLLAMA_HOST"] = _env_ollama

# Устанавливаем кодировку UTF-8 для stdout/stderr на Windows
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
    os.environ["PYTHONUTF8"] = "1"

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Глобальная ссылка на лаунчер для доступа из API
_launcher_instance = None

def get_launcher():
    return _launcher_instance


class SystemChecker:
    """Проверка состояния системы перед запуском."""
    
    def __init__(self):
        self.checks = {}
        
    async def check_docker(self) -> Dict[str, Any]:
        """Асинхронно проверяет доступность Docker."""
        try:
            result = await asyncio.to_thread(subprocess.run,
                ['docker', '--version'],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                return {
                    "available": True,
                    "version": result.stdout.strip(),
                    "error": None
                }
        except Exception as e:
            return {
                "available": False,
                "version": None,
                "error": str(e)
            }
        
        return {
            "available": False,
            "version": None,
            "error": "Docker не найден"
        }
    
    async def check_qdrant(self) -> Dict[str, Any]:
        """Асинхронно проверяет доступность Qdrant (удалённого или локального)."""
        qdrant_host = os.getenv("QDRANT_HOST", "localhost")
        qdrant_port = int(os.getenv("QDRANT_PORT", "6333"))
        qdrant_url = f"http://{qdrant_host}:{qdrant_port}"
        try:
            response = await asyncio.to_thread(requests.get, qdrant_url, timeout=5)
            if response.status_code == 200:
                return {
                    "available": True,
                    "status": "running",
                    "host": qdrant_host,
                    "port": qdrant_port,
                    "error": None
                }
        except Exception as e:
            return {
                "available": False,
                "status": "stopped",
                "host": qdrant_host,
                "port": qdrant_port,
                "error": str(e)
            }
        
        return {
            "available": False,
            "status": "unknown",
            "error": "Qdrant недоступен"
        }
    
    async def check_ollama(self) -> Dict[str, Any]:
        """Асинхронно проверяет доступность Ollama."""
        try:
            ollama_host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
            # Нормализуем URL: добавляем http:// если отсутствует
            if not ollama_host.startswith(("http://", "https://")):
                ollama_host = "http://" + ollama_host
            ollama_url = f"{ollama_host}/api/tags"
            
            response = await asyncio.to_thread(requests.get, ollama_url, timeout=5)
            if response.status_code == 200:
                models = [m['name'] for m in response.json().get('models', [])]
                return {
                    "available": True,
                    "models": models,
                    "error": None,
                    "host": ollama_host
                }
        except Exception as e:
            return {
                "available": False,
                "models": [],
                "error": str(e)
            }
        
        return {
            "available": False,
            "models": [],
            "error": "Ollama недоступен"
        }
    
    async def check_port(self, port: int) -> bool:
        """Асинхронно проверяет доступность порта."""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2)
            result = await asyncio.to_thread(sock.connect_ex, ('localhost', port))
            sock.close()
            return result == 0
        except:
            return False
    
    async def check_python_deps(self) -> Dict[str, Any]:
        """Асинхронно проверяет наличие необходимых Python зависимостей."""
        required_packages = [
            'fastapi', 'uvicorn', 'requests', 'qdrant-client',
            'langgraph', 'langchain', 'openai', 'python-dotenv',
            'apscheduler'
        ]
        
        missing = []
        for package in required_packages:
            try:
                if package == 'python-dotenv':
                    __import__('dotenv')
                elif package == 'apscheduler':
                    __import__('apscheduler')
                else:
                    __import__(package.replace('-', '_'))
            except ImportError:
                missing.append(package)
        
        return {
            "available": len(missing) == 0,
            "missing": missing,
            "error": f"Отсутствуют пакеты: {', '.join(missing)}" if missing else None
        }
    
    async def run_all_checks(self):
        """Асинхронно выполняет все проверки."""
        logger.info("🔍 Проверка состояния системы ZORA...")
        
        checks = {
            "docker": await self.check_docker(),
            "qdrant": await self.check_qdrant(),
            "ollama": await self.check_ollama(),
            "python_deps": await self.check_python_deps(),
            "port_8002": {"available": not await self.check_port(8002), "error": "Порт свободен" if not await self.check_port(8002) else "Порт занят"}
        }
        
        all_available = all(check["available"] for check in checks.values())
        
        result = {
            "timestamp": datetime.now().isoformat(),
            "all_available": all_available,
            "checks": checks
        }
        
        logger.info("📊 Результаты проверки:")
        for name, check in checks.items():
            status = "✅" if check["available"] else "❌"
            error = check.get("error", "OK")
            logger.info(f"  {status} {name}: {error}")
        
        if all_available:
            logger.info("🎉 Все компоненты системы доступны!")
        else:
            logger.warning("⚠️ Некоторые компоненты недоступны. Система будет работать с ограниченной функциональностью.")
        
        return result


class ServiceManager:
    """Менеджер сервисов для автоматического запуска зависимостей."""
    
    def __init__(self):
        qdrant_host = os.getenv("QDRANT_HOST", "localhost")
        qdrant_port = int(os.getenv("QDRANT_PORT", "6333"))
        qdrant_container = os.getenv("QDRANT_CONTAINER", "zora_qdrant")
        qdrant_volume = os.getenv("QDRANT_VOLUME", f"{qdrant_container}_storage")
        
        self.services = {
            'qdrant': {
                'name': 'Qdrant (Память)',
                'host': qdrant_host,
                'port': qdrant_port,
                'container_name': qdrant_container,
                'volume': qdrant_volume,
                'check_url': f"http://{qdrant_host}:{qdrant_port}",
                'start_cmd': ['docker', 'start', qdrant_container],
                'stop_cmd': ['docker', 'stop', qdrant_container],
                'is_docker': True,
                'remote': qdrant_host != "localhost"
            },
            'ollama': {
                'name': 'Ollama (LLM)',
                'port': 11434,
                'check_url': f"{os.getenv('OLLAMA_HOST', 'http://localhost:11434')}/api/tags",
                'start_cmd': None,
                'stop_cmd': None,
                'is_docker': False,
                'remote': True
            }
        }
        
        # Нормализуем URL для Ollama в check_url
        ollama_host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
        if not ollama_host.startswith(("http://", "https://")):
            ollama_host = "http://" + ollama_host
        self.services['ollama']['check_url'] = f"{ollama_host}/api/tags"
        
        self.checker = SystemChecker()
    
    async def start_service(self, service_name: str) -> bool:
        """Асинхронно запускает указанный сервис."""
        if service_name not in self.services:
            logger.error(f"Неизвестный сервис: {service_name}")
            return False
        
        service = self.services[service_name]
        logger.info(f"▶ Запуск сервиса: {service['name']}")
        
        try:
            response = await asyncio.to_thread(requests.get, service['check_url'], timeout=3)
            if response.status_code == 200:
                logger.info(f"✅ {service['name']} уже запущен")
                return True
        except:
            pass
        
        if service.get('remote', False):
            logger.warning(f"⚠️ {service['name']} находится на удалённом хосте и должен быть запущен вручную")
            return False
        
        if service['start_cmd'] and service['is_docker']:
            try:
                docker_check = await self.checker.check_docker()
                if not docker_check['available']:
                    logger.error(f"❌ Docker недоступен: {docker_check.get('error')}")
                    return False
                
                result = await asyncio.to_thread(subprocess.run,
                    ['docker', 'ps', '-a', '--filter', f'name=^{service["container_name"]}$', '--format', '{{.Names}}'],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                
                if result.stdout.strip():
                    await asyncio.to_thread(subprocess.run, ['docker', 'start', service['container_name']], capture_output=True, timeout=10)
                else:
                    run_cmd = [
                        'docker', 'run', '-d', '--name', service['container_name'],
                        '-p', f"{service['port']}:6333",
                        '-v', f"{service['volume']}:/qdrant/storage",
                        '--restart', 'unless-stopped',
                        'qdrant/qdrant:latest'
                    ]
                    await asyncio.to_thread(subprocess.run, run_cmd, capture_output=True, timeout=30)
                
                logger.info(f"⏳ Ожидание запуска {service['name']}...")
                for _ in range(10):
                    try:
                        response = await asyncio.to_thread(requests.get, service['check_url'], timeout=3)
                        if response.status_code == 200:
                            logger.info(f"✅ {service['name']} успешно запущен")
                            return True
                    except:
                        await asyncio.sleep(2)
                
                logger.error(f"❌ Не удалось запустить {service['name']}")
                return False
                
            except Exception as e:
                logger.error(f"❌ Ошибка запуска {service['name']}: {e}")
                return False
        
        return False
    
    async def stop_service(self, service_name: str) -> bool:
        """Асинхронно останавливает указанный сервис."""
        if service_name not in self.services:
            logger.error(f"Неизвестный сервис: {service_name}")
            return False
        
        service = self.services[service_name]
        
        if service.get('remote', False):
            logger.warning(f"⚠️ {service['name']} находится на удалённом хосте, остановка невозможна")
            return False
        
        if service['stop_cmd']:
            try:
                logger.info(f"🛑 Остановка сервиса: {service['name']}")
                await asyncio.to_thread(subprocess.run, service['stop_cmd'], capture_output=True, timeout=10)
                logger.info(f"✅ {service['name']} остановлен")
                return True
            except Exception as e:
                logger.error(f"❌ Ошибка остановки {service['name']}: {e}")
                return False
        
        return False
    
    async def start_all(self) -> bool:
        results = [await self.start_service(name) for name in self.services]
        return all(results)
    
    async def stop_all(self) -> bool:
        results = [await self.stop_service(name) for name in self.services]
        return all(results)


class ZoraLauncher:
    """Основной класс для запуска ZORA."""
    
    def __init__(self, port: int = 8002):
        self.port = port
        self.checker = SystemChecker()
        self.service_manager = ServiceManager()
        self.scheduler = None
        self.background_agents = {}
        
    async def stop_process_on_port(self, port: int):
        """Асинхронно останавливает процессы на указанном порту."""
        try:
            result = await asyncio.to_thread(subprocess.run,
                ['netstat', '-ano'],
                capture_output=True,
                text=True,
                encoding='cp866'
            )
            
            for line in result.stdout.split('\n'):
                if f':{port}' in line and 'LISTENING' in line:
                    parts = line.strip().split()
                    if len(parts) >= 5:
                        pid = parts[-1]
                        logger.info(f"  Останавливаю процесс PID: {pid}")
                        await asyncio.to_thread(subprocess.run,
                            ['taskkill', '/f', '/pid', pid],
                            capture_output=True,
                            shell=True
                        )
            await asyncio.sleep(2)
        except Exception as e:
            logger.warning(f"  Предупреждение: {e}")
    
    async def start_web_server(self):
        """Асинхронно запускает веб-сервер ZORA."""
        logger.info(f"🚀 Запуск веб-сервера ZORA на порту {self.port}...")
        
        if await self.checker.check_port(self.port):
            logger.info(f"🛑 Порт {self.port} занят, останавливаю процессы...")
            await self.stop_process_on_port(self.port)
        
        try:
            import uvicorn
            from interfaces.web import app
            
            def run_server():
                uvicorn.run(app, host="0.0.0.0", port=self.port, log_level="info")
            
            server_thread = threading.Thread(target=run_server, daemon=True)
            server_thread.start()
            
            for _ in range(10):
                if await self.checker.check_port(self.port):
                    logger.info(f"✅ Веб-сервер запущен на http://localhost:{self.port}")
                    return True
                await asyncio.sleep(1)
            
            logger.error("❌ Не удалось запустить веб-сервер")
            return False
            
        except Exception as e:
            logger.error(f"❌ Ошибка запуска веб-сервера: {e}")
            return False
    
    def _open_url_in_browser(self, url: str):
        """Открывает URL в браузере.
        Использует subprocess.Popen (fire-and-forget) — не ждёт завершения.
        В безголовом режиме (SSH) ничего не делает.
        """
        if self._is_headless():
            return
        try:
            if sys.platform == "win32":
                subprocess.Popen(
                    ["cmd", "/c", "start", "", url],
                    shell=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
            else:
                subprocess.Popen(
                    ["xdg-open", url],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
        except Exception as e:
            logger.debug(f"  Не удалось открыть {url}: {e}")
    
    async def open_browser(self):
        """Асинхронно открывает браузер с веб-интерфейсом.
        Запускает в отдельном потоке, чтобы не блокировать event loop.
        """
        url = f"http://localhost:{self.port}/modern"
        logger.info(f"🌐 Открываю браузер: {url}")
        self._open_url_in_browser(url)
        return True
    
    def _is_headless(self) -> bool:
        """Определяет, запущена ли система в безголовом режиме (SSH, без GUI).
        
        Проверяет несколько признаков:
        1. Переменная окружения SSH_CONNECTION (SSH-соединение)
        2. Переменная окружения DISPLAY не установлена (Linux без GUI)
        3. На Windows: отсутствие интерактивной сессии пользователя
        """
        # Проверка SSH-соединения
        if os.environ.get("SSH_CONNECTION") or os.environ.get("SSH_CLIENT") or os.environ.get("SSH_TTY"):
            return True
        
        # На Linux: если DISPLAY не установлен — нет GUI
        if sys.platform != "win32" and not os.environ.get("DISPLAY"):
            return True
        
        # На Windows: проверяем, есть ли десктопное окружение
        if sys.platform == "win32":
            try:
                import ctypes
                # GetForegroundWindow() вернёт 0, если нет активного окна (сессия заблокирована)
                # GetDesktopWindow() вернёт 0 в некоторых headless-ситуациях
                user32 = ctypes.windll.user32
                if user32.GetDesktopWindow() == 0:
                    return True
                # Дополнительная проверка: GetShellWindow() — возвращает 0 если оболочка не загружена
                if user32.GetShellWindow() == 0:
                    return True
            except Exception:
                pass
        
        return False
    
    def _register_background_agents(self):
        """Регистрирует фоновых агентов в планировщике."""
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        
        self.scheduler = AsyncIOScheduler()
        
        # Импортируем агентов (если они существуют)
        try:
            from agents.operator_1c_local import Operator1CLocal
            op_agent = Operator1CLocal()
            self.background_agents['operator_1c'] = op_agent
            
            # Запуск цикла в 7:30 по будням
            self.scheduler.add_job(
                op_agent.monitoring_loop,
                trigger='cron',
                day_of_week='mon-fri',
                hour=7,
                minute=30,
                id='operator_1c_loop',
                kwargs={'check_interval': 60}
            )
            logger.info("📅 Оператор 1С запланирован на 7:30 по будням")
        except ImportError:
            logger.warning("⚠️ Агент оператора 1С не найден, пропускаем")
        
        # Аналогично можно добавить PurchaserAgent, AccountantAgent, ParserAgent
        # ...
        
        self.scheduler.start()
        logger.info("✅ Планировщик фоновых задач запущен")
    
    async def run(self, open_browser: bool = True):
        """Асинхронный основной метод запуска системы."""
        global _launcher_instance
        _launcher_instance = self
        
        print("=" * 60, flush=True)
        print(">>> ЗАПУСК СИСТЕМЫ ZORA", flush=True)
        print("=" * 60, flush=True)
        
        check_result = await self.checker.run_all_checks()
        
        if not check_result['checks']['qdrant']['available']:
            logger.info("🔄 Попытка запуска Qdrant...")
            await self.service_manager.start_service('qdrant')
        
        if not check_result['checks']['ollama']['available']:
            ollama_host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
            logger.warning(f"⚠️ Ollama недоступен ({ollama_host}). Убедитесь, что сервер запущен.")
        
        if not await self.start_web_server():
            logger.error("❌ Не удалось запустить веб-сервер")
            return False
        
        # Запускаем дашборд мониторинга (всегда, чтобы был доступен по сети)
        try:
            logger.info("🔄 Запуск дашборда мониторинга...")
            from monitoring.dashboard import Dashboard
            dashboard = Dashboard(host="0.0.0.0", port=8003)
            dashboard_thread = threading.Thread(target=dashboard.run, daemon=True)
            dashboard_thread.start()
            logger.info(f"✅ Дашборд запущен на http://localhost:8003")
        except Exception as e:
            logger.warning(f"⚠️ Не удалось запустить дашборд: {e}")
        
        # Запускаем планировщик фоновых агентов
        self._register_background_agents()
        
        # Определяем режим запуска (headless или с GUI)
        headless = self._is_headless()
        if headless:
            logger.info("🖥️ Безголовый режим (SSH/без GUI): браузер не открывается автоматически")
            logger.info("   Веб-интерфейс: http://localhost:8002/modern")
            logger.info("   Дашборд: http://localhost:8003")
        elif open_browser:
            await self.open_browser()
            # Открываем дашборд мониторинга
            logger.info("🌐 Открываю дашборд мониторинга: http://localhost:8003")
            self._open_url_in_browser("http://localhost:8003")
        
        print("\n" + "=" * 60, flush=True)
        print(">>> СИСТЕМА ZORA УСПЕШНО ЗАПУЩЕНА", flush=True)
        print("=" * 60, flush=True)
        print(f"Веб-интерфейс: http://localhost:{self.port}/modern", flush=True)
        print(f"Дашборд мониторинга: http://localhost:8003", flush=True)
        print(f"Ollama: {os.getenv('OLLAMA_HOST', 'http://localhost:11434')}", flush=True)
        print(f"Qdrant: http://{os.getenv('QDRANT_HOST', 'localhost')}:{os.getenv('QDRANT_PORT', '6333')}", flush=True)
        print("\nДля тестирования API:", flush=True)
        print(f'curl -X POST http://localhost:{self.port}/ask \\', flush=True)
        print('  -H "Content-Type: application/json" \\', flush=True)
        print('  -d \'{"query": "Привет! Как дела?", "agent": "developer_assistant"}\'', flush=True)
        print("\nДля остановки системы нажмите Ctrl+C", flush=True)
        print("=" * 60, flush=True)
        
        try:
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            logger.info("\n🛑 Остановка системы...")
            if self.scheduler:
                self.scheduler.shutdown(wait=False)
            # Останавливаем всех агентов
            for agent in self.background_agents.values():
                if hasattr(agent, 'stop'):
                    agent.stop()
            await self.service_manager.stop_all()
            logger.info("✅ Система остановлена")
        
        return True


async def main():
    """Точка входа."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Запуск системы ZORA')
    parser.add_argument('--port', type=int, default=8002, help='Порт веб-сервера')
    parser.add_argument('--no-browser', action='store_true', help='Не открывать браузер')
    parser.add_argument('--check-only', action='store_true', help='Только проверка системы')
    
    args = await asyncio.to_thread(parser.parse_args)
    
    launcher = ZoraLauncher(port=args.port)
    
    if args.check_only:
        check_result = await launcher.checker.run_all_checks()
        print(check_result)
        return 0
    
    return 0 if await launcher.run(open_browser=not args.no_browser) else 1


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 Система ZORA остановлена.")
        sys.exit(0)
