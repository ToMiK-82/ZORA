"""
Утилиты для выполнения shell-команд.
"""

import logging
import subprocess
import sys

logger = logging.getLogger(__name__)


def run_command(command: str, timeout: int = 60) -> str:
    """
    Выполняет shell-команду и возвращает её вывод.
    
    Args:
        command: Команда для выполнения
        timeout: Таймаут в секундах
        
    Returns:
        stdout + stderr команды
    """
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout
        )
        output = result.stdout
        if result.stderr:
            output += f"\nSTDERR:\n{result.stderr}"
        if result.returncode != 0:
            output += f"\nExit code: {result.returncode}"
        return output
    except subprocess.TimeoutExpired:
        return f"Command timed out after {timeout}s"
    except Exception as e:
        logger.error(f"Shell command error: {e}")
        return f"Error: {str(e)}"
