# -*- coding: utf-8 -*-
"""
h_menu.py
Comandos básicos (/start, /menu, /id, /help), menú principal y ayuda.
"""
from aiogram import Router, F
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery

import keyboards as kb
import database as db
import broadcaster
from guard import IsOwner

router = Router()
router.message.filter(IsOwner())
router.callback_query.filter(IsOwner())

CABECERA = "🐷 <b>MALA STUDIOS · Bot de difusión</b>\n\n"


async def _resumen() -> str:
    """Pequeño resumen del estado actual, para la cabecera del menú."""
    try:
        s = await db.stats()
        trabajos = broadcaster.scheduler.get_jobs()
        proximo = None
        for j in trabajos:
            t = getattr(j, "next_run_time", None)
            if t and (proximo is None or t < proximo):
                proximo = t
        prox_txt = proximo.strftime("%d/%m %H:%M") if proximo else "—"
        return (
            f"📡 {s['canales']} canales · 🚀 {s['campanas_on']} campañas "
            f"activas · 🤝 {s.get('alianzas_on', 0)} alianzas\n"
            f"⏭️ Próxima tarea: {prox_txt}\n\n"
            f"Pulsa una opción 👇")
    except Exception:
        return "Pulsa una opción del menú 👇"

AYUDA = (
    "❓ <b>Ayuda · Cómo funciona el bot</b>\n\n"
    "<b>1) Promos</b> — Crea tu publicación una vez. Le mandas al bot el "
    "mensaje tal cual (foto + texto + emojis premium) y se guarda como "
    "«mensaje maestro». El bot siempre lo reenvía con copy_message, así "
    "que <b>los emojis premium nunca se pierden</b>.\n\n"
    "<b>2) Canales</b> — Añade los canales de las creadoras pegando "
    "<code>@usuario</code>, un enlace o un ID. También puedes simplemente "
    "<b>añadir el bot como administrador</b> al canal y aparecerá solo. "
    "Funciona con canales públicos y privados.\n\n"
    "<b>3) Enviar ahora</b> — Difunde una promo al instante: eliges promo, "
    "a quién, y cuánto tarda en autoborrarse (6/12/24/48/72 h, nunca, o "
    "personalizado).\n\n"
    "<b>4) Campañas automáticas</b> — Lo defines una vez (canales, promo, "
    "días, hora, lotes de 5, separación de 5 min, rotación de promos) y el "
    "bot lo hace solo cada semana. Adiós a escribir comandos.\n\n"
    "<b>Comandos disponibles:</b>\n"
    "/start /menu — abrir el menú\n"
    "/promos — gestionar promos\n"
    "/canales /list — gestionar y ver canales\n"
    "/campanas — campañas automáticas\n"
    "/enviar — enviar una promo ahora\n"
    "/stats — estadísticas\n"
    "/verify — verificar permisos de los canales\n"
    "/delall — borrar TODAS las publicaciones enviadas\n"
    "/cancel — cancelar lo que estés haciendo\n"
    "/id — ver tu user_id de Telegram"
)


async def mostrar_menu(target: Message | CallbackQuery) -> None:
    texto = CABECERA + await _resumen()
    if isinstance(target, CallbackQuery):
        try:
            await target.message.edit_text(
                texto, reply_markup=kb.menu_principal())
        except Exception:
            # Si el mensaje no se puede editar, se envía uno nuevo.
            await target.message.answer(
                texto, reply_markup=kb.menu_principal())
    else:
        await target.answer(texto, reply_markup=kb.menu_principal())


@router.message(CommandStart())
@router.message(Command("menu"))
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await mostrar_menu(message)


@router.message(Command("id"))
async def cmd_id(message: Message):
    await message.answer(
        f"🆔 Tu user_id es <code>{message.from_user.id}</code>")


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("✖️ Operación cancelada.", reply_markup=kb.menu_principal())


@router.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(AYUDA, reply_markup=kb.volver())


@router.callback_query(F.data == "menu:home")
async def cb_home(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    await mostrar_menu(callback)


@router.callback_query(F.data == "menu:help")
async def cb_help(callback: CallbackQuery):
    await callback.answer()
    await callback.message.edit_text(AYUDA, reply_markup=kb.volver())
