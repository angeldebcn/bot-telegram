"""CRUD de alianzas. Usuarias exentas de las 3 reglas."""
from typing import Optional

from db import get_db


async def add_alianza(chat_id: int, user_id: int, username: Optional[str]) -> bool:
    """Añade una usuaria a las alianzas. Devuelve True si era nueva."""
    async with get_db() as db:
        cur = await db.execute(
            "SELECT 1 FROM alianzas WHERE chat_id = ? AND user_id = ?",
            (chat_id, user_id),
        )
        if await cur.fetchone() is not None:
            return False
        await db.execute(
            "INSERT INTO alianzas (chat_id, user_id, username) VALUES (?, ?, ?)",
            (chat_id, user_id, username),
        )
        await db.commit()
        return True


async def remove_alianza(chat_id: int, user_id: int) -> bool:
    """Quita una alianza. Devuelve True si existía."""
    async with get_db() as db:
        cur = await db.execute(
            "DELETE FROM alianzas WHERE chat_id = ? AND user_id = ?",
            (chat_id, user_id),
        )
        await db.commit()
        return cur.rowcount > 0


async def is_alianza(chat_id: int, user_id: int) -> bool:
    """Comprueba si una usuaria está en alianzas."""
    async with get_db() as db:
        cur = await db.execute(
            "SELECT 1 FROM alianzas WHERE chat_id = ? AND user_id = ?",
            (chat_id, user_id),
        )
        return await cur.fetchone() is not None


async def list_alianzas(chat_id: int) -> list[dict]:
    """Lista todas las alianzas del chat."""
    async with get_db() as db:
        cur = await db.execute(
            "SELECT user_id, username, added_at FROM alianzas "
            "WHERE chat_id = ? ORDER BY added_at DESC",
            (chat_id,),
        )
        return [dict(r) for r in await cur.fetchall()]


async def clear_alianzas(chat_id: int) -> int:
    """Borra todas las alianzas del chat."""
    async with get_db() as db:
        cur = await db.execute(
            "DELETE FROM alianzas WHERE chat_id = ?", (chat_id,)
        )
        await db.commit()
        return cur.rowcount
