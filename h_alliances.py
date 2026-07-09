# -*- coding: utf-8 -*-
"""
h_alliances.py
Alianzas: grupos de terceros (intercambios) donde tú publicas tu promo
a unas horas concretas cada día. Cada alianza es independiente:
su grupo, su promo, sus días, sus horas y su zona horaria.
"""
import logging

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery

import keyboards as kb
import database as db
import broadcaster
from guard import IsOwner
from states import NewAlliance, AllyNum, EditAlliance, AllianceTopics

router = Router()
router.message.filter(IsOwner())
router.callback_query.filter(IsOwner())

log = logging.getLogger("mala-bot.alliances")

DIA_NOMBRE = {"mon": "Lun", "tue": "Mar", "wed": "Mié", "thu": "Jue",
              "fri": "Vie", "sat": "Sáb", "sun": "Dom"}


# ---------------------------------------------------------------------------
# MENÚ DE ALIANZAS
# ---------------------------------------------------------------------------
@router.callback_query(F.data == "menu:alliances")
@router.message(Command("alianzas"))
async def menu_alianzas(evento, state: FSMContext):
    await state.clear()
    alianzas = await db.get_alliances()
    texto = (
        f"🤝 <b>Alianzas</b>\n\n"
        f"Tienes <b>{len(alianzas)}</b> alianzas.\n"
        f"🟢 = activa · 🔴 = pausada\n\n"
        f"Una alianza publica tu promo en el grupo de un aliado a las "
        f"horas que tú marques, todos los días que elijas. Cada alianza "
        f"va por su cuenta.")
    if isinstance(evento, Message):
        await evento.answer(texto, reply_markup=kb.menu_alianzas(alianzas))
    else:
        await evento.answer()
        await evento.message.edit_text(
            texto, reply_markup=kb.menu_alianzas(alianzas))


