"""
Инструменты для анализа кода Python.
"""

import ast
import os
import re
from typing import List, Dict, Any, Optional


def parse_python_file(filepath: str) -> Optional[ast.Module]:
    """Парсит Python файл и возвращает AST."""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        return ast.parse(content)
    except Exception as e:
        print(f"Ошибка парсинга {filepath}: {e}")
        return None


def extract_functions(ast_tree: ast.Module) -> List[Dict[str, Any]]:
    """Извлекает функции из AST."""
    functions = []
    for node in ast.walk(ast_tree):
        if isinstance(node, ast.FunctionDef):
            functions.append({
                'name': node.name,
                'lineno': node.lineno,
                'args': [arg.arg for arg in node.args.args],
                'docstring': ast.get_docstring(node)
            })
    return functions


def extract_classes(ast_tree: ast.Module) -> List[Dict[str, Any]]:
    """Извлекает классы из AST."""
    classes = []
    for node in ast.walk(ast_tree):
        if isinstance(node, ast.ClassDef):
            methods = []
            for subnode in node.body:
                if isinstance(subnode, ast.FunctionDef):
                    methods.append(subnode.name)
            classes.append({
                'name': node.name,
                'lineno': node.lineno,
                'methods': methods,
                'docstring': ast.get_docstring(node)
            })
    return classes


