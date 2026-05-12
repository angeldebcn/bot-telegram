"""CRUD de publicaciones. Implementa las consultas de las 3 reglas."""
import logging
from datetime import datetime, timedelta
from typing import Optional

from database.db import get_db

logger = logging.getLogger(__name__)


async def insert_post(
    chat_id: int,
    user_id: int,
    username: Optional[str],
    message_id: int,
    media_group_id: Optional[str],
    phash: Optional[str],
    video_size: Optional[int],
    video_duration: Optional[int],
) -> None:
    """Registra una publicación válida (que pasó las 3 reglas)."""
    async with get_db() as db:
        await db.execute(
            """INSERT INTO posts (chat_id, user_id, username, message_id,
               media_group_id, phash, video_size, video_duration)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (chat_id, user_id, username, message_id, media_group_id,
             phash, video_size, video_duration),
        )
        await db.commit()


async def get_last_post_time(chat_id: int, user_id: int) -> Optional[datetime]:
    """Devuelve la hora de la última publicación de un usuario en el chat."""
    async with get_db() as db:
        cur = await db.execute(
            "SELECT MAX(posted_at) AS last FROM posts "
            "WHERE chat_id = ? AND user_id = ?",
            (chat_id, user_id),
        )
        row = await cur.fetchone()
        if row is None or row["last"] is None:
            return None
        return datetime.fromisoformat(row["last"])


async def count_distinct_users_after(
    chat_id: int, since: datetime, exclude_user_id: int
) -> int:
    """
    Cuenta cuántos usuarios DISTINTOS han publicado en chat_id
    después de la fecha `since`, sin contar al propio usuario.
    """
    async with get_db() as db:
        cur = await db.execute(
            "SELECT COUNT(DISTINCT user_id) AS n FROM posts "
            "WHERE chat_id = ? AND posted_at > ? AND user_id != ?",
            (chat_id, since.isoformat(sep=" "), exclude_user_id),
        )
        row = await cur.fetchone()
        return int(row["n"] or 0)


async def find_duplicate_photo(
    chat_id: int,
    phash_hex: str,
    threshold: int,
    hours: int,
) -> Optional[dict]:
    """
    Busca fotos en el chat de las últimas `hours` horas cuya distancia
    Hamming con phash_hex sea <= threshold. Devuelve la primera match o None.
    """
    since = datetime.utcnow() - timedelta(hours=hours)
    async with get_db() as db:
        cur = await db.execute(
            "SELECT id, user_id, phash, posted_at FROM posts "
            "WHERE chat_id = ? AND phash IS NOT NULL AND video_size IS NULL "
            "AND posted_at > ?",
            (chat_id, since.isoformat(sep=" ")),
        )
        rows = await cur.fetchall()
    target = int(phash_hex, 16)
    for row in rows:
        try:
            stored = int(row["phash"], 16)
        except (ValueError, TypeError):
            continue
        # Distancia de Hamming
        if bin(target ^ stored).count("1") <= threshold:
            return dict(row)
    return None


async def find_duplicate_video(
    chat_id: int,
    phash_hex: Optional[str],
    video_size: int,
    video_duration: int,
    threshold: int,
    hours: int,
) -> Optional[dict]:
    """
    Busca vídeos duplicados. Criterio (estricto, según preferencia del dueño):
    mismo tamaño exacto + misma duración exacta + primer frame con distancia
    Hamming <= threshold. Solo considera duplicado si los TRES coinciden.
    """
    since = datetime.utcnow() - timedelta(hours=hours)
    async with get_db() as db:
        cur = await db.execute(
            "SELECT id, user_id, phash, posted_at FROM posts "
            "WHERE chat_id = ? AND video_size = ? AND video_duration = ? "
            "AND posted_at > ?",
            (chat_id, video_size, video_duration, since.isoformat(sep=" ")),
        )
        rows = await cur.fetchall()
    if not rows:
        return None
    if not phash_hex:
        # Sin hash de frame, ya basta con tamaño+duración
        return dict(rows[0])
    target = int(phash_hex, 16)
    for row in rows:
        try:
            stored = int(row["phash"], 16)
        except (ValueError, TypeError):
            continue
        if bin(target ^ stored).count("1") <= threshold:
            return dict(row)
    return None


async def reset_queue(chat_id: int) -> int:
    """Borra TODAS las publicaciones del chat (resetea la cola). Devuelve nº borradas."""
    async with get_db() as db:
        cur = await db.execute(
            "DELETE FROM posts WHERE chat_id = ?", (chat_id,)
        )
        await db.commit()
        return cur.rowcount


async def cleanup_old(days: int) -> int:
    """Borra publicaciones más antiguas que `days` días en TODOS los chats."""
    cutoff = datetime.utcnow() - timedelta(days=days)
    async with get_db() as db:
        cur = await db.execute(
            "DELETE FROM posts WHERE posted_at < ?",
            (cutoff.isoformat(sep=" "),),
        )
        await db.commit()
        return cur.rowcount


async def list_recent_posters(chat_id: int, hours: int = 24) -> list[dict]:
    """Devuelve usuarias que han publicado en las últimas N horas."""
    since = datetime.utcnow() - timedelta(hours=hours)
    async with get_db() as db:
        cur = await db.execute(
            "SELECT user_id, username, COUNT(*) AS n_posts, MAX(posted_at) AS last "
            "FROM posts WHERE chat_id = ? AND posted_at > ? "
            "GROUP BY user_id ORDER BY n_posts DESC",
            (chat_id, since.isoformat(sep=" ")),
        )
        return [dict(r) for r in await cur.fetchall()]
