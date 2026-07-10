"""Log de acciones y estadísticas."""
from datetime import datetime, timedelta
from typing import Optional

from db import get_db


async def log_action(
    chat_id: int,
    action: str,
    user_id: Optional[int] = None,
    username: Optional[str] = None,
    rule: Optional[str] = None,
    details: Optional[str] = None,
) -> None:
    """
    Registra una acción del bot.
    action: 'post', 'delete', 'warn', 'mute', 'kick', 'ban', 'config_change', ...
    rule:   'queue', 'cooldown', 'antidup', 'manual', None
    """
    async with get_db() as db:
        await db.execute(
            "INSERT INTO actions_log (chat_id, user_id, username, action, rule, details) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (chat_id, user_id, username, action, rule, details),
        )
        await db.commit()


async def get_stats(chat_id: int, hours: int = 24) -> dict:
    """Estadísticas básicas de los últimos N horas en el chat."""
    since = datetime.utcnow() - timedelta(hours=hours)
    async with get_db() as db:
        # Publicaciones permitidas
        cur = await db.execute(
            "SELECT COUNT(*) AS n FROM posts WHERE chat_id = ? AND posted_at > ?",
            (chat_id, since.isoformat(sep=" ")),
        )
        total_posts = int((await cur.fetchone())["n"] or 0)

        cur = await db.execute(
            "SELECT COUNT(DISTINCT user_id) AS n FROM posts "
            "WHERE chat_id = ? AND posted_at > ?",
            (chat_id, since.isoformat(sep=" ")),
        )
        distinct_users = int((await cur.fetchone())["n"] or 0)

        # Borrados por regla
        deletes = {}
        for rule in ("queue", "cooldown", "antidup"):
            cur = await db.execute(
                "SELECT COUNT(*) AS n FROM actions_log "
                "WHERE chat_id = ? AND action = 'delete' AND rule = ? AND timestamp > ?",
                (chat_id, rule, since.isoformat(sep=" ")),
            )
            deletes[rule] = int((await cur.fetchone())["n"] or 0)

    return {
        "hours": hours,
        "total_posts": total_posts,
        "distinct_users": distinct_users,
        "deletes": deletes,
    }


async def get_top_posters(chat_id: int, hours: int = 168, limit: int = 10) -> list[dict]:
    """Top usuarias por nº de publicaciones en las últimas N horas."""
    since = datetime.utcnow() - timedelta(hours=hours)
    async with get_db() as db:
        cur = await db.execute(
            "SELECT user_id, username, COUNT(*) AS n FROM posts "
            "WHERE chat_id = ? AND posted_at > ? "
            "GROUP BY user_id ORDER BY n DESC LIMIT ?",
            (chat_id, since.isoformat(sep=" "), limit),
        )
        return [dict(r) for r in await cur.fetchall()]


async def get_recent_logs(chat_id: int, limit: int = 20) -> list[dict]:
    """Últimas acciones del bot en el chat."""
    async with get_db() as db:
        cur = await db.execute(
            "SELECT action, rule, user_id, username, details, timestamp "
            "FROM actions_log WHERE chat_id = ? "
            "ORDER BY timestamp DESC LIMIT ?",
            (chat_id, limit),
        )
        return [dict(r) for r in await cur.fetchall()]


async def cleanup_old_logs(days: int) -> int:
    """Borra logs más antiguos que `days` días."""
    cutoff = datetime.utcnow() - timedelta(days=days)
    async with get_db() as db:
        cur = await db.execute(
            "DELETE FROM actions_log WHERE timestamp < ?",
            (cutoff.isoformat(sep=" "),),
        )
        await db.commit()
        return cur.rowcount


# === Bot chats (para el selector remoto) ===
async def upsert_bot_chat(chat_id: int, title: Optional[str], chat_type: str) -> None:
    """Registra/actualiza un chat donde el bot está presente."""
    async with get_db() as db:
        await db.execute(
            "INSERT INTO bot_chats (chat_id, chat_title, chat_type, last_seen) "
            "VALUES (?, ?, ?, CURRENT_TIMESTAMP) "
            "ON CONFLICT(chat_id) DO UPDATE SET "
            "chat_title = excluded.chat_title, chat_type = excluded.chat_type, "
            "last_seen = CURRENT_TIMESTAMP",
            (chat_id, title, chat_type),
        )
        await db.commit()


async def remove_bot_chat(chat_id: int) -> None:
    """Quita un chat del registro (bot expulsado o salido)."""
    async with get_db() as db:
        await db.execute("DELETE FROM bot_chats WHERE chat_id = ?", (chat_id,))
        await db.commit()


async def list_bot_chats() -> list[dict]:
    """Todos los chats donde el bot está activo (grupos, supergrupos y canales)."""
    async with get_db() as db:
        cur = await db.execute(
            "SELECT chat_id, chat_title, chat_type, last_seen FROM bot_chats "
            "WHERE chat_type IN ('group', 'supergroup', 'channel') "
            "ORDER BY last_seen DESC"
        )
        return [dict(r) for r in await cur.fetchall()]


# === Users cache (resolver username -> user_id) ===
async def cache_user(
    chat_id: int, user_id: int, username: Optional[str], full_name: Optional[str]
) -> None:
    async with get_db() as db:
        await db.execute(
            "INSERT INTO users_cache (chat_id, user_id, username, full_name) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(chat_id, user_id) DO UPDATE SET "
            "username = excluded.username, full_name = excluded.full_name, "
            "last_seen = CURRENT_TIMESTAMP",
            (chat_id, user_id, username, full_name),
        )
        await db.commit()


async def find_user_by_username(chat_id: int, username: str) -> Optional[dict]:
    """Busca un user_id por username en el chat."""
    username = username.lstrip("@").lower()
    async with get_db() as db:
        cur = await db.execute(
            "SELECT user_id, username, full_name FROM users_cache "
            "WHERE chat_id = ? AND LOWER(username) = ? LIMIT 1",
            (chat_id, username),
        )
        row = await cur.fetchone()
        return dict(row) if row else None
