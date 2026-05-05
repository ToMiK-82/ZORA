#!/usr/bin/env python3
"""
Поиск и удаление дубликатов файлов в проекте ZORA.
"""

import os
import hashlib
import logging
from collections import defaultdict
from typing import Dict, List, Any

logger = logging.getLogger(__name__)


def find_duplicates(directory: str = None) -> Dict[str, List[str]]:
    """Находит дубликаты файлов по содержимому (MD5)."""
    if directory is None:
        directory = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    hashes = defaultdict(list)

    for root, dirs, files in os.walk(directory):
        # Пропускаем системные и виртуальные окружения
        dirs[:] = [d for d in dirs if d not in ['venv', '.git', '__pycache__', 'node_modules', '.mypy_cache', '.pytest_cache']]

        for file in files:
            if file.endswith(('.pyc', '.pyo', '.so', '.dll', '.pyd')):
                continue

            filepath = os.path.join(root, file)
            try:
                with open(filepath, 'rb') as f:
                    file_hash = hashlib.md5(f.read()).hexdigest()
                hashes[file_hash].append(filepath)
            except (PermissionError, OSError):
                pass

    return {h: paths for h, paths in hashes.items() if len(paths) > 1}


def get_duplicate_report() -> Dict[str, Any]:
    """Возвращает отчёт о дубликатах."""
    duplicates = find_duplicates()

    # Группируем по размеру
    size_groups = defaultdict(list)
    for hash_val, paths in duplicates.items():
        try:
            size = os.path.getsize(paths[0])
            size_groups[size].append({"hash": hash_val, "paths": paths, "size": size})
        except OSError:
            pass

    return {
        "total_duplicate_groups": len(duplicates),
        "total_duplicate_files": sum(len(paths) for paths in duplicates.values()),
        "total_size_mb": sum(os.path.getsize(p[0]) for p in duplicates.values() if p) / (1024 * 1024),
        "duplicates": duplicates,
        "by_size": sorted(size_groups.items(), key=lambda x: x[0], reverse=True)
    }


def remove_duplicates(keep_first: bool = True) -> Dict[str, Any]:
    """Удаляет дубликаты, оставляя только первый файл в каждой группе."""
    report = get_duplicate_report()
    removed = []
    errors = []

    for hash_value, paths in report["duplicates"].items():
        # Сортируем по длине пути (чем короче, тем вероятнее корневой/оригинал)
        paths.sort(key=len)

        # Первый файл оставляем
        to_keep = paths[0]
        to_remove = paths[1:]

        for path in to_remove:
            try:
                os.remove(path)
                removed.append(path)
                logger.info(f"Удалён дубликат: {path}")
            except Exception as e:
                errors.append({"path": path, "error": str(e)})
                logger.error(f"Ошибка удаления {path}: {e}")

    return {
        "removed_count": len(removed),
        "removed_files": removed,
        "errors": errors,
        "kept_originals": [paths[0] for paths in report["duplicates"].values()]
    }


def find_orphan_files() -> Dict[str, Any]:
    """Находит .py файлы, которые не импортируются нигде в проекте."""
    import re

    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def find_all_py_files(directory: str) -> List[str]:
        py_files = []
        for root, dirs, files in os.walk(directory):
            dirs[:] = [d for d in dirs if d not in ['venv', '.git', '__pycache__']]
            for file in files:
                if file.endswith('.py'):
                    py_files.append(os.path.join(root, file))
        return py_files

    def find_imports_in_file(filepath: str) -> set:
        imports = set()
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
                matches = re.findall(r'^(?:from|import)\s+([a-zA-Z_][a-zA-Z0-9_.]*)', content, re.MULTILINE)
                for match in matches:
                    module = match.split('.')[0]
                    imports.add(module)
        except Exception:
            pass
        return imports

    all_files = find_all_py_files(project_root)
    entry_points = ['zora_launcher.py', 'main.py', 'setup.py']

    all_imports = set()
    for filepath in all_files:
        filename = os.path.basename(filepath)
        if filename in entry_points:
            continue
        imports = find_imports_in_file(filepath)
        all_imports.update(imports)

    orphan_files = []
    for filepath in all_files:
        filename = os.path.basename(filepath).replace('.py', '')
        if filename in entry_points:
            continue
        if filename not in all_imports:
            orphan_files.append(filepath)

    return {
        "total_files": len(all_files),
        "orphan_files": orphan_files,
        "orphan_count": len(orphan_files)
    }


if __name__ == "__main__":
    import json
    print("=== ОТЧЁТ О ДУБЛИКАТАХ ===")
    report = get_duplicate_report()
    print(json.dumps(report, indent=2, ensure_ascii=False, default=str))

    print("\n=== СИРОТСКИЕ ФАЙЛЫ ===")
    orphans = find_orphan_files()
    print(f"Всего файлов: {orphans['total_files']}")
    print(f"Сиротских: {orphans['orphan_count']}")
    for f in orphans['orphan_files']:
        print(f"  - {f}")
