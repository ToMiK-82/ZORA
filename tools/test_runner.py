"""
Инструменты для запуска тестов.
"""

import subprocess
import sys
import os
import time
from typing import List, Dict, Any


def run_pytest(test_path: str = ".", options: List[str] = None) -> Dict[str, Any]:
    """
    Запускает pytest для указанного пути с детализированными результатами.
    
    Args:
        test_path: Путь к тестам (файл, директория, маркер).
        options: Дополнительные опции pytest.
    
    Returns:
        Словарь с детализированными результатами.
    """
    if options is None:
        options = []
    
    # Добавляем опции для детализированного вывода
    detailed_options = options + ["-v", "--tb=short"]
    
    cmd = [sys.executable, "-m", "pytest", test_path] + detailed_options
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,
            cwd=os.getcwd()
        )
        
        # Анализируем вывод для извлечения деталей
        stdout = result.stdout
        stderr = result.stderr
        
        # Извлекаем статистику тестов
        passed = 0
        failed = 0
        skipped = 0
        errors = 0
        
        # Парсим строки с результатами
        for line in stdout.split('\n'):
            if "passed" in line and "failed" in line and "skipped" in line:
                # Формат: "X passed, Y failed, Z skipped"
                import re
                numbers = re.findall(r'\d+', line)
                if len(numbers) >= 3:
                    passed = int(numbers[0])
                    failed = int(numbers[1])
                    skipped = int(numbers[2])
                break
        
        # Извлекаем имена упавших тестов
        failed_tests = []
        current_test = None
        for line in stdout.split('\n'):
            if line.startswith("FAILED "):
                test_name = line.split("FAILED ")[1].split("::")[-1]
                failed_tests.append(test_name)
            elif line.startswith("ERROR "):
                test_name = line.split("ERROR ")[1].split("::")[-1]
                failed_tests.append(test_name)
        
        # Формируем детализированный отчет
        detailed_report = f"📊 Результаты тестов:\n"
        detailed_report += f"✅ Пройдено: {passed}\n"
        detailed_report += f"❌ Не пройдено: {failed}\n"
        detailed_report += f"⏭️  Пропущено: {skipped}\n"
        
        if failed_tests:
            detailed_report += f"\n📋 Упавшие тесты:\n"
            for i, test in enumerate(failed_tests[:10], 1):  # Ограничиваем 10 тестами
                detailed_report += f"  {i}. {test}\n"
            if len(failed_tests) > 10:
                detailed_report += f"  ... и ещё {len(failed_tests) - 10} тестов\n"
        
        # Сохраняем полный отчет в файл
        report_file = "test_report.txt"
        with open(report_file, "w", encoding="utf-8") as f:
            f.write(f"Команда: {' '.join(cmd)}\n")
            f.write(f"Время: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"\n{detailed_report}\n")
            f.write(f"\nПолный вывод:\n{stdout}\n")
            if stderr:
                f.write(f"\nОшибки:\n{stderr}\n")
        
        return {
            "success": result.returncode == 0,
            "returncode": result.returncode,
            "stdout": stdout,
            "stderr": stderr,
            "command": " ".join(cmd),
            "detailed_report": detailed_report,
            "statistics": {
                "passed": passed,
                "failed": failed,
                "skipped": skipped,
                "errors": errors,
                "total": passed + failed + skipped + errors
            },
            "failed_tests": failed_tests,
            "report_file": report_file
        }
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "error": "Таймаут выполнения тестов (5 минут)",
            "command": " ".join(cmd),
            "detailed_report": "❌ Таймаут выполнения тестов (5 минут)"
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "command": " ".join(cmd),
            "detailed_report": f"❌ Ошибка выполнения тестов: {e}"
        }


def run_unittest(test_module: str = "discover") -> Dict[str, Any]:
    """
    Запускает unittest.
    
    Args:
        test_module: Модуль для тестирования или 'discover'.
    
    Returns:
        Словарь с результатами.
    """
    if test_module == "discover":
        cmd = [sys.executable, "-m", "unittest", "discover", "-s", ".", "-p", "*test*.py"]
    else:
        cmd = [sys.executable, "-m", "unittest", test_module]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300
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
            "error": "Таймаут выполнения тестов (5 минут)",
            "command": " ".join(cmd)
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "command": " ".join(cmd)
        }


