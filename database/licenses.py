"""CRUD del sistema de licencias por chat."""
import logging
from datetime import datetime, timedelta
from typing import Optional

from database.db import get_db

logger = logging.getLogger(__name__)


# Estados:
# - owner:   chat del propietario (gratis para siempre)
# - active:  pagado, con expiración (None = lifetime)
# - pending: nuevo, sin pagar
# - expired: pagó pero caducó
# - banned:  vetado por el owner

VALID_STATUSES = {"owner", "active", "pending", "expired", "banned"}


async def get_license(chat_id: int) -> Optional[dict]:
    """Devuelve la licencia del chat o None si no existe."""
    async with get_db() as db:
        cur = await db.execute(
            "SELECT * FROM licenses WHERE chat_id = ?", (chat_id,)
        )
        row = await cur.fetchone()
        return dict(row) if row else None


async def create_license(
    chat_id: int,
    status: str = "pending",
    expires_at: Optional[datetime] = None,
    added_by_user_id: Optional[int] = None,
    added_by_username: Optional[str] = None,
    activated_by: Optional[int] = None,
) -> dict:
    """Crea una licencia si no existe. Devuelve la licencia."""
    existing = await get_license(chat_id)
    if existing:
        return existing
    if status not in VALID_STATUSES:
        status = "pending"
    expires_iso = expires_at.isoformat(sep=" ") if expires_at else None
    activated_iso = (
        datetime.utcnow().isoformat(sep=" ") if status in ("owner", "active") else None
    )
    async with get_db() as db:
        await db.execute(
            """INSERT INTO licenses
               (chat_id, status, expires_at, activated_at, activated_by,
                added_by_user_id, added_by_username)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (chat_id, status, expires_iso, activated_iso, activated_by,
             added_by_user_id, added_by_username),
        )
        await db.commit()
    return await get_license(chat_id)


async def set_status(
    chat_id: int,
    status: str,
    expires_at: Optional[datetime] = None,
    activated_by: Optional[int] = None,
) -> None:
    """Cambia el estado y opcionalmente la expiración."""
    if status not in VALID_STATUSES:
        raise ValueError(f"Estado inválido: {status}")
    expires_iso = expires_at.isoformat(sep=" ") if expires_at else None
    activated_iso = (
        datetime.utcnow().isoformat(sep=" ") if status in ("owner", "active") else None
    )
    # Aseguramos que existe
    if await get_license(chat_id) is None:
        await create_license(chat_id, status=status, expires_at=expires_at,
                             activated_by=activated_by)
        return
    async with get_db() as db:
        await db.execute(
            """UPDATE licenses SET
               status = ?, expires_at = ?, activated_at = ?, activated_by = ?,
               notified_expiry_warn = 0,
               updated_at = CURRENT_TIMESTAMP
               WHERE chat_id = ?""",
            (status, expires_iso, activated_iso, activated_by, chat_id),
        )
        await db.commit()


async def extend(chat_id: int, days: int, activated_by: Optional[int] = None) -> datetime:
    """Extiende la licencia X días. Devuelve la nueva fecha de expiración."""
    lic = await get_license(chat_id)
    now = datetime.utcnow()
    if lic and lic.get("expires_at"):
        try:
            current = datetime.fromisoformat(lic["expires_at"])
        except ValueError:
            current = now
        base = current if current > now else now
    else:
        base = now
    new_expiry = base + timedelta(days=days)
    await set_status(chat_id, "active", expires_at=new_expiry, activated_by=activated_by)
    return new_expiry


async def set_lifetime(chat_id: int, activated_by: Optional[int] = None) -> None:
    """Activa de por vida."""
    await set_status(chat_id, "active", expires_at=None, activated_by=activated_by)


async def is_chat_allowed(chat_id: int) -> bool:
    """True si el chat tiene una licencia válida ahora mismo."""
    lic = await get_license(chat_id)
    if lic is None:
        return False
    status = lic.get("status")
    if status == "owner":
        return True
    if status != "active":
        return False
    exp = lic.get("expires_at")
    if exp is None:
        return True  # lifetime
    try:
        exp_dt = datetime.fromisoformat(exp)
    except ValueError:
        return False
    return exp_dt > datetime.utcnow()


async def list_licenses(status_filter: Optional[str] = None) -> list[dict]:
    """Lista todas las licencias (opcionalmente filtradas por estado)."""
    async with get_db() as db:
        if status_filter:
            cur = await db.execute(
                """SELECT l.*, c.chat_title FROM licenses l
                   LEFT JOIN bot_chats c ON l.chat_id = c.chat_id
                   WHERE l.status = ?
                   ORDER BY l.updated_at DESC""",
                (status_filter,),
            )
        else:
            cur = await db.execute(
                """SELECT l.*, c.chat_title FROM licenses l
                   LEFT JOIN bot_chats c ON l.chat_id = c.chat_id
                   ORDER BY
                     CASE l.status
                       WHEN 'pending' THEN 1
                       WHEN 'active' THEN 2
                       WHEN 'owner' THEN 3
                       WHEN 'expired' THEN 4
                       WHEN 'banned' THEN 5
                     END,
                     l.updated_at DESC"""
            )
        return [dict(r) for r in await cur.fetchall()]


async def count_by_status() -> dict[str, int]:
    """Devuelve un dict {status: count}."""
    async with get_db() as db:
        cur = await db.execute(
            "SELECT status, COUNT(*) AS n FROM licenses GROUP BY status"
        )
        rows = await cur.fetchall()
    result = {s: 0 for s in VALID_STATUSES}
    for r in rows:
        result[r["status"]] = int(r["n"])
    return result


async def mark_expiry_warned(chat_id: int) -> None:
    """Marca que ya se avisó al chat del próximo vencimiento (para no spamear)."""
    async with get_db() as db:
        await db.execute(
            "UPDATE licenses SET notified_expiry_warn = 1 WHERE chat_id = ?",
            (chat_id,),
        )
        await db.commit()


async def get_expiring_soon(days: int = 3) -> list[dict]:
    """Licencias active que expiran en menos de X días y aún no se avisó."""
    until = datetime.utcnow() + timedelta(days=days)
    async with get_db() as db:
        cur = await db.execute(
            """SELECT l.*, c.chat_title FROM licenses l
               LEFT JOIN bot_chats c ON l.chat_id = c.chat_id
               WHERE l.status = 'active'
               AND l.expires_at IS NOT NULL
               AND l.expires_at <= ?
               AND l.notified_expiry_warn = 0""",
            (until.isoformat(sep=" "),),
        )
        return [dict(r) for r in await cur.fetchall()]


async def mark_expired_licenses() -> int:
    """Marca como 'expired' las licencias active que ya caducaron. Devuelve cuántas."""
    now = datetime.utcnow().isoformat(sep=" ")
    async with get_db() as db:
        cur = await db.execute(
            """UPDATE licenses SET status = 'expired', updated_at = CURRENT_TIMESTAMP
               WHERE status = 'active'
               AND expires_at IS NOT NULL
               AND expires_at <= ?""",
            (now,),
        )
        await db.commit()
        return cur.rowcount


async def delete_license(chat_id: int) -> None:
    """Borra la licencia (uso interno cuando el bot sale del chat)."""
    async with get_db() as db:
        await db.execute("DELETE FROM licenses WHERE chat_id = ?", (chat_id,))
        await db.commit()
