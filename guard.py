# -*- coding: utf-8 -*-
"""
guard.py
Filtro de seguridad: solo el dueño (OWNER_ID) puede usar el bot.
"""
from aiogram.filters import BaseFilter
from aiogram.types import Message, CallbackQuery

import config


class IsOwner(BaseFilter):
    """Devuelve True solo si quien escribe es el dueño del bot."""

    async def __call__(self, event: Message | CallbackQuery) -> bool:
        if event.from_user is None:
            return False
        return event.from_user.id == config.OWNER_ID
