"""Comando /menu con check de licencia + selector de grupo en privado."""
import logging
from typing import Any

from aiogram import Bot, Router
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import Message

from config import OWNER_USERNAME, PUNISHMENT_TYPES
from config_db import get_config
from stats import list_bot_chats
from builders import group_selector, main_menu
import es
from helpers import format_minutes
from license_helpers import chat_is_allowed
from permissions import is_admin

logger = logging.getLogger(__name__)
router = Router(name="menu")


@router.message(Command("menu", "settings", "config"))
async def cmd_menu(message: Message, bot: Bot) -> None:
    """Abre el menú. En privado lista grupos; en grupo abre el menú directo."""
    if message.chat.type == ChatType.PRIVATE:
        await _menu_private(message, bot)
        return
    await _menu_group(message, bot)


async def _menu_group(message: Message, bot: Bot) -> None:
    chat_id = message.chat.id
    cfg = await get_config(chat_id)

    if int(cfg.get("admin_only_menu", 1)):
        if not message.from_user or not await is_admin(bot, chat_id, message.from_user.id):
            await message.reply(es.ERR_NOT_ADMIN)
            return

    if not await chat_is_allowed(chat_id):
        await message.reply(es.ERR_NOT_LICENSED)
        return

    text = await render_main_menu_text(bot, chat_id, cfg)
    await message.reply(text, reply_markup=main_menu(cfg))


async def _menu_private(message: Message, bot: Bot) -> None:
    chats = await list_bot_chats()
    if not chats:
        await message.reply(es.NO_GROUPS_PRIVATE.format(owner=OWNER_USERNAME))
        return
    # Filtrar a los grupos donde el usuario es admin
    user_id = message.from_user.id
    accessible = []
    for chat in chats:
        try:
            if await is_admin(bot, chat["chat_id"], user_id):
                accessible.append(chat)
        except TelegramBadRequest:
            continue
    if not accessible:
        await message.reply(es.NOT_ADMIN_ANYWHERE.format(owner=OWNER_USERNAME))
        return
    await message.answer(es.SELECT_GROUP, reply_markup=group_selector(accessible))


async def render_main_menu_text(bot: Bot, chat_id: int, cfg: dict[str, Any]) -> str:
    """Texto resumen para el menú principal."""
    qen = bool(int(cfg.get("queue_enabled", 1)))
    cden = bool(int(cfg.get("cooldown_enabled", 1)))
    aden = bool(int(cfg.get("antidup_enabled", 1)))

    queue_str = f"<b>{cfg['queue_size']}</b> chicas" if qen else "<i>desactivada</i>"
    cd_str = f"<b>{format_minutes(int(cfg['cooldown_minutes']))}</b>" if cden else "<i>desactivado</i>"
    ad_str = f"<b>{cfg['antidup_hours']}h</b>" if aden else "<i>desactivado</i>"

    locked_line = ""
    if int(cfg.get("locked", 0)):
        locked_line = "🔕 <b>BOT EN PAUSA</b>\n\n"

    return (
        f"{locked_line}"
        f"⚙️ <b>Configuración del grupo</b>\n\n"
        f"🔄 Cola: {queue_str}\n"
        f"⏱️ Cooldown: {cd_str}\n"
        f"🖼️ Anti-duplicado: {ad_str}\n\n"
        f"⚖️ Castigos:\n"
        f"  • Cola: {PUNISHMENT_TYPES[int(cfg['punishment_queue'])][0]} "
        f"{PUNISHMENT_TYPES[int(cfg['punishment_queue'])][1]}\n"
        f"  • Cooldown: {PUNISHMENT_TYPES[int(cfg['punishment_cooldown'])][0]} "
        f"{PUNISHMENT_TYPES[int(cfg['punishment_cooldown'])][1]}\n"
        f"  • Duplicado: {PUNISHMENT_TYPES[int(cfg['punishment_antidup'])][0]} "
        f"{PUNISHMENT_TYPES[int(cfg['punishment_antidup'])][1]}\n\n"
        f"💡 Pulsa cualquier opción para configurar."
    )
