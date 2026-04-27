#!/usr/bin/env python3
"""
УНИВЕРСАЛЬНЫЙ СКРИПТ ИНДЕКСАЦИИ ФАЙЛОВ ДЛЯ ZORA
Индексирует любые файлы (код, документы, конфигурации, PDF, DOCX) в векторную память Qdrant.
Позволяет ассистенту разработчика находить релевантный код и документацию.

Особенности:
- Автоматическое включение рекурсии при передаче папки
- Поддержка множества форматов (код, документы, PDF, DOCX)
- Очистка старых данных по параметру --clean
- Фоновая реиндексация и режим watch
- Инкрементальная индексация (по умолчанию) с хранением хэшей файлов
- Потоковая обработка PDF и DOCX для экономии памяти
"""

import os
import sys
import logging
import argparse
import time
import re
import gc
import sqlite3
import hashlib
from pathlib import Path
from typing import List, Dict, Any, Optional, Generator, Tuple

# Добавляем путь к проекту
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Расширения файлов по типам
FILE_TYPES = {
    'code': {'.py', '.js', '.ts', '.go', '.java', '.cpp', '.h', '.hpp', '.cs', '.php', '.rb', '.rs', '.swift', '.kt', '.scala', '.sql'},
    'document': {'.md', '.txt', '.rst', '.tex', '.org', '.wiki', '.adoc'},
    'config': {'.json', '.yaml', '.yml', '.toml', '.ini', '.cfg', '.conf', '.xml', '.env'},
    'web': {'.html', '.htm', '.css', '.scss', '.less', '.jsx', '.tsx', '.vue'},
    'data': {'.csv', '.tsv', '.xlsx', '.xls', '.ods'},
}

BINARY_FORMATS = {
    '.pdf': 'pypdf',
    '.docx': 'docx',
    '.doc': 'docx',
    '.pptx': 'python-pptx',
    '.ppt': 'python-pptx',
}

# База данных хэшей файлов (SQLite)
HASH_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "file_hashes.db")

class FileHashDB:
    """Управление хэшами файлов в SQLite для инкрементальной индексации."""
    
    def __init__(self, db_path: str = HASH_DB_PATH):
        self.db_path = db_path
        self._init_db()
    
    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS file_hashes (
                path TEXT PRIMARY KEY,
                hash TEXT NOT NULL,
                mtime REAL NOT NULL,
                size INTEGER NOT NULL,
                indexed_at REAL NOT NULL
            )
        """)
        conn.commit()
        conn.close()
    
    def get_file_hash(self, filepath: str) -> Optional[Tuple[str, float, int]]:
        """Возвращает (hash, mtime, size) для файла, если есть."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT hash, mtime, size FROM file_hashes WHERE path = ?",
            (filepath,)
        )
        row = cursor.fetchone()
        conn.close()
        if row:
            return row[0], row[1], row[2]
        return None
    
    def update_file_hash(self, filepath: str, hash_val: str, mtime: float, size: int):
        """Обновляет или вставляет запись о файле."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO file_hashes (path, hash, mtime, size, indexed_at)
            VALUES (?, ?, ?, ?, ?)
        """, (filepath, hash_val, mtime, size, time.time()))
        conn.commit()
        conn.close()
    
    def delete_file_hash(self, filepath: str):
        """Удаляет запись о файле (например, при --clean для конкретного файла)."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM file_hashes WHERE path = ?", (filepath,))
        conn.commit()
        conn.close()
    
    def clear(self):
        """Очищает всю таблицу (при --clear-all)."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM file_hashes")
        conn.commit()
        conn.close()

def calculate_file_hash(filepath: str) -> str:
    """Вычисляет MD5 хэш файла (бинарное чтение)."""
    try:
        with open(filepath, 'rb') as f:
            return hashlib.md5(f.read()).hexdigest()
    except Exception as e:
        logger.warning(f"Не удалось вычислить хэш файла {filepath}: {e}")
        return ""

