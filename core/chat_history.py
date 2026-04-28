"""
Модуль для работы с историей диалогов в PostgreSQL.
Если PostgreSQL недоступен, система работает без истории чатов.
"""

import os
import logging
import asyncpg
from typing import List, Dict

logger = logging.getLogger(__name__)

# Параметры подключения из .env
DB_HOST = os.getenv("POSTGRES_HOST", "localhost")
DB_PORT = os.getenv("POSTGRES_PORT", "5432")
DB_NAME = os.getenv("POSTGRES_DB", "zora")
DB_USER = os.getenv("POSTGRES_USER", "postgres")
DB_PASSWORD = os.getenv("POSTGRES_PASSWORD", "postgres")

_pool = None
DB_AVAILABLE = False  # Флаг доступности БД


async def get_pool():
    """Возвращает пул соединений с PostgreSQL."""
    global _pool, DB_AVAILABLE
    if _pool is None:
        try:
            _pool = await asyncpg.create_pool(
                host=DB_HOST,
                port=int(DB_PORT),
                database=DB_NAME,
                user=DB_USER,
                password=DB_PASSWORD,
                min_size=1,
                max_size=10,
                command_timeout=5  # Быстрый таймаут, чтобы не ждать долго
            )
            DB_AVAILABLE = True
            logger.info(f"✅ Подключение к PostgreSQL: {DB_HOST}:{DB_PORT}/{DB_NAME}")
        except Exception as e:
            DB_AVAILABLE = False
            _pool = None
            logger.warning(f"⚠️ PostgreSQL недоступен ({DB_HOST}:{DB_PORT}): {e}")
            logger.warning("⚠️ История чатов будет работать без сохранения (in-memory режим)")
    return _pool


async def init_db():
    """Инициализирует таблицы в PostgreSQL (если их нет)."""
    pool = await get_pool()
    if pool is None:
        return  # БД недоступна — пропускаем

    async with pool.acquire() as conn:
        # Таблица чатов
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS chats (
                id SERIAL PRIMARY KEY,
                chat_id VARCHAR(100) NOT NULL UNIQUE,
                user_id VARCHAR(100) DEFAULT 'default',
                name VARCHAR(255) NOT NULL DEFAULT 'Новый чат',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Таблица сообщений
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id SERIAL PRIMARY KEY,
                chat_id VARCHAR(100) NOT NULL REFERENCES chats(chat_id) ON DELETE CASCADE,
                message_id VARCHAR(100) NOT NULL UNIQUE,
                role VARCHAR(20) NOT NULL,
                content TEXT NOT NULL,
                agent VARCHAR(100),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Индексы
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_messages_chat_id ON messages(chat_id);
            CREATE INDEX IF NOT EXISTS idx_messages_created_at ON messages(created_at);
        """)

        # Создаём чат по умолчанию, если его нет
        await conn.execute("""
            INSERT INTO chats (chat_id, name, user_id)
            VALUES ('default', 'Основной чат', 'default')
            ON CONFLICT (chat_id) DO NOTHING
        """)

        logger.info("✅ Таблицы истории чатов созданы/проверены")


async def get_chats(user_id: str = "default") -> List[Dict]:
    """Возвращает список чатов пользователя."""
    pool = await get_pool()
    if pool is None:
        return [{"chat_id": "default", "name": "Основной чат"}]

    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT chat_id, name, created_at, updated_at
            FROM chats
            WHERE user_id = $1
            ORDER BY updated_at DESC
        """, user_id)
        return [dict(row) for row in rows]


async def create_chat(chat_id: str, name: str, user_id: str = "default") -> bool:
    """Создаёт новый чат."""
    pool = await get_pool()
    if pool is None:
        return True  # Имитируем успех

    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO chats (chat_id, name, user_id, created_at, updated_at)
            VALUES ($1, $2, $3, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ON CONFLICT (chat_id) DO UPDATE SET updated_at = CURRENT_TIMESTAMP
        """, chat_id, name, user_id)
        return True


async def update_chat_name(chat_id: str, name: str) -> bool:
    """Обновляет название чата."""
    pool = await get_pool()
    if pool is None:
        return True

    async with pool.acquire() as conn:
        await conn.execute("""
            UPDATE chats SET name = $2, updated_at = CURRENT_TIMESTAMP
            WHERE chat_id = $1
        """, chat_id, name)
        return True


async def delete_chat(chat_id: str) -> bool:
    """Удаляет чат и все его сообщения (каскадно)."""
    pool = await get_pool()
    if pool is None:
        return True

    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM chats WHERE chat_id = $1", chat_id)
        return True


async def get_messages(chat_id: str, limit: int = 50) -> List[Dict]:
    """Возвращает последние сообщения чата."""
    pool = await get_pool()
    if pool is None:
        return []

    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT message_id, role, content, agent, created_at
            FROM messages
            WHERE chat_id = $1
            ORDER BY created_at ASC
            LIMIT $2
        """, chat_id, limit)
        return [dict(row) for row in rows]


async def add_message(chat_id: str, message_id: str, role: str, content: str, agent: str = None) -> bool:
    """Добавляет сообщение в чат. Обновляет updated_at чата."""
    pool = await get_pool()
    if pool is None:
        return True  # Имитируем успех

    async with pool.acquire() as conn:
        # Обновляем updated_at в чате
        await conn.execute("""
            UPDATE chats SET updated_at = CURRENT_TIMESTAMP
            WHERE chat_id = $1
        """, chat_id)

        # Добавляем сообщение
        await conn.execute("""
            INSERT INTO messages (chat_id, message_id, role, content, agent, created_at)
            VALUES ($1, $2, $3, $4, $5, CURRENT_TIMESTAMP)
            ON CONFLICT (message_id) DO UPDATE SET
                content = EXCLUDED.content,
                created_at = CURRENT_TIMESTAMP
        """, chat_id, message_id, role, content, agent)
        return True


async def delete_messages(chat_id: str) -> bool:
    """Удаляет все сообщения чата."""
    pool = await get_pool()
    if pool is None:
        return True

    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM messages WHERE chat_id = $1", chat_id)
        return True
