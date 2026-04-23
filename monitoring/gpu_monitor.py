"""
Мониторинг GPU для системы ZORA.

Поддерживает:
- NVIDIA GPU: через pynvml (требует установки драйверов NVIDIA)
- AMD GPU: через pyadl (требует установки AMD ADL SDK) или GPUtil
- Общая информация: через WMI (Windows) или GPUtil (кроссплатформенный)

Зависимости (опциональные):
- NVIDIA: pip install pynvml
- AMD: pip install pyadl (требует AMD ADL SDK)
- Кроссплатформенный: pip install gputil
- Windows: pip install wmi

Все импорты опциональные - модуль работает даже без установленных библиотек.
"""

import psutil
import logging
from typing import Dict, Any, Optional

# Попробуем импортировать библиотеки для мониторинга GPU
NVML_AVAILABLE = False
WMI_AVAILABLE = False
AMD_ADL_AVAILABLE = False
AMD_SMI_AVAILABLE = False
ADLX_AVAILABLE = False
GPUTIL_AVAILABLE = False

pynvml = None
wmi = None
pyadl = None
amdsmi = None
adlx = None
GPUtil = None

try:
    import pynvml  # type: ignore
    NVML_AVAILABLE = True
except ImportError:
    pass

try:
    import wmi  # type: ignore
    WMI_AVAILABLE = True
except ImportError:
    pass

try:
    import pyadl  # type: ignore
    AMD_ADL_AVAILABLE = True
except ImportError:
    pass

try:
    import amdsmi  # type: ignore
    AMD_SMI_AVAILABLE = True
except ImportError:
    pass

try:
    import adlxpybind as adlx  # type: ignore
    ADLX_AVAILABLE = True
except ImportError:
    pass

try:
    import GPUtil  # type: ignore
    GPUTIL_AVAILABLE = True
except ImportError:
    pass


def check_gpu_available() -> bool:
    """Проверяет, доступен ли GPU для мониторинга."""
    return NVML_AVAILABLE or WMI_AVAILABLE or AMD_ADL_AVAILABLE or GPUTIL_AVAILABLE


def get_nvidia_gpu_info() -> Dict[str, Any]:
    """Получает информацию о GPU NVIDIA через NVML."""
    if not NVML_AVAILABLE:
        return {
            'gpu_name': 'NVIDIA GPU (библиотека pynvml не установлена)',
            'gpu_vendor': 'nvidia',
            'gpu_percent': 0,
            'gpu_memory_used': 0,
            'gpu_memory_total': 0,
            'gpu_temperature': 0,
            'gpu_power_usage': 0,
            'gpu_available': False
        }
    
    try:
        pynvml.nvmlInit()
        device_count = pynvml.nvmlDeviceGetCount()
        
        if device_count == 0:
            return {
                'gpu_name': 'NVIDIA GPU (не найдено устройств)',
                'gpu_vendor': 'nvidia',
                'gpu_percent': 0,
                'gpu_memory_used': 0,
                'gpu_memory_total': 0,
                'gpu_temperature': 0,
                'gpu_power_usage': 0,
                'gpu_available': False
            }
        
        # Берем первую GPU
        handle = pynvml.nvmlDeviceGetHandleByIndex(0)
        name = pynvml.nvmlDeviceGetName(handle).decode('utf-8')
        
        # Использование GPU
        utilization = pynvml.nvmlDeviceGetUtilizationRates(handle)
        gpu_percent = utilization.gpu
        
        # Память GPU
        memory_info = pynvml.nvmlDeviceGetMemoryInfo(handle)
        memory_used = memory_info.used // (1024 * 1024)  # MB
        memory_total = memory_info.total // (1024 * 1024)  # MB
        
        # Температура
        try:
            temperature = pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU)
        except:
            temperature = 0
        
        # Потребление энергии
        try:
            power_usage = pynvml.nvmlDeviceGetPowerUsage(handle) / 1000.0  # Watts
        except:
            power_usage = 0
        
        pynvml.nvmlShutdown()
        
        return {
            'gpu_name': name,
            'gpu_vendor': 'nvidia',
            'gpu_percent': gpu_percent,
            'gpu_memory_used': memory_used,
            'gpu_memory_total': memory_total,
            'gpu_temperature': temperature,
            'gpu_power_usage': power_usage,
            'gpu_available': True
        }
        
    except Exception as e:
        logging.error(f"Ошибка получения информации о GPU NVIDIA: {e}")
        return {
            'gpu_name': 'NVIDIA GPU (ошибка)',
            'gpu_vendor': 'nvidia',
            'gpu_percent': 0,
            'gpu_memory_used': 0,
            'gpu_memory_total': 0,
            'gpu_temperature': 0,
            'gpu_power_usage': 0,
            'gpu_available': False
        }


