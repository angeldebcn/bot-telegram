"""
Agrupador de álbumes de Telegram.

Telegram envía cada media de un álbum como un mensaje independiente con el
mismo `media_group_id`. Esperamos un breve tiempo (`ALBUM_COLLECT_SECONDS`)
para juntarlos y procesarlos como una sola publicación.
"""
import asyncio
import logging
from typing import Awaitable, Callable

from aiogram.types import Message

from config import ALBUM_COLLECT_SECONDS

logger = logging.getLogger(__name__)


class AlbumCollector:
    """Buffer de álbumes en memoria."""

    def __init__(self, delay: float = ALBUM_COLLECT_SECONDS):
        self.delay = delay
        self._albums: dict[str, list[Message]] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        self._lock = asyncio.Lock()

    async def add(
        self,
        message: Message,
        on_complete: Callable[[list[Message]], Awaitable[None]],
    ) -> None:
        """
        Añade un mensaje al colector.
        Si no tiene media_group_id, llama a on_complete inmediatamente con [message].
        Si lo tiene, agrupa y dispara on_complete tras `delay` segundos.
        """
        if not message.media_group_id:
            await on_complete([message])
            return

        key = f"{message.chat.id}:{message.media_group_id}"
        async with self._lock:
            if key not in self._albums:
                self._albums[key] = []
            self._albums[key].append(message)
            # Cancelar el timer anterior si lo había
            if key in self._tasks:
                self._tasks[key].cancel()
            self._tasks[key] = asyncio.create_task(
                self._fire_after_delay(key, on_complete)
            )

    async def _fire_after_delay(
        self, key: str, on_complete: Callable[[list[Message]], Awaitable[None]]
    ) -> None:
        try:
            await asyncio.sleep(self.delay)
        except asyncio.CancelledError:
            return
        async with self._lock:
            messages = self._albums.pop(key, [])
            self._tasks.pop(key, None)
        if messages:
            try:
                await on_complete(messages)
            except Exception:
                logger.exception("Error procesando álbum %s", key)


# Singleton global
album_collector = AlbumCollector()
