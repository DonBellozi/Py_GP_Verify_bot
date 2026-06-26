import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import aiosqlite

from app.config import settings


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def now_iso() -> str:
    return now_utc().isoformat(timespec="seconds")


def _ensure_db_dir() -> None:
    if settings.db_path == ":memory:":
        return

    db_parent = Path(settings.db_path).expanduser().resolve().parent
    db_parent.mkdir(parents=True, exist_ok=True)


async def _ensure_column(
    db: aiosqlite.Connection,
    table: str,
    column: str,
    definition: str,
) -> None:
    cursor = await db.execute(f"PRAGMA table_info({table})")
    rows = await cursor.fetchall()
    existing_columns = {row[1] for row in rows}

    if column not in existing_columns:
        await db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


async def init_db() -> None:
    _ensure_db_dir()

    async with aiosqlite.connect(settings.db_path) as db:
        await db.executescript(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS bot_admins (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                full_name TEXT,
                role TEXT NOT NULL DEFAULT 'admin',
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS source_chats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL UNIQUE,
                title TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                removed_from_processing INTEGER NOT NULL DEFAULT 0,
                created_by_user_id INTEGER,
                created_by_username TEXT,
                created_by_full_name TEXT,
                created_at TEXT NOT NULL,
                removed_by_user_id INTEGER,
                removed_at TEXT,
                remove_reason TEXT,
                updated_at TEXT
            );

            CREATE TABLE IF NOT EXISTS target_chats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL UNIQUE,
                title TEXT NOT NULL,
                reaction TEXT NOT NULL DEFAULT '👌',
                enabled INTEGER NOT NULL DEFAULT 1,
                removed_from_processing INTEGER NOT NULL DEFAULT 0,
                created_by_user_id INTEGER,
                created_by_username TEXT,
                created_by_full_name TEXT,
                created_at TEXT NOT NULL,
                removed_by_user_id INTEGER,
                removed_at TEXT,
                remove_reason TEXT,
                updated_at TEXT
            );

            CREATE TABLE IF NOT EXISTS membership_cache (
                user_id INTEGER PRIMARY KEY,
                is_verified INTEGER NOT NULL,
                checked_at TEXT NOT NULL,
                expires_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS events_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                target_chat_id INTEGER,
                message_id INTEGER,
                user_id INTEGER,
                is_verified INTEGER,
                action TEXT NOT NULL,
                error TEXT
            );

            CREATE TABLE IF NOT EXISTS pending_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                request_type TEXT NOT NULL,
                requested_by_user_id INTEGER NOT NULL,
                requested_by_username TEXT,
                requested_by_full_name TEXT,
                chat_id INTEGER,
                chat_title TEXT,
                chat_role TEXT,
                payload_json TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                resolved_at TEXT,
                resolved_by_user_id INTEGER
            );

            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                actor_user_id INTEGER,
                actor_username TEXT,
                actor_full_name TEXT,
                action TEXT NOT NULL,
                entity_type TEXT,
                entity_id TEXT,
                details TEXT
            );
            """
        )

        # Мягкая миграция для уже созданных тестовых БД.
        await _ensure_column(db, "bot_admins", "created_by_user_id", "INTEGER")
        await _ensure_column(db, "bot_admins", "updated_at", "TEXT")
        await _ensure_column(db, "bot_admins", "disabled_by_user_id", "INTEGER")
        await _ensure_column(db, "bot_admins", "disabled_at", "TEXT")

        await _ensure_column(db, "source_chats", "removed_from_processing", "INTEGER NOT NULL DEFAULT 0")
        await _ensure_column(db, "source_chats", "removed_by_user_id", "INTEGER")
        await _ensure_column(db, "source_chats", "removed_at", "TEXT")
        await _ensure_column(db, "source_chats", "remove_reason", "TEXT")

        await _ensure_column(db, "target_chats", "removed_from_processing", "INTEGER NOT NULL DEFAULT 0")
        await _ensure_column(db, "target_chats", "removed_by_user_id", "INTEGER")
        await _ensure_column(db, "target_chats", "removed_at", "TEXT")
        await _ensure_column(db, "target_chats", "remove_reason", "TEXT")
        await _ensure_column(db, "target_chats", "reaction", "TEXT NOT NULL DEFAULT '👌'")

        # events_log безопасно пересоздаем, если осталась старая структура.
        # Это технический журнал событий, поэтому потеря старых строк не влияет на работу бота.
        cursor = await db.execute("PRAGMA table_info(events_log)")
        rows = await cursor.fetchall()
        event_columns = {row[1] for row in rows}
        required_event_columns = {
            "id",
            "created_at",
            "target_chat_id",
            "message_id",
            "user_id",
            "is_verified",
            "action",
            "error",
        }

        if not required_event_columns.issubset(event_columns):
            await db.execute("DROP TABLE IF EXISTS events_log")
            await db.execute(
                """
                CREATE TABLE events_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    target_chat_id INTEGER,
                    message_id INTEGER,
                    user_id INTEGER,
                    is_verified INTEGER,
                    action TEXT NOT NULL,
                    error TEXT
                )
                """
            )

        await _ensure_column(db, "audit_log", "actor_user_id", "INTEGER")
        await _ensure_column(db, "audit_log", "actor_username", "TEXT")
        await _ensure_column(db, "audit_log", "actor_full_name", "TEXT")
        await _ensure_column(db, "audit_log", "entity_type", "TEXT")
        await _ensure_column(db, "audit_log", "entity_id", "TEXT")
        await _ensure_column(db, "audit_log", "details", "TEXT")

        # membership_cache безопасно пересоздаем, если осталась старая структура.
        # Это только временный кеш проверок, поэтому его можно очищать без потери настроек.
        cursor = await db.execute("PRAGMA table_info(membership_cache)")
        rows = await cursor.fetchall()
        cache_columns = {row[1] for row in rows}
        required_cache_columns = {"user_id", "is_verified", "checked_at", "expires_at"}

        if not required_cache_columns.issubset(cache_columns):
            await db.execute("DROP TABLE IF EXISTS membership_cache")
            await db.execute(
                """
                CREATE TABLE membership_cache (
                    user_id INTEGER PRIMARY KEY,
                    is_verified INTEGER NOT NULL,
                    checked_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL
                )
                """
            )

        await db.execute(
            """
            INSERT OR IGNORE INTO settings (key, value)
            VALUES ('admin_approval_mode', ?)
            """,
            (settings.admin_approval_mode,),
        )

        await db.execute(
            """
            INSERT OR IGNORE INTO settings (key, value)
            VALUES ('default_reaction', ?)
            """,
            (settings.default_reaction,),
        )

        await db.commit()


async def get_setting(key: str, default: str | None = None) -> str | None:
    async with aiosqlite.connect(settings.db_path) as db:
        cursor = await db.execute(
            "SELECT value FROM settings WHERE key = ?",
            (key,),
        )
        row = await cursor.fetchone()
        return row[0] if row else default


async def set_setting(key: str, value: str) -> None:
    async with aiosqlite.connect(settings.db_path) as db:
        await db.execute(
            """
            INSERT INTO settings (key, value)
            VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, value),
        )
        await db.commit()