def should_reindex(filepath: str, hash_db: FileHashDB, force: bool = False, clean: bool = False) -> Tuple[bool, str]:
    """
    Определяет, нужно ли переиндексировать файл.
    Возвращает (need_reindex, reason).
    """
    if force or clean:
        return True, "force или clean режим"
    
    if not os.path.exists(filepath):
        return False, "файл не существует"
    
    try:
        current_mtime = os.path.getmtime(filepath)
        current_size = os.path.getsize(filepath)
        current_hash = calculate_file_hash(filepath)
        if not current_hash:
            return True, "не удалось вычислить хэш"
    except Exception as e:
        logger.warning(f"Ошибка получения атрибутов файла {filepath}: {e}")
        return True, "ошибка атрибутов"
    
    stored = hash_db.get_file_hash(filepath)
    if stored is None:
        return True, "файл ещё не индексирован"
    
    stored_hash, stored_mtime, stored_size = stored
    
    if current_hash != stored_hash:
        return True, "хэш изменился"
    if abs(current_mtime - stored_mtime) > 1:  # допуск 1 секунда
        return True, "время модификации изменилось"
    if current_size != stored_size:
        return True, "размер изменился"
    
    return False, "файл не изменился"

def get_file_type(filepath: str) -> str:
    ext = os.path.splitext(filepath)[1].lower()
    for file_type, extensions in FILE_TYPES.items():
        if ext in extensions:
            return file_type
    if ext in BINARY_FORMATS:
        return 'document'
    return 'unknown'

def read_text_file(filepath: str) -> Optional[str]:
    try:
        # Сначала пробуем UTF-8
        with open(filepath, 'r', encoding='utf-8') as f:
            return f.read()
    except UnicodeDecodeError:
        try:
            # Пробуем UTF-16 (часто используется в Windows)
            with open(filepath, 'r', encoding='utf-16') as f:
                return f.read()
        except UnicodeDecodeError:
            try:
                # Пробуем UTF-16LE (маленький эндиан)
                with open(filepath, 'r', encoding='utf-16-le') as f:
                    return f.read()
            except UnicodeDecodeError:
                try:
                    # Пробуем cp1251 (кириллица Windows)
                    with open(filepath, 'r', encoding='cp1251') as f:
                        return f.read()
                except UnicodeDecodeError:
                    try:
                        # Пробуем latin-1 как последний вариант
                        with open(filepath, 'r', encoding='latin-1') as f:
                            return f.read()
                    except:
                        return None
    except Exception as e:
        logger.error(f"Ошибка чтения файла {filepath}: {e}")
        return None

