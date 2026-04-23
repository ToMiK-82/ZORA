"""
Мониторинг состояния системы и агентов.
"""

import psutil
import time
import logging
import threading
import json
import os
import socket
import subprocess
from datetime import datetime
from typing import Dict, Any, List, Optional

try:
    from .gpu_monitor import get_gpu_info
except ImportError:
    from monitoring.gpu_monitor import get_gpu_info


class SystemMonitor:
    """Мониторинг системных ресурсов."""
    
    def __init__(self, log_file: str = None):
        self.log_file = log_file or os.path.join(os.path.dirname(__file__), "monitor_log.json")
        self.running = False
        self.thread = None
        self.metrics_history = []
        self.max_history = 1000
        
    def collect_metrics(self) -> Dict[str, Any]:
        """Собирает метрики системы."""
        cpu_percent = psutil.cpu_percent(interval=0.1)
        cpu_count = psutil.cpu_count(logical=False)  # физические ядра
        cpu_count_logical = psutil.cpu_count(logical=True)  # логические процессоры
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        net_io = psutil.net_io_counters()
        
        # Процессы
        processes = []
        for proc in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent']):
            try:
                processes.append({
                    'pid': proc.info['pid'],
                    'name': proc.info['name'],
                    'cpu': proc.info['cpu_percent'],
                    'memory': proc.info['memory_percent']
                })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        
        # Топ процессов по CPU и памяти
        top_cpu = sorted(processes, key=lambda x: x['cpu'], reverse=True)[:5]
        top_memory = sorted(processes, key=lambda x: x['memory'], reverse=True)[:5]
        
        return {
            'timestamp': datetime.now().isoformat(),
            'cpu_percent': cpu_percent,
            'cpu_count': cpu_count,
            'cpu_count_logical': cpu_count_logical,
            'memory_percent': memory.percent,
            'disk_percent': disk.percent,
            'process_count': len(processes),
            'memory': {
                'total': memory.total,
                'available': memory.available,
                'percent': memory.percent,
                'used': memory.used
            },
            'disk': {
                'total': disk.total,
                'used': disk.used,
                'free': disk.free,
                'percent': disk.percent
            },
            'network': {
                'bytes_sent': net_io.bytes_sent,
                'bytes_recv': net_io.bytes_recv
            },
            'top_cpu': top_cpu,
            'top_memory': top_memory
        }
    
    def log_metrics(self, metrics: Dict[str, Any]):
        """Сохраняет метрики в лог."""
        self.metrics_history.append(metrics)
        if len(self.metrics_history) > self.max_history:
            self.metrics_history = self.metrics_history[-self.max_history:]
        
        try:
            with open(self.log_file, 'a', encoding='utf-8') as f:
                f.write(json.dumps(metrics, ensure_ascii=False) + '\n')
        except Exception as e:
            logging.error(f"Ошибка записи метрик: {e}")
    
    def monitor_loop(self, interval: int = 10):
        """Цикл мониторинга."""
        while self.running:
            try:
                metrics = self.collect_metrics()
                self.log_metrics(metrics)
                
                # Проверка аномалий
                if metrics['cpu_percent'] > 90:
                    logging.warning(f"Высокая загрузка CPU: {metrics['cpu_percent']}%")
                if metrics['memory_percent'] > 90:
                    logging.warning(f"Высокая загрузка памяти: {metrics['memory_percent']}%")
                if metrics['disk_percent'] > 90:
                    logging.warning(f"Мало свободного места на диске: {metrics['disk_percent']}%")
                
            except Exception as e:
                logging.error(f"Ошибка сбора метрик: {e}")
            
            time.sleep(interval)
    
    def start(self, interval: int = 10):
        """Запускает мониторинг в фоновом потоке."""
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(target=self.monitor_loop, args=(interval,))
        self.thread.daemon = True
        self.thread.start()
        logging.info(f"Мониторинг системы запущен (интервал {interval} сек)")
    
    def stop(self):
        """Останавливает мониторинг."""
        self.running = False
        if self.thread:
            self.thread.join(timeout=5)
        logging.info("Мониторинг системы остановлен")
    
    def get_summary(self) -> Dict[str, Any]:
        """Возвращает сводку текущего состояния."""
        metrics = self.collect_metrics()
        return {
            'status': 'running' if self.running else 'stopped',
            'current_metrics': metrics,
            'history_size': len(self.metrics_history),
            'last_update': self.metrics_history[-1]['timestamp'] if self.metrics_history else None
        }


