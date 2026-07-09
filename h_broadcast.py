# -*- coding: utf-8 -*-
"""
h_broadcast.py
Flujo "Enviar ahora" y "Programar envío único".
Pasos: elegir promo -> elegir destino -> modo (golpe/escalonado)
       -> autoborrado -> confirmar (o fecha si es programado).
"""
import logging
import datetime

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery

import keyboards as kb
import database as db
import config
import broadcaster
from broadcaster import scheduler
from guard import IsOwner
from states import CustomValue, ScheduleOne

router = Router()
router.message.filter(IsOwner())
router.callback_query.filter(IsOwner())

log = logging.getLogger("mala-bot.broadcast")

# Guarda el último envío con fallos, para el botón "reenviar fallidos".
ULTIMO_FALLO: dict = {}


# ---------------------------------------------------------------------------
# Utilidades del flujo
# ---------------------------------------------------------------------------
async def _canales_de(data: dict) -> list:
    kind = data.get("target_kind")
    val = data.get("target_value")
    if kind == "region":
        return await db.get_channels(region=val)
    if kind == "cat":
        return await db.get_channels(category=val)
    return await db.get_channels()


def _texto_destino(data: dict) -> str:
    kind = data.get("target_kind")
    if kind == "region":
        return f"Región: {data['target_value']}"
    if kind == "cat":
        return f"Categoría: {data['target_value']}"
    return "TODOS los canales"


def _texto_borrado(h: int) -> str:
    return "no se borra" if not h else f"se borra a las {h} h"


# ---------------------------------------------------------------------------
# Inicio del flujo
# ---------------------------------------------------------------------------
@router.callback_query(F.data == "menu:sendnow")
@router.message(Command("enviar"))
async def inicio_envio(evento, state: FSMContext):
    await state.clear()
    await state.update_data(when="now")
    promos = await db.get_promos()
    if not promos:
        await _responder(evento, "❌ No tienes promos. Crea una primero "
                                  "en 📢 Promos.")
        return
    await _responder(evento, "⚡ <b>Enviar ahora</b>\n\nPaso 1 — Elige la "
                              "promo a difundir:",
                      kb.elegir_promo("sendpromo", promos))