def read_pdf_pages(filepath: str) -> Generator[Optional[str], None, None]:
    """Генератор, возвращает текст каждой страницы PDF по одной с таймаутом и улучшенной обработкой ошибок."""
    import threading
    import queue
    import time
    
    def _extract_page_text(page, page_num, result_queue):
        """Извлекает текст со страницы в отдельном потоке."""
        try:
            page_text = page.extract_text()
            if page_text and page_text.strip():
                result_queue.put((page_num, page_text, None))
            else:
                result_queue.put((page_num, "", "Пустая страница"))
        except Exception as e:
            result_queue.put((page_num, "", str(e)))
    
    try:
        import pypdf
        
        # Проверяем размер файла
        file_size = os.path.getsize(filepath)
        if file_size > 100 * 1024 * 1024:  # > 100 MB
            logger.warning(f"PDF файл слишком большой ({file_size / 1024 / 1024:.1f} MB): {filepath}")
            yield f"[ВНИМАНИЕ: PDF файл слишком большой ({file_size / 1024 / 1024:.1f} MB), обработка может занять время]"
        
        with open(filepath, 'rb') as f:
            pdf_reader = pypdf.PdfReader(f)
            total_pages = len(pdf_reader.pages)
            
            if total_pages > 100:
                logger.warning(f"PDF содержит много страниц ({total_pages}): {filepath}")
                yield f"[ВНИМАНИЕ: PDF содержит {total_pages} страниц, обработка может занять время]"
            
            for page_num, page in enumerate(pdf_reader.pages):
                # Используем таймаут для каждой страницы
                result_queue = queue.Queue()
                thread = threading.Thread(
                    target=_extract_page_text,
                    args=(page, page_num, result_queue),
                    daemon=True
                )
                thread.start()
                
                # Ждём результат с таймаутом 30 секунд на страницу
                try:
                    thread.join(timeout=30)
                    if thread.is_alive():
                        logger.warning(f"Таймаут извлечения текста со страницы {page_num + 1} PDF: {filepath}")
                        yield f"[ПРЕРВАНО: таймаут извлечения текста со страницы {page_num + 1}]"
                        continue
                    
                    # Получаем результат
                    result_page_num, page_text, error = result_queue.get(timeout=5)
                    
                    if error:
                        if "Пустая страница" not in error:
                            logger.warning(f"Ошибка извлечения текста со страницы {page_num + 1}: {error}")
                        continue
                    
                    if page_text:
                        yield page_text
                    else:
                        logger.debug(f"Пустая страница {page_num + 1} в PDF: {filepath}")
                        
                except queue.Empty:
                    logger.warning(f"Таймаут получения результата со страницы {page_num + 1} PDF: {filepath}")
                    yield f"[ПРЕРВАНО: таймаут получения результата со страницы {page_num + 1}]"
                    continue
                except Exception as e:
                    logger.warning(f"Ошибка обработки страницы {page_num + 1} PDF: {e}")
                    continue
                
    except ImportError:
        logger.warning(f"Библиотека pypdf не установлена. Пропускаем PDF: {filepath}")
        yield None
    except Exception as e:
        logger.error(f"Ошибка чтения PDF {filepath}: {e}")
        yield None

def read_docx_paragraphs(filepath: str) -> Generator[Optional[str], None, None]:
    """Генератор, возвращает текст каждого параграфа DOCX по одному."""
    try:
        import docx
        doc = docx.Document(filepath)
        for para in doc.paragraphs:
            if para.text.strip():
                yield para.text
    except ImportError:
        logger.warning(f"Библиотека python-docx не установлена. Пропускаем DOCX: {filepath}")
        yield None
    except Exception as e:
        logger.error(f"Ошибка чтения DOCX {filepath}: {e}")
        yield None

def read_file_content(filepath: str) -> Optional[str]:
    """Возвращает весь текст файла (для небольших файлов)."""
    ext = os.path.splitext(filepath)[1].lower()
    if ext == '.pdf':
        # Для PDF используем генератор, но здесь для совместимости собираем всё
        pages = []
        for page_text in read_pdf_pages(filepath):
            if page_text:
                pages.append(page_text)
        return '\n\n'.join(pages) if pages else None
    elif ext in ['.docx', '.doc']:
        paras = []
        for para_text in read_docx_paragraphs(filepath):
            if para_text:
                paras.append(para_text)
        return '\n'.join(paras) if paras else None
    else:
        return read_text_file(filepath)

def split_code_into_chunks(content: str, filepath: str) -> List[str]:
    """
    Разбивает код на чанки по логическим блокам (классы, функции).
    Если код не разбился на блоки (маленький файл), использует обычный чанкинг.
    """
    chunks = []
    current_chunk = []
    lines = content.split('\n')

    for line in lines:
        line_stripped = line.strip()
        # Начало нового блока
        if (line_stripped.startswith('def ') or
            line_stripped.startswith('class ') or
            line_stripped.startswith('async def ')):
            if current_chunk:
                chunks.append('\n'.join(current_chunk))
                current_chunk = []
        current_chunk.append(line)

    if current_chunk:
        chunks.append('\n'.join(current_chunk))

    # Если код не разбился на блоки (маленький файл), используем обычный чанкинг
    if len(chunks) <= 1:
        return split_text_into_chunks(content, max_chunk_size=1500, overlap=100)

    return chunks