async def clear_membership_cache() -> None:
    async with aiosqlite.connect(settings.db_path) as db:
        await db.execute("DELETE FROM membership_cache")
        await db.commit()


async def get_cached_membership(user_id: int) -> bool | None:
    async with aiosqlite.connect(settings.db_path) as db:
        cursor = await db.execute(
            """
            SELECT is_verified, expires_at
            FROM membership_cache
            WHERE user_id = ?
            """,
            (user_id,),
        )
        row = await cursor.fetchone()

        if not row:
            return None

        expires_at = datetime.fromisoformat(row[1])

        if expires_at <= now_utc():
            await db.execute("DELETE FROM membership_cache WHERE user_id = ?", (user_id,))
            await db.commit()
            return None

        return bool(row[0])


async def set_cached_membership(
    *,
    user_id: int,
    is_verified: bool,
    ttl_minutes: int,
) -> None:
    checked_at = now_utc()
    expires_at = checked_at + timedelta(minutes=ttl_minutes)

    async with aiosqlite.connect(settings.db_path) as db:
        await db.execute(
            """
            INSERT INTO membership_cache (user_id, is_verified, checked_at, expires_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                is_verified = excluded.is_verified,
                checked_at = excluded.checked_at,
                expires_at = excluded.expires_at
            """,
            (
                user_id,
                int(is_verified),
                checked_at.isoformat(timespec="seconds"),
                expires_at.isoformat(timespec="seconds"),
            ),
        )
        await db.commit()


