"""
=====================================================================
ROLES DE GRUPO Y LISTA BLANCA DE STAFF
=====================================================================

Dos cosas viven aquí:

1. group_roles: el rol de cada grupo donde está el bot.
   - is_verified_group: el grupo de "solo verificadas" (se usa /reporte)
   - is_staff_group: el grupo de staff (llegan reportes + botones + listas)
   - applies_rules: si aplican las 3 reglas (cola/cooldown/antidup)
   - applies_sanctions: si se ejecutan mutes/bans en este grupo

2. staff: la lista blanca de quién puede usar los comandos de sanción
   (/warnleve, /warngrave, /ban, /mute, /delete y sus inversos).
   El OWNER siempre es staff implícito (no hace falta añadirlo).
"""
import logging
from typing import Optional

from db import get_db

logger = logging.getLogger(__name__)


# ===========================================================================
# ROLES DE GRUPO
# ===========================================================================
async def ensure_group(chat_id: int, title: Optional[str] = None) -> None:
    """Crea la fila de roles para un grupo si no existe (con defaults)."""
    async with get_db() as db:
        await db.execute(
            "INSERT INTO group_roles (chat_id, title) VALUES (?, ?) "
            "ON CONFLICT(chat_id) DO UPDATE SET "
            "title = COALESCE(excluded.title, group_roles.title)",
            (chat_id, title),
        )
        await db.commit()


async def get_group_roles(chat_id: int) -> dict:
    """
    Devuelve el rol de un grupo. Si no existe, devuelve defaults
    (aplica reglas, aplica sanciones, no es verificadas ni staff).
    """
    async with get_db() as db:
        cur = await db.execute(
            "SELECT * FROM group_roles WHERE chat_id = ?", (chat_id,)
        )
        row = await cur.fetchone()
        if row:
            return dict(row)
    return {
        "chat_id": chat_id,
        "title": None,
        "is_verified_group": 0,
        "is_staff_group": 0,
        "applies_rules": 1,
        "applies_sanctions": 1,
    }


async def set_group_flag(chat_id: int, flag: str, value: int) -> None:
    """
    Cambia un flag de rol de un grupo.
    flag ∈ {is_verified_group, is_staff_group, applies_rules, applies_sanctions}
    """
    valid = {"is_verified_group", "is_staff_group", "applies_rules", "applies_sanctions"}
    if flag not in valid:
        raise ValueError(f"flag inválido: {flag}")
    await ensure_group(chat_id)
    async with get_db() as db:
        await db.execute(
            f"UPDATE group_roles SET {flag} = ?, updated_at = CURRENT_TIMESTAMP "
            "WHERE chat_id = ?",
            (value, chat_id),
        )
        await db.commit()


async def get_staff_group() -> Optional[int]:
    """Devuelve el chat_id del grupo de staff (o None si no hay)."""
    async with get_db() as db:
        cur = await db.execute(
            "SELECT chat_id FROM group_roles WHERE is_staff_group = 1 LIMIT 1"
        )
        row = await cur.fetchone()
        return int(row["chat_id"]) if row else None


async def get_verified_groups() -> list[int]:
    """Lista de grupos marcados como 'verificadas' (donde se usa /reporte)."""
    async with get_db() as db:
        cur = await db.execute(
            "SELECT chat_id FROM group_roles WHERE is_verified_group = 1"
        )
        return [int(r["chat_id"]) for r in await cur.fetchall()]


async def is_verified_group(chat_id: int) -> bool:
    roles = await get_group_roles(chat_id)
    return bool(roles.get("is_verified_group", 0))


async def is_staff_group(chat_id: int) -> bool:
    roles = await get_group_roles(chat_id)
    return bool(roles.get("is_staff_group", 0))


async def group_applies_rules(chat_id: int) -> bool:
    roles = await get_group_roles(chat_id)
    return bool(roles.get("applies_rules", 1))


async def group_applies_sanctions(chat_id: int) -> bool:
    roles = await get_group_roles(chat_id)
    return bool(roles.get("applies_sanctions", 1))


async def get_sanction_groups() -> list[int]:
    """Todos los grupos donde se ejecutan mutes/bans."""
    async with get_db() as db:
        cur = await db.execute(
            "SELECT chat_id FROM group_roles WHERE applies_sanctions = 1"
        )
        return [int(r["chat_id"]) for r in await cur.fetchall()]


async def list_all_group_roles() -> list[dict]:
    """Todos los grupos con sus roles (para el panel de configuración)."""
    async with get_db() as db:
        cur = await db.execute(
            "SELECT * FROM group_roles ORDER BY title IS NULL, title"
        )
        return [dict(r) for r in await cur.fetchall()]


# ===========================================================================
# LISTA BLANCA DE STAFF
# ===========================================================================
async def add_staff(
    user_id: int, username: Optional[str], full_name: Optional[str],
    added_by: Optional[int],
) -> None:
    async with get_db() as db:
        await db.execute(
            "INSERT INTO staff (user_id, username, full_name, added_by) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET "
            "username = excluded.username, full_name = excluded.full_name",
            (user_id, username, full_name, added_by),
        )
        await db.commit()


async def remove_staff(user_id: int) -> bool:
    async with get_db() as db:
        cur = await db.execute("DELETE FROM staff WHERE user_id = ?", (user_id,))
        await db.commit()
        return cur.rowcount > 0


async def is_staff(user_id: int) -> bool:
    """True si el usuario está en la lista blanca de staff."""
    async with get_db() as db:
        cur = await db.execute(
            "SELECT 1 FROM staff WHERE user_id = ? LIMIT 1", (user_id,)
        )
        return await cur.fetchone() is not None


async def list_staff() -> list[dict]:
    async with get_db() as db:
        cur = await db.execute(
            "SELECT user_id, username, full_name FROM staff ORDER BY created_at"
        )
        return [dict(r) for r in await cur.fetchall()]