def split_text_into_chunks(content: str, max_chunk_size: int = 1500, overlap: int = 200) -> List[str]:
    """
    Разбивает текст на чанки с перекрытием.
    - max_chunk_size: 1500 символов (безопасно для nomic-embed-text)
    - overlap: 200 символов (сохраняет контекст на границах)

    Ищет границу предложения/слова, чтобы не разрывать текст посередине.
    """
    if not content:
        return []

    chunks = []
    start = 0
    content_length = len(content)

    while start < content_length:
        end = min(start + max_chunk_size, content_length)

        # Если не конец текста, ищем границу слова/предложения
        if end < content_length:
            # Ищем последний пробел, точку или перенос строки
            last_space = content.rfind(' ', start, end)
            last_period = content.rfind('.', start, end)
            last_newline = content.rfind('\n', start, end)

            # Берём самую правую границу (приоритет: точка > перенос строки > пробел)
            boundary = max(last_newline, last_period, last_space)
            if boundary > start:
                end = boundary + 1

        chunk = content[start:end].strip()
        if chunk:
            chunks.append(chunk)

        # Сдвигаем на (размер чанка - overlap)
        start = end - overlap if end < content_length else end

    return chunks

def enrich_code_chunk(chunk: str, filepath: str) -> str:
    filename = os.path.basename(filepath)
    classes = re.findall(r'class\s+(\w+)', chunk)
    functions = re.findall(r'def\s+(\w+)', chunk)
    prefix = f"[Файл: {filename}]"
    if classes:
        prefix += f" [Классы: {', '.join(classes)}]"
    if functions:
        prefix += f" [Функции: {', '.join(functions)}]"
    return prefix + "\n" + chunk

def delete_file_from_index(filepath: str, memory_client):
    """Удаляет все точки из Qdrant, связанные с данным файлом."""
    try:
        # Используем метод delete_by_filter, если он есть (у LazyMemory и ZoraMemory)
        if hasattr(memory_client, 'delete_by_filter'):
            memory_client.delete_by_filter({"path": filepath})
            logger.info(f"🗑️ Удалены старые данные для файла: {filepath}")
        else:
            # Fallback: если нет delete_by_filter, но есть прямой клиент Qdrant
            if hasattr(memory_client, 'client'):
                from qdrant_client.http import models
                filter_condition = models.Filter(
                    must=[models.FieldCondition(key="path", match=models.MatchValue(value=filepath))]
                )
                memory_client.client.delete(
                    collection_name=memory_client.collection_name,
                    points_selector=filter_condition
                )
                logger.info(f"🗑️ Удалены старые данные для файла: {filepath}")
            else:
                logger.warning(f"Не могу удалить данные файла {filepath}: нет метода delete_by_filter и нет client")
    except Exception as e:
        logger.error(f"Ошибка удаления данных файла {filepath}: {e}")

