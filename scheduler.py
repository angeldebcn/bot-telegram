"""Tareas programadas: backups, limpieza, warns expirados, licencias."""
import logging
import shutil
from datetime import datetime, timedelta
from pathlib import Path

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import BACKUPS_DIR, DB_PATH, OWNER_USERNAME
import licenses as licenses_db
import posts as posts_db
import warns as warns_db
from db import get_db
from stats import cleanup_old_logs
from license_helpers import expiring_soon_warning, notify_owner

logger = logging.getLogger(__name__)


async def daily_backup() -> None:
    if not DB_PATH.exists():
        return
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    dest = BACKUPS_DIR / f"bot_{ts}.db"
    try:
        shutil.copy2(DB_PATH, dest)
        logger.info("📦 Backup creado: %s", dest)
        backups = sorted(BACKUPS_DIR.glob("bot_*.db"), key=lambda p: p.stat().st_mtime)
        for old in backups[:-14]:
            try:
                old.unlink()
            except OSError:
                pass
    except OSError as e:
        logger.warning("Fallo creando backup: %s", e)


async def autoclean_db() -> None:
    async with get_db() as db:
        cur = await db.execute("SELECT chat_id, autoclean_days FROM chat_config")
        rows = await cur.fetchall()
    total_posts = 0
    for row in rows:
        days = int(row["autoclean_days"] or 0)
        if days <= 0:
            continue
        cutoff = datetime.utcnow() - timedelta(days=days)
        async with get_db() as db:
            cur = await db.execute(
                "DELETE FROM posts WHERE chat_id = ? AND posted_at < ?",
                (row["chat_id"], cutoff.isoformat(sep=" ")),
            )
            await db.commit()
            total_posts += cur.rowcount
    n_logs = await cleanup_old_logs(60)
    n_warns = await warns_db.cleanup_expired_warns()
    if total_posts or n_logs or n_warns:
        logger.info(
            "🧹 Auto-limpieza: posts=%s logs=%s warns=%s",
            total_posts, n_logs, n_warns,
        )


async def licenses_daily(bot: Bot) -> None:
    """
    Job diario:
    - Marca como 'expired' las licencias active caducadas.
    - Avisa al grupo y al owner si una licencia va a caducar en menos de 3 días.
    """
    # 1. Marcar expiradas
    n_expired = await licenses_db.mark_expired_licenses()
    if n_expired:
        logger.info("⏰ %s licencias marcadas como expiradas", n_expired)

    # 2. Avisar a los que están por caducar (3 días o menos)
    expiring = await licenses_db.get_expiring_soon(days=3)
    for lic in expiring:
        chat_id = lic["chat_id"]
        try:
            exp = datetime.fromisoformat(lic["expires_at"])
            days_left = (exp - datetime.utcnow()).days
        except (ValueError, TypeError):
            days_left = 0
        # Avisar al grupo
        try:
            await bot.send_message(chat_id, expiring_soon_warning(max(0, days_left)))
        except (TelegramBadRequest, TelegramForbiddenError) as e:
            logger.warning("No se pudo avisar a %s: %s", chat_id, e)
        # Avisar al owner
        title = lic.get("chat_title") or f"Chat {chat_id}"
        from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔁 Renovar 30 días",
                                  callback_data=f"licext:{chat_id}:30")],
            [InlineKeyboardButton(text="🔁 Renovar 90 días",
                                  callback_data=f"licext:{chat_id}:90")],
            [InlineKeyboardButton(text="📋 Ver detalles",
                                  callback_data=f"licinfo:{chat_id}")],
        ])
        await notify_owner(
            bot,
            (
                f"⏰ <b>Suscripción próxima a expirar</b>\n\n"
                f"📍 <b>{title}</b>\n"
                f"🆔 <code>{chat_id}</code>\n"
                f"📅 Quedan: <b>{max(0, days_left)} días</b>"
            ),
            reply_markup=kb,
        )
        await licenses_db.mark_expiry_warned(chat_id)


def setup_scheduler(bot: Bot) -> AsyncIOScheduler:
    """Configura y devuelve el scheduler (sin arrancarlo)."""
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(daily_backup, "cron", hour=3, minute=0, id="daily_backup")
    scheduler.add_job(autoclean_db, "interval", hours=6, id="autoclean")
    scheduler.add_job(
        licenses_daily, "cron", hour=9, minute=0, id="licenses_daily",
        args=[bot],
    )
    return scheduler
