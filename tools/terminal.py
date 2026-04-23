"""
Инструменты для работы с терминалом.
"""

import subprocess
import threading
import queue
import time
import os
import sys
from typing import List, Dict, Any, Optional, Callable


def run_command(
    command: List[str],
    cwd: str = None,
    timeout: int = 60,
    realtime_callback: Callable[[str], None] = None
) -> Dict[str, Any]:
    """
    Выполняет команду в терминале и возвращает результат.
    
    Args:
        command: Команда и аргументы.
        cwd: Рабочая директория.
        timeout: Таймаут в секундах.
        realtime_callback: Функция для получения вывода в реальном времени.
    
    Returns:
        Словарь с результатами.
    """
    if cwd is None:
        cwd = os.getcwd()
    
    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.PIPE,
            text=True,
            cwd=cwd,
            bufsize=1,
            universal_newlines=True
        )
        
        stdout_lines = []
        stderr_lines = []
        
        def read_stream(stream, store, prefix=''):
            for line in iter(stream.readline, ''):
                if line:
                    store.append(line)
                    if realtime_callback:
                        realtime_callback(prefix + line)
        
        stdout_thread = threading.Thread(target=read_stream, args=(process.stdout, stdout_lines))
        stderr_thread = threading.Thread(target=read_stream, args=(process.stderr, stderr_lines, '[stderr] '))
        stdout_thread.daemon = True
        stderr_thread.daemon = True
        stdout_thread.start()
        stderr_thread.start()
        
        process.wait(timeout=timeout)
        
        # Дожидаемся завершения потоков чтения
        stdout_thread.join(timeout=1)
        stderr_thread.join(timeout=1)
        
        return {
            "success": process.returncode == 0,
            "returncode": process.returncode,
            "stdout": "".join(stdout_lines),
            "stderr": "".join(stderr_lines),
            "command": " ".join(command)
        }
    except subprocess.TimeoutExpired:
        process.kill()
        return {
            "success": False,
            "error": f"Таймаут выполнения команды ({timeout} секунд)",
            "command": " ".join(command)
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "command": " ".join(command)
        }


def run_shell_command(
    shell_cmd: str,
    cwd: str = None,
    timeout: int = 60,
    shell: bool = True
) -> Dict[str, Any]:
    """
    Выполняет команду в оболочке (shell).
    
    Args:
        shell_cmd: Команда для выполнения.
        cwd: Рабочая директория.
        timeout: Таймаут в секундах.
        shell: Использовать ли shell.
    
    Returns:
        Словарь с результатами.
    """
    if cwd is None:
        cwd = os.getcwd()
    
    try:
        result = subprocess.run(
            shell_cmd,
            shell=shell,
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=timeout
        )
        return {
            "success": result.returncode == 0,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "command": shell_cmd
        }
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "error": f"Таймаут выполнения команды ({timeout} секунд)",
            "command": shell_cmd
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "command": shell_cmd
        }


def run_background_command(
    command: List[str],
    cwd: str = None,
    output_queue: queue.Queue = None
) -> Dict[str, Any]:
    """
    Запускает команду в фоновом режиме.
    
    Args:
        command: Команда и аргументы.
        cwd: Рабочая директория.
        output_queue: Очередь для получения вывода.
    
    Returns:
        Словарь с идентификатором процесса.
    """
    if cwd is None:
        cwd = os.getcwd()
    
    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.PIPE,
            text=True,
            cwd=cwd,
            bufsize=1,
            universal_newlines=True
        )
        
        def monitor():
            while True:
                line = process.stdout.readline()
                if line:
                    if output_queue:
                        output_queue.put(('stdout', line))
                else:
                    break
            process.wait()
            if output_queue:
                output_queue.put(('exit', process.returncode))
        
        thread = threading.Thread(target=monitor)
        thread.daemon = True
        thread.start()
        
        return {
            "success": True,
            "pid": process.pid,
            "process": process,
            "thread": thread
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


def list_processes() -> List[Dict[str, Any]]:
    """
    Возвращает список запущенных процессов (только для Unix-подобных систем).
    """
    try:
        if sys.platform == "win32":
            # Для Windows используем tasklist
            result = run_shell_command("tasklist /FO CSV /NH")
            if not result['success']:
                return []
            processes = []
            for line in result['stdout'].strip().split('\n'):
                if line:
                    parts = line.strip('"').split('","')
                    if len(parts) >= 5:
                        processes.append({
                            'name': parts[0],
                            'pid': int(parts[1]),
                            'memory': parts[4]
                        })
            return processes
        else:
            # Для Linux/Mac используем ps
            result = run_shell_command("ps aux")
            if not result['success']:
                return []
            processes = []
            lines = result['stdout'].strip().split('\n')
            if len(lines) > 1:
                headers = lines[0].split()
                for line in lines[1:]:
                    parts = line.split(None, len(headers)-1)
                    if len(parts) >= len(headers):
                        processes.append({
                            'user': parts[0],
                            'pid': int(parts[1]),
                            'cpu': parts[2],
                            'mem': parts[3],
                            'command': ' '.join(parts[10:]) if len(parts) > 10 else ''
                        })
            return processes
    except Exception as e:
        return []


def kill_process(pid: int) -> Dict[str, Any]:
    """
    Завершает процесс по PID.
    """
    try:
        if sys.platform == "win32":
            result = run_shell_command(f"taskkill /PID {pid} /F")
        else:
            result = run_shell_command(f"kill -9 {pid}")
        return result
    except Exception as e:
        return {"success": False, "error": str(e)}


if __name__ == "__main__":
    # Пример использования
    print("Запуск команды 'echo Hello World':")
    result = run_command(["echo", "Hello World"])
    print(f"Успех: {result['success']}")
    print(f"Вывод: {result['stdout']}")
    
    print("\nЗапуск shell команды 'dir' (Windows) или 'ls' (Linux):")
    if sys.platform == "win32":
        result = run_shell_command("dir")
    else:
        result = run_shell_command("ls -la")
    print(f"Успех: {result['success']}")
    print(f"Вывод (первые 200 символов): {result['stdout'][:200]}")