"""
=====================================================================
ALIANZAS GLOBALES — Acuerdos con dueños de otros grupos
=====================================================================

Una "alianza" es el dueño de otro grupo con el que tienes un acuerdo de
colaboración. Al darle /freespam:

  • Queda exento de TODO en TODOS los grupos:
      - Las 3 reglas (cola, cooldown, anti-duplicado)
      - El filtro de palabras prohibidas
      - El bloqueo de reenviados

  • Por defecto puede publicar en TODOS los grupos.

Después, desde el panel, eliges en qué grupos SÍ y en cuáles NO puede
publicar. Ejemplo: una alianza de ventas solo en los grupos de ventas;
una alianza de findom solo en los de findom.

Si publica en un grupo donde NO tiene permiso, el bot borra la publicación
y le avisa (mensaje permanente) indicándole dónde sí puede publicar.

TABLAS
------
alianzas_global : quién es alianza (global, no por grupo)
alianza_permisos: excepciones por grupo. Si no hay fila para un grupo,
                  se entiende PERMITIDO (por defecto puede en todos).
"""
import logging
from typing import Optional

import aiosqlite

from db import get_db

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS alianzas_global (
    user_id     INTEGER PRIMARY KEY,
    username    TEXT,
    full_name   TEXT,
    nota        TEXT,
    added_by    INTEGER,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS alianza_permisos (
    user_id   INTEGER NOT NULL,
    chat_id   INTEGER NOT NULL,
    allowed   INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (user_id, chat_id)
);
"""


async def init_alianzas_global() -> None:
    async with get_db() as db:
        try:
            await db.executescript(SCHEMA)
            await db.commit()
            logger.info("✅ Tablas de alianzas globales inicializadas")
        except aiosqlite.Error as e:
            logger.warning("Error creando tablas de alianzas globales: %s", e)


# ===========================================================================
# ALTA / BAJA
# ===========================================================================
async def add_global_alianza(
    user_id: int, username: Optional[str], full_name: Optional[str],
    added_by: Optional[int] = None, nota: Optional[str] = None,
) -> bool:
    """Añade una alianza global. True si es nueva, False si ya existía."""
    async with get_db() as db:
        cur = await db.execute(
            "INSERT OR IGNORE INTO alianzas_global "
            "(user_id, username, full_name, nota, added_by) VALUES (?,?,?,?,?)",
            (user_id, username, full_name, nota, added_by),
        )
        # Si ya existía, refrescar sus datos (por si cambió el @ o el nombre)
        if cur.rowcount == 0:
            await db.execute(
                "UPDATE alianzas_global SET username = COALESCE(?, username), "
                "full_name = COALESCE(?, full_name) WHERE user_id = ?",
                (username, full_name, user_id),
            )
            await db.commit()
            return False
        await db.commit()
        return True


async def remove_global_alianza(user_id: int) -> bool:
    """Quita una alianza global y sus permisos por grupo."""
    async with get_db() as db:
        cur = await db.execute(
            "DELETE FROM alianzas_global WHERE user_id = ?", (user_id,)
        )
        await db.execute(
            "DELETE FROM alianza_permisos WHERE user_id = ?", (user_id,)
        )
        await db.commit()
        return cur.rowcount > 0


async def is_global_alianza(user_id: int) -> bool:
    """True si esta persona es una alianza (en cualquier grupo)."""
    async with get_db() as db:
        cur = await db.execute(
            "SELECT 1 FROM alianzas_global WHERE user_id = ?", (user_id,)
        )
        return await cur.fetchone() is not None


async def get_alianza(user_id: int) -> Optional[dict]:
    async with get_db() as db:
        cur = await db.execute(
            "SELECT * FROM alianzas_global WHERE user_id = ?", (user_id,)
        )
        row = await cur.fetchone()
        return dict(row) if row else None


async def list_global_alianzas() -> list[dict]:
    async with get_db() as db:
        cur = await db.execute(
            "SELECT * FROM alianzas_global ORDER BY created_at DESC"
        )
        return [dict(r) for r in await cur.fetchall()]


async def count_global_alianzas() -> int:
    async with get_db() as db:
        cur = await db.execute("SELECT COUNT(*) AS n FROM alianzas_global")
        row = await cur.fetchone()
        return int(row["n"] or 0)


# ===========================================================================
# PERMISOS POR GRUPO
# ===========================================================================
async def can_post_in(user_id: int, chat_id: int) -> bool:
    """
    True si esta alianza puede publicar en este grupo.
    Por DEFECTO puede en todos: solo devuelve False si hay una fila que lo
    prohíbe explícitamente.
    """
    async with get_db() as db:
        cur = await db.execute(
            "SELECT allowed FROM alianza_permisos WHERE user_id = ? AND chat_id = ?",
            (user_id, chat_id),
        )
        row = await cur.fetchone()
        if row is None:
            return True  # por defecto: permitido
        return bool(row["allowed"])


async def set_permiso(user_id: int, chat_id: int, allowed: bool) -> None:
    """Marca si una alianza puede publicar o no en un grupo."""
    async with get_db() as db:
        await db.execute(
            "INSERT INTO alianza_permisos (user_id, chat_id, allowed) VALUES (?,?,?) "
            "ON CONFLICT(user_id, chat_id) DO UPDATE SET allowed = excluded.allowed",
            (user_id, chat_id, 1 if allowed else 0),
        )
        await db.commit()


async def toggle_permiso(user_id: int, chat_id: int) -> bool:
    """Invierte el permiso de un grupo. Devuelve el nuevo valor."""
    actual = await can_post_in(user_id, chat_id)
    nuevo = not actual
    await set_permiso(user_id, chat_id, nuevo)
    return nuevo


async def get_permisos(user_id: int) -> dict:
    """Devuelve {chat_id: allowed} de las excepciones guardadas."""
    async with get_db() as db:
        cur = await db.execute(
            "SELECT chat_id, allowed FROM alianza_permisos WHERE user_id = ?",
            (user_id,),
        )
        return {r["chat_id"]: bool(r["allowed"]) for r in await cur.fetchall()}


async def get_allowed_chats(user_id: int, all_chats: list[dict]) -> list[dict]:
    """
    De una lista de chats del bot, devuelve aquellos donde la alianza SÍ
    puede publicar. Sirve para decirle en el aviso dónde debe publicar.
    """
    permisos = await get_permisos(user_id)
    return [c for c in all_chats if permisos.get(c["chat_id"], True)]


async def allow_all(user_id: int) -> None:
    """Resetea: puede publicar en todos los grupos (borra excepciones)."""
    async with get_db() as db:
        await db.execute(
            "DELETE FROM alianza_permisos WHERE user_id = ?", (user_id,)
        )
        await db.commit()