# ---------------------------------------------------------------------------
# ASISTENTE: NUEVA ALIANZA
# ---------------------------------------------------------------------------
@router.callback_query(F.data == "ally:new")
async def cb_nueva(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    promos = await db.get_promos()
    if not promos:
        await callback.answer("Primero crea una promo", show_alert=True)
        return
    # Grupos candidatos: los que no están en una región (sin bloque).
    canales = [c for c in await db.get_channels() if not c["slot"]]
    if not canales:
        await callback.message.edit_text(
            "🤝 <b>Nueva alianza</b>\n\n"
            "No hay grupos disponibles. Primero añade el bot al grupo del "
            "aliado (te llegará el aviso) y cuando te pregunte la región "
            "elige «🤝 Es una alianza». Luego vuelve aquí.",
            reply_markup=kb.volver("menu:alliances"))
        return
    await state.set_state(NewAlliance.nombre)
    await state.update_data(dias=[])
    await callback.message.edit_text(
        "🤝 <b>Nueva alianza</b> · Paso 1 de 7\n\n"
        "Escribe un <b>nombre</b> para la alianza "
        "(ej: «Aliado Latino X»):\n\n/cancel para salir.")


@router.message(NewAlliance.nombre)
async def paso_nombre(message: Message, state: FSMContext):
    await state.update_data(nombre=(message.text or "Alianza").strip()[:40])
    await state.set_state(NewAlliance.grupo)
    canales = [c for c in await db.get_channels() if not c["slot"]]
    await message.answer(
        "Paso 2 de 7 — Elige el <b>grupo del aliado</b>:",
        reply_markup=kb.elegir_grupo_alianza(canales))


@router.callback_query(NewAlliance.grupo, F.data.startswith("allygrp:"))
async def paso_grupo(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    chat_id = int(callback.data.split(":")[-1])
    await state.update_data(chat_id=chat_id)
    await state.set_state(NewAlliance.promo)
    promos = await db.get_promos()
    await callback.message.edit_text(
        "Paso 3 de 7 — Elige la <b>promo</b> que se publicará en ese grupo:",
        reply_markup=kb.elegir_promo("allypromo", promos))


@router.callback_query(NewAlliance.promo, F.data.startswith("allypromo:"))
async def paso_promo(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    promo_id = int(callback.data.split(":")[-1])
    await state.update_data(promo_id=promo_id)
    await state.set_state(NewAlliance.zona)
    await callback.message.edit_text(
        "Paso 4 de 7 — ¿En qué <b>hora</b> defines los horarios?\n\n"
        "Si la alianza la coordinas en tu horario, elige «Hora de España». "
        "Si el trato es «a las 21:00 hora de allí», elige la zona del "
        "aliado y el bot lo convierte solo.",
        reply_markup=kb.tz_alianza())


@router.callback_query(NewAlliance.zona, F.data.startswith("allytz:"))
async def paso_zona(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    region = callback.data.split(":", 1)[1]
    tz = broadcaster.tz_de_region(region)
    await state.update_data(tz=tz, zona_region=region)
    await state.set_state(NewAlliance.dias)
    await state.update_data(dias=[])
    await callback.message.edit_text(
        f"Zona: <b>{region}</b>\n\n"
        "Paso 5 de 7 — Marca los <b>días</b> en que se publica:",
        reply_markup=kb.multi_dias([], "allyday"))


@router.callback_query(NewAlliance.dias, F.data.startswith("allyday:toggle:"))
async def paso_dia_toggle(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    cod = callback.data.split(":")[-1]
    data = await state.get_data()
    sel = data.get("dias", [])
    if cod in sel:
        sel.remove(cod)
    else:
        sel.append(cod)
    await state.update_data(dias=sel)
    await callback.message.edit_reply_markup(
        reply_markup=kb.multi_dias(sel, "allyday"))


@router.callback_query(NewAlliance.dias, F.data == "allyday:done")
async def paso_dia_done(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    data = await state.get_data()
    if not data.get("dias"):
        await callback.answer("Marca al menos un día", show_alert=True)
        return
    await state.set_state(NewAlliance.horas)
    await callback.message.edit_text(
        "Paso 6 de 7 — Escribe las <b>horas</b> de publicación en formato "
        "<code>HH:MM</code>.\n\n"
        "Puedes poner varias separadas por espacios o comas. Ejemplos:\n"
        "• <code>20:45</code> (una vez al día)\n"
        "• <code>20:45 03:15</code> (dos veces al día)\n"
        "• <code>09:00, 15:00, 21:00</code> (tres veces)\n\n"
        "/cancel para salir.")


@router.message(NewAlliance.horas)
async def paso_horas(message: Message, state: FSMContext):
    crudo = (message.text or "").replace(",", " ").split()
    horas = []
    for t in crudo:
        try:
            h, m = t.split(":")
            h, m = int(h), int(m)
            assert 0 <= h <= 23 and 0 <= m <= 59
            horas.append(f"{h:02d}:{m:02d}")
        except Exception:
            await message.answer(
                f"❌ «{t}» no es una hora válida. Usa HH:MM. Inténtalo otra "
                f"vez con todas las horas:")
            return
    if not horas:
        await message.answer("❌ Escribe al menos una hora (HH:MM):")
        return
    await state.update_data(horas=horas)
    await state.set_state(NewAlliance.borrado)
    await message.answer(
        "Paso 7 de 7 — ¿Cuándo se <b>autoborra</b> cada publicación?",
        reply_markup=kb.elegir_duracion("allydel"))


@router.callback_query(NewAlliance.borrado, F.data.startswith("allydel:"))
async def paso_borrado(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    valor = callback.data.split(":")[1]
    if valor == "custom":
        await state.set_state(AllyNum.esperando)
        await callback.message.edit_text(
            "✏️ Escribe en cuántas <b>horas</b> se autoborra (un número):")
        return
    await state.update_data(borrado=int(valor))
    await _guardar(callback, state)


@router.message(AllyNum.esperando, F.text)
async def numero_custom(message: Message, state: FSMContext):
    texto = (message.text or "").strip()
    if not texto.isdigit():
        await message.answer("❌ Tiene que ser un número. Otra vez:")
        return
    data = await state.get_data()
    # ¿Estamos editando el autoborrado de una alianza ya creada?
    if data.get("edit_autodel"):
        ally_id = data["ally_id"]
        await db.update_alliance(ally_id, delete_after_h=int(texto))
        await state.clear()
        await _volver_ficha(message, ally_id)
        return
    # Si no, es el paso de creación.
    await state.update_data(borrado=int(texto))
    await state.set_state(NewAlliance.borrado)
    await _guardar(message, state)


async def _guardar(evento, state: FSMContext):
    data = await state.get_data()
    bot = evento.bot
    ally_data = {
        "name": data["nombre"],
        "chat_id": data["chat_id"],
        "promo_id": data["promo_id"],
        "days": ",".join(data["dias"]),
        "times": ",".join(data["horas"]),
        "tz": data.get("tz", "Europe/Madrid"),
        "delete_after_h": data["borrado"],
    }
    ally_id = await db.add_alliance(ally_data)
    await state.clear()
    ally = await db.get_alliance(ally_id)
    broadcaster.registrar_alianza(bot, ally)

    canal = await db.get_channel(data["chat_id"])
    promo = await db.get_promo(data["promo_id"])
    dias_txt = " ".join(DIA_NOMBRE.get(d, d) for d in data["dias"])
    # Aviso sobre permisos según tipo de destino y autoborrado.
    borrado = data["borrado"]
    es_grupo = canal and canal["ctype"] in ("group", "supergroup")
    if es_grupo:
        nota_permiso = ("ℹ️ Es un <b>grupo</b>: al bot le basta con ser "
                        "<b>miembro</b>, no necesita ser admin (ni para el "
                        "autoborrado de menos de 48h).")
    elif borrado <= 48:
        nota_permiso = ("ℹ️ Es un <b>canal</b>: el bot necesita ser "
                        "<b>admin con «Publicar mensajes»</b>. "
                        "<b>NO</b> hace falta «Eliminar mensajes» "
                        "(el autoborrado de menos de 48h funciona sin él).")
    else:
        nota_permiso = (f"⚠️ Es un <b>canal</b> con autoborrado de {borrado}h "
                        f"(más de 48h): el bot necesita ser admin con "
                        f"<b>«Publicar» Y «Eliminar mensajes»</b>.")
    texto = (
        f"✅ <b>Alianza «{ally['name']}» creada y activada</b>\n\n"
        f"• Destino: {canal['title'] if canal else data['chat_id']}\n"
        f"• Promo: {promo['name'] if promo else '—'}\n"
        f"• Zona: {data.get('zona_region', 'España')}\n"
        f"• Días: {dias_txt}\n"
        f"• Horas: {', '.join(data['horas'])}\n"
        f"• Autoborrado: {borrado} h\n\n"
        f"{nota_permiso}\n\n"
        f"El bot publicará solo. Es independiente de las campañas.")
    if isinstance(evento, CallbackQuery):
        await evento.message.edit_text(
            texto, reply_markup=kb.volver("menu:alliances"))
    else:
        await evento.answer(texto, reply_markup=kb.volver("menu:alliances"))


# ---------------------------------------------------------------------------
# VER / ACTIVAR / PAUSAR / PUBLICAR / ELIMINAR
# ---------------------------------------------------------------------------
async def _mostrar_ficha(callback: CallbackQuery, ally_id: int):
    a = await db.get_alliance(ally_id)
    if not a:
        return
    canal = await db.get_channel(a["chat_id"])
    promo = await db.get_promo(a["promo_id"])
    dias = " ".join(DIA_NOMBRE.get(d, d)
                    for d in str(a["days"]).split(",") if d)
    estado = "🟢 Activa" if a["active"] else "🔴 Pausada"
    await callback.message.edit_text(
        f"🤝 <b>{a['name']}</b>\n"
        f"• Estado: {estado}\n"
        f"• Grupo: {canal['title'] if canal else a['chat_id']}\n"
        f"• Promo: {promo['name'] if promo else '— (borrada)'}\n"
        f"• Días: {dias}\n"
        f"• Horas: {a['times']}\n"
        f"• Autoborrado: {a['delete_after_h']} h",
        reply_markup=kb.ficha_alianza(ally_id, bool(a["active"])))


@router.callback_query(F.data.startswith("ally:view:"))
async def cb_ver(callback: CallbackQuery):
    await callback.answer()
    ally_id = int(callback.data.split(":")[-1])
    if not await db.get_alliance(ally_id):
        await callback.answer("No existe", show_alert=True)
        return
    await _mostrar_ficha(callback, ally_id)


@router.callback_query(F.data.startswith("ally:on:"))
async def cb_activar(callback: CallbackQuery):
    ally_id = int(callback.data.split(":")[-1])
    await db.set_alliance_active(ally_id, True)
    ally = await db.get_alliance(ally_id)
    broadcaster.registrar_alianza(callback.bot, ally)
    await callback.answer("Alianza activada")
    await _mostrar_ficha(callback, ally_id)


@router.callback_query(F.data.startswith("ally:off:"))
async def cb_pausar(callback: CallbackQuery):
    ally_id = int(callback.data.split(":")[-1])
    await db.set_alliance_active(ally_id, False)
    broadcaster.quitar_alianza(ally_id)
    await callback.answer("Alianza pausada")
    await _mostrar_ficha(callback, ally_id)


@router.callback_query(F.data.startswith("ally:run:"))
async def cb_publicar(callback: CallbackQuery):
    await callback.answer("Publicando ahora...")
    ally_id = int(callback.data.split(":")[-1])
    a = await db.get_alliance(ally_id)
    if not a:
        return
    promo = await db.get_promo(a["promo_id"])
    canal = await db.get_channel(a["chat_id"])
    if not promo or not canal:
        await callback.message.answer(
            "⚠️ No se pudo publicar: falta la promo o el grupo.")
        return
    resumen = await broadcaster.difundir(
        callback.bot, promo, [canal], a["delete_after_h"])
    if resumen["ok"]:
        await callback.message.answer(
            f"✅ Alianza «{a['name']}» publicada ahora.")
    else:
        motivo = resumen["fallidos"][0][2] if resumen["fallidos"] else "?"
        await callback.message.answer(
            f"⚠️ No se pudo publicar: {motivo}")


@router.callback_query(F.data.startswith("ally:del:"))
async def cb_eliminar(callback: CallbackQuery):
    """Pide confirmación antes de eliminar la alianza."""
    await callback.answer()
    ally_id = int(callback.data.split(":")[-1])
    a = await db.get_alliance(ally_id)
    nombre = a["name"] if a else ally_id
    await callback.message.edit_text(
        f"🗑️ <b>¿Eliminar la alianza «{nombre}»?</b>\n\n"
        f"Dejará de publicarse para siempre. Esta acción no se puede "
        f"deshacer.",
        reply_markup=kb.confirmar_borrado(
            "delally", ally_id, f"ally:view:{ally_id}"))


@router.callback_query(F.data.startswith("delally:yes:"))
async def cb_eliminar_ok(callback: CallbackQuery):
    await callback.answer("Alianza eliminada")
    ally_id = int(callback.data.split(":")[-1])
    broadcaster.quitar_alianza(ally_id)
    await db.delete_alliance(ally_id)
    alianzas = await db.get_alliances()
    await callback.message.edit_text(
        f"✅ Alianza eliminada.\n\n🤝 <b>Alianzas</b> ({len(alianzas)})",
        reply_markup=kb.menu_alianzas(alianzas))


# ===========================================================================
# EDICIÓN DE UNA ALIANZA
# ===========================================================================
async def _volver_ficha(evento, ally_id: int):
    a = await db.get_alliance(ally_id)
    if not a:
        return
    canal = await db.get_channel(a["chat_id"])
    promo = await db.get_promo(a["promo_id"])
    dias = " ".join(DIA_NOMBRE.get(d, d)
                    for d in str(a["days"]).split(",") if d)
    estado = "🟢 Activa" if a["active"] else "🔴 Pausada"
    texto = (
        f"✅ Cambio guardado.\n\n"
        f"🤝 <b>{a['name']}</b>\n"
        f"• Estado: {estado}\n"
        f"• Grupo: {canal['title'] if canal else a['chat_id']}\n"
        f"• Promo: {promo['name'] if promo else '— (borrada)'}\n"
        f"• Días: {dias}\n"
        f"• Horas: {a['times']}\n"
        f"• Autoborrado: {a['delete_after_h']} h")
    teclado = kb.ficha_alianza(ally_id, bool(a["active"]))
    if isinstance(evento, CallbackQuery):
        await evento.message.edit_text(texto, reply_markup=teclado)
    else:
        await evento.answer(texto, reply_markup=teclado)


@router.callback_query(F.data.startswith("ally:edit:"))
async def cb_editar(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    ally_id = int(callback.data.split(":")[-1])
    if not await db.get_alliance(ally_id):
        await callback.answer("No existe", show_alert=True)
        return
    await callback.message.edit_text(
        "✏️ <b>Editar alianza</b>\n\nElige qué quieres cambiar:",
        reply_markup=kb.editar_alianza(ally_id))


async def _reprogramar(ally_id: int, bot) -> None:
    ally = await db.get_alliance(ally_id)
    if ally:
        broadcaster.registrar_alianza(bot, ally)


# ---- Nombre y horas (se escriben) ----
@router.callback_query(F.data.startswith("aedit:name:"))
async def edit_name(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    ally_id = int(callback.data.split(":")[-1])
    await state.set_state(EditAlliance.valor)
    await state.update_data(ally_id=ally_id, campo="name")
    await callback.message.edit_text(
        "🏷️ Escribe el <b>nuevo nombre</b> de la alianza:\n\n"
        "/cancel para salir.")


@router.callback_query(F.data.startswith("aedit:times:"))
async def edit_times(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    ally_id = int(callback.data.split(":")[-1])
    await state.set_state(EditAlliance.valor)
    await state.update_data(ally_id=ally_id, campo="times")
    await callback.message.edit_text(
        "⏰ Escribe las <b>horas</b> de publicación en formato "
        "<code>HH:MM</code>.\nVarias separadas por espacios o comas.\n"
        "Ej: <code>20:45 03:15</code>\n\n/cancel para salir.")


@router.message(EditAlliance.valor)
async def recibir_valor(message: Message, state: FSMContext):
    data = await state.get_data()
    campo = data["campo"]
    ally_id = data["ally_id"]
    texto = (message.text or "").strip()
    if campo == "name":
        await db.update_alliance(ally_id, name=texto[:40])
    else:  # times
        crudo = texto.replace(",", " ").split()
        horas = []
        for t in crudo:
            try:
                h, m = t.split(":")
                h, m = int(h), int(m)
                assert 0 <= h <= 23 and 0 <= m <= 59
                horas.append(f"{h:02d}:{m:02d}")
            except Exception:
                await message.answer(
                    f"❌ «{t}» no es válida. Usa HH:MM. Otra vez:")
                return
        if not horas:
            await message.answer("❌ Escribe al menos una hora:")
            return
        await db.update_alliance(ally_id, times=",".join(horas))
    await state.clear()
    await _reprogramar(ally_id, message.bot)
    await _volver_ficha(message, ally_id)


# ---- Promo ----
@router.callback_query(F.data.startswith("aedit:promo:"))
async def edit_promo(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    ally_id = int(callback.data.split(":")[-1])
    await state.set_state(EditAlliance.promo)
    await state.update_data(ally_id=ally_id)
    promos = await db.get_promos()
    await callback.message.edit_text(
        "📢 Elige la <b>nueva promo</b>:",
        reply_markup=kb.elegir_promo("asetpromo", promos))


@router.callback_query(EditAlliance.promo, F.data.startswith("asetpromo:"))
async def set_promo(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    promo_id = int(callback.data.split(":")[-1])
    data = await state.get_data()
    await db.update_alliance(data["ally_id"], promo_id=promo_id)
    await state.clear()
    await _volver_ficha(callback, data["ally_id"])


# ---- Zona horaria ----
@router.callback_query(F.data.startswith("aedit:tz:"))
async def edit_tz(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    ally_id = int(callback.data.split(":")[-1])
    await state.set_state(EditAlliance.zona)
    await state.update_data(ally_id=ally_id)
    await callback.message.edit_text(
        "🕙 Elige la <b>zona horaria</b> de la alianza:",
        reply_markup=kb.tz_alianza())


@router.callback_query(EditAlliance.zona, F.data.startswith("allytz:"))
async def set_tz(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    region = callback.data.split(":", 1)[1]
    tz = broadcaster.tz_de_region(region)
    data = await state.get_data()
    await db.update_alliance(data["ally_id"], tz=tz)
    await state.clear()
    await _reprogramar(data["ally_id"], callback.bot)
    await _volver_ficha(callback, data["ally_id"])


# ---- Días ----
@router.callback_query(F.data.startswith("aedit:days:"))
async def edit_days(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    ally_id = int(callback.data.split(":")[-1])
    a = await db.get_alliance(ally_id)
    actuales = [d for d in str(a["days"]).split(",") if d]
    await state.set_state(EditAlliance.dias)
    await state.update_data(ally_id=ally_id, dias=actuales)
    await callback.message.edit_text(
        "📆 Marca los <b>días</b> (los actuales ya están marcados):",
        reply_markup=kb.multi_dias(actuales, "eallyday"))


@router.callback_query(EditAlliance.dias, F.data.startswith("eallyday:toggle:"))
async def edit_day_toggle(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    cod = callback.data.split(":")[-1]
    data = await state.get_data()
    sel = data.get("dias", [])
    if cod in sel:
        sel.remove(cod)
    else:
        sel.append(cod)
    await state.update_data(dias=sel)
    await callback.message.edit_reply_markup(
        reply_markup=kb.multi_dias(sel, "eallyday"))


@router.callback_query(EditAlliance.dias, F.data == "eallyday:done")
async def edit_day_done(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    data = await state.get_data()
    if not data.get("dias"):
        await callback.answer("Marca al menos un día", show_alert=True)
        return
    ally_id = data["ally_id"]
    await db.update_alliance(ally_id, days=",".join(data["dias"]))
    await state.clear()
    await _reprogramar(ally_id, callback.bot)
    await _volver_ficha(callback, ally_id)


# ---- Autoborrado ----
@router.callback_query(F.data.startswith("aedit:autodel:"))
async def edit_autodel(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    ally_id = int(callback.data.split(":")[-1])
    await state.set_state(EditAlliance.duracion)
    await state.update_data(ally_id=ally_id)
    await callback.message.edit_text(
        "🗑️ Elige cuándo se <b>autoborra</b> cada publicación:",
        reply_markup=kb.elegir_duracion("asetdel"))


@router.callback_query(EditAlliance.duracion, F.data.startswith("asetdel:"))
async def set_autodel(callback: CallbackQuery, state: FSMContext):
    valor = callback.data.split(":")[1]
    data = await state.get_data()
    ally_id = data["ally_id"]
    if valor == "custom":
        await callback.answer()
        await state.set_state(AllyNum.esperando)
        await state.update_data(edit_autodel=True)
        await callback.message.edit_text(
            "✏️ Escribe en cuántas <b>horas</b> se autoborra (un número):")
        return
    await callback.answer()
    await db.update_alliance(ally_id, delete_after_h=int(valor))
    await state.clear()
    await _volver_ficha(callback, ally_id)


# ===========================================================================
# DUPLICAR UNA ALIANZA
# ===========================================================================
@router.callback_query(F.data.startswith("ally:dup:"))
async def cb_duplicar(callback: CallbackQuery):
    await callback.answer("Duplicando...")
    ally_id = int(callback.data.split(":")[-1])
    a = await db.get_alliance(ally_id)
    if not a:
        await callback.answer("No existe", show_alert=True)
        return
    nueva = {
        "name": (a["name"] + " (copia)")[:40],
        "chat_id": a["chat_id"],
        "promo_id": a["promo_id"],
        "days": a["days"],
        "times": a["times"],
        "tz": a["tz"],
        "delete_after_h": a["delete_after_h"],
    }
    nuevo_id = await db.add_alliance(nueva)
    await db.set_alliance_active(nuevo_id, False)
    await callback.message.edit_text(
        f"📑 <b>Alianza duplicada</b>\n\n"
        f"Se ha creado «{nueva['name']}» como copia exacta, <b>pausada</b>.\n"
        f"Edítale lo que quieras y actívala cuando esté lista.",
        reply_markup=kb.ficha_alianza(nuevo_id, False))


# ===========================================================================
# HILOS DE FORO DE UNA ALIANZA
# ===========================================================================
from h_channels import AYUDA_HILOS  # reutilizamos el texto de ayuda


@router.callback_query(F.data.startswith("ally:topics:"))
async def cb_ally_topics(callback: CallbackQuery):
    await callback.answer()
    ally_id = int(callback.data.split(":")[-1])
    a = await db.get_alliance(ally_id)
    if not a:
        await callback.answer("No existe", show_alert=True)
        return
    hilos = db.topics_a_texto(a["topics"])
    if hilos:
        actual = "Hilos actuales: <b>" + ", ".join(
            f"#{h}" for h in hilos) + f"</b> ({len(hilos)})."
    else:
        actual = "Ahora publico en <b>#General</b> (sin hilo)."
    await callback.message.edit_text(
        f"🧵 <b>Hilos de la alianza «{a['name']}»</b>\n\n{actual}\n\n"
        f"¿Qué quieres hacer?",
        reply_markup=kb.gestion_topics(ally_id, bool(hilos), "ally"))


@router.callback_query(F.data.startswith("allytop:add:"))
async def cb_ally_topics_add(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    ally_id = int(callback.data.split(":")[-1])
    await state.set_state(AllianceTopics.esperando)
    await state.update_data(ally_id=ally_id, modo="add")
    await callback.message.edit_text(
        AYUDA_HILOS + "\n\n➕ Envíame el/los enlace(s) a <b>añadir</b>.\n"
        "/cancel para salir.")


@router.callback_query(F.data.startswith("allytop:set:"))
async def cb_ally_topics_set(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    ally_id = int(callback.data.split(":")[-1])
    await state.set_state(AllianceTopics.esperando)
    await state.update_data(ally_id=ally_id, modo="set")
    await callback.message.edit_text(
        AYUDA_HILOS + "\n\n✏️ Envíame el/los enlace(s). Esto <b>reemplaza</b> "
        "los hilos anteriores.\n/cancel para salir.")


@router.callback_query(F.data.startswith("allytop:clear:"))
async def cb_ally_topics_clear(callback: CallbackQuery):
    await callback.answer("Hilos quitados")
    ally_id = int(callback.data.split(":")[-1])
    await db.set_alliance_topics(ally_id, [])
    a = await db.get_alliance(ally_id)
    await callback.message.edit_text(
        f"🧵 <b>Hilos de «{a['name']}»</b>\n\n"
        f"✅ Quitados. Ahora publico en <b>#General</b>.\n\n¿Algo más?",
        reply_markup=kb.gestion_topics(ally_id, False, "ally"))


@router.message(AllianceTopics.esperando)
async def recibir_ally_topics(message: Message, state: FSMContext):
    data = await state.get_data()
    await state.clear()
    ally_id = data["ally_id"]
    modo = data["modo"]
    nuevos = db.parsear_topics(message.text or "")
    if not nuevos:
        await message.answer(
            "❌ No reconocí ningún enlace de hilo válido. Pega el enlace "
            "completo (t.me/c/.../número).",
            reply_markup=kb.gestion_topics(ally_id, False, "ally"))
        return
    a = await db.get_alliance(ally_id)
    actuales = db.topics_a_texto(a["topics"])
    if modo == "add":
        final = actuales + [t for t in nuevos if t not in actuales]
    else:
        final = nuevos
    await db.set_alliance_topics(ally_id, final)
    lista = ", ".join(f"#{h}" for h in final)
    await message.answer(
        f"✅ <b>Hilos guardados</b> para la alianza «{a['name']}».\n"
        f"Publicaré en: <b>{lista}</b> ({len(final)} hilo(s)).",
        reply_markup=kb.gestion_topics(ally_id, True, "ally"))
