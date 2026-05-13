"""Helpers de licencia: comprobación rápida, formato de estado, etc."""
import logging
from datetime import datetime
from typing import Optional

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

from config import LICENSING_ENABLED, OWNER_USER_ID, OWNER_USERNAME, SUBSCRIPTION_PRICE_EUR
from database import licenses as licenses_db

logger = logging.getLogger(__name__)


STATUS_LABELS = {
    "owner": ("👑", "Propietario", "Gratis para siempre"),
    "active": ("✅", "Activa", "Suscripción al día"),
    "pending": ("⏳", "Pendiente", "Esperando pago"),
    "expired": ("❌", "Expirada", "Suscripción caducada"),
    "banned": ("🚫", "Vetada", "Bloqueada por el owner"),
}


async def chat_is_allowed(chat_id: int) -> bool:
    """
    True si el bot debe funcionar en este chat.
    Si LICENSING_ENABLED=False, siempre True (modo libre).
    """
    if not LICENSING_ENABLED:
        return True
    return await licenses_db.is_chat_allowed(chat_id)


def is_owner(user_id: Optional[int]) -> bool:
    """True si el user_id es el owner del bot."""
    if user_id is None or OWNER_USER_ID is None:
        return False
    return int(user_id) == int(OWNER_USER_ID)


def format_license_status(lic: dict) -> str:
    """Devuelve un string bonito con el estado de la licencia."""
    if not lic:
        return "⏳ <b>Pendiente</b> · Sin licencia"
    status = lic.get("status", "pending")
    emoji, label, desc = STATUS_LABELS.get(status, ("❓", "Desconocido", ""))
    text = f"{emoji} <b>{label}</b>"
    if status == "active":
        exp = lic.get("expires_at")
        if exp:
            try:
                exp_dt = datetime.fromisoformat(exp)
                delta = exp_dt - datetime.utcnow()
                days_left = delta.days
                if days_left < 0:
                    text += " · ⚠️ Caducada"
                elif days_left == 0:
                    text += " · Caduca <b>hoy</b>"
                else:
                    text += f" · {days_left} días restantes"
            except ValueError:
                text += " · fecha inválida"
        else:
            text += " · ♾️ De por vida"
    elif status == "expired":
        text += f" · {desc}"
    elif status == "pending":
        text += f" · {desc}"
    return text


def subscription_pitch(chat_title: Optional[str] = None) -> str:
    """Texto bonito para grupos pending. Lo ve la gente que añade el bot."""
    chat_part = f" en <b>{chat_title}</b>" if chat_title else ""
    return (
        "🤖 <b>Bot de Moderación Premium</b>\n\n"
        "Hola 👋 Acabas de añadirme a tu grupo. Para activarme"
        f"{chat_part} necesitas una suscripción.\n\n"
        f"💎 <b>{SUBSCRIPTION_PRICE_EUR:.2f} €/mes</b> por grupo\n"
        f"📞 Contacto: @{OWNER_USERNAME}\n"
        f"💳 Pago: Revolut (te paso datos al contactar)\n\n"
        "⚠️ Mientras tanto el bot está en pausa. <b>No aplicaré ninguna regla.</b>\n\n"
        f"Escríbeme a @{OWNER_USERNAME} para activar."
    )


def expiring_soon_warning(days_left: int) -> str:
    if days_left <= 0:
        return (
            f"⚠️ <b>Tu suscripción ha caducado.</b>\n\n"
            f"El bot está en pausa. Renueva en @{OWNER_USERNAME}."
        )
    return (
        f"⚠️ <b>Tu suscripción caduca en {days_left} día"
        f"{'s' if days_left != 1 else ''}</b>.\n\n"
        f"Para renovar contacta @{OWNER_USERNAME}."
    )


async def notify_owner(bot: Bot, text: str, reply_markup=None) -> None:
    """Envía un mensaje privado al owner. Silencioso si falla."""
    if OWNER_USER_ID is None:
        return
    try:
        await bot.send_message(
            OWNER_USER_ID, text, reply_markup=reply_markup,
            disable_web_page_preview=True,
        )
    except (TelegramBadRequest, TelegramForbiddenError) as e:
        logger.warning("No se pudo notificar al owner: %s", e)
