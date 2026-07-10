"""CRUD del sistema de warns (advertencias acumulativas)."""
from datetime import datetime, timedelta
from typing import Optional

from db import get_db


async def add_warn(
    chat_id: int,
    user_id: int,
    username: Optional[str],
    reason: str,
    expiration_days: int,
) -> int:
    """Añade un warn. Devuelve el total de warns activos de la usuaria."""
    expires = datetime.utcnow() + timedelta(days=expiration_days)
    async with get_db() as db:
        await db.execute(
            "INSERT INTO warns (chat_id, user_id, username, reason, expires_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (chat_id, user_id, username, reason, expires.isoformat(sep=" ")),
        )
        await db.commit()
    return await count_active_warns(chat_id, user_id)


async def remove_last_warn(chat_id: int, user_id: int) -> bool:
    """Quita el warn activo más reciente. Devuelve True si había alguno."""
    async with get_db() as db:
        cur = await db.execute(
            "SELECT id FROM warns WHERE chat_id = ? AND user_id = ? "
            "AND expires_at > CURRENT_TIMESTAMP ORDER BY warned_at DESC LIMIT 1",
            (chat_id, user_id),
        )
        row = await cur.fetchone()
        if row is None:
            return False
        await db.execute("DELETE FROM warns WHERE id = ?", (row["id"],))
        await db.commit()
        return True


async def count_active_warns(chat_id: int, user_id: int) -> int:
    """Cuenta los warns activos (no expirados) de una usuaria."""
    async with get_db() as db:
        cur = await db.execute(
            "SELECT COUNT(*) AS n FROM warns WHERE chat_id = ? AND user_id = ? "
            "AND expires_at > CURRENT_TIMESTAMP",
            (chat_id, user_id),
        )
        row = await cur.fetchone()
        return int(row["n"] or 0)


async def list_warns(chat_id: int, user_id: int) -> list[dict]:
    """Lista los warns activos de una usuaria."""
    async with get_db() as db:
        cur = await db.execute(
            "SELECT reason, warned_at, expires_at FROM warns "
            "WHERE chat_id = ? AND user_id = ? AND expires_at > CURRENT_TIMESTAMP "
            "ORDER BY warned_at DESC",
            (chat_id, user_id),
        )
        return [dict(r) for r in await cur.fetchall()]


async def reset_warns(chat_id: int, user_id: int) -> int:
    """Borra TODOS los warns activos de una usuaria."""
    async with get_db() as db:
        cur = await db.execute(
            "DELETE FROM warns WHERE chat_id = ? AND user_id = ?",
            (chat_id, user_id),
        )
        await db.commit()
        return cur.rowcount


async def cleanup_expired_warns() -> int:
    """Borra warns ya expirados de TODOS los chats."""
    async with get_db() as db:
        cur = await db.execute(
            "DELETE FROM warns WHERE expires_at <= CURRENT_TIMESTAMP"
        )
        await db.commit()
        return cur.rowcount
