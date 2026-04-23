"""
Утилита для выполнения shell команд.
"""

import subprocess
import logging
import sys

logger = logging.getLogger(__name__)

def _decode_output(bytes_output: bytes) -> str:
    """Декодирует вывод команды с учётом кодовой страницы Windows."""
    if not bytes_output:
        return ''
    # Сначала пробуем UTF-8
    try:
        return bytes_output.decode('utf-8')
    except UnicodeDecodeError:
        # Если не вышло, пробуем cp866 (кодовая страница консоли Windows по умолчанию)
        try:
            return bytes_output.decode('cp866')
        except UnicodeDecodeError:
            # В крайнем случае заменяем ошибки
            return bytes_output.decode('utf-8', errors='replace')

def run_command(cmd: str) -> str:
    """
    Выполняет shell команду и возвращает результат в UTF-8.
    """
    try:
        # Запускаем команду, получаем вывод в байтах
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            timeout=30
        )
        # Декодируем stdout и stderr с учётом кодировки
        stdout = _decode_output(result.stdout)
        stderr = _decode_output(result.stderr)
        return f"STDOUT:\n{stdout}\nSTDERR:\n{stderr}"
    except subprocess.TimeoutExpired:
        return "Ошибка: команда выполнялась слишком долго (таймаут 30 секунд)"
    except Exception as e:
        return f"Ошибка: {str(e)}"
