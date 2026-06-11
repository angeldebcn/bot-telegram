"""
CRUD de publicaciones. Implementa las consultas de las 3 reglas.

IMPORTANTE: la columna `deleted_at` marca posts anulados. Cuando una usuaria
o admin borra una publicación manualmente, o cuando el bot detecta vía lazy
check que un post ya no existe en Telegram, marcamos `deleted_at` en lugar
de borrar la fila (para preservar el histórico para stats/logs).

Todas las queries que afectan a las reglas ignoran posts con `deleted_at`.
"""
import logging
from datetime import datetime, timedelta
from typing import Optional

from db import get_db

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
) -> int:
    """Registra una publicación válida. Devuelve el id de la fila."""
    async with get_db() as db:
        cur = await db.execute(
            """INSERT INTO posts (chat_id, user_id, username, message_id,
               media_group_id, phash, video_size, video_duration)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (chat_id, user_id, username, message_id, media_group_id,
             phash, video_size, video_duration),
        )
        await db.commit()
        return cur.lastrowid or 0


async def get_last_post_time(chat_id: int, user_id: int) -> Optional[datetime]:
    """Hora de la última publicación NO BORRADA del usuario."""
    async with get_db() as db:
        cur = await db.execute(
            "SELECT MAX(posted_at) AS last FROM posts "
            "WHERE chat_id = ? AND user_id = ? AND deleted_at IS NULL",
            (chat_id, user_id),
        )
        row = await cur.fetchone()
        if row is None or row["last"] is None:
            return None
        return datetime.fromisoformat(row["last"])


async def get_last_post(chat_id: int, user_id: int) -> Optional[dict]:
    """Devuelve la última publicación NO BORRADA del usuario (con message_id)."""
    async with get_db() as db:
        cur = await db.execute(
            "SELECT * FROM posts "
            "WHERE chat_id = ? AND user_id = ? AND deleted_at IS NULL "
            "ORDER BY posted_at DESC LIMIT 1",
            (chat_id, user_id),
        )
        row = await cur.fetchone()
        return dict(row) if row else None


async def get_recent_posts(
    chat_id: int, user_id: int, limit: int = 5,
) -> list[dict]:
    """Las N últimas publicaciones no borradas del usuario."""
    async with get_db() as db:
        cur = await db.execute(
            "SELECT * FROM posts "
            "WHERE chat_id = ? AND user_id = ? AND deleted_at IS NULL "
            "ORDER BY posted_at DESC LIMIT ?",
            (chat_id, user_id, limit),
        )
        return [dict(r) for r in await cur.fetchall()]


async def count_distinct_users_after(
    chat_id: int, since: datetime, exclude_user_id: int
) -> int:
    """Cuántos usuarios DISTINTOS han publicado después de `since`."""
    async with get_db() as db:
        cur = await db.execute(
            "SELECT COUNT(DISTINCT user_id) AS n FROM posts "
            "WHERE chat_id = ? AND posted_at > ? AND user_id != ? "
            "AND deleted_at IS NULL",
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
    """Foto duplicada (Hamming <= threshold) en las últimas `hours` horas, no borrada."""
    since = datetime.utcnow() - timedelta(hours=hours)
    async with get_db() as db:
        cur = await db.execute(
            "SELECT id, user_id, phash, posted_at FROM posts "
            "WHERE chat_id = ? AND phash IS NOT NULL AND video_size IS NULL "
            "AND posted_at > ? AND deleted_at IS NULL",
            (chat_id, since.isoformat(sep=" ")),
        )
        rows = await cur.fetchall()
    target = int(phash_hex, 16)
    for row in rows:
        try:
            stored = int(row["phash"], 16)
        except (ValueError, TypeError):
            continue
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
    """Vídeo duplicado: mismo tamaño + duración + primer frame similar, no borrado."""
    since = datetime.utcnow() - timedelta(hours=hours)
    async with get_db() as db:
        cur = await db.execute(
            "SELECT id, user_id, phash, posted_at FROM posts "
            "WHERE chat_id = ? AND video_size = ? AND video_duration = ? "
            "AND posted_at > ? AND deleted_at IS NULL",
            (chat_id, video_size, video_duration, since.isoformat(sep=" ")),
        )
        rows = await cur.fetchall()
    if not rows:
        return None
    if not phash_hex:
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
    """Marca como borradas TODAS las publicaciones recientes del chat."""
    now = datetime.utcnow().isoformat(sep=" ")
    async with get_db() as db:
        cur = await db.execute(
            "UPDATE posts SET deleted_at = ? "
            "WHERE chat_id = ? AND deleted_at IS NULL",
            (now, chat_id),
        )
        await db.commit()
        return cur.rowcount


async def cleanup_old(days: int) -> int:
    """Borra físicamente publicaciones más antiguas que `days` días."""
    cutoff = datetime.utcnow() - timedelta(days=days)
    async with get_db() as db:
        cur = await db.execute(
            "DELETE FROM posts WHERE posted_at < ?",
            (cutoff.isoformat(sep=" "),),
        )
        await db.commit()
        return cur.rowcount


async def list_recent_posters(chat_id: int, hours: int = 24) -> list[dict]:
    """Usuarias que han publicado en las últimas N horas (no borradas)."""
    since = datetime.utcnow() - timedelta(hours=hours)
    async with get_db() as db:
        cur = await db.execute(
            "SELECT user_id, username, COUNT(*) AS n_posts, MAX(posted_at) AS last "
            "FROM posts WHERE chat_id = ? AND posted_at > ? AND deleted_at IS NULL "
            "GROUP BY user_id ORDER BY n_posts DESC",
            (chat_id, since.isoformat(sep=" ")),
        )
        return [dict(r) for r in await cur.fetchall()]


async def mark_deleted_by_message_id(chat_id: int, message_id: int) -> int:
    """
    Marca como borrado el post con ese chat_id+message_id.
    Para álbumes, marca TODOS los posts con el mismo media_group_id.
    Devuelve cuántas filas se actualizaron (0 si no había nada).
    """
    now = datetime.utcnow().isoformat(sep=" ")
    async with get_db() as db:
        # Buscar el post
        cur = await db.execute(
            "SELECT id, media_group_id FROM posts "
            "WHERE chat_id = ? AND message_id = ? AND deleted_at IS NULL",
            (chat_id, message_id),
        )
        row = await cur.fetchone()
        if not row:
            return 0
        # Si forma parte de un álbum, anular todo el álbum
        if row["media_group_id"]:
            cur = await db.execute(
                "UPDATE posts SET deleted_at = ? "
                "WHERE chat_id = ? AND media_group_id = ? AND deleted_at IS NULL",
                (now, chat_id, row["media_group_id"]),
            )
        else:
            cur = await db.execute(
                "UPDATE posts SET deleted_at = ? WHERE id = ?",
                (now, row["id"]),
            )
        await db.commit()
        return cur.rowcount


async def mark_deleted_by_id(post_id: int) -> bool:
    """Marca como borrado un post por su id de BD."""
    now = datetime.utcnow().isoformat(sep=" ")
    async with get_db() as db:
        cur = await db.execute(
            "UPDATE posts SET deleted_at = ? WHERE id = ? AND deleted_at IS NULL",
            (now, post_id),
        )
        await db.commit()
        return cur.rowcount > 0


async def mark_user_last_deleted(chat_id: int, user_id: int) -> Optional[dict]:
    """
    Marca como borrada la última publicación NO BORRADA del usuario.
    Devuelve el post anulado o None si no había.
    Usada por /cancel.
    """
    last = await get_last_post(chat_id, user_id)
    if not last:
        return None
    # Si es álbum, anular todo el álbum
    if last.get("media_group_id"):
        await mark_deleted_by_message_id(chat_id, last["message_id"])
    else:
        await mark_deleted_by_id(last["id"])
    return last