def index_file(filepath: str, memory_client, clean: bool = False, max_file_mb: int = 10,
               hash_db: Optional[FileHashDB] = None, incremental: bool = True, force: bool = False):
    """
    Индексирует один файл с учётом инкрементального режима.
    """
    try:
        file_type = get_file_type(filepath)
        if file_type == 'unknown':
            logger.debug(f"Пропускаем неизвестный тип файла: {filepath}")
            return
        
        # Проверка размера файла
        file_size_bytes = os.path.getsize(filepath)
        file_size_mb = file_size_bytes / (1024 * 1024)
        if file_size_mb > max_file_mb:
            logger.warning(f"Файл {filepath} слишком большой ({file_size_mb:.1f} МБ > {max_file_mb} МБ), пропускаем")
            return
        
        # Инкрементальная проверка
        need_reindex = True
        reason = "force или clean режим"
        if hash_db and incremental and not force and not clean:
            need_reindex, reason = should_reindex(filepath, hash_db, force, clean)
            if not need_reindex:
                logger.debug(f"Пропускаем неизменившийся файл: {filepath} ({reason})")
                return
        
        # Если нужно переиндексировать, удаляем старые данные
        if clean or need_reindex:
            delete_file_from_index(filepath, memory_client)
        
        ext = os.path.splitext(filepath)[1].lower()
        mtime = os.path.getmtime(filepath)
        chunk_index = 0
        
        # --- Потоковая обработка PDF ---
        if ext == '.pdf':
            for page_num, page_text in enumerate(read_pdf_pages(filepath)):
                if not page_text:
                    continue
                chunks = split_text_into_chunks(page_text, max_chunk_size=1500, overlap=150)
                for chunk in chunks:
                    if not chunk.strip():
                        continue
                    metadata = {
                        "path": filepath,
                        "filename": os.path.basename(filepath),
                        "type": file_type,
                        "mtime": mtime,
                        "chunk": chunk_index,
                        "page": page_num + 1,
                        "indexed_at": time.time()
                    }
                    memory_client.store(chunk, metadata)
                    chunk_index += 1
                    logger.debug(f"Индексирован чанк {chunk_index} (страница {page_num+1}) файла {filepath}")
        
        # --- Потоковая обработка DOCX ---
        elif ext in ['.docx', '.doc']:
            for para_num, para_text in enumerate(read_docx_paragraphs(filepath)):
                if not para_text:
                    continue
                chunks = split_text_into_chunks(para_text, max_chunk_size=1500, overlap=150)
                for chunk in chunks:
                    if not chunk.strip():
                        continue
                    metadata = {
                        "path": filepath,
                        "filename": os.path.basename(filepath),
                        "type": file_type,
                        "mtime": mtime,
                        "chunk": chunk_index,
                        "paragraph": para_num + 1,
                        "indexed_at": time.time()
                    }
                    memory_client.store(chunk, metadata)
                    chunk_index += 1
                    logger.debug(f"Индексирован чанк {chunk_index} (параграф {para_num+1}) файла {filepath}")
        
        # --- Обычные текстовые файлы и код (небольшие, можно читать целиком) ---
        else:
            content = read_file_content(filepath)
            if not content or not content.strip():
                logger.debug(f"Пропускаем пустой файл: {filepath}")
                return
            if file_type == 'code':
                chunks = split_code_into_chunks(content, filepath)
            else:
                chunks = split_text_into_chunks(content)
            if not chunks:
                logger.debug(f"Не удалось разбить файл на чанки: {filepath}")
                return
            for i, chunk in enumerate(chunks):
                if not chunk.strip():
                    continue
                if file_type == 'code':
                    chunk = enrich_code_chunk(chunk, filepath)
                metadata = {
                    "path": filepath,
                    "filename": os.path.basename(filepath),
                    "type": file_type,
                    "mtime": mtime,
                    "chunk": i,
                    "total_chunks": len(chunks),
                    "indexed_at": time.time()
                }
                memory_client.store(chunk, metadata)
                chunk_index += 1
                logger.debug(f"Индексирован чанк {i+1}/{len(chunks)} файла {filepath}")
        
        if chunk_index > 0:
            logger.info(f"✅ Индексирован файл: {filepath} ({chunk_index} чанков, тип: {file_type})")
        else:
            logger.warning(f"⚠️ Файл {filepath} не содержит индексируемого контента")
        
        # --- Сохраняем хэш файла в БД для будущих инкрементальных запусков ---
        if hash_db and incremental and need_reindex:
            current_hash = calculate_file_hash(filepath)
            if current_hash:
                hash_db.update_file_hash(filepath, current_hash, mtime, file_size_bytes)
                logger.debug(f"Хэш файла сохранён: {filepath}")
        
        # Очистка памяти после обработки каждого файла
        gc.collect()
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass
            
    except UnicodeDecodeError:
        logger.warning(f"Пропускаем бинарный файл: {filepath}")
    except Exception as e:
        logger.error(f"Ошибка индексации файла {filepath}: {e}")

