import os
import aiosqlite
import json
from datetime import datetime, timezone
from typing import Optional

os.makedirs("data", exist_ok=True)
DB_PATH = "data/sender.db"


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                user_id   INTEGER PRIMARY KEY,
                api_id    INTEGER,
                api_hash  TEXT,
                phone     TEXT,
                session_string TEXT,
                is_authorized  INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS subscriptions (
                user_id    INTEGER PRIMARY KEY,
                expires_at TEXT  -- ISO8601 или NULL = бессрочно
            );

            CREATE TABLE IF NOT EXISTS groups (
                id      INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                chat_id TEXT    NOT NULL,
                title   TEXT    NOT NULL,
                UNIQUE(user_id, chat_id)
            );

            CREATE TABLE IF NOT EXISTS messages (
                user_id     INTEGER PRIMARY KEY,
                text        TEXT,
                photo_path  TEXT,
                buttons_json TEXT
            );

            CREATE TABLE IF NOT EXISTS settings (
                user_id INTEGER NOT NULL,
                key     TEXT    NOT NULL,
                value   TEXT    NOT NULL,
                PRIMARY KEY(user_id, key)
            );
        """)
        await db.commit()


# ── Subscription ──────────────────────────────────────────────────────────────

async def grant_subscription(user_id: int, days: Optional[int] = None):
    if days is None:
        expires_at = None
    else:
        from datetime import timedelta
        expires_at = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO subscriptions VALUES (?, ?)",
            (user_id, expires_at),
        )
        await db.commit()


async def revoke_subscription(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM subscriptions WHERE user_id=?", (user_id,))
        await db.commit()


async def has_subscription(user_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT expires_at FROM subscriptions WHERE user_id=?", (user_id,)
        )
        row = await cur.fetchone()
    if not row:
        return False
    expires_at = row[0]
    if expires_at is None:
        return True
    return datetime.fromisoformat(expires_at) > datetime.now(timezone.utc)


async def get_all_users() -> list[tuple]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("""
            SELECT u.user_id, u.phone, u.is_authorized,
                   CASE
                       WHEN s.user_id IS NULL THEN 'no_sub'
                       WHEN s.expires_at IS NULL THEN 'permanent'
                       ELSE s.expires_at
                   END as sub_status
            FROM users u
            LEFT JOIN subscriptions s ON u.user_id = s.user_id
            ORDER BY u.user_id
        """)
        return await cur.fetchall()


# ── Users / Auth ──────────────────────────────────────────────────────────────

async def upsert_user(user_id: int, api_id: int = None, api_hash: str = None, phone: str = None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,)
        )
        if api_id is not None:
            await db.execute("UPDATE users SET api_id=? WHERE user_id=?", (api_id, user_id))
        if api_hash is not None:
            await db.execute("UPDATE users SET api_hash=? WHERE user_id=?", (api_hash, user_id))
        if phone is not None:
            await db.execute("UPDATE users SET phone=? WHERE user_id=?", (phone, user_id))
        await db.commit()


async def save_session(user_id: int, session_string: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET session_string=?, is_authorized=1 WHERE user_id=?",
            (session_string, user_id),
        )
        await db.commit()


async def get_user(user_id: int) -> Optional[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT user_id, api_id, api_hash, phone, session_string, is_authorized FROM users WHERE user_id=?",
            (user_id,),
        )
        row = await cur.fetchone()
    if not row:
        return None
    keys = ("user_id", "api_id", "api_hash", "phone", "session_string", "is_authorized")
    return dict(zip(keys, row))


async def logout_user(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET session_string=NULL, is_authorized=0 WHERE user_id=?",
            (user_id,),
        )
        await db.commit()


# ── Groups ────────────────────────────────────────────────────────────────────

async def add_group(user_id: int, chat_id: str, title: str) -> bool:
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT INTO groups (user_id, chat_id, title) VALUES (?, ?, ?)",
                (user_id, chat_id, title),
            )
            await db.commit()
        return True
    except aiosqlite.IntegrityError:
        return False


async def remove_group(user_id: int, group_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "DELETE FROM groups WHERE id=? AND user_id=?", (group_id, user_id)
        )
        await db.commit()
        return cur.rowcount > 0


async def get_groups(user_id: int) -> list[tuple]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT id, chat_id, title FROM groups WHERE user_id=? ORDER BY id",
            (user_id,),
        )
        return await cur.fetchall()


# ── Message ───────────────────────────────────────────────────────────────────

async def save_message(user_id: int, text: Optional[str], photo_path: Optional[str], buttons: Optional[list]):
    buttons_json = json.dumps(buttons, ensure_ascii=False) if buttons else None
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO messages VALUES (?, ?, ?, ?)",
            (user_id, text, photo_path, buttons_json),
        )
        await db.commit()


async def get_message(user_id: int) -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT text, photo_path, buttons_json FROM messages WHERE user_id=?",
            (user_id,),
        )
        row = await cur.fetchone()
    if not row:
        return {}
    text, photo_path, buttons_json = row
    return {
        "text": text,
        "photo_path": photo_path,
        "buttons": json.loads(buttons_json) if buttons_json else None,
    }


# ── Settings ──────────────────────────────────────────────────────────────────

async def get_setting(user_id: int, key: str, default: str = "2") -> str:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT value FROM settings WHERE user_id=? AND key=?", (user_id, key)
        )
        row = await cur.fetchone()
    return row[0] if row else default


async def set_setting(user_id: int, key: str, value: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO settings VALUES (?, ?, ?)", (user_id, key, value)
        )
        await db.commit()
