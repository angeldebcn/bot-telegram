"""
Bot de Telegram para moderación multimedia + SaaS.
Punto de entrada principal.
"""
import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import (
    BotCommand,
    BotCommandScopeAllChatAdministrators,
    BotCommandScopeAllPrivateChats,
)

from config import BOT_TOKEN, LOG_LEVEL, OWNER_USER_ID, OWNER_USERNAME
from db import init_db
from sanctions_db import init_sanctions_db
import sanctions_commands
import reports
import sanctions_panels
import sanctions_config
import admin
import callbacks
import commands
import media
import menu
from middleware import MetaCacheMiddleware
from scheduler import setup_scheduler


logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("bot")


async def setup_commands(bot: Bot) -> None:
    """Configura los comandos visibles del bot en distintos contextos."""
    admin_cmds = [
        BotCommand(command="menu", description="🤖 Configurar el bot"),
        BotCommand(command="status", description="📊 Estado del grupo"),
        BotCommand(command="help", description="📚 Lista de comandos"),
        BotCommand(command="lock", description="🔕 Pausar el bot"),
        BotCommand(command="unlock", description="✅ Reanudar el bot"),
        BotCommand(command="freespam", description="👥 Añadir a alianzas (reply, @user o ID)"),
        BotCommand(command="unfreespam", description="🚫 Quitar de alianzas"),
        BotCommand(command="alianzas", description="📋 Ver lista de alianzas"),
        BotCommand(command="forcepost", description="⚡ Pase libre próxima publicación"),
        BotCommand(command="delete", description="🗑️ Moderar post con motivo (responde al post)"),
        BotCommand(command="cancel", description="↩️ Anular publicación (no cuenta)"),
        BotCommand(command="warn", description="⚠️ Advertir a una usuaria"),
        BotCommand(command="unwarn", description="✅ Quitar advertencia"),
        BotCommand(command="warns", description="📑 Ver advertencias"),
        BotCommand(command="whocanpost", description="✏️ Quién puede publicar ahora"),
        BotCommand(command="myturn", description="⏳ Cuándo me toca"),
        BotCommand(command="logs", description="📜 Últimas acciones"),
        BotCommand(command="reload", description="🔄 Recargar admins"),
        BotCommand(command="export", description="💾 Exportar config"),
        BotCommand(command="import", description="📥 Importar config"),
    ]
    private_cmds = [
        BotCommand(command="menu", description="🤖 Configurar uno de mis grupos"),
        BotCommand(command="start", description="ℹ️ Información del bot"),
        BotCommand(command="help", description="📚 Lista de comandos"),
    ]
    await bot.set_my_commands(admin_cmds, scope=BotCommandScopeAllChatAdministrators())
    await bot.set_my_commands(private_cmds, scope=BotCommandScopeAllPrivateChats())


async def main() -> None:
    await init_db()
    await init_sanctions_db()

    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()

    # Middleware: cachea metadata
    dp.message.middleware(MetaCacheMiddleware())

    # Routers en orden:
    # 1. admin (owner-only, captura /admin primero)
    # 2. commands (resto de /comandos)
    # 3. menu (/menu)
    # 4. callbacks (botones inline + valor personalizado en privado)
    # 5. media (catch-all final)
    dp.include_router(admin.router)
    dp.include_router(sanctions_config.router)
    dp.include_router(sanctions_commands.router)
    dp.include_router(sanctions_panels.router)
    dp.include_router(reports.router)
    dp.include_router(commands.router)
    dp.include_router(menu.router)
    dp.include_router(callbacks.router)
    dp.include_router(media.router)

    # Scheduler
    scheduler = setup_scheduler(bot)
    scheduler.start()

    await setup_commands(bot)

    # Banner de arranque
    if OWNER_USER_ID:
        logger.info("👑 Owner configurado: user_id=%s @%s", OWNER_USER_ID, OWNER_USERNAME)
    else:
        logger.warning(
            "⚠️ OWNER_USER_ID no configurado. El sistema de licencias está "
            "en modo libre (cualquier grupo puede usar el bot).",
        )
    logger.info("🤖 Bot arrancando en modo polling...")

    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        scheduler.shutdown()
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("🛑 Bot detenido manualmente.")
