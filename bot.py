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
    # Comandos visibles para administradores en los grupos.
    # Incluye moderación de las 3 reglas + comandos de sanción de la comunidad.
    admin_cmds = [
        # Sanciones de comunidad (staff)
        BotCommand(command="warnleve", description="⚠️ Warn leve (1 punto)"),
        BotCommand(command="warngrave", description="⛔ Warn grave (2 puntos)"),
        BotCommand(command="ban", description="🚫 Banear de toda la comunidad"),
        BotCommand(command="mute7", description="🔇 Silenciar 7 días"),
        BotCommand(command="mute", description="🔇 Silenciar (ej: /mute @u 3d motivo)"),
        BotCommand(command="delete", description="🗑️ Borrar post con motivo (responde)"),
        BotCommand(command="unwarnleve", description="↩️ Quitar warn leve"),
        BotCommand(command="unwarngrave", description="↩️ Quitar warn grave"),
        BotCommand(command="unban", description="↩️ Quitar ban"),
        BotCommand(command="unmute", description="↩️ Quitar silencio"),
        # Reportes y consultas (staff)
        BotCommand(command="reporte", description="🚨 Reportar (solo grupo verificadas)"),
        BotCommand(command="lista", description="📋 Lista de sancionados"),
        BotCommand(command="buscar", description="🔎 Buscar a una persona"),
        BotCommand(command="pendientes", description="⏳ Reportes sin resolver"),
        # Moderación de las 3 reglas
        BotCommand(command="menu", description="🤖 Configurar el bot del grupo"),
        BotCommand(command="status", description="📊 Estado del grupo"),
        BotCommand(command="lock", description="🔕 Pausar el bot"),
        BotCommand(command="unlock", description="✅ Reanudar el bot"),
        BotCommand(command="freespam", description="👥 Añadir a alianzas"),
        BotCommand(command="unfreespam", description="🚫 Quitar de alianzas"),
        BotCommand(command="alianzas", description="📋 Ver alianzas"),
        BotCommand(command="forcepost", description="⚡ Pase libre próxima publicación"),
        BotCommand(command="cancel", description="↩️ Anular publicación (no cuenta)"),
        BotCommand(command="whocanpost", description="✏️ Quién puede publicar ahora"),
        BotCommand(command="myturn", description="⏳ Cuándo me toca"),
        BotCommand(command="help", description="📚 Lista de comandos"),
    ]
    # Comandos en privado: SOLO para el owner (config del sistema).
    # A los demás no les mostramos comandos privados.
    private_cmds = [
        BotCommand(command="config", description="⚙️ Configurar roles y staff"),
        BotCommand(command="lista", description="📋 Ver sancionados"),
        BotCommand(command="buscar", description="🔎 Buscar a una persona"),
        BotCommand(command="pendientes", description="⏳ Reportes sin resolver"),
        BotCommand(command="addstaff", description="👮 Añadir staff"),
        BotCommand(command="help", description="📚 Todos los comandos"),
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
