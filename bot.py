# -*- coding: utf-8 -*-
"""
bot.py
Punto de entrada. Arranca la base de datos, el bot, el planificador
de tareas y empieza a escuchar Telegram en modo polling.
"""
import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

import config
import database as db
import broadcaster
from broadcaster import scheduler

# Routers (cada archivo h_*.py aporta su parte del bot).
import h_menu
import h_channels
import h_promos
import h_broadcast
import h_campaigns
import h_misc
import h_alliances
import h_backup
import h_repost

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("mala-bot")


async def main() -> None:
    # 1) Base de datos
    await db.init_db()
    log.info(f"Base de datos lista en {config.DB_PATH}")

    # 2) Bot y dispatcher (parse_mode HTML por defecto)
    bot = Bot(
        token=config.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())

    # --- Red de seguridad global ---
    # Algunos botones redibujan un mensaje idéntico y Telegram responde
    # "message is not modified". Eso no es un fallo real, pero si no se
    # captura, tumba el procesamiento del evento. Este middleware lo
    # ignora silenciosamente para TODOS los callbacks del bot.
    from aiogram.exceptions import TelegramBadRequest as _TBR

    @dp.callback_query.middleware
    async def _ignorar_no_modificado(handler, event, data):
        try:
            return await handler(event, data)
        except _TBR as e:
            if "message is not modified" in str(e).lower():
                try:
                    await event.answer()
                except Exception:
                    pass
                return None
            raise

    # 3) Registrar todos los routers
    dp.include_router(h_menu.router)
    dp.include_router(h_channels.router)
    dp.include_router(h_promos.router)
    dp.include_router(h_broadcast.router)
    dp.include_router(h_campaigns.router)
    dp.include_router(h_alliances.router)
    dp.include_router(h_backup.router)
    dp.include_router(h_repost.router)
    dp.include_router(h_misc.router)

    # 4) Planificador de tareas (campañas y autoborrados)
    if not scheduler.running:
        scheduler.start()

    # 5) Recuperar trabajos pendientes tras un posible reinicio
    await broadcaster.restaurar(bot)
    # Backup automático semanal
    h_backup.programar_backup_automatico(bot)

    # 6) Arrancar
    me = await bot.get_me()
    log.info(f"🤖 Bot @{me.username} arrancado correctamente")
    if config.OWNER_ID:
        try:
            await bot.send_message(
                config.OWNER_ID,
                "🟢 Bot de difusión MALA STUDIOS en marcha.\n"
                "Escribe /menu para empezar.")
        except Exception:
            pass

    await dp.start_polling(
        bot, allowed_updates=dp.resolve_used_update_types())


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        log.info("Bot detenido.")
