"""
Дашборд для мониторинга системы и агентов.
"""

import json
import os
import sys
import logging
import asyncio
from datetime import datetime, timedelta
from typing import Dict, Any, List

# Добавляем текущую директорию в путь для импортов
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import uvicorn

from monitoring.system_monitor import (
    SystemMonitor, 
    AgentMonitor, 
    monitor_system_health,
    get_zora_status,
    check_docker,
    check_qdrant,
    check_ollama
)


class Dashboard:
    """Класс дашборда для визуализации метрик."""
    
    def __init__(self, host="0.0.0.0", port=8003):
        self.host = host
        self.port = port
        self.app = FastAPI(title="ZORA Monitoring Dashboard")
        # Абсолютный путь к папке с шаблонами
        import os
        template_dir = os.path.join(os.path.dirname(__file__), "templates")
        self.templates = Jinja2Templates(directory=template_dir)
        self.system_monitor = SystemMonitor()
        self.agent_monitor = AgentMonitor()
        self.setup_routes()
        
    def setup_routes(self):
        """Настраивает маршруты API."""
        
        @self.app.get("/", response_class=HTMLResponse)
        async def dashboard(request: Request):
            # Читаем HTML файл напрямую, чтобы обойти проблему с Jinja2
            import os
            template_path = os.path.join(os.path.dirname(__file__), "templates", "dashboard.html")
            with open(template_path, 'r', encoding='utf-8') as f:
                html_content = f.read()
            return HTMLResponse(content=html_content)
        
        @self.app.get("/api/health")
        async def get_health():
            """Возвращает детальную информацию о состоянии системы."""
            try:
                from monitoring.system_monitor import get_detailed_system_info
                detailed_info = get_detailed_system_info()
                
                # Добавляем базовую оценку здоровья
                health_score = 100
                issues = []
                
                if detailed_info['cpu']['percent'] > 80:
                    health_score -= 10
                    issues.append("Высокая загрузка CPU")
                if detailed_info['memory']['percent'] > 80:
                    health_score -= 10
                    issues.append("Высокая загрузка памяти")
                if detailed_info['gpu']['percent'] > 90:
                    health_score -= 5
                    issues.append("Высокая загрузка GPU")
                if detailed_info['disk']['percent'] > 90:
                    health_score -= 10
                    issues.append("Мало свободного места на диске")
                
                # Формируем ответ согласно ТЗ
                system_data = {
                    'cpu_percent': detailed_info['cpu']['percent'],
                    'cpu_count': detailed_info['cpu']['cores_physical'],
                    'cpu_count_logical': detailed_info['cpu']['cores_logical'],
                    'cpu_name': detailed_info['cpu']['model'],
                    'cpu_freq_current': detailed_info['cpu']['frequency_current'],
                    'cpu_freq_max': detailed_info['cpu']['frequency_max'],
                    'cpu_temp': detailed_info['cpu']['temperature'],
                    'memory_percent': detailed_info['memory']['percent'],
                    'memory_total': detailed_info['memory']['total'],
                    'memory_used': detailed_info['memory']['used'],
                    'memory_free': detailed_info['memory']['free'],
                    'disk_percent': detailed_info['disk']['percent'],
                    'disk_total': detailed_info['disk']['total'],
                    'disk_used': detailed_info['disk']['used'],
                    'disk_name': detailed_info['disk']['model'],
                    'disk_temp': detailed_info['disk']['temperature'],
                    'gpu_name': detailed_info['gpu']['name'],
                    'gpu_percent': detailed_info['gpu']['percent'],
                    'gpu_memory_total': detailed_info['gpu']['memory_total'],
                    'gpu_memory_used': detailed_info['gpu']['memory_used'],
                    'gpu_temp': detailed_info['gpu']['temperature']
                }
                
                # Очищаем None значения
                for key, value in system_data.items():
                    if value is None:
                        system_data[key] = None
                
                return {
                    'success': True,
                    'system': system_data,
                    'health_score': max(0, health_score),
                    'issues': issues
                }
            except Exception as e:
                return {
                    'success': False,
                    'error': str(e),
                    'health_score': 0,
                    'issues': [f"Ошибка получения данных: {e}"]
                }
        
        @self.app.get("/api/metrics")
        async def get_metrics(limit: int = 100):
            # Загружаем историю метрик из файла
            metrics = []
            log_file = self.system_monitor.log_file
            if os.path.exists(log_file):
                with open(log_file, 'r', encoding='utf-8') as f:
                    lines = f.readlines()[-limit:]
                    for line in lines:
                        try:
                            metrics.append(json.loads(line.strip()))
                        except:
                            pass
            return {"metrics": metrics}
        
        @self.app.get("/api/agents")
        async def get_agents():
            return self.agent_monitor.get_status()
        
        @self.app.get("/api/system")
        async def get_system():
            return self.system_monitor.collect_metrics()
        
        @self.app.websocket("/ws")
        async def websocket_endpoint(websocket: WebSocket):
            await websocket.accept()
            try:
                while True:
                    # Отправляем обновления каждые 5 секунд
                    health = monitor_system_health()
                    await websocket.send_json(health)
                    await asyncio.sleep(5)
            except WebSocketDisconnect:
                logging.info("WebSocket отключён")
            except Exception as e:
                logging.error(f"Ошибка WebSocket: {e}")
        
        @self.app.post("/api/parse_its")
        async def parse_its_docs():
            """Запускает парсинг документации ИТС 1С."""
            try:
                from parsers.its_parser import ITSParser, index_to_memory
                parser = ITSParser(headless=True)
                documents = parser.parse_all_documentation(limit_sections=2)
                parser.close()
                
                if documents:
                    # Индексируем в память
                    index_to_memory(documents)
                    return {
                        "success": True,
                        "message": f"Успешно собрано {len(documents)} документов и проиндексировано в память",
                        "documents_count": len(documents)
                    }
                else:
                    return {
                        "success": False,
                        "message": "Не удалось собрать документы"
                    }
            except Exception as e:
                logging.error(f"Ошибка парсинга ИТС: {e}")
                return {
                    "success": False,
                    "message": f"Ошибка: {str(e)}"
                }
        
        @self.app.post("/api/index_project")
        async def index_project():
            """Индексирует весь проект в векторную память."""
            try:
                from memory.indexer import index_project_files
                result = index_project_files()
                return {
                    "success": True,
                    "message": f"Проиндексировано {result['indexed_files']} файлов, добавлено {result['added_chunks']} чанков"
                }
            except Exception as e:
                logging.error(f"Ошибка индексации проекта: {e}")
                return {
                    "success": False,
                    "message": f"Ошибка индексации проекта: {str(e)}"
                }
        
        @self.app.post("/api/analyze_code")
        async def analyze_code():
            """Запускает статический анализ кода."""
            try:
                from tools.code_analyzer import analyze_project
                results = analyze_project()
                issues_count = len(results.get('issues', []))
                return {
                    "success": True,
                    "message": f"Анализ кода завершён. Найдено {issues_count} проблем.",
                    "details": "\n".join([f"- {issue}" for issue in results.get('issues', [])[:10]])
                }
            except Exception as e:
                logging.error(f"Ошибка анализа кода: {e}")
                return {
                    "success": False,
                    "message": f"Ошибка анализа кода: {str(e)}"
                }
        
        @self.app.post("/api/run_tests")
        async def run_tests():
            """Запускает тесты проекта."""
            try:
                from tools.test_runner import run_all_tests
                results = run_all_tests()
                passed = results.get('passed', 0)
                failed = results.get('failed', 0)
                total = passed + failed
                return {
                    "success": True,
                    "message": f"Тесты завершены: {passed}/{total} пройдено",
                    "details": f"Пройдено: {passed}, Провалено: {failed}"
                }
            except Exception as e:
                logging.error(f"Ошибка запуска тестов: {e}")
                return {
                    "success": False,
                    "message": f"Ошибка запуска тестов: {str(e)}"
                }
        
        @self.app.post("/api/agents/{agent_name}/restart")
        async def restart_agent(agent_name: str):
            """Перезапускает указанного агента."""
            try:
                # Импортируем необходимые модули
                import importlib
                import sys
                
                # Маппинг имен агентов на модули
                agent_modules = {
                    'economist': 'agents.economist',
                    'purchaser': 'agents.purchaser',
                    'accountant': 'agents.accountant',
                    'support': 'agents.support',
                    'smm': 'agents.smm',
                    'website': 'agents.website',
                    'developer': 'agents.developer_assistant',
                    'logistician': 'agents.logistician',
                    'operator_1c': 'agents.operator_1c_local',
                    'sales_manager': 'agents.sales_manager',
                    'parser': 'agents.parser_agent'
                }
                
                if agent_name not in agent_modules:
                    return {
                        "success": False,
                        "message": f"Агент '{agent_name}' не найден. Доступные агенты: {', '.join(agent_modules.keys())}"
                    }
                
                module_path = agent_modules[agent_name]
                
                # Пытаемся перезагрузить модуль
                try:
                    if module_path in sys.modules:
                        importlib.reload(sys.modules[module_path])
                        logging.info(f"Модуль {module_path} перезагружен")
                    
                    # Импортируем класс агента
                    module = importlib.import_module(module_path)
                    
                    # Определяем имя класса
                    class_name_map = {
                        'parser': 'ParserAgent',
                        'developer': 'DeveloperAssistant',
                        'operator_1c': 'Operator1CLocal',
                        'sales_manager': 'SalesManager',
                        'economist': 'Economist',
                        'purchaser': 'Purchaser',
                        'accountant': 'Accountant',
                        'support': 'Support',
                        'smm': 'SMM',
                        'website': 'Website',
                        'logistician': 'Logistician'
                    }
                    
                    class_name = class_name_map.get(agent_name, agent_name.capitalize())
                    agent_class = getattr(module, class_name, None)
                    
                    if not agent_class:
                        return {
                            "success": False,
                            "message": f"Класс {class_name} не найден в модуле {module_path}"
                        }
                    
                    # Создаем новый экземпляр агента
                    agent_instance = agent_class()
                    
                    # Если у агента есть метод initialize, вызываем его
                    if hasattr(agent_instance, 'initialize'):
                        agent_instance.initialize()
                    
                    return {
                        "success": True,
                        "message": f"Агент '{agent_name}' успешно перезапущен"
                    }
                    
                except Exception as e:
                    logging.error(f"Ошибка перезапуска агента {agent_name}: {e}")
                    return {
                        "success": False,
                        "message": f"Ошибка перезапуска агента '{agent_name}': {str(e)}"
                    }
                
            except Exception as e:
                logging.error(f"Ошибка обработки запроса перезапуска агента: {e}")
                return {
                    "success": False,
                    "message": f"Ошибка обработки запроса: {str(e)}"
                }
        
        @self.app.get("/api/zora_status")
        async def zora_status():
            """Возвращает статус системы ZORA."""
            try:
                return get_zora_status()
            except Exception as e:
                logging.error(f"Ошибка проверки статуса ZORA: {e}")
                return {
                    "success": False,
                    "status": "error",
                    "message": f"Ошибка проверки статуса ZORA: {str(e)}"
                }
        
        @self.app.post("/api/reindex")
        async def reindex():
            """Запускает полную переиндексацию проекта."""
            try:
                from memory.indexer import index_project_files
                # Очищаем коллекцию Qdrant
                try:
                    from memory.qdrant_memory import ZoraMemory
                    memory = ZoraMemory()
                    memory.clear()
                    logging.info("Коллекция Qdrant очищена")
                except Exception as e:
                    logging.warning(f"Не удалось очистить коллекцию Qdrant: {e}")
                
                # Запускаем индексацию
                result = index_project_files()
                return {
                    "success": True,
                    "message": f"Переиндексация завершена. Проиндексировано {result['indexed_files']} файлов, добавлено {result['added_chunks']} чанков"
                }
            except Exception as e:
                logging.error(f"Ошибка переиндексации: {e}")
                return {
                    "success": False,
                    "message": f"Ошибка переиндексации: {str(e)}"
                }
        
        @self.app.post("/api/cache/clear")
        async def clear_cache():
            """Очищает внутренний кэш системы."""
            try:
                # Очищаем кэш импортов Python
                import sys
                modules_to_clear = [m for m in sys.modules.keys() 
                                  if m.startswith('memory.') or 
                                     m.startswith('agents.') or
                                     m.startswith('core.')]
                for module in modules_to_clear:
                    if module in sys.modules:
                        del sys.modules[module]
                
                # Очищаем кэш в памяти (если есть)
                try:
                    from memory.qdrant_memory import ZoraMemory
                    memory = ZoraMemory()
                    if hasattr(memory, 'clear_cache'):
                        memory.clear_cache()
                        logging.info("Кэш памяти очищен")
                except Exception as e:
                    logging.debug(f"Не удалось очистить кэш памяти: {e}")
                
                return {
                    "success": True,
                    "message": "Внутренний кэш системы очищен"
                }
            except Exception as e:
                logging.error(f"Ошибка очистки кэша: {e}")
                return {
                    "success": False,
                    "message": f"Ошибка очистки кэша: {str(e)}"
                }
        
        @self.app.get("/api/git_status")
        async def git_status():
            """Возвращает статус Git репозитория."""
            try:
                from tools.git_tools import get_git_status
                status = get_git_status()
                return {
                    "success": True,
                    "message": f"Git статус: {status.get('branch', 'unknown')}",
                    "details": f"Изменения: {status.get('changes', 0)} файлов"
                }
            except Exception as e:
                logging.error(f"Ошибка получения Git статуса: {e}")
                return {
                    "success": False,
                    "message": f"Ошибка получения Git статуса: {str(e)}"
                }
    
    def run(self):
        """Запускает сервер дашборда."""
        logging.info(f"Запуск дашборда на http://{self.host}:{self.port}")
        uvicorn.run(self.app, host=self.host, port=self.port)


def generate_sample_data():
    """Генерирует пример данных для тестирования."""
    import random
    from datetime import datetime, timedelta
    
    data = []
    now = datetime.now()
    for i in range(100):
        timestamp = (now - timedelta(minutes=i*5)).isoformat()
        data.append({
            'timestamp': timestamp,
            'cpu_percent': random.randint(10, 80),
            'memory_percent': random.randint(30, 90),
            'disk_percent': random.randint(40, 95),
            'process_count': random.randint(50, 200)
        })
    
    # Сохраняем в файл
    log_file = os.path.join(os.path.dirname(__file__), "monitor_log.json")
    with open(log_file, 'w', encoding='utf-8') as f:
        for item in data:
            f.write(json.dumps(item, ensure_ascii=False) + '\n')
    
    print(f"Сгенерировано {len(data)} записей в {log_file}")


if __name__ == "__main__":
    import asyncio
    
    # Генерируем пример данных, если нет файла
    log_file = os.path.join(os.path.dirname(__file__), "monitor_log.json")
    if not os.path.exists(log_file):
        generate_sample_data()
    
    # Запускаем дашборд
    dashboard = Dashboard()
    dashboard.run()