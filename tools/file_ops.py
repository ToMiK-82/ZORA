import os
import logging
import threading

logger = logging.getLogger(__name__)


def _index_file_in_background(filepath: str):
    """Запускает индексацию файла в фоновом потоке."""
    try:
        from memory.indexer import index_file
        chunks_count = index_file(filepath)
        if chunks_count > 0:
            logger.info(f"Файл проиндексирован в фоне: {filepath} ({chunks_count} чанков)")
        else:
            logger.warning(f"Не удалось проиндексировать файл: {filepath}")
    except ImportError as e:
        logger.warning(f"Модуль индексации не найден: {e}")
    except Exception as e:
        logger.error(f"Ошибка фоновой индексации файла {filepath}: {e}")

def read_file(filepath: str) -> str:
    """Чтение файла с указанного пути."""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return f.read()
    except UnicodeDecodeError:
        # fallback для старых файлов в cp1251
        try:
            with open(filepath, 'r', encoding='cp1251') as f:
                return f.read()
        except Exception as e:
            return f"Ошибка чтения (и cp1251): {e}"
    except Exception as e:
        return f"Ошибка чтения: {e}"

def write_file(filepath: str, content: str) -> str:
    """Запись содержимого в файл, создание директорий при необходимости."""
    try:
        # Если путь пустой или None, используем текущую директорию
        if not filepath or filepath.strip() == "":
            return "Ошибка: не указан путь к файлу"
        
        # Нормализуем путь
        filepath = os.path.normpath(filepath)
        
        # Создаем директории если нужно
        dirname = os.path.dirname(filepath)
        if dirname:
            os.makedirs(dirname, exist_ok=True)
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        
        # Запускаем индексацию файла в фоновом потоке
        try:
            threading.Thread(target=_index_file_in_background, args=(filepath,), daemon=True).start()
            logger.debug(f"Запущена фоновая индексация файла: {filepath}")
        except Exception as e:
            logger.warning(f"Не удалось запустить фоновую индексацию: {e}")
        
        return f"Файл {filepath} сохранён."
    except Exception as e:
        return f"Ошибка записи: {e}"

def list_directory(dirpath: str) -> str:
    """Список файлов и папок в указанной директории."""
    try:
        # Нормализуем путь
        dirpath = os.path.normpath(dirpath)
        
        # Проверяем существование директории
        if not os.path.exists(dirpath):
            return f"Ошибка: директория не существует: {dirpath}"
        
        # Проверяем, что это директория
        if not os.path.isdir(dirpath):
            return f"Ошибка: путь не является директорией: {dirpath}"
        
        # Пытаемся получить список файлов
        try:
            items = os.listdir(dirpath)
        except PermissionError as e:
            return f"Ошибка доступа к директории {dirpath}: {e}"
        
        files = []
        for item in items:
            try:
                item_path = os.path.join(dirpath, item)
                # Проверяем доступ к файлу/папке
                if os.path.isdir(item_path):
                    files.append(f"{item}/")
                else:
                    files.append(item)
            except (PermissionError, OSError):
                # Пропускаем элементы с ошибками доступа
                continue
        
        if not files:
            return "Директория пуста или нет доступа к содержимому"
        
        # Сортируем: сначала папки, потом файлы
        files.sort(key=lambda x: (not x.endswith('/'), x.lower()))
        
        return "\n".join(files)
    except Exception as e:
        return f"Ошибка: {e}"
