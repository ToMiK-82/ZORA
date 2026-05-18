"""
Запуск тестов проекта.
"""

import logging
import subprocess
import os
import sys

logger = logging.getLogger(__name__)


def run_all_tests(path: str = None) -> dict:
    """
    Запускает все тесты проекта через pytest.
    
    Args:
        path: Путь к проекту (по умолчанию корень проекта)
        
    Returns:
        Словарь с результатами: {"passed": int, "failed": int, "output": str}
    """
    if path is None:
        path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    
    try:
        result = subprocess.run(
            [sys.executable, '-m', 'pytest', path, '-v', '--tb=short'],
            capture_output=True,
            text=True,
            timeout=120
        )
        
        output = result.stdout + result.stderr
        
        # Парсим результаты
        passed = 0
        failed = 0
        
        for line in output.split('\n'):
            if 'passed' in line and 'failed' not in line:
                passed += 1
            elif 'FAILED' in line:
                failed += 1
        
        # Пробуем распарсить итоговую строку pytest
        import re
        match = re.search(r'(\d+)\s+passed', output)
        if match:
            passed = int(match.group(1))
        match = re.search(r'(\d+)\s+failed', output)
        if match:
            failed = int(match.group(1))
        
        return {
            "passed": passed,
            "failed": failed,
            "output": output[:2000]  # Ограничиваем вывод
        }
    except subprocess.TimeoutExpired:
        return {"passed": 0, "failed": 0, "output": "Tests timed out"}
    except Exception as e:
        logger.error(f"Test runner error: {e}")
        return {"passed": 0, "failed": 0, "output": f"Error: {str(e)}"}
