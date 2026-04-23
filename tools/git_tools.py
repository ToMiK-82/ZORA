"""
Инструменты для работы с Git.
"""

import subprocess
import os
import sys
from typing import List, Dict, Any, Optional


def run_git_command(args: List[str], cwd: str = None) -> Dict[str, Any]:
    """
    Выполняет команду Git и возвращает результат.
    
    Args:
        args: Аргументы команды (например, ['status', '--short']).
        cwd: Рабочая директория (по умолчанию текущая).
    
    Returns:
        Словарь с результатами.
    """
    if cwd is None:
        cwd = os.getcwd()
    cmd = ['git'] + args
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=30
        )
        return {
            "success": result.returncode == 0,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "command": " ".join(cmd)
        }
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "error": "Таймаут выполнения команды Git (30 секунд)",
            "command": " ".join(cmd)
        }
    except FileNotFoundError:
        return {
            "success": False,
            "error": "Git не установлен или не найден в PATH",
            "command": " ".join(cmd)
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "command": " ".join(cmd)
        }


def git_status(cwd: str = None) -> Dict[str, Any]:
    """Возвращает статус репозитория."""
    return run_git_command(['status', '--short'], cwd)


def git_branch(cwd: str = None) -> Dict[str, Any]:
    """Возвращает список веток."""
    result = run_git_command(['branch', '-a'], cwd)
    if result['success']:
        branches = [b.strip() for b in result['stdout'].split('\n') if b.strip()]
        current = None
        for b in branches:
            if b.startswith('*'):
                current = b[1:].strip()
                break
        result['branches'] = branches
        result['current'] = current
    return result


def git_log(count: int = 10, cwd: str = None) -> Dict[str, Any]:
    """Возвращает последние коммиты."""
    result = run_git_command(['log', f'--oneline', f'-{count}'], cwd)
    if result['success']:
        commits = [c.strip() for c in result['stdout'].split('\n') if c.strip()]
        result['commits'] = commits
    return result


def git_diff(file_path: str = None, cwd: str = None) -> Dict[str, Any]:
    """Возвращает diff изменений."""
    args = ['diff']
    if file_path:
        args.append(file_path)
    return run_git_command(args, cwd)


def git_add(files: List[str] = None, cwd: str = None) -> Dict[str, Any]:
    """Добавляет файлы в индекс."""
    if files is None:
        return run_git_command(['add', '.'], cwd)
    else:
        args = ['add'] + files
        return run_git_command(args, cwd)


def git_commit(message: str, cwd: str = None) -> Dict[str, Any]:
    """Создаёт коммит."""
    return run_git_command(['commit', '-m', message], cwd)


def git_push(branch: str = None, remote: str = 'origin', cwd: str = None) -> Dict[str, Any]:
    """Пушит изменения в удалённый репозиторий."""
    args = ['push', remote]
    if branch:
        args.append(branch)
    return run_git_command(args, cwd)


def git_pull(remote: str = 'origin', branch: str = None, cwd: str = None) -> Dict[str, Any]:
    """Тянет изменения из удалённого репозитория."""
    args = ['pull', remote]
    if branch:
        args.append(branch)
    return run_git_command(args, cwd)


def git_checkout(branch: str, create: bool = False, cwd: str = None) -> Dict[str, Any]:
    """Переключается на ветку."""
    args = ['checkout']
    if create:
        args.append('-b')
    args.append(branch)
    return run_git_command(args, cwd)


def git_merge(branch: str, cwd: str = None) -> Dict[str, Any]:
    """Сливает ветку в текущую."""
    return run_git_command(['merge', branch], cwd)


def git_reset(hard: bool = False, commit: str = None, cwd: str = None) -> Dict[str, Any]:
    """Сбрасывает изменения."""
    args = ['reset']
    if hard:
        args.append('--hard')
    if commit:
        args.append(commit)
    else:
        args.append('HEAD')
    return run_git_command(args, cwd)


def git_stash(action: str = 'list', message: str = None, cwd: str = None) -> Dict[str, Any]:
    """Работает со stash."""
    if action == 'list':
        return run_git_command(['stash', 'list'], cwd)
    elif action == 'save':
        args = ['stash', 'save']
        if message:
            args.append(message)
        return run_git_command(args, cwd)
    elif action == 'pop':
        return run_git_command(['stash', 'pop'], cwd)
    elif action == 'apply':
        return run_git_command(['stash', 'apply'], cwd)
    elif action == 'drop':
        return run_git_command(['stash', 'drop'], cwd)
    else:
        return {"success": False, "error": f"Неизвестное действие stash: {action}"}


def git_remote(cwd: str = None) -> Dict[str, Any]:
    """Возвращает список удалённых репозиториев."""
    result = run_git_command(['remote', '-v'], cwd)
    if result['success']:
        remotes = {}
        for line in result['stdout'].strip().split('\n'):
            if line:
                parts = line.split()
                if len(parts) >= 2:
                    name = parts[0]
                    url = parts[1]
                    remotes[name] = url
        result['remotes'] = remotes
    return result


def git_clone(repo_url: str, target_dir: str = None, cwd: str = None) -> Dict[str, Any]:
    """Клонирует репозиторий."""
    args = ['clone', repo_url]
    if target_dir:
        args.append(target_dir)
    return run_git_command(args, cwd)


def get_git_status():
    """Возвращает сводный статус Git репозитория."""
    import os
    
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    
    # Проверяем, является ли директория Git репозиторием
    if not os.path.exists(os.path.join(project_root, '.git')):
        return {
            'success': False,
            'message': 'Не является Git репозиторием',
            'branch': 'unknown',
            'changes': 0
        }
    
    # Получаем статус
    status_result = git_status()
    branch_result = git_branch()
    
    # Анализируем вывод статуса для подсчёта изменений
    changes = 0
    if status_result['success'] and status_result.get('stdout'):
        output = status_result['stdout']
        # Подсчитываем строки с изменениями
        lines = output.split('\n')
        for line in lines:
            if line.strip() and not line.startswith('#'):
                changes += 1
    
    # Получаем текущую ветку
    current_branch = 'unknown'
    if branch_result['success']:
        current_branch = branch_result.get('current', 'unknown')
    
    return {
        'success': True,
        'message': f'Git репозиторий: ветка {current_branch}, изменений: {changes}',
        'branch': current_branch,
        'changes': changes,
        'status_output': status_result.get('stdout', '')[:500] if status_result['success'] else ''
    }


if __name__ == "__main__":
    # Пример использования
    print("Статус Git:")
    status = git_status()
    if status['success']:
        print(status['stdout'])
    else:
        print("Ошибка:", status.get('error'))
    
    print("\nВетки:")
    branches = git_branch()
    if branches['success']:
        print("Текущая ветка:", branches.get('current'))
        print("Все ветки:", branches.get('branches'))
    
    print("\nПоследние коммиты:")
    log = git_log(5)
    if log['success']:
        for commit in log.get('commits', []):
            print("  ", commit)
    
    print("\nСводный статус:")
    summary = get_git_status()
    print(f"  Ветка: {summary['branch']}")
    print(f"  Изменений: {summary['changes']}")
    print(f"  Сообщение: {summary['message']}")
