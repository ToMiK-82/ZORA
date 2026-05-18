"""
Статический анализ кода проекта.
"""

import logging
import os

logger = logging.getLogger(__name__)


def analyze_project(path: str = None) -> dict:
    """
    Выполняет статический анализ кода проекта.
    
    Args:
        path: Путь к проекту (по умолчанию корень проекта)
        
    Returns:
        Словарь с результатами анализа: {"issues": [...], "files_analyzed": int}
    """
    if path is None:
        path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    
    issues = []
    files_analyzed = 0
    
    try:
        for root, dirs, files in os.walk(path):
            # Пропускаем node_modules, .git, __pycache__
            dirs[:] = [d for d in dirs if d not in ('node_modules', '.git', '__pycache__', 'venv', '.venv')]
            
            for file in files:
                if file.endswith('.py'):
                    files_analyzed += 1
                    filepath = os.path.join(root, file)
                    try:
                        with open(filepath, 'r', encoding='utf-8') as f:
                            content = f.read()
                        lines = content.split('\n')
                        for i, line in enumerate(lines, 1):
                            stripped = line.strip()
                            if 'TODO' in stripped:
                                issues.append(f"{filepath}:{i}: TODO found")
                            elif 'FIXME' in stripped:
                                issues.append(f"{filepath}:{i}: FIXME found")
                            elif 'XXX' in stripped:
                                issues.append(f"{filepath}:{i}: XXX found")
                    except Exception as e:
                        issues.append(f"{filepath}: Error reading: {e}")
    except Exception as e:
        logger.error(f"Analysis error: {e}")
        issues.append(f"Analysis error: {e}")
    
    return {
        "issues": issues,
        "files_analyzed": files_analyzed
    }