def index_path(path: str, recursive: bool = False, clean: bool = False, max_file_mb: int = 10,
               incremental: bool = True, force: bool = False):
    """
    Индексирует файл или папку.
    """
    try:
        from memory import memory
        logger.info("✅ Векторная память загружена")
    except ImportError as e:
        logger.error(f"❌ Не удалось загрузить векторную память: {e}")
        return
    
    path = os.path.abspath(path)
    if not os.path.exists(path):
        logger.error(f"Путь не существует: {path}")
        return
    
    hash_db = None
    if incremental:
        hash_db = FileHashDB()
        logger.info("📊 Используется инкрементальная индексация (проверка хэшей)")
    if clean:
        logger.warning("⚠️ Режим --clean: старые данные файлов будут удалены перед индексацией")
    if force:
        logger.warning("⚠️ Режим --force: принудительная переиндексация всех файлов")
    
    exclude_dirs = {
        'venv', '.git', '__pycache__', '.idea', '.vscode',
        'node_modules', 'dist', 'build', 'coverage', '.pytest_cache',
        '.docker', '.github', '.gitlab'
    }
    include_extensions = set()
    for extensions in FILE_TYPES.values():
        include_extensions.update(extensions)
    include_extensions.update(BINARY_FORMATS.keys())
    
    stats = {'total_files': 0, 'indexed_files': 0, 'skipped_files': 0, 'errors': 0}
    
    if os.path.isfile(path):
        stats['total_files'] = 1
        index_file(path, memory, clean, max_file_mb, hash_db, incremental, force)
        stats['indexed_files'] = 1
    else:
        for dirpath, dirnames, filenames in os.walk(path):
            if not recursive:
                dirnames.clear()
            else:
                dirnames[:] = [d for d in dirnames if d not in exclude_dirs]
            for filename in filenames:
                filepath = os.path.join(dirpath, filename)
                ext = os.path.splitext(filename)[1].lower()
                if ext not in include_extensions:
                    continue
                stats['total_files'] += 1
                try:
                    index_file(filepath, memory, clean, max_file_mb, hash_db, incremental, force)
                    stats['indexed_files'] += 1
                except Exception as e:
                    logger.error(f"Ошибка индексации файла {filepath}: {e}")
                    stats['errors'] += 1
    
    logger.info("📊 ИТОГИ ИНДЕКСАЦИИ:")
    logger.info(f"   Всего файлов: {stats['total_files']}")
    logger.info(f"   Успешно проиндексировано: {stats['indexed_files']}")
    logger.info(f"   Пропущено: {stats['skipped_files']}")
    logger.info(f"   Ошибок: {stats['errors']}")
    if stats['indexed_files'] > 0:
        logger.info("✅ Индексация завершена успешно!")
        logger.info("   Ассистент теперь может использовать индексированные знания.")
    else:
        logger.warning("⚠️ Не было проиндексировано ни одного файла")

def clear_index():
    """Полностью очищает коллекцию Qdrant и базу хэшей."""
    try:
        from memory import memory
        if hasattr(memory, 'clear'):
            memory.clear()
            logger.info("✅ Векторная память очищена")
            # Также очищаем базу хэшей
            hash_db = FileHashDB()
            hash_db.clear()
            logger.info("✅ База хэшей файлов очищена")
        else:
            logger.warning("⚠️ Очистка памяти не поддерживается")
    except Exception as e:
        logger.error(f"❌ Ошибка очистки памяти: {e}")