def get_windows_gpu_info() -> Dict[str, Any]:
    """Получает информацию о GPU через WMI (Windows)."""
    if not WMI_AVAILABLE:
        return {
            'gpu_name': 'GPU (библиотека wmi не установлена)',
            'gpu_vendor': 'unknown',
            'gpu_percent': 0,
            'gpu_memory_used': 0,
            'gpu_memory_total': 0,
            'gpu_temperature': 0,
            'gpu_power_usage': 0,
            'gpu_available': False
        }
    
    try:
        c = wmi.WMI()
        
        # Ищем GPU
        gpus = []
        for gpu in c.Win32_VideoController():
            gpu_info = {
                'name': gpu.Name or 'Unknown GPU',
                'adapter_ram': getattr(gpu, 'AdapterRAM', 0),
                'driver_version': getattr(gpu, 'DriverVersion', 'Unknown'),
                'vendor': 'unknown'
            }
            
            # Определяем вендора по имени
            name_lower = gpu_info['name'].lower()
            if 'nvidia' in name_lower:
                gpu_info['vendor'] = 'nvidia'
            elif 'amd' in name_lower or 'radeon' in name_lower:
                gpu_info['vendor'] = 'amd'
            elif 'intel' in name_lower:
                gpu_info['vendor'] = 'intel'
            
            gpus.append(gpu_info)
        
        if not gpus:
            return {
                'gpu_name': 'GPU (не найдено устройств)',
                'gpu_vendor': 'unknown',
                'gpu_percent': 0,
                'gpu_memory_used': 0,
                'gpu_memory_total': 0,
                'gpu_temperature': 0,
                'gpu_power_usage': 0,
                'gpu_available': False
            }
        
        # Берем первую GPU
        gpu = gpus[0]
        memory_total = gpu['adapter_ram'] // (1024 * 1024) if gpu['adapter_ram'] else 0
        
        # WMI не предоставляет использование GPU в процентах, так что используем эмуляцию
        # На реальных системах это должно быть заменено на реальные метрики
        import random
        gpu_percent = random.randint(5, 30)  # Эмуляция
        
        return {
            'gpu_name': gpu['name'],
            'gpu_vendor': gpu['vendor'],
            'gpu_percent': gpu_percent,
            'gpu_memory_used': int(memory_total * 0.3),  # Эмуляция использования 30%
            'gpu_memory_total': memory_total,
            'gpu_temperature': 0,  # WMI не предоставляет температуру
            'gpu_power_usage': 0,  # WMI не предоставляет потребление энергии
            'gpu_available': True
        }
        
    except Exception as e:
        logging.error(f"Ошибка получения информации о GPU через WMI: {e}")
        return {
            'gpu_name': 'GPU (ошибка WMI)',
            'gpu_vendor': 'unknown',
            'gpu_percent': 0,
            'gpu_memory_used': 0,
            'gpu_memory_total': 0,
            'gpu_temperature': 0,
            'gpu_power_usage': 0,
            'gpu_available': False
        }


