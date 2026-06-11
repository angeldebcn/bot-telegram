"""Utilidades para comprobar permisos: admin del grupo, alianza, etc."""
import logging
from typing import Optional

from aiogram import Bot
from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramBadRequest

from alianzas import is_alianza

logger = logging.getLogger(__name__)


# Cache simple en memoria: (chat_id, user_id) -> (es_admin, timestamp)
_admin_cache: dict[tuple[int, int], tuple[bool, float]] = {}
_CACHE_TTL = 300  # 5 minutos


async def is_admin(bot: Bot, chat_id: int, user_id: int) -> bool:
    """Comprueba si user_id es admin/creador del chat. Con cache de 5 min."""
    import time
    now = time.time()
    cached = _admin_cache.get((chat_id, user_id))
    if cached and (now - cached[1] < _CACHE_TTL):
        return cached[0]
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        result = member.status in (
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.CREATOR,
        )
    except TelegramBadRequest as e:
        logger.warning("No se pudo verificar admin %s/%s: %s", chat_id, user_id, e)
        result = False
    _admin_cache[(chat_id, user_id)] = (result, now)
    return result


def invalidate_admin_cache(chat_id: Optional[int] = None) -> None:
    """Invalida el cache de admins (todo o solo un chat)."""
    if chat_id is None:
        _admin_cache.clear()
    else:
        keys = [k for k in _admin_cache if k[0] == chat_id]
        for k in keys:
            _admin_cache.pop(k, None)


async def can_delete_messages(bot: Bot, chat_id: int, user_id: int) -> bool:
    """
    True si el usuario es CREADOR del grupo, o es ADMIN con permiso explícito
    para borrar mensajes. Se usa para comandos como /delete que requieren ese
    permiso concreto, no solo ser admin a secas.
    """
    try:
        member = await bot.get_chat_member(chat_id, user_id)
    except TelegramBadRequest as e:
        logger.warning("No se pudo verificar permisos %s/%s: %s", chat_id, user_id, e)
        return False
    if member.status == ChatMemberStatus.CREATOR:
        return True
    if member.status == ChatMemberStatus.ADMINISTRATOR:
        # En aiogram, el permiso está en can_delete_messages
        return bool(getattr(member, "can_delete_messages", False))
    return False


async def is_exempt(bot: Bot, chat_id: int, user_id: int) -> bool:
    """
    True si la usuaria está exenta de las 3 reglas:
    - Es admin del grupo, O
    - Está en alianzas, O
    - Es un bot (is_bot se chequea fuera)
    """
    if await is_alianza(chat_id, user_id):
        return True
    if await is_admin(bot, chat_id, user_id):
        return True
    return False


async def list_admin_chats_for_user(bot: Bot, user_id: int, all_chats: list[dict]) -> list[dict]:
    """
    Dado un user_id y la lista de chats del bot, devuelve solo aquellos
    donde el usuario es admin. Usado para el selector de grupo en privado.
    """
    result = []
    for chat in all_chats:
        try:
            if await is_admin(bot, chat["chat_id"], user_id):
                result.append(chat)
        except Exception as e:
            logger.debug("No se pudo verificar admin en %s: %s", chat["chat_id"], e)
    return result
