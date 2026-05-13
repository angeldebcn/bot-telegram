"""
Aplicación de castigos cuando se incumple una regla.

Cada regla (cola, cooldown, antidup) tiene su propio tipo de castigo
configurable en la BD. Aquí está la implementación de los 6 tipos.
"""
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import ChatPermissions, Message

from config import RULE_LABELS
from database import warns as warns_db
from database.config_db import get_config
from database.stats import log_action

logger = logging.getLogger(__name__)


# Permisos de "silencio total" para mute
MUTED_PERMISSIONS = ChatPermissions(
    can_send_messages=False,
    can_send_audios=False,
    can_send_documents=False,
    can_send_photos=False,
    can_send_videos=False,
    can_send_video_notes=False,
    can_send_voice_notes=False,
    can_send_polls=False,
    can_send_other_messages=False,
    can_add_web_page_previews=False,
    can_change_info=False,
    can_invite_users=False,
    can_pin_messages=False,
    can_manage_topics=False,
)


async def delete_messages_safe(bot: Bot, chat_id: int, message_ids: list[int]) -> int:
    """Borra una lista de mensajes ignorando errores. Devuelve cuántos borró."""
    deleted = 0
    for mid in message_ids:
        try:
            await bot.delete_message(chat_id, mid)
            deleted += 1
        except (TelegramBadRequest, TelegramForbiddenError) as e:
            logger.debug("No se pudo borrar mensaje %s: %s", mid, e)
    return deleted


async def _send_autodestruct_notice(
    bot: Bot, chat_id: int, text: str, seconds: int
) -> None:
    """
    Envía un aviso. Si seconds > 0, se autodestruye tras esos segundos.
    Si seconds == 0, el aviso se queda PERMANENTE (no se borra).
    """
    try:
        msg = await bot.send_message(chat_id, text, disable_notification=True)
    except (TelegramBadRequest, TelegramForbiddenError):
        return

    if seconds <= 0:
        # Aviso permanente: no programar borrado
        return

    async def _delete_later() -> None:
        await asyncio.sleep(seconds)
        try:
            await bot.delete_message(chat_id, msg.message_id)
        except (TelegramBadRequest, TelegramForbiddenError):
            pass

    asyncio.create_task(_delete_later())


def _mention(user_id: int, username: Optional[str]) -> str:
    """Mención HTML segura para Telegram."""
    if username:
        return f"@{username}"
    return f'<a href="tg://user?id={user_id}">usuaria</a>'


def _violation_text(rule: str, mention: str, extra: str = "") -> str:
    """Texto humano explicando por qué se borró."""
    base = {
        "queue": f"{mention}, te toca esperar a que publiquen otras chicas antes de tu próximo turno.",
        "cooldown": f"{mention}, debes esperar antes de subir otra foto/vídeo.",
        "antidup": f"{mention}, esta foto/vídeo ya se publicó hace poco en el grupo.",
    }
    text = base.get(rule, f"{mention}, mensaje borrado.")
    if extra:
        text += f" {extra}"
    return text


async def apply_punishment(
    bot: Bot,
    chat_id: int,
    user_id: int,
    username: Optional[str],
    message_ids: list[int],
    rule: str,
    extra_info: str = "",
) -> None:
    """
    Aplica el castigo configurado para una regla.
    `rule` es 'queue', 'cooldown' o 'antidup'.
    `message_ids` es la lista de mensajes a borrar (1 para foto/vídeo suelto,
    N para álbum).
    """
    cfg = await get_config(chat_id)
    punishment = int(cfg[f"punishment_{rule}"])
    notice_seconds = int(cfg[f"notice_{rule}_seconds"])
    mute_seconds = int(cfg[f"mute_{rule}_seconds"])

    # 1. Siempre se borran los mensajes infractores
    n_deleted = await delete_messages_safe(bot, chat_id, message_ids)
    await log_action(
        chat_id, "delete", user_id=user_id, username=username, rule=rule,
        details=f"borrados={n_deleted}",
    )

    mention = _mention(user_id, username)
    rule_label = RULE_LABELS.get(rule, rule)

    # 2. Acción adicional según tipo de castigo
    if punishment == 1:
        # Solo borrar, nada más
        return

    if punishment == 2:
        # Aviso autodestructivo
        text = _violation_text(rule, mention, extra_info)
        await _send_autodestruct_notice(bot, chat_id, text, notice_seconds)
        return

    if punishment == 3:
        # Warn acumulativo
        await _apply_warn(
            bot, chat_id, user_id, username,
            reason=f"Infracción {rule_label}", rule=rule,
        )
        return

    if punishment == 4:
        # Mute temporal
        await _apply_mute(bot, chat_id, user_id, username, mute_seconds, rule)
        return

    if punishment == 5:
        # Kick (ban + unban)
        await _apply_kick(bot, chat_id, user_id, username, rule)
        return

    if punishment == 6:
        # Ban permanente
        await _apply_ban(bot, chat_id, user_id, username, rule)
        return