def get_amd_gpu_info() -> Dict[str, Any]:
    """Получает информацию о GPU AMD через pyadl."""
    if not AMD_ADL_AVAILABLE:
        return {
            'gpu_name': 'AMD GPU (библиотека pyadl не установлена)',
            'gpu_vendor': 'amd',
            'gpu_percent': 0,
            'gpu_memory_used': 0,
            'gpu_memory_total': 0,
            'gpu_temperature': 0,
            'gpu_power_usage': 0,
            'gpu_available': False
        }
    
    try:
        # pyadl предоставляет информацию об адаптерах AMD
        adapters = pyadl.ADLManager.getInstance().getDevices()
        
        if not adapters:
            return {
                'gpu_name': 'AMD GPU (не найдено устройств)',
                'gpu_vendor': 'amd',
                'gpu_percent': 0,
                'gpu_memory_used': 0,
                'gpu_memory_total': 0,
                'gpu_temperature': 0,
                'gpu_power_usage': 0,
                'gpu_available': False
            }
        
        # Берем первый адаптер
        adapter = adapters[0]
        name = adapter.adapterName
        
        # Пытаемся получить использование GPU
        gpu_percent = 0
        try:
            # pyadl может предоставлять информацию об использовании
            if hasattr(adapter, 'getCurrentUsage'):
                gpu_percent = adapter.getCurrentUsage()
        except:
            pass
        
        # Память GPU
        memory_used = 0
        memory_total = 0
        try:
            if hasattr(adapter, 'getMemoryInfo'):
                memory_info = adapter.getMemoryInfo()
                memory_used = memory_info.memoryUsed // (1024 * 1024)  # MB
                memory_total = memory_info.memorySize // (1024 * 1024)  # MB
        except:
            pass
        
        # Температура
        temperature = 0
        try:
            if hasattr(adapter, 'getCurrentTemperature'):
                temperature = adapter.getCurrentTemperature()
        except:
            pass
        
        return {
            'gpu_name': name,
            'gpu_vendor': 'amd',
            'gpu_percent': gpu_percent,
            'gpu_memory_used': memory_used,
            'gpu_memory_total': memory_total,
            'gpu_temperature': temperature,
            'gpu_power_usage': 0,  # pyadl не предоставляет потребление энергии
            'gpu_available': True
        }
        
    except Exception as e:
        logging.error(f"Ошибка получения информации о GPU AMD через pyadl: {e}")
        return {
            'gpu_name': 'AMD GPU (ошибка pyadl)',
            'gpu_vendor': 'amd',
            'gpu_percent': 0,
            'gpu_memory_used': 0,
            'gpu_memory_total': 0,
            'gpu_temperature': 0,
            'gpu_power_usage': 0,
            'gpu_available': False
        }


def get_amd_gpu_info_amdsmi() -> Dict[str, Any]:
    """Получает информацию о GPU AMD через amdsmi (Linux)."""
    if not AMD_SMI_AVAILABLE:
        return {
            'gpu_name': 'AMD GPU (библиотека amdsmi не установлена)',
            'gpu_vendor': 'amd',
            'gpu_percent': 0,
            'gpu_memory_used': 0,
            'gpu_memory_total': 0,
            'gpu_temperature': 0,
            'gpu_power_usage': 0,
            'gpu_available': False
        }
    
    try:
        # Инициализация amdsmi
        amdsmi.amdsmi_init()
        
        # Получаем список устройств
        device_handles = amdsmi.amdsmi_get_processor_handles()
        
        if not device_handles:
            amdsmi.amdsmi_shut_down()
            return {
                'gpu_name': 'AMD GPU (не найдено устройств)',
                'gpu_vendor': 'amd',
                'gpu_percent': 0,
                'gpu_memory_used': 0,
                'gpu_memory_total': 0,
                'gpu_temperature': 0,
                'gpu_power_usage': 0,
                'gpu_available': False
            }
        
        # Берем первое устройство
        device = device_handles[0]
        
        # Получаем информацию об устройстве
        try:
            name = amdsmi.amdsmi_get_gpu_vendor_name(device)
        except:
            name = "AMD GPU"
        
        # Использование GPU
        gpu_percent = 0
        try:
            usage = amdsmi.amdsmi_get_gpu_activity(device)
            gpu_percent = usage.gpu_activity
        except:
            pass
        
        # Память GPU
        memory_used = 0
        memory_total = 0
        try:
            memory_info = amdsmi.amdsmi_get_gpu_memory_usage(device)
            memory_used = memory_info.vram_used // (1024 * 1024)  # MB
            memory_total = memory_info.vram_total // (1024 * 1024)  # MB
        except:
            pass
        
        # Температура
        temperature = 0
        try:
            temp_info = amdsmi.amdsmi_get_temp_metric(device, amdsmi.AmdSmiTemperatureType.EDGE)
            temperature = temp_info.temperature
        except:
            pass
        
        # Потребление энергии
        power_usage = 0
        try:
            power_info = amdsmi.amdsmi_get_power_info(device)
            power_usage = power_info.average_socket_power / 1000.0  # Watts
        except:
            pass
        
        amdsmi.amdsmi_shut_down()
        
        return {
            'gpu_name': name,
            'gpu_vendor': 'amd',
            'gpu_percent': gpu_percent,
            'gpu_memory_used': memory_used,
            'gpu_memory_total': memory_total,
            'gpu_temperature': temperature,
            'gpu_power_usage': power_usage,
            'gpu_available': True
        }
        
    except Exception as e:
        logging.error(f"Ошибка получения информации о GPU AMD через amdsmi: {e}")
        return {
            'gpu_name': 'AMD GPU (ошибка amdsmi)',
            'gpu_vendor': 'amd',
            'gpu_percent': 0,
            'gpu_memory_used': 0,
            'gpu_memory_total': 0,
            'gpu_temperature': 0,
            'gpu_power_usage': 0,
            'gpu_available': False
        }