def start_background_reindexing(interval_hours: int = 24, watch_path: str = "."):
    import threading
    import time
    logger.info(f"🚀 Запуск фоновой реиндексации (интервал: {interval_hours}ч, путь: {watch_path})")
    
    hash_db = FileHashDB()
    
    def get_modified_files() -> List[str]:
        modified = []
        for root, dirs, files in os.walk(watch_path):
            dirs[:] = [d for d in dirs if d not in ['.git', '__pycache__', 'node_modules', 'venv', '.venv']]
            for file in files:
                filepath = os.path.join(root, file)
                if os.path.getsize(filepath) > 10*1024*1024:
                    continue
                file_type = get_file_type(filepath)
                if not file_type and os.path.splitext(filepath)[1].lower() not in BINARY_FORMATS:
                    continue
                need_reindex, _ = should_reindex(filepath, hash_db, force=False, clean=False)
                if need_reindex:
                    modified.append(filepath)
        return modified
    
    def reindex_modified_files():
        try:
            from memory import memory
            modified = get_modified_files()
            if modified:
                logger.info(f"🔍 Обнаружено {len(modified)} изменённых файлов")
                for fp in modified:
                    try:
                        index_file(fp, memory, clean=False, hash_db=hash_db, incremental=True, force=False)
                    except Exception as e:
                        logger.error(f"❌ Ошибка реиндексации файла {fp}: {e}")
            else:
                logger.debug("📊 Изменений не обнаружено")
        except Exception as e:
            logger.error(f"❌ Ошибка в фоновой реиндексации: {e}")
    
    def background_task():
        while True:
            try:
                logger.info("🔄 Проверка изменений файлов...")
                reindex_modified_files()
                time.sleep(interval_hours * 3600)
            except KeyboardInterrupt:
                logger.info("⏹️ Фоновая реиндексация остановлена")
                break
            except Exception as e:
                logger.error(f"❌ Ошибка в фоновой задаче: {e}")
                time.sleep(300)
    
    thread = threading.Thread(target=background_task, daemon=True)
    thread.start()
    return thread

def start_watch_mode(watch_path: str = ".", poll_interval: int = 60):
    import time
    try:
        from watchdog.observers import Observer
        from watchdog.events import FileSystemEventHandler
    except ImportError as e:
        logger.error(f"❌ Для режима отслеживания установите watchdog: pip install watchdog. Ошибка: {e}")
        return None
    
    class FileChangeHandler(FileSystemEventHandler):
        def __init__(self):
            super().__init__()
            self.logger = logging.getLogger("watchdog")
            self.hash_db = FileHashDB()
        
        def on_modified(self, event):
            if not event.is_directory:
                fp = event.src_path
                ft = get_file_type(fp)
                if ft or os.path.splitext(fp)[1].lower() in BINARY_FORMATS:
                    self.logger.info(f"📝 Файл изменён: {fp}")
                    time.sleep(1)
                    try:
                        from memory import memory
                        index_file(fp, memory, clean=False, hash_db=self.hash_db, incremental=True, force=False)
                        self.logger.info(f"✅ Файл проиндексирован: {fp}")
                    except Exception as e:
                        self.logger.error(f"❌ Ошибка индексации файла {fp}: {e}")
        
        def on_created(self, event):
            if not event.is_directory:
                fp = event.src_path
                ft = get_file_type(fp)
                if ft or os.path.splitext(fp)[1].lower() in BINARY_FORMATS:
                    self.logger.info(f"📄 Новый файл: {fp}")
                    time.sleep(1)
                    try:
                        from memory import memory
                        index_file(fp, memory, clean=False, hash_db=self.hash_db, incremental=True, force=False)
                        self.logger.info(f"✅ Новый файл проиндексирован: {fp}")
                    except Exception as e:
                        self.logger.error(f"❌ Ошибка индексации нового файла {fp}: {e}")
    
    logger.info(f"👁️ Запуск режима отслеживания (путь: {watch_path}, интервал: {poll_interval}с)")
    event_handler = FileChangeHandler()
    observer = Observer()
    observer.schedule(event_handler, watch_path, recursive=True)
    observer.start()
    return observer

