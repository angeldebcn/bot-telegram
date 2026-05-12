"""Tareas programadas: backups diarios, limpieza de BD, warns expirados."""
import logging
import shutil
from datetime import datetime
from pathlib import Path

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import BACKUPS_DIR, DB_PATH
from database import posts as posts_db
from database import warns as warns_db
from database.stats import cleanup_old_logs
from database.db import get_db

logger = logging.getLogger(__name__)


async def daily_backup() -> None:
    """Copia bot.db a backups/ con timestamp."""
    if not DB_PATH.exists():
        return
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    dest = BACKUPS_DIR / f"bot_{ts}.db"
    try:
        shutil.copy2(DB_PATH, dest)
        logger.info("📦 Backup creado: %s", dest)
        # Mantener solo los últimos 14 backups
        backups = sorted(BACKUPS_DIR.glob("bot_*.db"), key=lambda p: p.stat().st_mtime)
        for old in backups[:-14]:
            try:
                old.unlink()
            except OSError:
                pass
    except OSError as e:
        logger.warning("Fallo creando backup: %s", e)


async def autoclean_db() -> None:
    """Limpia datos antiguos según la config de cada chat (autoclean_days)."""
    async with get_db() as db:
        cur = await db.execute("SELECT chat_id, autoclean_days FROM chat_config")
        rows = await cur.fetchall()
    total_posts = 0
    for row in rows:
        days = int(row["autoclean_days"] or 30)
        if days <= 0:
            continue
        # Limpieza por chat individualmente
        from datetime import timedelta
        cutoff = datetime.utcnow() - timedelta(days=days)
        async with get_db() as db:
            cur = await db.execute(
                "DELETE FROM posts WHERE chat_id = ? AND posted_at < ?",
                (row["chat_id"], cutoff.isoformat(sep=" ")),
            )
            await db.commit()
            total_posts += cur.rowcount
    # Logs antiguos: globalmente 60 días
    n_logs = await cleanup_old_logs(60)
    # Warns expirados
    n_warns = await warns_db.cleanup_expired_warns()
    if total_posts or n_logs or n_warns:
        logger.info(
            "🧹 Auto-limpieza: posts=%s logs=%s warns=%s",
            total_posts, n_logs, n_warns,
        )


def setup_scheduler(bot: Bot) -> AsyncIOScheduler:
    """Configura y devuelve el scheduler (sin arrancarlo)."""
    scheduler = AsyncIOScheduler(timezone="UTC")
    # Backup diario a las 03:00 UTC
    scheduler.add_job(daily_backup, "cron", hour=3, minute=0, id="daily_backup")
    # Limpieza cada 6 horas
    scheduler.add_job(autoclean_db, "interval", hours=6, id="autoclean")
    return scheduler