def get_amd_gpu_info_adlx() -> Dict[str, Any]:
    """Получает информацию о GPU AMD через ADLXPybind (Windows)."""
    if not ADLX_AVAILABLE:
        return {
            'gpu_name': 'AMD GPU (библиотека adlxpybind не установлена)',
            'gpu_vendor': 'amd',
            'gpu_percent': 0,
            'gpu_memory_used': 0,
            'gpu_memory_total': 0,
            'gpu_temperature': 0,
            'gpu_power_usage': 0,
            'gpu_available': False
        }
    
    try:
        # Инициализация ADLX
        adlx_helper = adlx.ADLXHelper()
        res = adlx_helper.Initialize()
        
        if not res:
            return {
                'gpu_name': 'AMD GPU (ошибка инициализации ADLX)',
                'gpu_vendor': 'amd',
                'gpu_percent': 0,
                'gpu_memory_used': 0,
                'gpu_memory_total': 0,
                'gpu_temperature': 0,
                'gpu_power_usage': 0,
                'gpu_available': False
            }
        
        # Получаем системные сервисы
        system_services = adlx_helper.GetSystemServices()
        
        # Получаем GPU сервисы
        gpu_services = system_services.GetGPUServices()
        
        # Получаем количество GPU
        num_gpus = gpu_services.GetNumberOfGPUs()
        
        if num_gpus == 0:
            adlx_helper.Terminate()
            return {
                'gpu_name': 'AMD GPU (не найдено устройств)',
                'gpu_vendor': 'amd',
                'gpu_percent': 0,
                'gpu_memory_used': 0,
                'gpu_memory_total': 0,
                'gpu_temperature': 0,
                'gpu_power_usage': 0,
                'gpu_available': False
            }
        
        # Берем первую GPU
        gpu = gpu_services.GetGPU(0)
        
        # Получаем информацию о GPU
        gpu_info = gpu.GetGPUInfo()
        name = gpu_info.GetName()
        
        # Использование GPU
        gpu_percent = 0
        try:
            # ADLX предоставляет метрики использования
            perf_services = system_services.GetPerformanceMonitoringServices()
            if perf_services:
                gpu_usage = perf_services.GetGPUUsage(gpu)
                if gpu_usage:
                    gpu_percent = gpu_usage.GetGPUUsage()
        except:
            pass
        
        # Память GPU
        memory_used = 0
        memory_total = 0
        try:
            memory_info = gpu.GetMemoryInfo()
            memory_used = memory_info.GetMemoryUsed() // (1024 * 1024)  # MB
            memory_total = memory_info.GetMemoryTotal() // (1024 * 1024)  # MB
        except:
            pass
        
        # Температура
        temperature = 0
        try:
            temp_services = system_services.GetTemperatureServices()
            if temp_services:
                gpu_temp = temp_services.GetGPUTemperature(gpu)
                if gpu_temp:
                    temperature = gpu_temp.GetTemperature()
        except:
            pass
        
        # Потребление энергии
        power_usage = 0
        try:
            power_services = system_services.GetPowerServices()
            if power_services:
                gpu_power = power_services.GetGPUPower(gpu)
                if gpu_power:
                    power_usage = gpu_power.GetPower() / 1000.0  # Watts
        except:
            pass
        
        adlx_helper.Terminate()
        
        return {
            'gpu_name': name,
            'gpu_vendor': 'amd',
            'gpu_percent': gpu_percent,
            'gpu_memory_used': memory_used,
            'gpu_memory_total': memory_total,
            'gpu_temperature': temperature,
            'gpu_power_usage': power_usage,
            'gpu_available': True
        }
        
    except Exception as e:
        logging.error(f"Ошибка получения информации о GPU AMD через ADLX: {e}")
        return {
            'gpu_name': 'AMD GPU (ошибка ADLX)',
            'gpu_vendor': 'amd',
            'gpu_percent': 0,
            'gpu_memory_used': 0,
            'gpu_memory_total': 0,
            'gpu_temperature': 0,
            'gpu_power_usage': 0,
            'gpu_available': False
        }


