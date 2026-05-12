"""
Middleware para cachear metadata de chats y usuarias sin consumir el mensaje.

Se ejecuta ANTES de los handlers y siempre pasa el control adelante,
por lo que no rompe la propagación entre routers.
"""
import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject

from database.stats import cache_user, upsert_bot_chat

logger = logging.getLogger(__name__)


class MetaCacheMiddleware(BaseMiddleware):
    """Cachea info de chat/usuaria en cada mensaje. No consume el evento."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if isinstance(event, Message) and event.chat:
            try:
                # Solo registramos GRUPOS en bot_chats (no privados)
                if event.chat.type in ("group", "supergroup"):
                    await upsert_bot_chat(
                        event.chat.id, event.chat.title, event.chat.type
                    )
                    if event.from_user and not event.from_user.is_bot:
                        await cache_user(
                            event.chat.id,
                            event.from_user.id,
                            event.from_user.username,
                            event.from_user.full_name,
                        )
            except Exception as e:
                logger.debug("Middleware cache error: %s", e)
        return await handler(event, data)
