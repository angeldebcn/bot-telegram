# -*- coding: utf-8 -*-
"""
h_campaigns.py
Campañas automáticas: defines UNA vez (canales, promos, días, hora,
tamaño de lote, intervalo, rotación, autoborrado) y el bot lo repite
solo cada semana. Esto sustituye todo el trabajo manual.
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
from states import NewCampaign, CampNum, EditCampaign

router = Router()
router.message.filter(IsOwner())
router.callback_query.filter(IsOwner())

log = logging.getLogger("mala-bot.campaigns")

DIA_NOMBRE = {"mon": "Lun", "tue": "Mar", "wed": "Mié", "thu": "Jue",
              "fri": "Vie", "sat": "Sáb", "sun": "Dom"}


# ---------------------------------------------------------------------------
# Menú de campañas
# ---------------------------------------------------------------------------
@router.callback_query(F.data == "menu:campaigns")
@router.message(Command("campanas"))
async def menu_campanas(evento, state: FSMContext):
    await state.clear()
    campanas = await db.get_campaigns()
    texto = (f"🚀 <b>Campañas automáticas</b>\n\n"
             f"Tienes <b>{len(campanas)}</b> campañas.\n"
             f"🟢 = activa · 🔴 = pausada\n\n"
             f"Una campaña se ejecuta sola los días y la hora que elijas.")
    if isinstance(evento, Message):
        await evento.answer(texto, reply_markup=kb.menu_campanas(campanas))
    else:
        await evento.message.edit_text(
            texto, reply_markup=kb.menu_campanas(campanas))
        await evento.answer()


# ---------------------------------------------------------------------------
# Asistente: crear campaña
# ---------------------------------------------------------------------------
@router.callback_query(F.data == "camp:new")
async def cb_nueva(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    promos = await db.get_promos()
    if not promos:
        await callback.answer(
            "Primero crea al menos una promo", show_alert=True)
        return
    await state.set_state(NewCampaign.nombre)
    await state.update_data(promos=[], dias=[])
    await callback.message.edit_text(
        "🚀 <b>Nueva campaña</b> · Paso 1 de 9\n\n"
        "Escribe un <b>nombre</b> para la campaña "
        "(ej: «España Jueves»):\n\n/cancel para salir.")
@router.message(NewCampaign.nombre)
async def paso_nombre(message: Message, state: FSMContext):
    await state.update_data(nombre=(message.text or "Campaña").strip()[:40])
    await state.set_state(NewCampaign.region)
    await message.answer(
        "Paso 2 de 9 — Elige la <b>región</b> de los canales:",
        reply_markup=kb.region_camp())


@router.callback_query(NewCampaign.region, F.data.startswith("campreg:"))
async def paso_region(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    region = callback.data.split(":")[1]
    # La zona horaria se asigna sola según la región: así escribes
    # SIEMPRE la hora local (21:30) y el bot la convierte automáticamente.
    tz = broadcaster.tz_de_region(region)
    await state.update_data(region=region, tz=tz)
    await state.set_state(NewCampaign.categoria)
    await callback.message.edit_text(
        f"Región: <b>{region}</b> · hora local <code>{tz}</code>\n\n"
        "Paso 3 de 9 — Elige la <b>categoría</b>:",
        reply_markup=kb.categoria_camp())
    await callback.answer()
@router.callback_query(NewCampaign.categoria, F.data.startswith("campcat:"))
async def paso_categoria(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.update_data(categoria=callback.data.split(":")[1])
    await state.set_state(NewCampaign.promos)
    promos = await db.get_promos()
    await callback.message.edit_text(
        "Paso 4 de 9 — Marca la(s) <b>promo(s)</b>.\n"
        "Si marcas varias, se podrán rotar entre bloques:",
        reply_markup=kb.multi_promos([], promos))
@router.callback_query(NewCampaign.promos, F.data.startswith("campromo:toggle:"))
async def paso_promo_toggle(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    pid = int(callback.data.split(":")[-1])
    data = await state.get_data()
    sel = data.get("promos", [])
    if pid in sel:
        sel.remove(pid)
    else:
        sel.append(pid)
    await state.update_data(promos=sel)
    promos = await db.get_promos()
    await callback.message.edit_reply_markup(
        reply_markup=kb.multi_promos(sel, promos))
@router.callback_query(NewCampaign.promos, F.data == "campromo:done")
async def paso_promo_done(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    data = await state.get_data()
    if not data.get("promos"):
        await callback.answer("Marca al menos una promo", show_alert=True)
        return
    if len(data["promos"]) > 1:
        await state.set_state(NewCampaign.rotacion)
        await callback.message.edit_text(
            "Paso 5 de 9 — ¿Cada cuántos bloques se <b>rota</b> de promo?",
            reply_markup=kb.opciones_numero("camprot", [3, 6, 12]))
    else:
        await state.update_data(rotacion=0)
        await _ir_a_dias(callback, state)
@router.callback_query(NewCampaign.rotacion, F.data.startswith("camprot:"))
async def paso_rotacion(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    valor = callback.data.split(":")[1]
    if valor == "custom":
        await state.update_data(custom_for="camprot")
        await state.set_state(CampNum.esperando)
        await callback.message.edit_text(
            "✏️ Escribe cada cuántos bloques rotar de promo (un número):")
        return
    await state.update_data(rotacion=int(valor))
    await _ir_a_dias(callback, state)
async def _ir_a_dias(evento, state: FSMContext):
    await state.set_state(NewCampaign.dias)
    await state.update_data(dias=[])
    texto = "Paso 6 de 9 — Marca los <b>días</b> de la semana:"
    if isinstance(evento, CallbackQuery):
        await evento.message.edit_text(
            texto, reply_markup=kb.multi_dias([]))
    else:
        await evento.answer(texto, reply_markup=kb.multi_dias([]))


@router.callback_query(NewCampaign.dias, F.data.startswith("campday:toggle:"))
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
        reply_markup=kb.multi_dias(sel))
@router.callback_query(NewCampaign.dias, F.data == "campday:done")
async def paso_dia_done(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    data = await state.get_data()
    if not data.get("dias"):
        await callback.answer("Marca al menos un día", show_alert=True)
        return
    await state.set_state(NewCampaign.hora)
    data = await state.get_data()
    region = data.get("region", "España")
    await callback.message.edit_text(
        f"Paso 7 de 9 — Escribe la <b>hora de inicio</b> en formato "
        f"<code>HH:MM</code>.\n\n"
        f"⏰ Es la <b>hora local de {region}</b>. Si quieres que llegue a "
        f"las 21:30 de allí, escribe simplemente <code>21:30</code> — el bot "
        f"hace la conversión solo.\n\nEj: <code>21:30</code>")
@router.message(NewCampaign.hora)
async def paso_hora(message: Message, state: FSMContext):
    texto = (message.text or "").strip()
    try:
        h, m = texto.split(":")
        h, m = int(h), int(m)
        assert 0 <= h <= 23 and 0 <= m <= 59
    except Exception:
        await message.answer("❌ Formato no válido. Escribe HH:MM "
                              "(ej: 21:30):")
        return
    await state.update_data(hora=h, minuto=m)
    await state.set_state(NewCampaign.lote)
    await message.answer(
        "Paso 8 de 9 — ¿Cuántos canales por <b>bloque</b>?",
        reply_markup=kb.opciones_numero("camplote", [3, 5, 8, 10]))


@router.callback_query(NewCampaign.lote, F.data.startswith("camplote:"))
async def paso_lote(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    valor = callback.data.split(":")[1]
    if valor == "custom":
        await state.update_data(custom_for="camplote")
        await state.set_state(CampNum.esperando)
        await callback.message.edit_text(
            "✏️ Escribe cuántos canales por bloque (un número):")
        return
    await state.update_data(lote=int(valor))
    await state.set_state(NewCampaign.intervalo)
    await callback.message.edit_text(
        "Paso 9 de 9 — ¿Cuántos <b>minutos</b> entre bloques?",
        reply_markup=kb.opciones_numero("campint", [3, 5, 10, 15]))
@router.callback_query(NewCampaign.intervalo, F.data.startswith("campint:"))
async def paso_intervalo(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    valor = callback.data.split(":")[1]
    if valor == "custom":
        await state.update_data(custom_for="campint")
        await state.set_state(CampNum.esperando)
        await callback.message.edit_text(
            "✏️ Escribe los minutos entre bloques (un número):")
        return
    await state.update_data(intervalo=int(valor))
    await state.set_state(NewCampaign.borrado)
    await callback.message.edit_text(
        "Último paso — ¿Cuándo se <b>autoborra</b> cada publicación?",
        reply_markup=kb.elegir_duracion("campdel"))
@router.callback_query(NewCampaign.borrado, F.data.startswith("campdel:"))
async def paso_borrado(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    valor = callback.data.split(":")[1]
    if valor == "custom":
        await state.update_data(custom_for="campdel")
        await state.set_state(CampNum.esperando)
        await callback.message.edit_text(
            "✏️ Escribe en cuántas horas se autoborra (un número):")
        return
    await state.update_data(borrado=int(valor))
    await _guardar_campana(callback, state)


# Recibe los números personalizados del asistente de campañas.
@router.message(CampNum.esperando, F.text)
async def numero_campana(message: Message, state: FSMContext):
    data = await state.get_data()
    para = data.get("custom_for", "")
    if not para.startswith("camp"):
        return  # lo gestiona h_broadcast
    texto = (message.text or "").strip()
    if not texto.isdigit():
        await message.answer("❌ Tiene que ser un número. Otra vez:")
        return
    valor = int(texto)
    await state.set_state(None)

    if para == "camprot":
        await state.update_data(rotacion=valor)
        await _ir_a_dias(message, state)
    elif para == "camplote":
        await state.update_data(lote=max(1, valor))
        await state.set_state(NewCampaign.intervalo)
        await message.answer(
            "Paso 9 de 9 — ¿Cuántos minutos entre bloques?",
            reply_markup=kb.opciones_numero("campint", [3, 5, 10, 15]))
    elif para == "campint":
        await state.update_data(intervalo=max(1, valor))
        await state.set_state(NewCampaign.borrado)
        await message.answer(
            "Último paso — ¿Cuándo se autoborra cada publicación?",
            reply_markup=kb.elegir_duracion("campdel"))
    elif para == "campdel":
        await state.update_data(borrado=valor)
        await _guardar_campana(message, state)


async def _guardar_campana(evento, state: FSMContext):
    data = await state.get_data()
    bot = evento.bot
    camp_data = {
        "name": data["nombre"],
        "region": data["region"],
        "category": data["categoria"],
        "promo_ids": ",".join(str(p) for p in data["promos"]),
        "days": ",".join(data["dias"]),
        "start_hour": data["hora"],
        "start_minute": data["minuto"],
        "batch_size": data["lote"],
        "interval_min": data["intervalo"],
        "delete_after_h": data["borrado"],
        "rotate_every": data.get("rotacion", 0),
        "tz": data.get("tz", "Europe/Madrid"),
    }
    camp_id = await db.add_campaign(camp_data)
    await state.clear()
    camp = await db.get_campaign(camp_id)
    broadcaster.registrar_campana(bot, camp)

    dias_txt = " ".join(DIA_NOMBRE[d] for d in data["dias"])
    resumen = (
        f"✅ <b>Campaña «{camp['name']}» creada y activada</b>\n\n"
        f"• Región: {data['region']}\n"
        f"• Categoría: {data['categoria']}\n"
        f"• Promos: {len(data['promos'])} "
        f"(rotación cada {data.get('rotacion', 0) or '—'} bloques)\n"
        f"• Días: {dias_txt}\n"
        f"• Hora: {data['hora']:02d}:{data['minuto']:02d} "
        f"(hora local de {data['region']})\n"
        f"• Bloques de {data['lote']} canales, {data['intervalo']} min "
        f"de separación\n"
        f"• Autoborrado: {data['borrado']} h\n\n"
        f"El bot la ejecutará solo. No tienes que hacer nada más.")
    texto = resumen
    if isinstance(evento, CallbackQuery):
        await evento.message.edit_text(texto, reply_markup=kb.volver(
            "menu:campaigns"))
    else:
        await evento.answer(texto, reply_markup=kb.volver("menu:campaigns"))


# ---------------------------------------------------------------------------
# Ver / editar / activar / pausar / ejecutar / eliminar
# ---------------------------------------------------------------------------
def _texto_ficha(c) -> str:
    """Texto descriptivo de una campaña."""
    dias = " ".join(DIA_NOMBRE.get(d, d)
                    for d in str(c["days"]).split(",") if d)
    estado = "🟢 Activa" if c["active"] else "🔴 Pausada"
    n_promos = len([x for x in str(c["promo_ids"]).split(",") if x])
    return (
        f"🚀 <b>{c['name']}</b>\n"
        f"• Estado: {estado}\n"
        f"• Región/Categoría: {c['region']} / {c['category']}\n"
        f"• Días: {dias} a las "
        f"{c['start_hour']:02d}:{c['start_minute']:02d} "
        f"(hora local de {c['region']})\n"
        f"• Bloques de {c['batch_size']}, cada {c['interval_min']} min\n"
        f"• Promos: {n_promos} · rotación cada "
        f"{c['rotate_every'] or '—'} bloques\n"
        f"• Autoborrado: {c['delete_after_h']} h")


async def _mostrar_ficha(callback: CallbackQuery, camp_id: int):
    """Dibuja la ficha de una campaña en el mensaje actual."""
    c = await db.get_campaign(camp_id)
    if not c:
        return
    await callback.message.edit_text(
        _texto_ficha(c),
        reply_markup=kb.ficha_campana(camp_id, bool(c["active"])))


async def _volver_a_ficha(evento, camp_id: int):
    """Vuelve a la ficha tras una edición (sirve para Message o Callback)."""
    c = await db.get_campaign(camp_id)
    if not c:
        return
    texto = "✅ Cambio guardado.\n\n" + _texto_ficha(c)
    teclado = kb.ficha_campana(camp_id, bool(c["active"]))
    if isinstance(evento, CallbackQuery):
        await evento.message.edit_text(texto, reply_markup=teclado)
    else:
        await evento.answer(texto, reply_markup=teclado)


@router.callback_query(F.data.startswith("camp:view:"))
async def cb_ver(callback: CallbackQuery):
    await callback.answer()
    camp_id = int(callback.data.split(":")[-1])
    c = await db.get_campaign(camp_id)
    if not c:
        await callback.answer("No existe", show_alert=True)
        return
    await _mostrar_ficha(callback, camp_id)


@router.callback_query(F.data.startswith("camp:on:"))
async def cb_activar(callback: CallbackQuery):
    camp_id = int(callback.data.split(":")[-1])
    await db.set_campaign_active(camp_id, True)
    camp = await db.get_campaign(camp_id)
    broadcaster.registrar_campana(callback.bot, camp)
    await callback.answer("Campaña activada")
    await _mostrar_ficha(callback, camp_id)


@router.callback_query(F.data.startswith("camp:off:"))
async def cb_pausar(callback: CallbackQuery):
    camp_id = int(callback.data.split(":")[-1])
    await db.set_campaign_active(camp_id, False)
    broadcaster.quitar_campana(camp_id)
    await callback.answer("Campaña pausada")
    await _mostrar_ficha(callback, camp_id)


@router.callback_query(F.data.startswith("camp:run:"))
async def cb_ejecutar(callback: CallbackQuery):
    """Muestra las opciones de ejecución manual de la campaña."""
    await callback.answer()
    camp_id = int(callback.data.split(":")[-1])
    c = await db.get_campaign(camp_id)
    if not c:
        await callback.answer("No existe", show_alert=True)
        return
    await callback.message.edit_text(
        f"🧪 <b>Ejecutar «{c['name']}» ahora</b>\n\n"
        f"Elige cómo quieres lanzarla:\n\n"
        f"• <b>Desde el principio</b> — empieza por el bloque 1.\n"
        f"• <b>Desde un bloque</b> — útil si un bloque falló y quieres "
        f"seguir desde ahí sin repetir los anteriores.\n"
        f"• <b>Reempezar limpio</b> — borra lo que esta campaña ya publicó "
        f"y vuelve a empezar de cero.",
        reply_markup=kb.ejecutar_campana(camp_id))


@router.callback_query(F.data.startswith("crun:full:"))
async def cb_run_full(callback: CallbackQuery):
    camp_id = int(callback.data.split(":")[-1])
    await callback.answer("Lanzando desde el bloque 1...")
    await callback.message.edit_text(
        "🚀 Campaña lanzada desde el bloque 1. Te avisaré de cada bloque.")
    await broadcaster.ejecutar_campana(callback.bot, camp_id,
                                       desde_bloque=1, borrar_antes=False)


@router.callback_query(F.data.startswith("crun:clean:"))
async def cb_run_clean(callback: CallbackQuery):
    camp_id = int(callback.data.split(":")[-1])
    await callback.answer("Borrando lo anterior y reempezando...")
    await callback.message.edit_text(
        "🧹 Borrando las publicaciones anteriores de esta campaña y "
        "reempezando desde el bloque 1...")
    await broadcaster.ejecutar_campana(callback.bot, camp_id,
                                       desde_bloque=1, borrar_antes=True)


@router.callback_query(F.data.startswith("crun:from:"))
async def cb_run_from(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    camp_id = int(callback.data.split(":")[-1])
    await state.set_state(EditCampaign.valor)
    await state.update_data(camp_id=camp_id, campo="run_from")
    await callback.message.edit_text(
        "🔢 ¿Desde qué <b>número de bloque</b> quieres empezar?\n"
        "Escribe el número (ej: <code>3</code> para empezar en el bloque 3).\n\n"
        "/cancel para salir.")


@router.callback_query(F.data.startswith("camp:del:"))
async def cb_eliminar(callback: CallbackQuery):
    """Pide confirmación antes de eliminar la campaña."""
    await callback.answer()
    camp_id = int(callback.data.split(":")[-1])
    c = await db.get_campaign(camp_id)
    nombre = c["name"] if c else camp_id
    await callback.message.edit_text(
        f"🗑️ <b>¿Eliminar la campaña «{nombre}»?</b>\n\n"
        f"Dejará de ejecutarse para siempre. Esta acción no se puede "
        f"deshacer.",
        reply_markup=kb.confirmar_borrado(
            "delcamp", camp_id, f"camp:view:{camp_id}"))


@router.callback_query(F.data.startswith("delcamp:yes:"))
async def cb_eliminar_ok(callback: CallbackQuery):
    await callback.answer("Campaña eliminada")
    camp_id = int(callback.data.split(":")[-1])
    broadcaster.quitar_campana(camp_id)
    await db.delete_campaign(camp_id)
    campanas = await db.get_campaigns()
    await callback.message.edit_text(
        f"✅ Campaña eliminada.\n\n🚀 <b>Campañas</b> ({len(campanas)})",
        reply_markup=kb.menu_campanas(campanas))

# ===========================================================================
# EDICIÓN DE UNA CAMPAÑA  (cambiar cualquier campo después de creada)
# ===========================================================================
@router.callback_query(F.data.startswith("camp:edit:"))
async def cb_editar(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    camp_id = int(callback.data.split(":")[-1])
    c = await db.get_campaign(camp_id)
    if not c:
        await callback.answer("No existe", show_alert=True)
        return
    await callback.message.edit_text(
        "✏️ <b>Editar campaña</b>\n\n" + _texto_ficha(c)
        + "\n\nElige qué quieres cambiar:",
        reply_markup=kb.editar_campana(camp_id))


async def _aplicar_y_reprogramar(camp_id: int, bot) -> None:
    """Guarda hechos los cambios: re-registra el cron de la campaña."""
    camp = await db.get_campaign(camp_id)
    if camp:
        broadcaster.registrar_campana(bot, camp)


# ---- Campos que se piden escribiendo (nombre, hora, números) ----
@router.callback_query(F.data.startswith("cedit:name:"))
async def edit_name(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    camp_id = int(callback.data.split(":")[-1])
    await state.set_state(EditCampaign.valor)
    await state.update_data(camp_id=camp_id, campo="name")
    await callback.message.edit_text(
        "🏷️ Escribe el <b>nuevo nombre</b> de la campaña:\n\n"
        "/cancel para salir.")


@router.callback_query(F.data.startswith("cedit:hour:"))
async def edit_hour(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    camp_id = int(callback.data.split(":")[-1])
    await state.set_state(EditCampaign.valor)
    await state.update_data(camp_id=camp_id, campo="hora")
    await callback.message.edit_text(
        "⏰ Escribe la <b>nueva hora de inicio</b> en formato "
        "<code>HH:MM</code> (hora local de la región).\n"
        "Ej: <code>21:30</code>\n\n/cancel para salir.")


@router.callback_query(F.data.startswith("cedit:rot:"))
async def edit_rot(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    camp_id = int(callback.data.split(":")[-1])
    await state.set_state(EditCampaign.valor)
    await state.update_data(camp_id=camp_id, campo="rotate_every")
    await callback.message.edit_text(
        "🔄 Escribe cada cuántos <b>bloques</b> se rota de promo.\n"
        "Pon <code>0</code> para no rotar.\n\n/cancel para salir.")


@router.callback_query(F.data.startswith("cedit:batch:"))
async def edit_batch(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    camp_id = int(callback.data.split(":")[-1])
    await state.set_state(EditCampaign.valor)
    await state.update_data(camp_id=camp_id, campo="batch_size")
    await callback.message.edit_text(
        "👥 Escribe cuántos <b>canales por bloque</b> (un número):\n\n"
        "/cancel para salir.")


@router.callback_query(F.data.startswith("cedit:interval:"))
async def edit_interval(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    camp_id = int(callback.data.split(":")[-1])
    await state.set_state(EditCampaign.valor)
    await state.update_data(camp_id=camp_id, campo="interval_min")
    await callback.message.edit_text(
        "⏱️ Escribe cuántos <b>minutos entre bloques</b> (un número):\n\n"
        "/cancel para salir.")


@router.message(EditCampaign.valor)
async def recibir_valor(message: Message, state: FSMContext):
    data = await state.get_data()
    campo = data["campo"]
    camp_id = data["camp_id"]
    texto = (message.text or "").strip()

    # Caso especial: ejecutar la campaña desde un bloque concreto.
    if campo == "run_from":
        if not texto.isdigit() or int(texto) < 1:
            await message.answer("❌ Escribe un número de bloque (ej: 3):")
            return
        bloque = int(texto)
        await state.clear()
        await message.answer(
            f"🚀 Lanzando «{(await db.get_campaign(camp_id))['name']}» "
            f"desde el bloque {bloque}. Te avisaré de cada bloque.")
        await broadcaster.ejecutar_campana(
            message.bot, camp_id, desde_bloque=bloque, borrar_antes=False)
        return

    if campo == "name":
        await db.update_campaign(camp_id, name=texto[:40])
    elif campo == "hora":
        try:
            h, m = texto.split(":")
            h, m = int(h), int(m)
            assert 0 <= h <= 23 and 0 <= m <= 59
        except Exception:
            await message.answer("❌ Formato no válido. Escribe HH:MM "
                                  "(ej: 21:30):")
            return
        await db.update_campaign(camp_id, start_hour=h, start_minute=m)
    else:  # rotate_every, batch_size, interval_min
        if not texto.isdigit():
            await message.answer("❌ Tiene que ser un número. Otra vez:")
            return
        valor = int(texto)
        if campo in ("batch_size", "interval_min") and valor < 1:
            valor = 1
        await db.update_campaign(camp_id, **{campo: valor})

    await state.clear()
    await _aplicar_y_reprogramar(camp_id, message.bot)
    await _volver_a_ficha(message, camp_id)


# ---- Región (reasigna también la zona horaria) ----
@router.callback_query(F.data.startswith("cedit:region:"))
async def edit_region(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    camp_id = int(callback.data.split(":")[-1])
    await state.set_state(EditCampaign.region)
    await state.update_data(camp_id=camp_id)
    await callback.message.edit_text(
        "📍 Elige la <b>nueva región</b> (la zona horaria se ajusta sola):",
        reply_markup=kb.editar_region_camp())


@router.callback_query(EditCampaign.region, F.data.startswith("csetreg:"))
async def set_region(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    region = callback.data.split(":", 1)[1]
    data = await state.get_data()
    camp_id = data["camp_id"]
    tz = broadcaster.tz_de_region(region)
    await db.update_campaign(camp_id, region=region, tz=tz)
    await state.clear()
    await _aplicar_y_reprogramar(camp_id, callback.bot)
    await _volver_a_ficha(callback, camp_id)


# ---- Categoría ----
@router.callback_query(F.data.startswith("cedit:cat:"))
async def edit_cat(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    camp_id = int(callback.data.split(":")[-1])
    await state.set_state(EditCampaign.categoria)
    await state.update_data(camp_id=camp_id)
    await callback.message.edit_text(
        "🗂️ Elige la <b>nueva categoría</b>:",
        reply_markup=kb.editar_categoria_camp())


@router.callback_query(EditCampaign.categoria, F.data.startswith("csetcat:"))
async def set_cat(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    cat = callback.data.split(":", 1)[1]
    data = await state.get_data()
    camp_id = data["camp_id"]
    await db.update_campaign(camp_id, category=cat)
    await state.clear()
    await _aplicar_y_reprogramar(camp_id, callback.bot)
    await _volver_a_ficha(callback, camp_id)


# ---- Autoborrado ----
@router.callback_query(F.data.startswith("cedit:autodel:"))
async def edit_autodel(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    camp_id = int(callback.data.split(":")[-1])
    await state.set_state(EditCampaign.duracion)
    await state.update_data(camp_id=camp_id)
    await callback.message.edit_text(
        "🗑️ Elige cuándo se <b>autoborra</b> cada publicación:",
        reply_markup=kb.elegir_duracion("csetdel"))


@router.callback_query(EditCampaign.duracion, F.data.startswith("csetdel:"))
async def set_autodel(callback: CallbackQuery, state: FSMContext):
    valor = callback.data.split(":")[1]
    data = await state.get_data()
    camp_id = data["camp_id"]
    if valor == "custom":
        await callback.answer()
        await state.set_state(EditCampaign.valor)
        await state.update_data(campo="delete_after_h")
        await callback.message.edit_text(
            "✏️ Escribe en cuántas <b>horas</b> se autoborra (un número):")
        return
    await callback.answer()
    await db.update_campaign(camp_id, delete_after_h=int(valor))
    await state.clear()
    await _aplicar_y_reprogramar(camp_id, callback.bot)
    await _volver_a_ficha(callback, camp_id)


# ---- Días (selección múltiple) ----
@router.callback_query(F.data.startswith("cedit:days:"))
async def edit_days(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    camp_id = int(callback.data.split(":")[-1])
    c = await db.get_campaign(camp_id)
    actuales = [d for d in str(c["days"]).split(",") if d]
    await state.set_state(EditCampaign.dias)
    await state.update_data(camp_id=camp_id, dias=actuales)
    await callback.message.edit_text(
        "📆 Marca los <b>días</b> (los actuales ya están marcados):",
        reply_markup=kb.multi_dias(actuales, "ecampday"))


@router.callback_query(EditCampaign.dias, F.data.startswith("ecampday:toggle:"))
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
        reply_markup=kb.multi_dias(sel, "ecampday"))


@router.callback_query(EditCampaign.dias, F.data == "ecampday:done")
async def edit_day_done(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    data = await state.get_data()
    if not data.get("dias"):
        await callback.answer("Marca al menos un día", show_alert=True)
        return
    camp_id = data["camp_id"]
    await db.update_campaign(camp_id, days=",".join(data["dias"]))
    await state.clear()
    await _aplicar_y_reprogramar(camp_id, callback.bot)
    await _volver_a_ficha(callback, camp_id)


# ---- Promos (selección múltiple) ----
@router.callback_query(F.data.startswith("cedit:promos:"))
async def edit_promos(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    camp_id = int(callback.data.split(":")[-1])
    c = await db.get_campaign(camp_id)
    actuales = [int(x) for x in str(c["promo_ids"]).split(",") if x]
    promos = await db.get_promos()
    await state.set_state(EditCampaign.promos)
    await state.update_data(camp_id=camp_id, promos=actuales)
    await callback.message.edit_text(
        "📢 Marca las <b>promos</b> de la campaña (las actuales ya están "
        "marcadas):",
        reply_markup=kb.multi_promos(actuales, promos, "ecampromo"))


@router.callback_query(EditCampaign.promos,
                       F.data.startswith("ecampromo:toggle:"))
async def edit_promo_toggle(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    pid = int(callback.data.split(":")[-1])
    data = await state.get_data()
    sel = data.get("promos", [])
    if pid in sel:
        sel.remove(pid)
    else:
        sel.append(pid)
    await state.update_data(promos=sel)
    promos = await db.get_promos()
    await callback.message.edit_reply_markup(
        reply_markup=kb.multi_promos(sel, promos, "ecampromo"))


@router.callback_query(EditCampaign.promos, F.data == "ecampromo:done")
async def edit_promo_done(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    data = await state.get_data()
    if not data.get("promos"):
        await callback.answer("Marca al menos una promo", show_alert=True)
        return
    camp_id = data["camp_id"]
    await db.update_campaign(
        camp_id, promo_ids=",".join(str(p) for p in data["promos"]))
    await state.clear()
    await _aplicar_y_reprogramar(camp_id, callback.bot)
    await _volver_a_ficha(callback, camp_id)


# ===========================================================================
# DUPLICAR UNA CAMPAÑA  (crea una copia idéntica, pausada)
# ===========================================================================
@router.callback_query(F.data.startswith("camp:dup:"))
async def cb_duplicar(callback: CallbackQuery):
    await callback.answer("Duplicando...")
    camp_id = int(callback.data.split(":")[-1])
    c = await db.get_campaign(camp_id)
    if not c:
        await callback.answer("No existe", show_alert=True)
        return
    nueva = {
        "name": (c["name"] + " (copia)")[:40],
        "region": c["region"],
        "category": c["category"],
        "promo_ids": c["promo_ids"],
        "days": c["days"],
        "start_hour": c["start_hour"],
        "start_minute": c["start_minute"],
        "batch_size": c["batch_size"],
        "interval_min": c["interval_min"],
        "delete_after_h": c["delete_after_h"],
        "rotate_every": c["rotate_every"],
        "tz": c["tz"],
    }
    nuevo_id = await db.add_campaign(nueva)
    # La copia nace PAUSADA, para que la revises antes de activarla.
    await db.set_campaign_active(nuevo_id, False)
    c2 = await db.get_campaign(nuevo_id)
    await callback.message.edit_text(
        f"📑 <b>Campaña duplicada</b>\n\n"
        f"Se ha creado «{c2['name']}» como copia exacta.\n"
        f"Está <b>🔴 pausada</b>: edítale lo que quieras (región, hora...) "
        f"y actívala cuando esté lista.\n\n" + _texto_ficha(c2),
        reply_markup=kb.ficha_campana(nuevo_id, False))
