"""
Bot de Telegram para moderación multimedia.
Implementa 3 reglas configurables: cola rotatoria, cooldown, anti-duplicado.
Punto de entrada del programa.
"""
import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand, BotCommandScopeAllPrivateChats, BotCommandScopeAllChatAdministrators

from config import BOT_TOKEN, LOG_LEVEL
from database.db import init_db
from handlers import commands, media, menu, callbacks
from utils.middleware import MetaCacheMiddleware
from utils.scheduler import setup_scheduler


logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("bot")


async def setup_commands(bot: Bot) -> None:
    """Configura los comandos visibles del bot en distintos contextos."""
    # Comandos visibles para admins en grupos
    admin_cmds = [
        BotCommand(command="menu", description="🤖 Configurar el bot"),
        BotCommand(command="status", description="📊 Estado del grupo"),
        BotCommand(command="freespam", description="👥 Añadir a alianzas (responde a usuaria)"),
        BotCommand(command="unfreespam", description="🚫 Quitar de alianzas"),
        BotCommand(command="alianzas", description="📋 Ver lista de alianzas"),
        BotCommand(command="warn", description="⚠️ Advertir a una usuaria"),
        BotCommand(command="unwarn", description="✅ Quitar advertencia"),
        BotCommand(command="warns", description="📑 Ver advertencias"),
        BotCommand(command="whocanpost", description="✏️ Quién puede publicar ahora"),
        BotCommand(command="myturn", description="⏳ Cuándo me toca"),
        BotCommand(command="logs", description="📜 Últimas acciones"),
        BotCommand(command="reload", description="🔄 Recargar config"),
        BotCommand(command="export", description="💾 Exportar config a JSON"),
        BotCommand(command="import", description="📥 Importar config"),
    ]
    # Comandos visibles en chat privado con el bot
    private_cmds = [
        BotCommand(command="menu", description="🤖 Configurar uno de mis grupos"),
        BotCommand(command="start", description="ℹ️ Información del bot"),
    ]
    await bot.set_my_commands(admin_cmds, scope=BotCommandScopeAllChatAdministrators())
    await bot.set_my_commands(private_cmds, scope=BotCommandScopeAllPrivateChats())


async def main() -> None:
    """Punto de entrada principal."""
    await init_db()

    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()

    # Middleware: cachea metadata de chats/usuarias en cada mensaje
    dp.message.middleware(MetaCacheMiddleware())

    # Routers en orden: comandos → menú → callbacks → media (catch-all al final)
    dp.include_router(commands.router)
    dp.include_router(menu.router)
    dp.include_router(callbacks.router)
    dp.include_router(media.router)

    # Tareas programadas (backup diario, limpieza, warns expirados)
    scheduler = setup_scheduler(bot)
    scheduler.start()

    await setup_commands(bot)
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
