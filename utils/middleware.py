"""
Middleware que se ejecuta ANTES de los handlers:

1. Cachea metadata de chats/usuarias (para que /freespam @username funcione).
2. Auto-registra licencias para grupos legacy:
   - Si el bot ya estaba en un grupo antes del despliegue v2 (sin licencia en BD),
     en cuanto llega un mensaje creamos automáticamente una entrada.
   - Si el primer mensaje es del owner Y es admin del grupo → status="owner".
   - Si no → status="pending" (silenciosamente). El owner los verá con /admin list pending.
"""
import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject

from config import OWNER_USER_ID
from database import licenses as licenses_db
from database.stats import cache_user, upsert_bot_chat
from utils.license_helpers import is_owner
from utils.permissions import is_admin

logger = logging.getLogger(__name__)


class MetaCacheMiddleware(BaseMiddleware):
    """Cachea info y auto-registra licencias. Nunca consume el evento."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if isinstance(event, Message) and event.chat:
            try:
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
                    # Auto-registro de licencia legacy
                    await self._ensure_license(event, data)
            except Exception as e:
                logger.debug("Middleware error: %s", e)
        return await handler(event, data)

    async def _ensure_license(self, event: Message, data: dict[str, Any]) -> None:
        """Crea entrada de licencia si no existe. Idempotente."""
        chat_id = event.chat.id
        lic = await licenses_db.get_license(chat_id)
        if lic is not None:
            return
        # No existe: crear
        actor = event.from_user
        actor_id = actor.id if actor else None
        actor_username = actor.username if actor else None

        # Si es el owner Y es admin del grupo → owner
        if is_owner(actor_id):
            bot = data.get("bot")
            try:
                if bot and await is_admin(bot, chat_id, actor_id):
                    await licenses_db.create_license(
                        chat_id=chat_id,
                        status="owner",
                        added_by_user_id=actor_id,
                        added_by_username=actor_username,
                        activated_by=actor_id,
                    )
                    logger.info(
                        "👑 Auto-activado como owner: %s (%s)",
                        chat_id, event.chat.title,
                    )
                    return
            except Exception as e:
                logger.debug("is_admin check failed: %s", e)

        # Cualquier otro caso → pending silencioso (el owner lo verá con /admin)
        await licenses_db.create_license(
            chat_id=chat_id,
            status="pending",
            added_by_user_id=actor_id,
            added_by_username=actor_username,
        )
        logger.info(
            "⏳ Auto-registrado como pending: %s (%s)",
            chat_id, event.chat.title,
        )