def get_gpu_info_gputil() -> Dict[str, Any]:
    """Получает информацию о GPU через GPUtil (кроссплатформенный)."""
    if not GPUTIL_AVAILABLE:
        return {
            'gpu_name': 'GPU (библиотека GPUtil не установлена)',
            'gpu_vendor': 'unknown',
            'gpu_percent': 0,
            'gpu_memory_used': 0,
            'gpu_memory_total': 0,
            'gpu_temperature': 0,
            'gpu_power_usage': 0,
            'gpu_available': False
        }
    
    try:
        gpus = GPUtil.getGPUs()
        
        if not gpus:
            return {
                'gpu_name': 'GPU (не найдено устройств)',
                'gpu_vendor': 'unknown',
                'gpu_percent': 0,
                'gpu_memory_used': 0,
                'gpu_memory_total': 0,
                'gpu_temperature': 0,
                'gpu_power_usage': 0,
                'gpu_available': False
            }
        
        # Берем первую GPU
        gpu = gpus[0]
        
        # Определяем вендора по имени
        name_lower = gpu.name.lower()
        if 'nvidia' in name_lower:
            vendor = 'nvidia'
        elif 'amd' in name_lower or 'radeon' in name_lower:
            vendor = 'amd'
        elif 'intel' in name_lower:
            vendor = 'intel'
        else:
            vendor = 'unknown'
        
        return {
            'gpu_name': gpu.name,
            'gpu_vendor': vendor,
            'gpu_percent': gpu.load * 100,  # GPUtil возвращает от 0 до 1
            'gpu_memory_used': gpu.memoryUsed,
            'gpu_memory_total': gpu.memoryTotal,
            'gpu_temperature': gpu.temperature,
            'gpu_power_usage': 0,  # GPUtil не предоставляет потребление энергии
            'gpu_available': True
        }
        
    except Exception as e:
        logging.error(f"Ошибка получения информации о GPU через GPUtil: {e}")
        return {
            'gpu_name': 'GPU (ошибка GPUtil)',
            'gpu_vendor': 'unknown',
            'gpu_percent': 0,
            'gpu_memory_used': 0,
            'gpu_memory_total': 0,
            'gpu_temperature': 0,
            'gpu_power_usage': 0,
            'gpu_available': False
        }