@router.callback_query(F.data == "menu:schedule")
async def inicio_programado(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    await state.update_data(when="schedule")
    promos = await db.get_promos()
    if not promos:
        await callback.message.edit_text(
            "❌ No tienes promos. Crea una primero en 📢 Promos.",
            reply_markup=kb.volver())
        return
    await callback.message.edit_text(
        "⏰ <b>Programar envío único</b>\n\nPaso 1 — Elige la promo:",
        reply_markup=kb.elegir_promo("sendpromo", promos))
@router.callback_query(F.data.startswith("sendpromo:"))
async def elegida_promo(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    promo_id = int(callback.data.split(":")[-1])
    await state.update_data(promo_id=promo_id)
    await callback.message.edit_text(
        "Paso 2 — ¿A quién se lo envío?",
        reply_markup=kb.elegir_objetivo("sendtarget"))
@router.callback_query(F.data.startswith("sendtarget:"))
async def elegido_destino(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    partes = callback.data.split(":")
    if partes[1] == "all":
        await state.update_data(target_kind="all", target_value=None)
    else:
        await state.update_data(target_kind=partes[1], target_value=partes[2])
    await callback.message.edit_text(
        "Paso 3 — ¿Cómo lo envío?",
        reply_markup=kb.modo_envio())
@router.callback_query(F.data.startswith("sendmode:"))
async def elegido_modo(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    modo = callback.data.split(":")[1]
    await state.update_data(mode=modo)
    if modo == "staggered":
        await callback.message.edit_text(
            "Paso 3b — ¿De cuántos canales por bloque?",
            reply_markup=kb.opciones_numero("sendbatch", [3, 5, 8, 10]))
    else:
        await callback.message.edit_text(
            "Paso 4 — ¿Cuándo se autoborra la publicación?",
            reply_markup=kb.elegir_duracion("senddur"))
@router.callback_query(F.data.startswith("sendbatch:"))
async def elegido_lote(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    valor = callback.data.split(":")[1]
    if valor == "custom":
        await state.update_data(custom_for="batch")
        await state.set_state(CustomValue.esperando_valor)
        await callback.message.edit_text(
            "✏️ Escribe cuántos canales por bloque (un número):")
        return
    await state.update_data(batch=int(valor))
    await callback.message.edit_text(
        "Paso 3c — ¿Cuántos minutos entre cada bloque?",
        reply_markup=kb.opciones_numero("sendint", [3, 5, 10, 15]))
@router.callback_query(F.data.startswith("sendint:"))
async def elegido_intervalo(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    valor = callback.data.split(":")[1]
    if valor == "custom":
        await state.update_data(custom_for="int")
        await state.set_state(CustomValue.esperando_valor)
        await callback.message.edit_text(
            "✏️ Escribe los minutos entre bloques (un número):")
        return
    await state.update_data(interval=int(valor))
    await callback.message.edit_text(
        "Paso 4 — ¿Cuándo se autoborra la publicación?",
        reply_markup=kb.elegir_duracion("senddur"))
@router.callback_query(F.data.startswith("senddur:"))
async def elegida_duracion(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    valor = callback.data.split(":")[1]
    if valor == "custom":
        await state.update_data(custom_for="dur")
        await state.set_state(CustomValue.esperando_valor)
        await callback.message.edit_text(
            "✏️ Escribe en cuántas <b>horas</b> se autoborra (un número):")
        return
    await state.update_data(delete_h=int(valor))
    await _ir_a_resumen(callback, state)


# ---- entrada de números personalizados ----
@router.message(CustomValue.esperando_valor)
async def recibir_numero(message: Message, state: FSMContext):
    texto = (message.text or "").strip()
    if not texto.isdigit():
        await message.answer("❌ Tiene que ser un número. Inténtalo otra vez:")
        return
    valor = int(texto)
    data = await state.get_data()
    para = data.get("custom_for")
    await state.set_state(None)

    if para == "batch":
        await state.update_data(batch=max(1, valor))
        await message.answer(
            "Paso 3c — ¿Cuántos minutos entre cada bloque?",
            reply_markup=kb.opciones_numero("sendint", [3, 5, 10, 15]))
    elif para == "int":
        await state.update_data(interval=max(1, valor))
        await message.answer(
            "Paso 4 — ¿Cuándo se autoborra la publicación?",
            reply_markup=kb.elegir_duracion("senddur"))
    elif para == "dur":
        await state.update_data(delete_h=valor)
        await _ir_a_resumen(message, state)


async def _ir_a_resumen(evento, state: FSMContext):
    data = await state.get_data()
    canales = await _canales_de(data)
    modo = "todo de golpe" if data["mode"] == "instant" else (
        f"escalonado ({data.get('batch', 5)} cada "
        f"{data.get('interval', 5)} min)")
    resumen = (
        f"📋 <b>Resumen del envío</b>\n\n"
        f"• Destino: {_texto_destino(data)} ({len(canales)} canales)\n"
        f"• Modo: {modo}\n"
        f"• Autoborrado: {_texto_borrado(data['delete_h'])}\n")

    if data.get("when") == "schedule":
        await state.set_state(ScheduleOne.esperando_fecha)
        await _responder(
            evento, resumen + "\n📅 Escribe la fecha y hora del envío con el "
            "formato <code>DD/MM HH:MM</code>\n(ej: <code>25/12 21:30</code>):")
    else:
        await _responder(evento, resumen + "\n¿Confirmas?",
                          kb.confirmar("sendgo"))


# ---------------------------------------------------------------------------
# Confirmar envío inmediato
# ---------------------------------------------------------------------------
@router.callback_query(F.data == "sendgo:yes")
async def confirmar_envio(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await state.clear()
    await callback.answer("Enviando...")
    await callback.message.edit_text("⏳ Enviando, espera el informe...")
    await _lanzar(callback.bot, data, callback.message)
async def _lanzar(bot, data: dict, mensaje):
    promo = await db.get_promo(data["promo_id"])
    canales = await _canales_de(data)
    delete_h = data["delete_h"]
    if not canales:
        await mensaje.answer("❌ No hay canales en ese destino.",
                             reply_markup=kb.menu_principal())
        return

    if data["mode"] == "instant":
        resumen = await broadcaster.difundir(bot, promo, canales, delete_h)
        await _informe(mensaje, resumen, promo, delete_h)
    else:
        tam = data.get("batch", 5)
        intervalo = data.get("interval", 5)
        lotes = [canales[i:i + tam] for i in range(0, len(canales), tam)]
        for idx, lote in enumerate(lotes):
            cuando = broadcaster.ahora() + datetime.timedelta(
                minutes=idx * intervalo)
            scheduler.add_job(
                broadcaster.difundir, "date", run_date=cuando,
                args=[bot, promo, lote, delete_h, None],
                id=f"send_{int(cuando.timestamp())}_{idx}",
                replace_existing=True)
        await mensaje.answer(
            f"🪜 <b>Envío escalonado programado</b>\n"
            f"• {len(canales)} canales en {len(lotes)} bloques\n"
            f"• {tam} por bloque, {intervalo} min de separación\n"
            f"• El primer bloque sale ya mismo.",
            reply_markup=kb.menu_principal())


async def _informe(mensaje, resumen: dict, promo, delete_h: int):
    texto = (
        f"✅ <b>Envío terminado</b>\n\n"
        f"• Enviados: {resumen['ok']}/{resumen['total']}\n"
        f"• Fallidos: {len(resumen['fallidos'])}\n"
        f"• Autoborrado: {_texto_borrado(delete_h)}")
    teclado = kb.menu_principal()
    if resumen["fallidos"]:
        detalle = "\n".join(
            f"• {n}: {e}" for _, n, e in resumen["fallidos"][:15])
        texto += f"\n\n⚠️ <b>Fallos:</b>\n{detalle}"
        ULTIMO_FALLO["promo_id"] = promo["id"]
        ULTIMO_FALLO["delete_h"] = delete_h
        ULTIMO_FALLO["ids"] = [c for c, _, _ in resumen["fallidos"]]
        from aiogram.utils.keyboard import InlineKeyboardBuilder
        b = InlineKeyboardBuilder()
        b.button(text="🔁 Reenviar fallidos", callback_data="send:retry")
        b.button(text="🏠 Menú", callback_data="menu:home")
        b.adjust(1)
        teclado = b.as_markup()
    await mensaje.answer(texto, reply_markup=teclado)


@router.callback_query(F.data == "send:retry")
async def reenviar_fallidos(callback: CallbackQuery):
    if not ULTIMO_FALLO.get("ids"):
        await callback.answer("No hay fallidos guardados", show_alert=True)
        return
    await callback.answer("Reintentando...")
    promo = await db.get_promo(ULTIMO_FALLO["promo_id"])
    canales = []
    for cid in ULTIMO_FALLO["ids"]:
        ch = await db.get_channel(cid)
        if ch:
            canales.append(ch)
    resumen = await broadcaster.difundir(
        callback.bot, promo, canales, ULTIMO_FALLO["delete_h"])
    await _informe(callback.message, resumen, promo,
                   ULTIMO_FALLO["delete_h"])


# ---------------------------------------------------------------------------
# Envío programado (fecha concreta)
# ---------------------------------------------------------------------------
@router.message(ScheduleOne.esperando_fecha)
async def recibir_fecha(message: Message, state: FSMContext):
    data = await state.get_data()
    cuando = _parsear_fecha((message.text or "").strip())
    if not cuando:
        await message.answer(
            "❌ Formato no válido. Usa <code>DD/MM HH:MM</code> "
            "(ej: <code>25/12 21:30</code>):")
        return
    await state.clear()
    payload = {
        "promo_id": data["promo_id"],
        "target_kind": data.get("target_kind"),
        "target_value": data.get("target_value"),
        "mode": data["mode"],
        "batch": data.get("batch", 5),
        "interval": data.get("interval", 5),
        "delete_h": data["delete_h"],
    }
    scheduler.add_job(
        _envio_diferido, "date", run_date=cuando,
        args=[message.bot, payload],
        id=f"prog_{int(cuando.timestamp())}", replace_existing=True)
    await message.answer(
        f"✅ <b>Envío programado</b> para el "
        f"{cuando.strftime('%d/%m/%Y a las %H:%M')}.",
        reply_markup=kb.menu_principal())


def _parsear_fecha(texto: str):
    """Convierte 'DD/MM HH:MM' o 'DD/MM/AAAA HH:MM' en datetime."""
    for fmt in ("%d/%m/%Y %H:%M", "%d/%m %H:%M"):
        try:
            dt = datetime.datetime.strptime(texto, fmt)
            if fmt == "%d/%m %H:%M":
                dt = dt.replace(year=broadcaster.ahora().year)
            return dt.replace(tzinfo=broadcaster.TZ)
        except ValueError:
            continue
    return None


async def _envio_diferido(bot, payload: dict):
    """Se ejecuta a la hora programada: resuelve canales y difunde."""
    promo = await db.get_promo(payload["promo_id"])
    if not promo:
        return
    if payload["target_kind"] == "region":
        canales = await db.get_channels(region=payload["target_value"])
    elif payload["target_kind"] == "cat":
        canales = await db.get_channels(category=payload["target_value"])
    else:
        canales = await db.get_channels()
    if not canales:
        return
    if payload["mode"] == "instant":
        await broadcaster.difundir(bot, promo, canales, payload["delete_h"])
    else:
        tam = payload["batch"]
        lotes = [canales[i:i + tam] for i in range(0, len(canales), tam)]
        for idx, lote in enumerate(lotes):
            cuando = broadcaster.ahora() + datetime.timedelta(
                minutes=idx * payload["interval"])
            scheduler.add_job(
                broadcaster.difundir, "date", run_date=cuando,
                args=[bot, promo, lote, payload["delete_h"], None],
                id=f"progb_{int(cuando.timestamp())}_{idx}",
                replace_existing=True)
    try:
        await bot.send_message(
            config.OWNER_ID,
            f"⏰ Envío programado «{promo['name']}» ejecutado "
            f"({len(canales)} canales).")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Helper para responder igual a Message o CallbackQuery
# ---------------------------------------------------------------------------
async def _responder(evento, texto: str, teclado=None):
    if isinstance(evento, CallbackQuery):
        await evento.message.edit_text(texto, reply_markup=teclado)
        await evento.answer()
    else:
        await evento.answer(texto, reply_markup=teclado)
