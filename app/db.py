import time
from typing import Any

import aiosqlite

from config import config


async def init_db() -> None:
    async with aiosqlite.connect(config.DB_PATH) as db:
        await db.executescript(
            """
            CREATE TABLE IF NOT EXISTS source_chats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL UNIQUE,
                title TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS target_chats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL UNIQUE,
                title TEXT NOT NULL,
                reaction TEXT NOT NULL DEFAULT '✅',
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS admin_users (
                user_id INTEGER PRIMARY KEY,
                name TEXT,
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS membership_cache (
                user_id INTEGER PRIMARY KEY,
                is_member_any_source INTEGER NOT NULL,
                checked_at INTEGER NOT NULL,
                expires_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at INTEGER NOT NULL,
                admin_user_id INTEGER,
                admin_name TEXT,
                action TEXT NOT NULL,
                details TEXT
            );

            CREATE TABLE IF NOT EXISTS events_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at INTEGER NOT NULL,
                target_chat_id INTEGER,
                message_id INTEGER,
                user_id INTEGER,
                result TEXT NOT NULL,
                details TEXT
            );
            """
        )
        await db.commit()


def now_ts() -> int:
    return int(time.time())


async def is_admin(user_id: int) -> bool:
    if user_id in config.admin_ids:
        return True

    async with aiosqlite.connect(config.DB_PATH) as db:
        cur = await db.execute(
            "SELECT enabled FROM admin_users WHERE user_id = ?",
            (user_id,),
        )
        row = await cur.fetchone()

    return bool(row and row[0] == 1)


async def add_admin(user_id: int, name: str | None = None) -> None:
    async with aiosqlite.connect(config.DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO admin_users (user_id, name, enabled, created_at)
            VALUES (?, ?, 1, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                name = excluded.name,
                enabled = 1
            """,
            (user_id, name, now_ts()),
        )
        await db.commit()


async def remove_admin(user_id: int) -> None:
    async with aiosqlite.connect(config.DB_PATH) as db:
        await db.execute(
            "UPDATE admin_users SET enabled = 0 WHERE user_id = ?",
            (user_id,),
        )
        await db.commit()


async def log_audit(admin_user_id: int | None, admin_name: str | None, action: str, details: str = "") -> None:
    async with aiosqlite.connect(config.DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO audit_log (created_at, admin_user_id, admin_name, action, details)
            VALUES (?, ?, ?, ?, ?)
            """,
            (now_ts(), admin_user_id, admin_name, action, details),
        )
        await db.commit()


async def log_event(
    result: str,
    target_chat_id: int | None = None,
    message_id: int | None = None,
    user_id: int | None = None,
    details: str = "",
) -> None:
    async with aiosqlite.connect(config.DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO events_log (created_at, target_chat_id, message_id, user_id, result, details)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (now_ts(), target_chat_id, message_id, user_id, result, details),
        )
        await db.commit()


async def upsert_source_chat(chat_id: int, title: str) -> None:
    async with aiosqlite.connect(config.DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO source_chats (chat_id, title, enabled, created_at)
            VALUES (?, ?, 1, ?)
            ON CONFLICT(chat_id) DO UPDATE SET
                title = excluded.title,
                enabled = 1
            """,
            (chat_id, title, now_ts()),
        )
        await db.commit()


async def upsert_target_chat(chat_id: int, title: str, reaction: str) -> None:
    async with aiosqlite.connect(config.DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO target_chats (chat_id, title, reaction, enabled, created_at)
            VALUES (?, ?, ?, 1, ?)
            ON CONFLICT(chat_id) DO UPDATE SET
                title = excluded.title,
                reaction = excluded.reaction,
                enabled = 1
            """,
            (chat_id, title, reaction, now_ts()),
        )
        await db.commit()


async def list_source_chats() -> list[dict[str, Any]]:
    async with aiosqlite.connect(config.DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT id, chat_id, title, enabled FROM source_chats ORDER BY id"
        )
        rows = await cur.fetchall()

    return [dict(row) for row in rows]


async def list_target_chats() -> list[dict[str, Any]]:
    async with aiosqlite.connect(config.DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT id, chat_id, title, reaction, enabled FROM target_chats ORDER BY id"
        )
        rows = await cur.fetchall()

    return [dict(row) for row in rows]


async def get_active_source_chats() -> list[dict[str, Any]]:
    async with aiosqlite.connect(config.DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT id, chat_id, title FROM source_chats WHERE enabled = 1 ORDER BY id"
        )
        rows = await cur.fetchall()

    return [dict(row) for row in rows]


async def get_target_chat(chat_id: int) -> dict[str, Any] | None:
    async with aiosqlite.connect(config.DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """
            SELECT id, chat_id, title, reaction, enabled
            FROM target_chats
            WHERE chat_id = ?
            """,
            (chat_id,),
        )
        row = await cur.fetchone()

    return dict(row) if row else None


async def set_source_enabled(row_id: int, enabled: bool) -> bool:
    async with aiosqlite.connect(config.DB_PATH) as db:
        cur = await db.execute(
            "UPDATE source_chats SET enabled = ? WHERE id = ?",
            (1 if enabled else 0, row_id),
        )
        await db.commit()

    return cur.rowcount > 0


async def set_target_enabled(row_id: int, enabled: bool) -> bool:
    async with aiosqlite.connect(config.DB_PATH) as db:
        cur = await db.execute(
            "UPDATE target_chats SET enabled = ? WHERE id = ?",
            (1 if enabled else 0, row_id),
        )
        await db.commit()

    return cur.rowcount > 0


async def get_membership_cache(user_id: int) -> bool | None:
    current = now_ts()

    async with aiosqlite.connect(config.DB_PATH) as db:
        cur = await db.execute(
            """
            SELECT is_member_any_source, expires_at
            FROM membership_cache
            WHERE user_id = ?
            """,
            (user_id,),
        )
        row = await cur.fetchone()

    if not row:
        return None

    is_member, expires_at = row

    if expires_at < current:
        return None

    return bool(is_member)


async def set_membership_cache(user_id: int, is_member: bool) -> None:
    current = now_ts()
    expires_at = current + config.CACHE_TTL_SECONDS

    async with aiosqlite.connect(config.DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO membership_cache (user_id, is_member_any_source, checked_at, expires_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                is_member_any_source = excluded.is_member_any_source,
                checked_at = excluded.checked_at,
                expires_at = excluded.expires_at
            """,
            (user_id, 1 if is_member else 0, current, expires_at),
        )
        await db.commit()


async def clear_cache() -> None:
    async with aiosqlite.connect(config.DB_PATH) as db:
        await db.execute("DELETE FROM membership_cache")
        await db.commit()