def extract_imports(ast_tree: ast.Module) -> List[str]:
    """Извлекает импорты из AST."""
    imports = []
    for node in ast.walk(ast_tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ''
            for alias in node.names:
                imports.append(f"{module}.{alias.name}")
    return imports


def analyze_file(filepath: str) -> Dict[str, Any]:
    """Анализирует Python файл и возвращает структуру."""
    tree = parse_python_file(filepath)
    if not tree:
        return {}
    return {
        'file': filepath,
        'functions': extract_functions(tree),
        'classes': extract_classes(tree),
        'imports': extract_imports(tree),
        'line_count': sum(1 for _ in open(filepath, 'r', encoding='utf-8'))
    }


def find_files_with_pattern(directory: str, pattern: str) -> List[str]:
    """Находит файлы, содержащие регулярное выражение."""
    matches = []
    for root, dirs, files in os.walk(directory):
        for file in files:
            if file.endswith('.py'):
                full_path = os.path.join(root, file)
                try:
                    with open(full_path, 'r', encoding='utf-8') as f:
                        if re.search(pattern, f.read(), re.IGNORECASE):
                            matches.append(full_path)
                except:
                    pass
    return matches


def get_function_source(filepath: str, function_name: str) -> Optional[str]:
    """Возвращает исходный код функции."""
    tree = parse_python_file(filepath)
    if not tree:
        return None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == function_name:
            lines = open(filepath, 'r', encoding='utf-8').readlines()
            start = node.lineno - 1
            end = node.end_lineno if hasattr(node, 'end_lineno') else start + 1
            return ''.join(lines[start:end])
    return None


def analyze_project():
    """Анализирует весь проект и возвращает сводку."""
    import os
    import glob
    
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    python_files = glob.glob(os.path.join(project_root, "**", "*.py"), recursive=True)
    
    total_files = len(python_files)
    total_functions = 0
    total_classes = 0
    total_lines = 0
    issues = []
    
    # Ограничим анализ для скорости
    sample_files = python_files[:20] if len(python_files) > 20 else python_files
    
    for filepath in sample_files:
        try:
            result = analyze_file(filepath)
            if result:
                total_functions += len(result['functions'])
                total_classes += len(result['classes'])
                total_lines += result['line_count']
                
                # Проверка на потенциальные проблемы
                if result['line_count'] > 500:
                    issues.append(f"Файл {os.path.basename(filepath)} слишком большой ({result['line_count']} строк)")
                if len(result['functions']) > 20:
                    issues.append(f"Файл {os.path.basename(filepath)} содержит много функций ({len(result['functions'])})")
        except Exception as e:
            issues.append(f"Ошибка анализа {os.path.basename(filepath)}: {str(e)}")
    
    return {
        'total_files': total_files,
        'analyzed_files': len(sample_files),
        'total_functions': total_functions,
        'total_classes': total_classes,
        'total_lines': total_lines,
        'issues': issues
    }


if __name__ == '__main__':
    # Пример использования
    test_file = __file__
    result = analyze_file(test_file)
    print(f"Анализ {test_file}:")
    print(f"  Функций: {len(result['functions'])}")
    print(f"  Классов: {len(result['classes'])}")
    print(f"  Импортов: {len(result['imports'])}")
    print(f"  Строк: {result['line_count']}")
    
    print("\nАнализ проекта:")
    project_result = analyze_project()
    print(f"  Всего файлов: {project_result['total_files']}")
    print(f"  Проанализировано: {project_result['analyzed_files']}")
    print(f"  Функций: {project_result['total_functions']}")
    print(f"  Классов: {project_result['total_classes']}")
    print(f"  Строк: {project_result['total_lines']}")
    if project_result['issues']:
        print(f"  Проблемы: {len(project_result['issues'])}")
        for issue in project_result['issues'][:3]:
            print(f"    - {issue}")


def analyze_code_quality(filepath: str) -> Dict[str, Any]:
    """Анализирует качество кода в файле с детализированными результатами."""
    ast_tree = parse_python_file(filepath)
    if not ast_tree:
        return {
            'file': filepath,
            'error': 'Не удалось распарсить файл',
            'issues': [],
            'issues_count': 0,
            'detailed_report': f"❌ Не удалось проанализировать файл: {filepath}"
        }
    
    issues = []
    warnings = []
    suggestions = []
    
    # Получаем содержимое файла для анализа строк
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            lines = f.readlines()
    except:
        lines = []
    
    # Проверка на слишком длинные функции
    functions = extract_functions(ast_tree)
    for func in functions:
        # Вычисляем длину функции
        func_lines = []
        for i, line in enumerate(lines, 1):
            if i >= func['lineno']:
                func_lines.append(line)
                if line.strip() and not line.strip().startswith(('#', '"""', "'''")) and len(line.strip()) > 0:
                    # Простая проверка конца функции
                    if i > func['lineno'] and line.strip() and line[0] != ' ' and line[0] != '\t':
                        break
        
        line_count = len([l for l in func_lines if l.strip()])
        
        if line_count > 50:
            issues.append({
                'type': 'long_function',
                'message': f"Функция '{func['name']}' слишком длинная ({line_count} строк)",
                'severity': 'warning',
                'location': f"{filepath}:{func['lineno']}",
                'suggestion': "Разбейте функцию на несколько более мелких функций"
            })
            warnings.append(f"⚠️ Строка {func['lineno']}: Функция '{func['name']}' слишком длинная ({line_count} строк)")
    
    # Проверка на слишком сложные функции (по количеству аргументов)
    for func in functions:
        if len(func.get('args', [])) > 5:
            issues.append({
                'type': 'too_many_args',
                'message': f"Функция '{func['name']}' имеет слишком много аргументов ({len(func.get('args', []))})",
                'severity': 'warning',
                'location': f"{filepath}:{func['lineno']}",
                'suggestion': "Используйте *args, **kwargs или передавайте параметры через словарь"
            })
            warnings.append(f"⚠️ Строка {func['lineno']}: Функция '{func['name']}' имеет {len(func.get('args', []))} аргументов")
    
    # Проверка на отсутствие docstring
    for func in functions:
        if not func.get('docstring'):
            issues.append({
                'type': 'missing_docstring',
                'message': f"Функция '{func['name']}' не имеет docstring",
                'severity': 'info',
                'location': f"{filepath}:{func['lineno']}",
                'suggestion': "Добавьте docstring для документации функции"
            })
            suggestions.append(f"💡 Строка {func['lineno']}: Добавьте docstring для функции '{func['name']}'")
    
    # Проверка классов
    classes = extract_classes(ast_tree)
    for cls in classes:
        if not cls.get('docstring'):
            issues.append({
                'type': 'missing_class_docstring',
                'message': f"Класс '{cls['name']}' не имеет docstring",
                'severity': 'info',
                'location': f"{filepath}:{cls['lineno']}",
                'suggestion': "Добавьте docstring для документации класса"
            })
            suggestions.append(f"💡 Строка {cls['lineno']}: Добавьте docstring для класса '{cls['name']}'")
    
    # Проверка на слишком длинные строки
    for i, line in enumerate(lines, 1):
        if len(line.rstrip('\n')) > 120:
            issues.append({
                'type': 'line_too_long',
                'message': f"Строка слишком длинная ({len(line.rstrip(chr(10)))} символов)",
                'severity': 'warning',
                'location': f"{filepath}:{i}",
                'suggestion': "Разбейте строку на несколько или используйте перенос"
            })
            warnings.append(f"⚠️ Строка {i}: Слишком длинная строка ({len(line.rstrip(chr(10)))} символов)")
    
    # Формируем детализированный отчет
    detailed_report = f"📊 Анализ кода: {os.path.basename(filepath)}\n"
    detailed_report += f"📁 Файл: {filepath}\n"
    detailed_report += f"📈 Функций: {len(functions)}\n"
    detailed_report += f"🏗️  Классов: {len(classes)}\n"
    detailed_report += f"🔍 Проблем: {len(issues)}\n"
    
    if warnings:
        detailed_report += f"\n⚠️  Предупреждения ({len(warnings)}):\n"
        for i, warning in enumerate(warnings[:10], 1):
            detailed_report += f"  {i}. {warning}\n"
        if len(warnings) > 10:
            detailed_report += f"  ... и ещё {len(warnings) - 10} предупреждений\n"
    
    if suggestions:
        detailed_report += f"\n💡 Рекомендации ({len(suggestions)}):\n"
        for i, suggestion in enumerate(suggestions[:10], 1):
            detailed_report += f"  {i}. {suggestion}\n"
        if len(suggestions) > 10:
            detailed_report += f"  ... и ещё {len(suggestions) - 10} рекомендаций\n"
    
    if not warnings and not suggestions:
        detailed_report += "\n✅ Код в хорошем состоянии! Проблем не обнаружено.\n"
    
    # Сохраняем отчет в файл
    report_file = f"code_analysis_{os.path.basename(filepath).replace('.', '_')}.txt"
    try:
        with open(report_file, 'w', encoding='utf-8') as f:
            f.write(detailed_report)
            f.write(f"\n📋 Детальный список проблем:\n")
            for i, issue in enumerate(issues, 1):
                f.write(f"\n{i}. [{issue['severity'].upper()}] {issue['type']}\n")
                f.write(f"   Сообщение: {issue['message']}\n")
                f.write(f"   Расположение: {issue['location']}\n")
                f.write(f"   Рекомендация: {issue.get('suggestion', 'Нет рекомендации')}\n")
    except Exception as e:
        detailed_report += f"\n⚠️ Не удалось сохранить отчет: {e}"
    
    return {
        'file': filepath,
        'functions_count': len(functions),
        'classes_count': len(classes),
        'issues': issues,
        'issues_count': len(issues),
        'warnings_count': len(warnings),
        'suggestions_count': len(suggestions),
        'detailed_report': detailed_report,
        'report_file': report_file if os.path.exists(report_file) else None
    }