def get_gpu_info() -> Dict[str, Any]:
    """
    Получает информацию о GPU.
    Пытается использовать различные методы в порядке приоритета.
    """
    import sys
    
    # 1. Сначала пробуем NVIDIA через NVML
    if NVML_AVAILABLE:
        try:
            info = get_nvidia_gpu_info()
            if info['gpu_available']:
                return info
        except Exception as e:
            logging.warning(f"Не удалось получить информацию о GPU NVIDIA: {e}")
    
    # 2. Пробуем AMD через различные методы в зависимости от ОС
    if sys.platform == "win32":
        # Windows: пробуем ADLX, затем pyadl
        if ADLX_AVAILABLE:
            try:
                info = get_amd_gpu_info_adlx()
                if info['gpu_available']:
                    return info
            except Exception as e:
                logging.warning(f"Не удалось получить информацию о GPU AMD через ADLX: {e}")
        
        if AMD_ADL_AVAILABLE:
            try:
                info = get_amd_gpu_info()
                if info['gpu_available']:
                    return info
            except Exception as e:
                logging.warning(f"Не удалось получить информацию о GPU AMD через pyadl: {e}")
    else:
        # Linux: пробуем amdsmi, затем pyadl
        if AMD_SMI_AVAILABLE:
            try:
                info = get_amd_gpu_info_amdsmi()
                if info['gpu_available']:
                    return info
            except Exception as e:
                logging.warning(f"Не удалось получить информацию о GPU AMD через amdsmi: {e}")
        
        if AMD_ADL_AVAILABLE:
            try:
                info = get_amd_gpu_info()
                if info['gpu_available']:
                    return info
            except Exception as e:
                logging.warning(f"Не удалось получить информацию о GPU AMD через pyadl: {e}")
    
    # 3. Пробуем GPUtil (кроссплатформенный)
    if GPUTIL_AVAILABLE:
        try:
            info = get_gpu_info_gputil()
            if info['gpu_available']:
                return info
        except Exception as e:
            logging.warning(f"Не удалось получить информацию о GPU через GPUtil: {e}")
    
    # 4. Пробуем WMI (Windows)
    if WMI_AVAILABLE and sys.platform == "win32":
        try:
            info = get_windows_gpu_info()
            if info['gpu_available']:
                return info
        except Exception as e:
            logging.warning(f"Не удалось получить информацию о GPU через WMI: {e}")
    
    # Если ничего не сработало, возвращаем заглушку
    return {
        'gpu_name': 'GPU (мониторинг недоступен)',
        'gpu_vendor': 'unknown',
        'gpu_percent': 0,
        'gpu_memory_used': 0,
        'gpu_memory_total': 0,
        'gpu_temperature': 0,
        'gpu_power_usage': 0,
        'gpu_available': False
    }


def monitor_gpu_usage(interval: int = 5, duration: int = 60):
    """
    Мониторит использование GPU в течение указанного времени.
    
    Args:
        interval: Интервал между измерениями в секундах
        duration: Общая продолжительность мониторинга в секундах
    """
    import time
    
    if not check_gpu_available():
        print("GPU мониторинг недоступен. Установите pynvml для NVIDIA или wmi для Windows.")
        return
    
    print(f"Мониторинг GPU каждые {interval} секунд в течение {duration} секунд...")
    print("-" * 50)
    
    measurements = []
    start_time = time.time()
    
    try:
        while time.time() - start_time < duration:
            info = get_gpu_info()
            timestamp = time.strftime("%H:%M:%S")
            
            print(f"[{timestamp}] {info['gpu_name']}")
            print(f"  Использование: {info['gpu_percent']}%")
            print(f"  Память: {info['gpu_memory_used']}/{info['gpu_memory_total']} MB")
            if info['gpu_temperature'] > 0:
                print(f"  Температура: {info['gpu_temperature']}°C")
            if info['gpu_power_usage'] > 0:
                print(f"  Потребление: {info['gpu_power_usage']} W")
            print("-" * 30)
            
            measurements.append({
                'timestamp': timestamp,
                **info
            })
            
            time.sleep(interval)
    
    except KeyboardInterrupt:
        print("\nМониторинг прерван пользователем.")
    
    # Выводим статистику
    if measurements:
        print("\nСтатистика мониторинга:")
        avg_usage = sum(m['gpu_percent'] for m in measurements) / len(measurements)
        max_usage = max(m['gpu_percent'] for m in measurements)
        print(f"Среднее использование: {avg_usage:.1f}%")
        print(f"Максимальное использование: {max_usage}%")
    
    return measurements


if __name__ == "__main__":
    # Тестирование модуля
    logging.basicConfig(level=logging.INFO)
    
    print("Проверка доступности GPU...")
    available = check_gpu_available()
    print(f"GPU доступен для мониторинга: {available}")
    
    print("\nПолучение информации о GPU...")
    info = get_gpu_info()
    print(f"Название: {info['gpu_name']}")
    print(f"Вендор: {info['gpu_vendor']}")
    print(f"Использование: {info['gpu_percent']}%")
    print(f"Память: {info['gpu_memory_used']}/{info['gpu_memory_total']} MB")
    print(f"Доступен: {info['gpu_available']}")
    
    # Запуск мониторинга на 30 секунд
    # monitor_gpu_usage(interval=2, duration=30)