class AgentMonitor:
    """Мониторинг состояния агентов."""
    
    def __init__(self):
        self.agent_status = {}
        self.last_check = {}
        self.agent_states = {}  # Дополнительные состояния: running, idle, unavailable, error
        self.agent_tasks = {}   # Текущие задачи агентов
        self.agent_last_activity = {}  # Время последней активности
        self.agent_start_time = {}  # Время запуска агента
        self.agent_metrics = {}  # Метрики производительности агентов
    
    def check_agent(self, agent_name: str, module_path: str) -> Dict[str, Any]:
        """Проверяет доступность агента и собирает дополнительную информацию."""
        try:
            import importlib
            module = importlib.import_module(module_path)
            # Специальная обработка для некоторых агентов
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
            if agent_class:
                # Пытаемся создать экземпляр
                instance = agent_class()
                
                # Определяем состояние агента
                state = 'idle'  # по умолчанию простаивает
                current_task = 'Ожидание запроса'
                task_start_time = None
                
                # Проверяем, есть ли у агента атрибут is_busy или аналогичный
                if hasattr(instance, 'is_busy') and instance.is_busy():
                    state = 'running'
                    current_task = 'Выполнение задачи'
                    task_start_time = datetime.now().isoformat()
                elif hasattr(instance, 'current_task'):
                    current_task = instance.current_task
                    state = 'running' if current_task else 'idle'
                    if hasattr(instance, 'task_start_time'):
                        task_start_time = instance.task_start_time
                
                # Получаем метрики производительности, если доступны
                metrics = {}
                if hasattr(instance, 'get_metrics'):
                    try:
                        metrics = instance.get_metrics()
                    except:
                        pass
                
                # Сохраняем состояние и задачу
                self.agent_states[agent_name] = state
                self.agent_tasks[agent_name] = current_task
                self.agent_last_activity[agent_name] = datetime.now().isoformat()
                
                # Сохраняем время запуска, если еще не сохранено
                if agent_name not in self.agent_start_time:
                    self.agent_start_time[agent_name] = datetime.now().isoformat()
                
                # Сохраняем метрики
                self.agent_metrics[agent_name] = metrics
                
                return {
                    'status': 'available',
                    'state': state,
                    'current_task': current_task,
                    'task_start_time': task_start_time,
                    'last_activity': self.agent_last_activity[agent_name],
                    'start_time': self.agent_start_time[agent_name],
                    'metrics': metrics,
                    'class': agent_class.__name__,
                    'module': module_path
                }
            else:
                self.agent_states[agent_name] = 'unavailable'
                return {
                    'status': 'class_not_found',
                    'state': 'unavailable',
                    'error': f"Класс {agent_name.capitalize()} не найден в {module_path}"
                }
        except Exception as e:
            self.agent_states[agent_name] = 'error'
            return {
                'status': 'error',
                'state': 'error',
                'error': str(e)
            }
    
    def check_all_agents(self) -> Dict[str, Any]:
        """Проверяет всех известных агентов."""
        agents = {
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
        
        results = {}
        for name, module in agents.items():
            try:
                results[name] = self.check_agent(name, module)
            except Exception as e:
                results[name] = {
                    'status': 'error',
                    'state': 'error',
                    'error': str(e)
                }
        
        self.agent_status = results
        self.last_check = datetime.now().isoformat()
        
        return results
    
    def get_status(self) -> Dict[str, Any]:
        """Возвращает статус всех агентов."""
        if not self.agent_status:
            self.check_all_agents()
        
        available = sum(1 for v in self.agent_status.values() if v.get('status') == 'available')
        total = len(self.agent_status)
        
        # Подсчёт по состояниям
        states_count = {
            'running': 0,
            'idle': 0,
            'unavailable': 0,
            'error': 0
        }
        
        # Собираем статистику по задачам
        tasks_summary = {}
        for agent_name, agent_data in self.agent_status.items():
            state = agent_data.get('state', 'unavailable')
            if state in states_count:
                states_count[state] += 1
            
            # Собираем информацию о задачах
            current_task = agent_data.get('current_task', '')
            if current_task and current_task != 'Ожидание запроса':
                if current_task not in tasks_summary:
                    tasks_summary[current_task] = 0
                tasks_summary[current_task] += 1
        
        # Рассчитываем время работы агентов
        agent_uptimes = {}
        for agent_name, agent_data in self.agent_status.items():
            start_time = agent_data.get('start_time')
            if start_time:
                try:
                    start_dt = datetime.fromisoformat(start_time)
                    uptime_seconds = (datetime.now() - start_dt).total_seconds()
                    
                    # Конвертируем в человекочитаемый формат
                    days = int(uptime_seconds // 86400)
                    hours = int((uptime_seconds % 86400) // 3600)
                    minutes = int((uptime_seconds % 3600) // 60)
                    
                    if days > 0:
                        uptime_str = f"{days}д {hours}ч {minutes}м"
                    elif hours > 0:
                        uptime_str = f"{hours}ч {minutes}м"
                    else:
                        uptime_str = f"{minutes}м"
                    
                    agent_uptimes[agent_name] = uptime_str
                except:
                    agent_uptimes[agent_name] = "Неизвестно"
        
        return {
            'total_agents': total,
            'available_agents': available,
            'unavailable_agents': total - available,
            'states_count': states_count,
            'tasks_summary': tasks_summary,
            'agent_uptimes': agent_uptimes,
            'last_check': self.last_check,
            'agents': self.agent_status
        }
    
    def update_agent_state(self, agent_name: str, state: str, task: str = None):
        """Обновляет состояние агента вручную."""
        if agent_name in self.agent_states:
            self.agent_states[agent_name] = state
            self.agent_last_activity[agent_name] = datetime.now().isoformat()
            
            if task:
                self.agent_tasks[agent_name] = task
            
            # Обновляем статус в основном словаре
            if agent_name in self.agent_status:
                self.agent_status[agent_name]['state'] = state
                self.agent_status[agent_name]['last_activity'] = self.agent_last_activity[agent_name]
                if task:
                    self.agent_status[agent_name]['current_task'] = task
    
    def get_agent_details(self, agent_name: str) -> Dict[str, Any]:
        """Возвращает детальную информацию об агенте."""
        if not self.agent_status:
            self.check_all_agents()
        
        if agent_name in self.agent_status:
            agent_data = self.agent_status[agent_name].copy()
            
            # Добавляем дополнительную информацию
            agent_data['uptime'] = self.agent_start_time.get(agent_name, 'Неизвестно')
            agent_data['metrics'] = self.agent_metrics.get(agent_name, {})
            
            # Рассчитываем время работы
            start_time = self.agent_start_time.get(agent_name)
            if start_time:
                try:
                    start_dt = datetime.fromisoformat(start_time)
                    uptime_seconds = (datetime.now() - start_dt).total_seconds()
                    agent_data['uptime_seconds'] = uptime_seconds
                except:
                    agent_data['uptime_seconds'] = 0
            
            return agent_data
        else:
            return {
                'status': 'not_found',
                'error': f"Агент {agent_name} не найден"
            }


def get_cpu_temperature() -> Optional[float]:
    """Получает температуру CPU в °C."""
    try:
        import sys
        if sys.platform == "win32":
            try:
                import wmi
                w = wmi.WMI(namespace="root\\OpenHardwareMonitor")
                for sensor in w.Sensor():
                    if sensor.SensorType == "Temperature" and "CPU" in sensor.Name:
                        return float(sensor.Value)
            except:
                # Альтернативный метод для Windows
                try:
                    import wmi
                    w = wmi.WMI()
                    for sensor in w.Win32_TemperatureProbe():
                        if sensor.Name and "CPU" in sensor.Name:
                            return float(sensor.CurrentReading)
                except:
                    pass
        else:
            # Linux через sensors
            try:
                temps = psutil.sensors_temperatures()
                if 'coretemp' in temps:
                    for entry in temps['coretemp']:
                        if 'Package' in entry.label or 'Core 0' in entry.label:
                            return entry.current
                # Ищем любую температуру CPU
                for name, entries in temps.items():
                    for entry in entries:
                        if 'cpu' in name.lower() or 'core' in name.lower():
                            return entry.current
            except:
                pass
    except:
        pass
    return None


def get_disk_model() -> Optional[str]:
    """Получает модель системного диска."""
    try:
        import sys
        if sys.platform == "win32":
            try:
                import wmi
                w = wmi.WMI()
                for disk in w.Win32_DiskDrive():
                    if disk.Size and disk.Caption:
                        return disk.Caption
            except:
                pass
        else:
            # Linux через /sys/block
            import subprocess
            try:
                result = subprocess.run(['lsblk', '-d', '-o', 'MODEL,SIZE,NAME'], 
                                       capture_output=True, text=True)
                lines = result.stdout.strip().split('\n')
                if len(lines) > 1:
                    # Берем первую строку с данными (пропускаем заголовок)
                    parts = lines[1].split()
                    if parts:
                        # Объединяем все части кроме последних двух (SIZE и NAME)
                        model_parts = parts[:-2]
                        return ' '.join(model_parts) if model_parts else None
            except:
                pass
    except:
        pass
    return None


def get_disk_temperature() -> Optional[float]:
    """Получает температуру диска в °C (для SSD/NVMe)."""
    try:
        import sys
        if sys.platform == "win32":
            try:
                import wmi
                w = wmi.WMI(namespace="root\\OpenHardwareMonitor")
                for sensor in w.Sensor():
                    if sensor.SensorType == "Temperature" and "Drive" in sensor.Name:
                        return float(sensor.Value)
            except:
                pass
        else:
            # Linux через smartctl (если установлен)
            import subprocess
            try:
                result = subprocess.run(['sudo', 'smartctl', '-a', '/dev/sda'], 
                                       capture_output=True, text=True)
                if result.returncode == 0:
                    for line in result.stdout.split('\n'):
                        if 'Temperature_Celsius' in line or 'Temperature' in line:
                            parts = line.split()
                            for part in parts:
                                if part.isdigit():
                                    return float(part)
            except:
                pass
    except:
        pass
    return None


def get_human_readable_uptime() -> str:
    """Возвращает время работы системы в человекочитаемом формате."""
    try:
        import time
        boot_time = psutil.boot_time()
        uptime_seconds = time.time() - boot_time
        
        days = int(uptime_seconds // 86400)
        hours = int((uptime_seconds % 86400) // 3600)
        minutes = int((uptime_seconds % 3600) // 60)
        
        if days > 0:
            return f"{days} дней {hours} часов {minutes} минут"
        elif hours > 0:
            return f"{hours} часов {minutes} минут"
        else:
            return f"{minutes} минут"
    except:
        return "Неизвестно"


def get_detailed_system_info() -> Dict[str, Any]:
    """
    Получает детальную информацию о системе.
    Включает температуры, частоты, модели CPU/GPU/диска.
    """
    # Базовые метрики через psutil
    cpu_percent = psutil.cpu_percent(interval=0.1)
    cpu_freq = psutil.cpu_freq()
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage('/')
    
    # Информация о CPU через cpuinfo (если установлен)
    cpu_model = "Unknown"
    cpu_arch = "Unknown"
    cpu_bits = 64
    cpu_vendor = "Unknown"
    
    try:
        # type: ignore - Pylance может не видеть этот модуль
        import cpuinfo  # type: ignore
        cpu_info_data = cpuinfo.get_cpu_info()
        cpu_model = cpu_info_data.get('brand_raw', 'Unknown')
        cpu_arch = cpu_info_data.get('arch', 'Unknown')
        cpu_bits = cpu_info_data.get('bits', 64)
        cpu_vendor = cpu_info_data.get('vendor_id', 'Unknown')
    except ImportError:
        # cpuinfo не установлен, используем альтернативные методы
        try:
            import platform
            cpu_model = platform.processor()
            cpu_arch = platform.machine()
            cpu_bits = 64 if platform.architecture()[0] == '64bit' else 32
        except:
            pass
    except Exception:
        # Ошибка при получении информации о CPU
        pass
    
    # Информация о GPU
    gpu_info_data = get_gpu_info()
    
    # Температуры (Windows через WMI, Linux через sensors)
    temperatures = {}
    try:
        # Попробуем через WMI для Windows
        import wmi
        w = wmi.WMI(namespace="root\\OpenHardwareMonitor")
        for sensor in w.Sensor():
            if sensor.SensorType == "Temperature":
                temperatures[sensor.Name] = sensor.Value
    except:
        try:
            # Попробуем через psutil (Linux)
            temps = psutil.sensors_temperatures()
            if temps:
                for name, entries in temps.items():
                    for entry in entries:
                        temperatures[f"{name}_{entry.label or 'core'}"] = entry.current
        except:
            pass
    
    # Диски
    disks = []
    for partition in psutil.disk_partitions():
        try:
            usage = psutil.disk_usage(partition.mountpoint)
            disks.append({
                'device': partition.device,
                'mountpoint': partition.mountpoint,
                'fstype': partition.fstype,
                'total': usage.total,
                'used': usage.used,
                'free': usage.free,
                'percent': usage.percent
            })
        except:
            pass
    
    # Сеть
    net_io = psutil.net_io_counters()
    
    # Дополнительная информация
    cpu_temp = get_cpu_temperature()
    disk_model = get_disk_model()
    disk_temp = get_disk_temperature()
    
    # Конвертируем байты в гигабайты
    memory_total_gb = memory.total / (1024**3)
    memory_used_gb = memory.used / (1024**3)
    memory_free_gb = memory.free / (1024**3)
    
    disk_total_gb = disk.total / (1024**3)
    disk_used_gb = disk.used / (1024**3)
    disk_free_gb = disk.free / (1024**3)
    
    # Конвертируем видеопамять в гигабайты
    gpu_memory_total_gb = gpu_info_data.get('gpu_memory_total', 0) / 1024 if gpu_info_data.get('gpu_memory_total') else 0
    gpu_memory_used_gb = gpu_info_data.get('gpu_memory_used', 0) / 1024 if gpu_info_data.get('gpu_memory_used') else 0
    
    return {
        'timestamp': datetime.now().isoformat(),
        'cpu': {
            'model': cpu_model,
            'cores_physical': psutil.cpu_count(logical=False),
            'cores_logical': psutil.cpu_count(logical=True),
            'percent': cpu_percent,
            'frequency_current': cpu_freq.current if cpu_freq else None,
            'frequency_min': cpu_freq.min if cpu_freq else None,
            'frequency_max': cpu_freq.max if cpu_freq else None,
            'architecture': cpu_arch,
            'bits': cpu_bits,
            'vendor': cpu_vendor,
            'temperature': cpu_temp
        },
        'gpu': {
            'name': gpu_info_data['gpu_name'],
            'vendor': gpu_info_data['gpu_vendor'],
            'percent': gpu_info_data['gpu_percent'],
            'memory_used': gpu_memory_used_gb,
            'memory_total': gpu_memory_total_gb,
            'temperature': gpu_info_data['gpu_temperature'],
            'power_usage': gpu_info_data['gpu_power_usage'],
            'available': gpu_info_data['gpu_available']
        },
        'memory': {
            'total': memory_total_gb,
            'used': memory_used_gb,
            'free': memory_free_gb,
            'percent': memory.percent,
            'total_bytes': memory.total,
            'available': memory.available,
            'used_bytes': memory.used
        },
        'disk': {
            'total': disk_total_gb,
            'used': disk_used_gb,
            'free': disk_free_gb,
            'percent': disk.percent,
            'model': disk_model,
            'temperature': disk_temp,
            'total_bytes': disk.total,
            'used_bytes': disk.used,
            'free_bytes': disk.free,
            'disks': disks
        },
        'temperatures': temperatures,
        'network': {
            'bytes_sent': net_io.bytes_sent,
            'bytes_recv': net_io.bytes_recv,
            'packets_sent': net_io.packets_sent,
            'packets_recv': net_io.packets_recv
        },
        'uptime': get_human_readable_uptime()
    }


def get_qdrant_vectors_count() -> int:
    """Возвращает количество векторов в коллекции Qdrant."""
    try:
        from memory.qdrant_memory import ZoraMemory
        memory = ZoraMemory()
        
        # Пробуем несколько методов для получения количества векторов
        try:
            # Метод 1: Используем count() метод клиента
            count_result = memory.client.count(collection_name=memory.collection_name)
            return count_result.count
        except AttributeError:
            # Метод 2: Пробуем получить информацию о коллекции
            collection_info = memory.client.get_collection(collection_name=memory.collection_name)
            # Проверяем различные возможные атрибуты
            if hasattr(collection_info, 'points_count'):
                return collection_info.points_count
            elif hasattr(collection_info, 'vectors_count'):
                return collection_info.vectors_count
            elif hasattr(collection_info, 'count'):
                return collection_info.count
            else:
                # Метод 3: Пробуем через get_collections
                collections = memory.client.get_collections()
                for collection in collections.collections:
                    if collection.name == memory.collection_name:
                        # Проверяем атрибуты в объекте collection
                        if hasattr(collection, 'points_count'):
                            return collection.points_count
                        elif hasattr(collection, 'vectors_count'):
                            return collection.vectors_count
                return 0
    except Exception as e:
        logging.error(f"Ошибка получения количества векторов Qdrant: {e}")
        return -1


def check_docker() -> Dict[str, Any]:
    """Проверяет состояние Docker."""
    try:
        import subprocess
        result = subprocess.run(['docker', 'ps'], capture_output=True, text=True)
        if result.returncode == 0:
            containers = len(result.stdout.strip().split('\n')) - 1  # минус заголовок
            return {
                'status': 'running',
                'containers': containers,
                'message': f'Docker работает, запущено {containers} контейнеров'
            }
        else:
            return {
                'status': 'stopped',
                'containers': 0,
                'message': 'Docker не запущен или недоступен'
            }
    except Exception as e:
        return {
            'status': 'error',
            'containers': 0,
            'message': f'Ошибка проверки Docker: {str(e)}'
        }


def check_qdrant() -> Dict[str, Any]:
    """Проверяет состояние Qdrant."""
    try:
        from qdrant_client import QdrantClient
        client = QdrantClient(host="localhost", port=6333)
        collections = client.get_collections()
        return {
            'status': 'running',
            'collections': len(collections.collections),
            'message': f'Qdrant работает, доступно {len(collections.collections)} коллекций'
        }
    except Exception as e:
        return {
            'status': 'stopped',
            'collections': 0,
            'message': f'Qdrant недоступен: {str(e)}'
        }


def check_ollama() -> Dict[str, Any]:
    """Проверяет состояние Ollama."""
    try:
        import requests
        response = requests.get('http://localhost:11434/api/tags', timeout=5)
        if response.status_code == 200:
            models = response.json().get('models', [])
            return {
                'status': 'running',
                'models': len(models),
                'message': f'Ollama работает, доступно {len(models)} моделей'
            }
        else:
            return {
                'status': 'stopped',
                'models': 0,
                'message': f'Ollama недоступен (код {response.status_code})'
            }
    except Exception as e:
        return {
            'status': 'error',
            'models': 0,
            'message': f'Ошибка проверки Ollama: {str(e)}'
        }


def monitor_system_health() -> Dict[str, Any]:
    """Возвращает базовую информацию о здоровье системы."""
    try:
        # Получаем базовую информацию о системе
        cpu_percent = psutil.cpu_percent(interval=0.1)
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        
        # Получаем информацию о GPU
        gpu_info = get_gpu_info()
        
        # Определяем статус компонентов
        components = {
            'cpu': {
                'status': 'warning' if cpu_percent > 80 else 'ok',
                'percent': cpu_percent
            },
            'memory': {
                'status': 'warning' if memory.percent > 80 else 'ok',
                'percent': memory.percent
            },
            'disk': {
                'status': 'warning' if disk.percent > 90 else 'ok',
                'percent': disk.percent
            },
            'gpu': {
                'status': 'ok' if gpu_info['gpu_available'] else 'unavailable',
                'available': gpu_info['gpu_available'],
                'percent': gpu_info['gpu_percent']
            }
        }
        
        # Определяем общий статус
        all_ok = all(
            comp['status'] in ['ok', 'warning'] 
            for comp in components.values()
        )
        
        return {
            'timestamp': datetime.now().isoformat(),
            'status': 'healthy' if all_ok else 'degraded',
            'components': components,
            'message': 'Все компоненты работают нормально' if all_ok else 'Некоторые компоненты требуют внимания'
        }
    except Exception as e:
        return {
            'timestamp': datetime.now().isoformat(),
            'status': 'error',
            'error': str(e),
            'message': f'Ошибка проверки здоровья системы: {e}'
        }


def get_zora_status() -> Dict[str, Any]:
    """Возвращает статус системы ZORA."""
    # Проверяем компоненты
    docker_status = check_docker()
    qdrant_status = check_qdrant()
    ollama_status = check_ollama()
    
    # Получаем количество векторов Qdrant
    qdrant_vectors = get_qdrant_vectors_count()
    
    # Проверяем основные компоненты
    components = {
        'core': {'status': 'running', 'message': 'Ядро ZORA работает'},
        'qdrant': qdrant_status,
        'agents': {'status': 'running', 'message': 'Агенты доступны'},
        'orchestrator': {'status': 'running', 'message': 'Оркестратор работает'},
        'web': {'status': 'running', 'message': 'Веб-интерфейс доступен'},
        'docker': docker_status,
        'ollama': ollama_status
    }
    
    # Определяем общий статус
    all_running = all(
        comp['status'] in ['running', 'available'] 
        for comp in components.values() 
        if isinstance(comp, dict)
    )
    
    # Подсчитываем работающие компоненты
    working_components = sum(
        1 for comp in components.values() 
        if isinstance(comp, dict) and comp['status'] in ['running', 'available']
    )
    total_components = len(components)
    
    # Получаем uptime системы
    uptime = get_human_readable_uptime()
    
    # Проверяем статус Docker
    docker_running = docker_status.get('status') == 'running'
    
    return {
        'success': True,
        'status': 'running' if all_running else 'degraded',
        'message': 'Все системы работают штатно' if all_running else 'Некоторые компоненты недоступны',
        'working_components': working_components,
        'total_components': total_components,
        'components': {
            'core': components['core']['status'] == 'running',
            'qdrant': components['qdrant']['status'] == 'running',
            'agents': components['agents']['status'] == 'running',
            'orchestrator': components['orchestrator']['status'] == 'running',
            'web': components['web']['status'] == 'running',
            'docker': docker_running,
            'ollama': components['ollama']['status'] == 'running'
        },
        'uptime': uptime,
        'docker_running': docker_running,
        'qdrant_vectors': qdrant_vectors
    }