def index_project_files():
    """Индексирует весь проект в векторную память."""
    import os
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    
    # Используем существующую функцию index_path
    from memory.indexer import index_path
    result = index_path(project_root, recursive=True, clean=False, max_file_mb=10, incremental=True, force=False)
    
    # Подсчитываем результаты
    indexed_files = 0
    added_chunks = 0
    if isinstance(result, dict):
        indexed_files = result.get('indexed_files', 0)
        added_chunks = result.get('added_chunks', 0)
    elif isinstance(result, tuple) and len(result) >= 2:
        indexed_files = result[0]
        added_chunks = result[1]
    
    return {
        'indexed_files': indexed_files,
        'added_chunks': added_chunks,
        'project_root': project_root
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Универсальный скрипт индексации файлов для ZORA")
    parser.add_argument("--path", default=".", help="Путь к файлу или папке для индексации")
    parser.add_argument("--recursive", action="store_true", help="Рекурсивная индексация папок (если не указан, для папок включается автоматически)")
    parser.add_argument("--clean", action="store_true", help="Очистить старые данные перед индексацией")
    parser.add_argument("--clear-all", action="store_true", help="Очистить всю векторную память и базу хэшей")
    parser.add_argument("--install-deps", action="store_true", help="Установить недостающие зависимости (pypdf, python-docx)")
    parser.add_argument("--watch", action="store_true", help="Запустить режим отслеживания файлов в реальном времени")
    parser.add_argument("--background", action="store_true", help="Запустить фоновую реиндексацию (интервал: 24 часа)")
    parser.add_argument("--interval", type=int, default=24, help="Интервал фоновой реиндексации в часах")
    parser.add_argument("--max-file-mb", type=int, default=10, help="Максимальный размер файла для индексации в МБ")
    parser.add_argument("--incremental", action="store_true", default=True, help="Использовать инкрементальную индексацию (по умолчанию)")
    parser.add_argument("--no-incremental", action="store_false", dest="incremental", help="Отключить инкрементальную индексацию")
    parser.add_argument("--force", action="store_true", help="Принудительно переиндексировать все файлы (игнорируя хэши, но без очистки коллекции)")
    args = parser.parse_args()

    # === АВТОМАТИЧЕСКАЯ РЕКУРСИЯ ДЛЯ ПАПОК ===
    if not args.recursive and os.path.isdir(args.path):
        args.recursive = True
        logger.info("🔁 Автоматически включена рекурсивная индексация для папки")

    if args.install_deps:
        logger.info("🔧 Установка зависимостей...")
        try:
            import subprocess
            deps = ['pypdf', 'python-docx']
            for dep in deps:
                subprocess.run([sys.executable, '-m', 'pip', 'install', dep], check=True)
                logger.info(f"✅ Установлен: {dep}")
        except Exception as e:
            logger.error(f"❌ Ошибка установки зависимостей: {e}")

    if args.clear_all:
        clear_index()

    if not args.clear_all:
        index_path(args.path, args.recursive, args.clean, args.max_file_mb, args.incremental, args.force)

    if args.watch:
        observer = start_watch_mode(args.path, poll_interval=60)
        if observer:
            try:
                logger.info("👁️ Режим отслеживания запущен. Нажмите Ctrl+C для остановки.")
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                observer.stop()
                observer.join()
                logger.info("⏹️ Режим отслеживания остановлен")

    if args.background:
        thread = start_background_reindexing(args.interval, args.path)
        if thread:
            try:
                logger.info(f"🚀 Фоновая реиндексация запущена (интервал: {args.interval}ч). Нажмите Ctrl+C для остановки.")
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                logger.info("⏹️ Фоновая реиндексация остановлена")