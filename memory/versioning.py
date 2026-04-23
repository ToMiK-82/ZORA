"""
Система версионирования и инкрементальной индексации для ZORA.
Позволяет отслеживать изменения файлов, управлять версиями и выполнять инкрементальную индексацию.
"""

import os
import json
import hashlib
import sqlite3
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
import logging

logger = logging.getLogger(__name__)

class VersioningSystem:
    """Система версионирования файлов для инкрементальной индексации."""
    
    def __init__(self, db_path: str = None):
        if db_path is None:
            db_path = os.path.join(os.path.dirname(__file__), "versioning.db")
        self.db_path = db_path
        self._init_db()
    
    def _init_db(self):
        """Инициализирует базу данных для версионирования."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Таблица для отслеживания версий файлов
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS file_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                path TEXT NOT NULL,
                version_hash TEXT NOT NULL,
                file_size INTEGER NOT NULL,
                mtime REAL NOT NULL,
                indexed_at REAL NOT NULL,
                metadata TEXT,
                UNIQUE(path, version_hash)
            )
        """)
        
        # Таблица для истории изменений
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS change_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                path TEXT NOT NULL,
                old_hash TEXT,
                new_hash TEXT,
                change_type TEXT NOT NULL,  -- 'created', 'modified', 'deleted'
                timestamp REAL NOT NULL,
                indexed BOOLEAN DEFAULT FALSE
            )
        """)
        
        # Индексы для быстрого поиска
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_file_versions_path ON file_versions(path)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_file_versions_hash ON file_versions(version_hash)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_change_history_path ON change_history(path)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_change_history_timestamp ON change_history(timestamp)")
        
        conn.commit()
        conn.close()
    
    def calculate_file_hash(self, filepath: str) -> str:
        """Вычисляет хэш файла."""
        try:
            with open(filepath, 'rb') as f:
                return hashlib.sha256(f.read()).hexdigest()
        except Exception as e:
            logger.warning(f"Не удалось вычислить хэш файла {filepath}: {e}")
            return ""
    
    def get_file_info(self, filepath: str) -> Optional[Dict[str, Any]]:
        """Получает информацию о файле."""
        try:
            stat = os.stat(filepath)
            return {
                'path': filepath,
                'size': stat.st_size,
                'mtime': stat.st_mtime,
                'hash': self.calculate_file_hash(filepath)
            }
        except Exception as e:
            logger.warning(f"Не удалось получить информацию о файле {filepath}: {e}")
            return None
    
    def check_file_changes(self, filepath: str) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Проверяет, изменился ли файл.
        Возвращает: (изменился, старый_хэш, новый_хэш)
        """
        file_info = self.get_file_info(filepath)
        if not file_info or not file_info['hash']:
            return False, None, None
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute(
            "SELECT version_hash FROM file_versions WHERE path = ? ORDER BY indexed_at DESC LIMIT 1",
            (filepath,)
        )
        row = cursor.fetchone()
        conn.close()
        
        old_hash = row[0] if row else None
        new_hash = file_info['hash']
        
        if old_hash is None:
            return True, None, new_hash  # Файл новый
        elif old_hash != new_hash:
            return True, old_hash, new_hash  # Файл изменился
        else:
            return False, old_hash, new_hash  # Файл не изменился
    
    def record_file_version(self, filepath: str, metadata: Dict = None) -> bool:
        """Записывает новую версию файла."""
        file_info = self.get_file_info(filepath)
        if not file_info or not file_info['hash']:
            return False
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        metadata_json = json.dumps(metadata) if metadata else "{}"
        
        try:
            cursor.execute("""
                INSERT INTO file_versions (path, version_hash, file_size, mtime, indexed_at, metadata)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                filepath,
                file_info['hash'],
                file_info['size'],
                file_info['mtime'],
                time.time(),
                metadata_json
            ))
            
            # Определяем тип изменения
            cursor.execute(
                "SELECT COUNT(*) FROM file_versions WHERE path = ?",
                (filepath,)
            )
            count = cursor.fetchone()[0]
            
            change_type = 'created' if count == 1 else 'modified'
            
            cursor.execute("""
                INSERT INTO change_history (path, old_hash, new_hash, change_type, timestamp)
                VALUES (?, ?, ?, ?, ?)
            """, (
                filepath,
                None,  # Для created old_hash будет NULL
                file_info['hash'],
                change_type,
                time.time()
            ))
            
            conn.commit()
            logger.info(f"Записана версия файла: {filepath} (хэш: {file_info['hash'][:16]}...)")
            return True
            
        except Exception as e:
            logger.error(f"Ошибка записи версии файла {filepath}: {e}")
            conn.rollback()
            return False
        finally:
            conn.close()
    
    def record_file_deletion(self, filepath: str) -> bool:
        """Записывает удаление файла."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            # Получаем последний хэш файла
            cursor.execute(
                "SELECT version_hash FROM file_versions WHERE path = ? ORDER BY indexed_at DESC LIMIT 1",
                (filepath,)
            )
            row = cursor.fetchone()
            old_hash = row[0] if row else None
            
            cursor.execute("""
                INSERT INTO change_history (path, old_hash, new_hash, change_type, timestamp)
                VALUES (?, ?, ?, ?, ?)
            """, (
                filepath,
                old_hash,
                None,
                'deleted',
                time.time()
            ))
            
            conn.commit()
            logger.info(f"Записано удаление файла: {filepath}")
            return True
            
        except Exception as e:
            logger.error(f"Ошибка записи удаления файла {filepath}: {e}")
            conn.rollback()
            return False
        finally:
            conn.close()
    
    def get_pending_changes(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Возвращает список необработанных изменений."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT ch.id, ch.path, ch.old_hash, ch.new_hash, ch.change_type, ch.timestamp,
                   fv.metadata
            FROM change_history ch
            LEFT JOIN file_versions fv ON ch.path = fv.path AND ch.new_hash = fv.version_hash
            WHERE ch.indexed = FALSE
            ORDER BY ch.timestamp ASC
            LIMIT ?
        """, (limit,))
        
        changes = []
        for row in cursor.fetchall():
            metadata = json.loads(row[6]) if row[6] else {}
            changes.append({
                'id': row[0],
                'path': row[1],
                'old_hash': row[2],
                'new_hash': row[3],
                'change_type': row[4],
                'timestamp': row[5],
                'metadata': metadata
            })
        
        conn.close()
        return changes
    
    def mark_change_as_indexed(self, change_id: int) -> bool:
        """Отмечает изменение как проиндексированное."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            cursor.execute(
                "UPDATE change_history SET indexed = TRUE WHERE id = ?",
                (change_id,)
            )
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"Ошибка обновления изменения {change_id}: {e}")
            conn.rollback()
            return False
        finally:
            conn.close()
    
    def get_file_history(self, filepath: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Возвращает историю изменений файла."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT version_hash, file_size, mtime, indexed_at, metadata
            FROM file_versions
            WHERE path = ?
            ORDER BY indexed_at DESC
            LIMIT ?
        """, (filepath, limit))
        
        history = []
        for row in cursor.fetchall():
            metadata = json.loads(row[4]) if row[4] else {}
            history.append({
                'version_hash': row[0],
                'file_size': row[1],
                'mtime': row[2],
                'indexed_at': row[3],
                'metadata': metadata
            })
        
        conn.close()
        return history
    
    def cleanup_old_versions(self, days_to_keep: int = 30) -> int:
        """Очищает старые версии файлов."""
        cutoff_time = time.time() - (days_to_keep * 24 * 3600)
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            # Удаляем старые версии файлов
            cursor.execute("""
                DELETE FROM file_versions
                WHERE indexed_at < ? AND path IN (
                    SELECT path FROM file_versions
                    GROUP BY path
                    HAVING COUNT(*) > 1
                )
            """, (cutoff_time,))
            
            deleted_versions = cursor.rowcount
            
            # Удаляем старые записи истории
            cursor.execute(
                "DELETE FROM change_history WHERE timestamp < ?",
                (cutoff_time,)
            )
            
            deleted_history = cursor.rowcount
            
            conn.commit()
            logger.info(f"Очищено {deleted_versions} старых версий и {deleted_history} записей истории")
            return deleted_versions + deleted_history
            
        except Exception as e:
            logger.error(f"Ошибка очистки старых версий: {e}")
            conn.rollback()
            return 0
        finally:
            conn.close()
    
    def get_statistics(self) -> Dict[str, Any]:
        """Возвращает статистику системы версионирования."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        stats = {}
        
        # Общая статистика
        cursor.execute("SELECT COUNT(*) FROM file_versions")
        stats['total_versions'] = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(DISTINCT path) FROM file_versions")
        stats['unique_files'] = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM change_history")
        stats['total_changes'] = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM change_history WHERE indexed = FALSE")
        stats['pending_changes'] = cursor.fetchone()[0]
        
        # Статистика по типам изменений
        cursor.execute("""
            SELECT change_type, COUNT(*) 
            FROM change_history 
            GROUP BY change_type
        """)
        stats['changes_by_type'] = dict(cursor.fetchall())
        
        # Самые часто изменяемые файлы
        cursor.execute("""
            SELECT path, COUNT(*) as change_count
            FROM change_history
            GROUP BY path
            ORDER BY change_count DESC
            LIMIT 10
        """)
        stats['most_changed_files'] = cursor.fetchall()
        
        conn.close()
        return stats


class IncrementalIndexer:
    """Инкрементальный индексатор на основе системы версионирования."""
    
    def __init__(self, versioning_system: VersioningSystem, memory_client):
        self.versioning = versioning_system
        self.memory = memory_client
        self.logger = logging.getLogger(__name__)
    
    def index_changes(self, batch_size: int = 50) -> Dict[str, Any]:
        """Индексирует накопившиеся изменения."""
        changes = self.versioning.get_pending_changes(batch_size)
        if not changes:
            return {'success': True, 'message': 'Нет изменений для индексации', 'processed': 0}
        
        results = {
            'processed': 0,
            'successful': 0,
            'failed': 0,
            'details': []
        }
        
        for change in changes:
            try:
                if change['change_type'] == 'deleted':
                    # Удаляем файл из индекса
                    self._delete_from_index(change['path'])
                    self.versioning.mark_change_as_indexed(change['id'])
                    results['details'].append({
                        'path': change['path'],
                        'status': 'deleted',
                        'message': 'Файл удалён из индекса'
                    })
                    results['successful'] += 1
                    
                elif change['change_type'] in ['created', 'modified']:
                    # Индексируем файл
                    if os.path.exists(change['path']):
                        from memory.indexer import index_file
                        index_file(change['path'], self.memory, clean=False, incremental=True, force=True)
                        self.versioning.mark_change_as_indexed(change['id'])
                        results['details'].append({
                            'path': change['path'],
                            'status': 'indexed',
                            'message': f"Файл проиндексирован ({change['change_type']})"
                        })
                        results['successful'] += 1
                    else:
                        results['details'].append({
                            'path': change['path'],
                            'status': 'skipped',
                            'message': 'Файл не существует'
                        })
                        results['failed'] += 1
                
                results['processed'] += 1
                
            except Exception as e:
                self.logger.error(f"Ошибка индексации изменения {change['path']}: {e}")
                results['details'].append({
                    'path': change['path'],
                    'status': 'error',
                    'message': str(e)
                })
                results['failed'] += 1
                results['processed'] += 1
        
        return {
            'success': results['failed'] == 0,
            'total_changes': len(changes),
            **results
        }
    
    def _delete_from_index(self, filepath: str):
        """Удаляет файл из векторной памяти."""
        try:
            if hasattr(self.memory, 'delete_by_filter'):
                self.memory.delete_by_filter({"path": filepath})
                self.logger.info(f"Удалён файл из индекса: {filepath}")
            else:
                self.logger.warning(f"Не удалось удалить файл {filepath}: метод delete_by_filter не найден")
        except Exception as e:
            self.logger.error(f"Ошибка удаления файла {filepath} из индекса: {e}")
    
    def scan_directory(self, directory: str, recursive: bool = True) -> Dict[str, Any]:
        """Сканирует директорию и обнаруживает изменения."""
        import os
        
        directory = os.path.abspath(directory)
        if not os.path.exists(directory):
            return {'success': False, 'error': f"Директория не существует: {directory}"}
        
        stats = {
            'scanned': 0,
            'new': 0,
            'modified': 0,
            'unchanged': 0,
            'deleted': 0,
            'errors': 0
        }
        
        # Получаем список файлов из базы данных
        conn = sqlite3.connect(self.versioning.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT DISTINCT path FROM file_versions")
        known_files = {row[0] for row in cursor.fetchall()}
        conn.close()
        
        current_files = set()
        
        # Сканируем файлы
        for root, dirs, files in os.walk(directory):
            if not recursive:
                dirs.clear()
            
            for file in files:
                filepath = os.path.join(root, file)
                current_files.add(filepath)
                
                stats['scanned'] += 1
                
                try:
                    changed, old_hash, new_hash = self.versioning.check_file_changes(filepath)
                    
                    if changed:
                        if old_hash is None:
                            # Новый файл
                            self.versioning.record_file_version(filepath)
                            stats['new'] += 1
                            self.logger.info(f"Обнаружен новый файл: {filepath}")
                        else:
                            # Изменённый файл
                            self.versioning.record_file_version(filepath)
                            stats['modified'] += 1
                            self.logger.info(f"Обнаружен изменённый файл: {filepath}")
                    else:
                        stats['unchanged'] += 1
                        
                except Exception as e:
                    self.logger.error(f"Ошибка проверки файла {filepath}: {e}")
                    stats['errors'] += 1
        
        # Обнаруживаем удалённые файлы
        deleted_files = known_files - current_files
        for filepath in deleted_files:
            if filepath.startswith(directory):
                self.versioning.record_file_deletion(filepath)
                stats['deleted'] += 1
                self.logger.info(f"Обнаружен удалённый файл: {filepath}")
        
        return {
            'success': True,
            'stats': stats,
            'total_files': len(current_files),
            'deleted_files': len(deleted_files)
        }
    
    def start_background_scanner(self, directory: str, interval_seconds: int = 3600):
        """Запускает фоновый сканер для автоматического обнаружения изменений."""
        import threading
        import time
        
        def scanner_loop():
            while True:
                try:
                    self.logger.info(f"Запуск фонового сканирования директории: {directory}")
                    result = self.scan_directory(directory, recursive=True)
                    if result['success']:
                        stats = result['stats']
                        self.logger.info(f"Сканирование завершено: {stats['scanned']} файлов, "
                                       f"{stats['new']} новых, {stats['modified']} изменённых, "
                                       f"{stats['deleted']} удалённых")
                        
                        # Индексируем обнаруженные изменения
                        index_result = self.index_changes()
                        if index_result['success']:
                            self.logger.info(f"Индексация изменений: {index_result['processed']} обработано")
                    else:
                        self.logger.error(f"Ошибка сканирования: {result.get('error', 'неизвестно')}")
                except Exception as e:
                    self.logger.error(f"Ошибка в фоновом сканере: {e}")
                
                time.sleep(interval_seconds)
        
        scanner_thread = threading.Thread(target=scanner_loop, daemon=True)
        scanner_thread.start()
        return scanner_thread


def create_versioning_system():
    """Создаёт и возвращает экземпляр системы версионирования."""
    return VersioningSystem()


def create_incremental_indexer(memory_client):
    """Создаёт и возвращает инкрементальный индексатор."""
    versioning = create_versioning_system()
    return IncrementalIndexer(versioning, memory_client)


if __name__ == "__main__":
    # Пример использования
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    
    try:
        from memory import memory
        print("✅ Векторная память загружена")
        
        # Создаём систему версионирования
        versioning = create_versioning_system()
        print("✅ Система версионирования создана")
        
        # Создаём инкрементальный индексатор
        indexer = IncrementalIndexer(versioning, memory)
        print("✅ Инкрементальный индексатор создан")
        
        # Получаем статистику
        stats = versioning.get_statistics()
        print(f"📊 Статистика системы версионирования:")
        print(f"   Всего версий: {stats['total_versions']}")
        print(f"   Уникальных файлов: {stats['unique_files']}")
        print(f"   Всего изменений: {stats['total_changes']}")
        print(f"   Ожидающих индексации: {stats['pending_changes']}")
        
        # Индексируем ожидающие изменения
        if stats['pending_changes'] > 0:
            print(f"🔍 Индексация {stats['pending_changes']} изменений...")
            result = indexer.index_changes()
            print(f"✅ Индексация завершена: {result['processed']} обработано, "
                  f"{result['successful']} успешно, {result['failed']} с ошибками")
        
        print("\n🚀 Система версионирования и инкрементальной индексации готова к работе!")
        
    except ImportError as e:
        print(f"❌ Ошибка импорта: {e}")
    except Exception as e:
        print(f"❌ Ошибка: {e}")
