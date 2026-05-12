"""Handler del comando /menu y rendering del menú principal."""
import logging
from typing import Optional

from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command
from aiogram.types import Message

from config import PUNISHMENT_TYPES, RULE_LABELS
from database.config_db import get_config
from database.stats import list_bot_chats, upsert_bot_chat
from keyboards.builders import group_selector, main_menu
from locales import es
from utils.helpers import format_minutes
from utils.permissions import is_admin, list_admin_chats_for_user

logger = logging.getLogger(__name__)
router = Router(name="menu")


def render_main_menu_text(cfg: dict) -> str:
    """Construye el texto que acompaña al teclado del menú principal."""
    title = cfg.get("chat_title") or f"Chat {cfg['chat_id']}"
    pq = PUNISHMENT_TYPES[cfg["punishment_queue"]]
    pc = PUNISHMENT_TYPES[cfg["punishment_cooldown"]]
    pa = PUNISHMENT_TYPES[cfg["punishment_antidup"]]
    return (
        f"🤖 <b>Configuración de {title}</b>\n\n"
        f"🔄 <b>Cola rotatoria:</b> {cfg['queue_size']} chicas\n"
        f"⏱️ <b>Cooldown:</b> {format_minutes(int(cfg['cooldown_minutes']))}\n"
        f"🖼️ <b>Anti-duplicado:</b> {cfg['antidup_hours']}h "
        f"(sensibilidad {cfg['phash_threshold']})\n\n"
        f"<b>Castigos:</b>\n"
        f"  • Cola: {pq[0]} {pq[1]}\n"
        f"  • Cooldown: {pc[0]} {pc[1]}\n"
        f"  • Duplicado: {pa[0]} {pa[1]}\n\n"
        f"<i>Toca cualquier opción para configurar.</i>"
    )


@router.message(Command("menu"))
async def cmd_menu(message: Message, bot: Bot) -> None:
    """
    Comando /menu:
    - En grupo: comprueba admin (si admin_only_menu) y abre el menú.
    - En privado: muestra selector de grupos donde el usuario es admin.
    """
    if message.chat.type == ChatType.PRIVATE:
        await _open_group_selector(message, bot)
        return

    if message.chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        await message.reply(es.ERR_NO_GROUP)
        return

    await upsert_bot_chat(message.chat.id, message.chat.title, message.chat.type)

    cfg = await get_config(message.chat.id)
    if int(cfg["admin_only_menu"]):
        if not message.from_user or not await is_admin(
            bot, message.chat.id, message.from_user.id
        ):
            await message.reply(es.ERR_NOT_ADMIN)
            return

    await message.reply(
        render_main_menu_text(cfg),
        reply_markup=main_menu(cfg),
    )


async def _open_group_selector(message: Message, bot: Bot) -> None:
    """Lista grupos donde el bot está y el usuario es admin."""
    if not message.from_user:
        return
    all_chats = await list_bot_chats()
    if not all_chats:
        await message.answer(es.MENU_NO_GROUPS)
        return
    admin_chats = await list_admin_chats_for_user(bot, message.from_user.id, all_chats)
    if not admin_chats:
        await message.answer(es.MENU_NO_GROUPS)
        return
    await message.answer(
        es.MENU_SELECT_GROUP,
        reply_markup=group_selector(admin_chats),
    )