def run_specific_test(file_path: str, test_name: str = None) -> Dict[str, Any]:
    """
    Запускает конкретный тест в файле.
    
    Args:
        file_path: Путь к файлу с тестами.
        test_name: Имя тестовой функции/класса (опционально).
    
    Returns:
        Словарь с результатами.
    """
    if not os.path.exists(file_path):
        return {"success": False, "error": f"Файл не найден: {file_path}"}
    if test_name:
        cmd = [sys.executable, "-m", "pytest", f"{file_path}::{test_name}", "-v"]
    else:
        cmd = [sys.executable, "-m", "pytest", file_path, "-v"]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300
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
            "error": "Таймаут выполнения теста (5 минут)",
            "command": " ".join(cmd)
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "command": " ".join(cmd)
        }


def get_test_coverage(source_path: str = ".", test_path: str = ".") -> Dict[str, Any]:
    """
    Запускает покрытие кода тестами с помощью coverage.
    
    Args:
        source_path: Путь к исходному коду.
        test_path: Путь к тестам.
    
    Returns:
        Словарь с результатами покрытия.
    """
    try:
        # Установим переменную окружения для coverage
        env = os.environ.copy()
        env["PYTHONPATH"] = os.getcwd()
        
        # Запускаем coverage run
        run_cmd = [sys.executable, "-m", "coverage", "run", "--source", source_path, "-m", "pytest", test_path]
        result = subprocess.run(
            run_cmd,
            capture_output=True,
            text=True,
            timeout=600,
            env=env
        )
        if result.returncode != 0:
            return {
                "success": False,
                "error": f"Ошибка выполнения тестов: {result.stderr[:500]}",
                "stdout": result.stdout,
                "stderr": result.stderr
            }
        
        # Получаем отчёт
        report_cmd = [sys.executable, "-m", "coverage", "report", "-m"]
        report = subprocess.run(
            report_cmd,
            capture_output=True,
            text=True
        )
        return {
            "success": True,
            "coverage_report": report.stdout,
            "coverage_stderr": report.stderr,
            "test_output": result.stdout[:2000]
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


def run_all_tests():
    """Запускает все тесты проекта."""
    import os
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    
    # Ищем тесты в проекте
    test_dirs = []
    for root, dirs, files in os.walk(project_root):
        if any(f.endswith('_test.py') or f.startswith('test_') for f in files):
            test_dirs.append(root)
    
    if not test_dirs:
        # Если не нашли тестов, запускаем в корне проекта
        test_dirs = [project_root]
    
    results = []
    for test_dir in test_dirs[:3]:  # Ограничим количество директорий для скорости
        result = run_pytest(test_dir, ["-v", "--tb=short"])
        results.append({
            'directory': os.path.relpath(test_dir, project_root),
            'success': result['success'],
            'output': result.get('stdout', '')[:1000]
        })
    
    # Подсчитываем результаты
    passed = sum(1 for r in results if r['success'])
    failed = len(results) - passed
    
    return {
        'passed': passed,
        'failed': failed,
        'total': len(results),
        'results': results
    }


if __name__ == "__main__":
    # Пример использования
    print("Запуск тестов через pytest...")
    result = run_pytest(".", ["-v"])
    print(f"Успех: {result['success']}")
    if result.get('stdout'):
        print("Вывод:", result['stdout'][:500])
    
    print("\nЗапуск конкретного теста...")
    result2 = run_specific_test(__file__, "run_pytest")
    print(f"Успех: {result2['success']}")
    
    print("\nЗапуск всех тестов проекта...")
    all_tests_result = run_all_tests()
    print(f"Всего тестовых директорий: {all_tests_result['total']}")
    print(f"Пройдено: {all_tests_result['passed']}, Провалено: {all_tests_result['failed']}")