async def _apply_warn(
    bot: Bot,
    chat_id: int,
    user_id: int,
    username: Optional[str],
    reason: str,
    rule: str,
) -> None:
    """Añade un warn. Si se llega al límite, aplica la acción final."""
    cfg = await get_config(chat_id)
    total = await warns_db.add_warn(
        chat_id, user_id, username, reason, int(cfg["warn_expiration_days"])
    )
    await log_action(
        chat_id, "warn", user_id=user_id, username=username, rule=rule,
        details=f"total={total}",
    )

    mention = _mention(user_id, username)
    limit = int(cfg["warn_limit"])

    if total < limit:
        text = (
            f"⚠️ {mention} ha recibido una advertencia ({total}/{limit}).\n"
            f"Motivo: {reason}"
        )
        try:
            await bot.send_message(chat_id, text)
        except (TelegramBadRequest, TelegramForbiddenError):
            pass
        return

    # Se alcanzó el límite → acción final
    final = int(cfg["warn_final_action"])
    final_mute = int(cfg["warn_final_mute_seconds"])
    await warns_db.reset_warns(chat_id, user_id)
    text = (
        f"🚨 {mention} ha alcanzado el límite de {limit} advertencias. "
    )
    if final == 4:
        await _apply_mute(bot, chat_id, user_id, username, final_mute, rule="warn_limit")
        text += "Silenciada."
    elif final == 5:
        await _apply_kick(bot, chat_id, user_id, username, rule="warn_limit")
        text += "Expulsada."
    elif final == 6:
        await _apply_ban(bot, chat_id, user_id, username, rule="warn_limit")
        text += "Baneada."
    try:
        await bot.send_message(chat_id, text)
    except (TelegramBadRequest, TelegramForbiddenError):
        pass


async def _apply_mute(
    bot: Bot, chat_id: int, user_id: int, username: Optional[str], seconds: int, rule: str
) -> None:
    until = datetime.utcnow() + timedelta(seconds=seconds)
    try:
        await bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=user_id,
            permissions=MUTED_PERMISSIONS,
            until_date=until,
        )
        await log_action(
            chat_id, "mute", user_id=user_id, username=username, rule=rule,
            details=f"seconds={seconds}",
        )
    except (TelegramBadRequest, TelegramForbiddenError) as e:
        logger.warning("No se pudo mutear a %s en %s: %s", user_id, chat_id, e)


async def _apply_kick(
    bot: Bot, chat_id: int, user_id: int, username: Optional[str], rule: str
) -> None:
    try:
        await bot.ban_chat_member(chat_id, user_id)
        # Unban inmediato para que pueda volver con un link
        await bot.unban_chat_member(chat_id, user_id, only_if_banned=True)
        await log_action(chat_id, "kick", user_id=user_id, username=username, rule=rule)
    except (TelegramBadRequest, TelegramForbiddenError) as e:
        logger.warning("No se pudo kickear a %s en %s: %s", user_id, chat_id, e)


async def _apply_ban(
    bot: Bot, chat_id: int, user_id: int, username: Optional[str], rule: str
) -> None:
    try:
        await bot.ban_chat_member(chat_id, user_id)
        await log_action(chat_id, "ban", user_id=user_id, username=username, rule=rule)
    except (TelegramBadRequest, TelegramForbiddenError) as e:
        logger.warning("No se pudo banear a %s en %s: %s", user_id, chat_id, e)


async def manual_warn(
    bot: Bot, chat_id: int, user_id: int, username: Optional[str], reason: str
) -> int:
    """Warn manual desde /warn. Devuelve total tras añadir."""
    cfg = await get_config(chat_id)
    total = await warns_db.add_warn(
        chat_id, user_id, username, reason or "manual",
        int(cfg["warn_expiration_days"]),
    )
    await log_action(
        chat_id, "warn", user_id=user_id, username=username, rule="manual",
        details=f"total={total}",
    )
    limit = int(cfg["warn_limit"])
    if total >= limit:
        final = int(cfg["warn_final_action"])
        final_mute = int(cfg["warn_final_mute_seconds"])
        await warns_db.reset_warns(chat_id, user_id)
        if final == 4:
            await _apply_mute(bot, chat_id, user_id, username, final_mute, "warn_limit")
        elif final == 5:
            await _apply_kick(bot, chat_id, user_id, username, "warn_limit")
        elif final == 6:
            await _apply_ban(bot, chat_id, user_id, username, "warn_limit")
    return total
