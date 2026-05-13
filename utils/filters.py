"""
Detección del tipo de un mensaje y aplicación de filtros de contenido.

El filtro se ejecuta ANTES de las 3 reglas. Si una foto tiene filter_photo=1
(Borrar), se borra inmediatamente y no llega al sistema de cola/cooldown/antidup.
Si filter_photo=0 (Off), la foto pasa al sistema de reglas como siempre.

Los demás tipos (sticker, gif, etc.) solo tienen filtro: nunca aplican las 3 reglas.
"""
import logging
import re
from typing import Optional

from aiogram import Bot
from aiogram.types import Message

from utils.punishment import (
    _apply_ban,
    _apply_kick,
    _apply_mute,
    _apply_warn,
    delete_messages_safe,
)

logger = logging.getLogger(__name__)


# Umbral de mayúsculas: % del texto que tienen que ser MAYÚSCULAS para considerarlo "shouting"
CAPS_RATIO_THRESHOLD = 0.7
CAPS_MIN_LENGTH = 10  # mensajes cortos no cuentan

# Regex simple para detectar URLs
_URL_RE = re.compile(
    r"(https?://|www\.|t\.me/|telegram\.me/|tg://)\S+", re.IGNORECASE
)


def detect_message_type(message: Message) -> Optional[str]:
    """
    Devuelve la clave de filtro asociada al mensaje, o None si no aplica.
    Devuelve la PRIMERA categoría que matchea (orden de precedencia).

    ⚠️ ORDEN CRÍTICO: primero detectamos el TIPO DE CONTENIDO real (foto,
    vídeo, sticker, etc). Solo si no hay contenido detectable consideramos
    meta-flags como "forwarded" o "via_bot".

    Una foto REENVIADA sigue siendo una foto. Si la detectamos como
    "forwarded" en lugar de "photo", el sistema count_X la ignoraría y la
    chica podría spamear reenviando contenido sin pasar por la cola.
    """
    # === 1. CONTENIDO MULTIMEDIA (prioridad máxima) ===
    if message.photo:
        return "filter_photo"
    if message.video:
        return "filter_video"
    if message.animation:
        return "filter_gif"
    if message.sticker:
        st = message.sticker
        if getattr(st, "is_animated", False) or getattr(st, "is_video", False):
            return "filter_sticker_animated"
        return "filter_sticker"
    if message.video_note:
        return "filter_video_note"
    if message.voice:
        return "filter_voice"
    if message.audio:
        return "filter_audio"
    if message.document:
        # Algunos clientes mandan vídeos como documento. Lo tratamos como vídeo
        # si el mime es de tipo video/image.
        mime = (message.document.mime_type or "").lower()
        if mime.startswith("video/"):
            return "filter_video"
        if mime.startswith("image/gif"):
            return "filter_gif"
        if mime.startswith("image/"):
            return "filter_photo"
        return "filter_document"
    if message.poll:
        return "filter_poll"
    if message.contact:
        return "filter_contact"
    if message.location or message.venue:
        return "filter_location"
    if message.giveaway or getattr(message, "giveaway_winners", None):
        return "filter_giveaway"

    # === 2. META-FLAGS (solo si NO había contenido detectable) ===
    # Estos solo aplican a mensajes que no son multimedia (p.ej. texto reenviado)
    if message.forward_origin or message.forward_from or message.forward_from_chat:
        return "filter_forwarded"
    if message.via_bot:
        return "filter_via_bot"

    # === 3. TEXTO ===
    if message.text:
        if _URL_RE.search(message.text):
            return "filter_links"
        if _is_caps_text(message.text):
            return "filter_caps"
    elif message.caption:
        if _URL_RE.search(message.caption):
            return "filter_links"
    return None


def _is_caps_text(text: str) -> bool:
    """True si el texto es mayoritariamente MAYÚSCULAS."""
    text = text.strip()
    if len(text) < CAPS_MIN_LENGTH:
        return False
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return False
    upper = sum(1 for c in letters if c.isupper())
    ratio = upper / len(letters)
    return ratio >= CAPS_RATIO_THRESHOLD


async def apply_filter_action(
    bot: Bot,
    chat_id: int,
    user_id: int,
    username: Optional[str],
    message_ids: list[int],
    action: int,
    filter_label: str,
) -> None:
    """
    Aplica una acción de filtro (1=Borrar, 2=Warn, 3=Mute, 4=Kick, 5=Ban).
    action=0 (Off) no debería llegar aquí.
    """
    from database.stats import log_action
    from database.config_db import get_config

    if action == 0:
        return

    # Siempre se borra el mensaje
    await delete_messages_safe(bot, chat_id, message_ids)
    await log_action(
        chat_id, "delete", user_id=user_id, username=username, rule="filter",
        details=filter_label,
    )

    if action == 1:
        # Solo borrar
        return

    if action == 2:
        await _apply_warn(
            bot, chat_id, user_id, username,
            reason=f"Filtro: {filter_label}", rule="filter",
        )
        return

    if action == 3:
        cfg = await get_config(chat_id)
        mute_seconds = int(cfg.get("mute_queue_seconds", 3600))
        await _apply_mute(bot, chat_id, user_id, username, mute_seconds, "filter")
        return

    if action == 4:
        await _apply_kick(bot, chat_id, user_id, username, "filter")
        return

    if action == 5:
        await _apply_ban(bot, chat_id, user_id, username, "filter")
        return