async def write_audit(
    *,
    actor_user_id: int | None,
    actor_username: str | None,
    actor_full_name: str | None,
    action: str,
    entity_type: str | None = None,
    entity_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    async with aiosqlite.connect(settings.db_path) as db:
        await db.execute(
            """
            INSERT INTO audit_log (
                created_at,
                actor_user_id,
                actor_username,
                actor_full_name,
                action,
                entity_type,
                entity_id,
                details
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                now_iso(),
                actor_user_id,
                actor_username,
                actor_full_name,
                action,
                entity_type,
                entity_id,
                json.dumps(details or {}, ensure_ascii=False),
            ),
        )
        await db.commit()


async def write_event(
    *,
    target_chat_id: int | None,
    message_id: int | None,
    user_id: int | None,
    is_verified: bool | None,
    action: str,
    error: str | None = None,
) -> None:
    async with aiosqlite.connect(settings.db_path) as db:
        await db.execute(
            """
            INSERT INTO events_log (
                created_at,
                target_chat_id,
                message_id,
                user_id,
                is_verified,
                action,
                error
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                now_iso(),
                target_chat_id,
                message_id,
                user_id,
                None if is_verified is None else int(is_verified),
                action,
                error,
            ),
        )
        await db.commit()


async def upsert_source_chat(
    *,
    chat_id: int,
    title: str,
    actor_user_id: int,
    actor_username: str | None,
    actor_full_name: str | None,
) -> None:
    async with aiosqlite.connect(settings.db_path) as db:
        ts = now_iso()
        await db.execute(
            """
            INSERT INTO source_chats (
                chat_id,
                title,
                enabled,
                removed_from_processing,
                created_by_user_id,
                created_by_username,
                created_by_full_name,
                created_at,
                updated_at
            )
            VALUES (?, ?, 1, 0, ?, ?, ?, ?, ?)
            ON CONFLICT(chat_id) DO UPDATE SET
                title = excluded.title,
                enabled = 1,
                removed_from_processing = 0,
                updated_at = excluded.updated_at
            """,
            (
                chat_id,
                title,
                actor_user_id,
                actor_username,
                actor_full_name,
                ts,
                ts,
            ),
        )
        await db.commit()


async def upsert_target_chat(
    *,
    chat_id: int,
    title: str,
    reaction: str,
    actor_user_id: int,
    actor_username: str | None,
    actor_full_name: str | None,
) -> None:
    async with aiosqlite.connect(settings.db_path) as db:
        ts = now_iso()
        await db.execute(
            """
            INSERT INTO target_chats (
                chat_id,
                title,
                reaction,
                enabled,
                removed_from_processing,
                created_by_user_id,
                created_by_username,
                created_by_full_name,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, 1, 0, ?, ?, ?, ?, ?)
            ON CONFLICT(chat_id) DO UPDATE SET
                title = excluded.title,
                reaction = excluded.reaction,
                enabled = 1,
                removed_from_processing = 0,
                updated_at = excluded.updated_at
            """,
            (
                chat_id,
                title,
                reaction,
                actor_user_id,
                actor_username,
                actor_full_name,
                ts,
                ts,
            ),
        )
        await db.commit()


async def list_source_chats() -> list[dict[str, Any]]:
    async with aiosqlite.connect(settings.db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT id, chat_id, title, enabled, removed_from_processing
            FROM source_chats
            ORDER BY title
            """
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def list_target_chats() -> list[dict[str, Any]]:
    async with aiosqlite.connect(settings.db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT id, chat_id, title, reaction, enabled, removed_from_processing
            FROM target_chats
            ORDER BY title
            """
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def get_active_source_chat_ids() -> list[int]:
    async with aiosqlite.connect(settings.db_path) as db:
        cursor = await db.execute(
            """
            SELECT chat_id
            FROM source_chats
            WHERE enabled = 1
              AND removed_from_processing = 0
            """
        )
        rows = await cursor.fetchall()
        return [int(row[0]) for row in rows]


async def is_active_target_chat(chat_id: int) -> bool:
    async with aiosqlite.connect(settings.db_path) as db:
        cursor = await db.execute(
            """
            SELECT 1
            FROM target_chats
            WHERE chat_id = ?
              AND enabled = 1
              AND removed_from_processing = 0
            """,
            (chat_id,),
        )
        row = await cursor.fetchone()
        return row is not None


async def get_target_reaction(chat_id: int) -> str | None:
    async with aiosqlite.connect(settings.db_path) as db:
        cursor = await db.execute(
            """
            SELECT reaction
            FROM target_chats
            WHERE chat_id = ?
              AND enabled = 1
              AND removed_from_processing = 0
            """,
            (chat_id,),
        )
        row = await cursor.fetchone()
        return row[0] if row else None


async def remove_chat_from_processing(
    *,
    table: str,
    chat_db_id: int,
    actor_user_id: int,
    reason: str | None = None,
) -> dict[str, Any] | None:
    if table not in {"source_chats", "target_chats"}:
        raise ValueError("Invalid table name")

    async with aiosqlite.connect(settings.db_path) as db:
        db.row_factory = aiosqlite.Row

        cursor = await db.execute(
            f"""
            SELECT id, chat_id, title, enabled, removed_from_processing
            FROM {table}
            WHERE id = ?
            """,
            (chat_db_id,),
        )
        row = await cursor.fetchone()

        if not row:
            return None

        chat = dict(row)
        ts = now_iso()

        await db.execute(
            f"""
            UPDATE {table}
            SET
                enabled = 0,
                removed_from_processing = 1,
                removed_by_user_id = ?,
                removed_at = ?,
                remove_reason = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                actor_user_id,
                ts,
                reason,
                ts,
                chat_db_id,
            ),
        )

        await db.execute("DELETE FROM membership_cache")
        await db.commit()

        return chat


async def restore_chat_to_processing(
    *,
    table: str,
    chat_db_id: int,
) -> dict[str, Any] | None:
    if table not in {"source_chats", "target_chats"}:
        raise ValueError("Invalid table name")

    async with aiosqlite.connect(settings.db_path) as db:
        db.row_factory = aiosqlite.Row

        cursor = await db.execute(
            f"""
            SELECT id, chat_id, title, enabled, removed_from_processing
            FROM {table}
            WHERE id = ?
            """,
            (chat_db_id,),
        )
        row = await cursor.fetchone()

        if not row:
            return None

        chat = dict(row)
        ts = now_iso()

        await db.execute(
            f"""
            UPDATE {table}
            SET
                enabled = 1,
                removed_from_processing = 0,
                removed_by_user_id = NULL,
                removed_at = NULL,
                remove_reason = NULL,
                updated_at = ?
            WHERE id = ?
            """,
            (ts, chat_db_id),
        )

        await db.execute("DELETE FROM membership_cache")
        await db.commit()

        return chat


async def create_pending_request(
    *,
    request_type: str,
    requested_by_user_id: int,
    requested_by_username: str | None,
    requested_by_full_name: str | None,
    chat_id: int,
    chat_title: str,
    chat_role: str,
    payload: dict[str, Any] | None = None,
) -> int:
    async with aiosqlite.connect(settings.db_path) as db:
        cursor = await db.execute(
            """
            INSERT INTO pending_requests (
                created_at,
                request_type,
                requested_by_user_id,
                requested_by_username,
                requested_by_full_name,
                chat_id,
                chat_title,
                chat_role,
                payload_json,
                status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')
            """,
            (
                now_iso(),
                request_type,
                requested_by_user_id,
                requested_by_username,
                requested_by_full_name,
                chat_id,
                chat_title,
                chat_role,
                json.dumps(payload or {}, ensure_ascii=False),
            ),
        )
        await db.commit()
        return int(cursor.lastrowid)


async def get_pending_request(request_id: int) -> dict[str, Any] | None:
    async with aiosqlite.connect(settings.db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT *
            FROM pending_requests
            WHERE id = ?
            """,
            (request_id,),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def update_pending_request_status(
    *,
    request_id: int,
    status: str,
    resolved_by_user_id: int,
) -> None:
    async with aiosqlite.connect(settings.db_path) as db:
        await db.execute(
            """
            UPDATE pending_requests
            SET
                status = ?,
                resolved_at = ?,
                resolved_by_user_id = ?
            WHERE id = ?
            """,
            (
                status,
                now_iso(),
                resolved_by_user_id,
                request_id,
            ),
        )
        await db.commit()

async def upsert_bot_admin(
    *,
    user_id: int,
    username: str | None,
    full_name: str | None,
    actor_user_id: int,
) -> None:
    async with aiosqlite.connect(settings.db_path) as db:
        ts = now_iso()
        await db.execute(
            """
            INSERT INTO bot_admins (
                user_id,
                username,
                full_name,
                role,
                enabled,
                created_at,
                created_by_user_id,
                updated_at
            )
            VALUES (?, ?, ?, 'admin', 1, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                username = COALESCE(excluded.username, bot_admins.username),
                full_name = COALESCE(excluded.full_name, bot_admins.full_name),
                enabled = 1,
                updated_at = excluded.updated_at,
                disabled_by_user_id = NULL,
                disabled_at = NULL
            """,
            (
                user_id,
                username,
                full_name,
                ts,
                actor_user_id,
                ts,
            ),
        )
        await db.commit()


async def update_bot_admin_profile(
    *,
    user_id: int,
    username: str | None,
    full_name: str | None,
) -> None:
    async with aiosqlite.connect(settings.db_path) as db:
        await db.execute(
            """
            UPDATE bot_admins
            SET
                username = COALESCE(?, username),
                full_name = COALESCE(?, full_name),
                updated_at = ?
            WHERE user_id = ?
              AND enabled = 1
            """,
            (
                username,
                full_name,
                now_iso(),
                user_id,
            ),
        )
        await db.commit()


async def get_bot_admin(user_id: int) -> dict[str, Any] | None:
    async with aiosqlite.connect(settings.db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT user_id, username, full_name, role, enabled, created_at, created_by_user_id, updated_at
            FROM bot_admins
            WHERE user_id = ?
            """,
            (user_id,),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def list_bot_admins(*, enabled_only: bool = True) -> list[dict[str, Any]]:
    async with aiosqlite.connect(settings.db_path) as db:
        db.row_factory = aiosqlite.Row

        where = "WHERE enabled = 1" if enabled_only else ""

        cursor = await db.execute(
            f"""
            SELECT user_id, username, full_name, role, enabled, created_at, created_by_user_id, updated_at
            FROM bot_admins
            {where}
            ORDER BY
                CASE WHEN full_name IS NULL OR full_name = '' THEN 1 ELSE 0 END,
                full_name,
                user_id
            """
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def remove_bot_admin(
    *,
    user_id: int,
    actor_user_id: int,
) -> dict[str, Any] | None:
    async with aiosqlite.connect(settings.db_path) as db:
        db.row_factory = aiosqlite.Row

        cursor = await db.execute(
            """
            SELECT user_id, username, full_name, role, enabled, created_at, created_by_user_id, updated_at
            FROM bot_admins
            WHERE user_id = ?
              AND enabled = 1
            """,
            (user_id,),
        )
        row = await cursor.fetchone()

        if not row:
            return None

        admin = dict(row)
        ts = now_iso()

        await db.execute(
            """
            UPDATE bot_admins
            SET
                enabled = 0,
                disabled_by_user_id = ?,
                disabled_at = ?,
                updated_at = ?
            WHERE user_id = ?
            """,
            (
                actor_user_id,
                ts,
                ts,
                user_id,
            ),
        )
        await db.commit()

        return admin

