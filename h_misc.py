# -*- coding: utf-8 -*-
"""
h_misc.py
Estadísticas, agenda de tareas programadas, ajustes y borrado global.
"""
import logging

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

import keyboards as kb
import database as db
import broadcaster
import config
from broadcaster import scheduler
from guard import IsOwner

router = Router()
router.message.filter(IsOwner())
router.callback_query.filter(IsOwner())

log = logging.getLogger("mala-bot.misc")


# ---------------------------------------------------------------------------
# ESTADÍSTICAS
# ---------------------------------------------------------------------------
@router.callback_query(F.data == "menu:stats")
@router.message(Command("stats"))
async def ver_stats(evento, state: FSMContext):
    await state.clear()
    s = await db.stats()
    texto = (
        "📊 <b>Estadísticas</b>\n\n"
        f"📡 Canales: <b>{s['canales']}</b> "
        f"(✅ {s['canales_ok']} con permisos OK)\n"
        f"📢 Promos: <b>{s['promos']}</b>\n"
        f"🚀 Campañas: <b>{s['campanas']}</b> "
        f"({s['campanas_on']} activas)\n"
        f"🤝 Alianzas: <b>{s.get('alianzas', 0)}</b> "
        f"({s.get('alianzas_on', 0)} activas)\n\n"
        f"✅ Envíos correctos: <b>{s['envios_ok']}</b>\n"
        f"⚠️ Envíos fallidos: <b>{s['envios_fail']}</b>\n"
        f"🗑️ Pendientes de autoborrado: <b>{s['pendientes_borrar']}</b>")
    if isinstance(evento, Message):
        await evento.answer(texto, reply_markup=kb.volver())
    else:
        await evento.message.edit_text(texto, reply_markup=kb.volver())
        await evento.answer()


# ---------------------------------------------------------------------------
# HISTORIAL DE ENVÍOS
# ---------------------------------------------------------------------------
@router.callback_query(F.data == "menu:history")
@router.message(Command("historial"))
async def ver_historial(evento, state: FSMContext):
    await state.clear()
    envios = await db.recent_sends(30)
    if not envios:
        texto = "🧾 <b>Historial</b>\n\nTodavía no se ha enviado nada."
    else:
        lineas = ["🧾 <b>Historial</b> · últimos envíos\n"]
        for s in envios:
            cuando = (s["sent_at"] or "")[5:16].replace("T", " ")
            ch = await db.get_channel(s["channel_chat_id"])
            nombre = (ch["title"] if ch else None) or str(
                s["channel_chat_id"])
            if s["status"] == "ok":
                icono = "✅"
                extra = ""
            else:
                icono = "⚠️"
                extra = f" — {s['error']}"
            lineas.append(f"{icono} {cuando} · {nombre[:24]}{extra}")
        texto = "\n".join(lineas)
        if len(texto) > 3900:
            texto = texto[:3900] + "\n…"
    if isinstance(evento, Message):
        await evento.answer(texto, reply_markup=kb.volver())
    else:
        await evento.answer()
        await evento.message.edit_text(texto, reply_markup=kb.volver())


# ---------------------------------------------------------------------------
# AGENDA (tareas programadas en memoria)
# ---------------------------------------------------------------------------
@router.callback_query(F.data == "menu:agenda")
async def ver_agenda(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    trabajos = scheduler.get_jobs()
    if not trabajos:
        await callback.message.edit_text(
            "📅 <b>Agenda</b>\n\nNo hay tareas programadas ahora mismo.",
            reply_markup=kb.volver())
        return
    lineas = []
    for j in sorted(trabajos, key=lambda x: str(x.next_run_time)):
        cuando = j.next_run_time
        cuando_txt = cuando.strftime("%d/%m %H:%M") if cuando else "—"
        if j.id.startswith("cron_camp_"):
            etiqueta = "🚀 Campaña (recurrente)"
        elif j.id.startswith("ally_"):
            etiqueta = "🤝 Alianza (recurrente)"
        elif j.id.startswith("del_"):
            etiqueta = "🗑️ Autoborrado"
        elif j.id.startswith("retry_"):
            etiqueta = "🔁 Reintento de fallidos"
        elif j.id.startswith(("send_", "prog", "camp")):
            etiqueta = "⚡ Envío programado"
        else:
            etiqueta = "🔧 Tarea"
        lineas.append(f"• {cuando_txt} — {etiqueta}")
    texto = ("📅 <b>Agenda</b> (próximas tareas)\n\n"
             + "\n".join(lineas[:40]))
    if len(trabajos) > 40:
        texto += f"\n\n(y {len(trabajos) - 40} más)"
    await callback.message.edit_text(texto, reply_markup=kb.volver())


# ---------------------------------------------------------------------------
# AJUSTES
# ---------------------------------------------------------------------------
@router.callback_query(F.data == "menu:settings")
async def ver_ajustes(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    await callback.message.edit_text(
        f"⚙️ <b>Ajustes</b>\n\n"
        f"• Zona horaria actual: <b>{config.DEFAULT_TZ}</b>\n"
        f"• Pausa entre envíos: {config.SEND_DELAY} s\n"
        f"• Base de datos: <code>{config.DB_PATH}</code>",
        reply_markup=kb.menu_ajustes())
@router.callback_query(F.data == "set:tz")
async def ajuste_tz(callback: CallbackQuery):
    await callback.answer()
    await callback.message.edit_text(
        "🕙 <b>Zona horaria</b>\n\n"
        f"Ahora mismo el bot trabaja en <b>{config.DEFAULT_TZ}</b>.\n\n"
        "Para cambiarla, ve a Railway → tu servicio → pestaña "
        "<b>Variables</b> → variable <code>TZ</code> y pon, por ejemplo, "
        "<code>Europe/Madrid</code>. El bot se reinicia solo y aplica el "
        "cambio.\n\nTodas las horas de las campañas se calculan en esa zona.",
        reply_markup=kb.volver("menu:settings"))
@router.callback_query(F.data == "set:delall")
async def ajuste_delall(callback: CallbackQuery):
    await callback.answer()
    b = InlineKeyboardBuilder()
    b.button(text="✅ Sí, borrar todo", callback_data="set:delall:yes")
    b.button(text="❌ No", callback_data="menu:settings")
    b.adjust(1)
    await callback.message.edit_text(
        "🧹 <b>Borrar TODAS las publicaciones</b>\n\n"
        "Esto borrará de los canales todas las publicaciones que el bot "
        "tenga pendientes de autoborrado. ¿Seguro?",
        reply_markup=b.as_markup())
@router.callback_query(F.data == "set:delall:yes")
@router.message(Command("delall"))
async def hacer_delall(evento):
    es_msg = isinstance(evento, Message)
    bot = evento.bot
    if not es_msg:
        await evento.answer("Borrando...")
    pendientes = await db.pending_deletes()
    borradas = 0
    for s in pendientes:
        if not s["dest_message_id"]:
            continue
        try:
            await bot.delete_message(s["channel_chat_id"],
                                     s["dest_message_id"])
            borradas += 1
        except Exception:
            pass
        await db.mark_deleted(s["id"])
    texto = (f"🧹 <b>Borrado global terminado</b>\n\n"
             f"Publicaciones borradas: <b>{borradas}</b>")
    if es_msg:
        await evento.answer(texto, reply_markup=kb.menu_principal())
    else:
        await evento.message.edit_text(texto,
                                       reply_markup=kb.menu_principal())


# ---------------------------------------------------------------------------
# PAUSAR / REANUDAR TODO
# ---------------------------------------------------------------------------
@router.callback_query(F.data == "set:pauseall")
async def pausar_todo(callback: CallbackQuery):
    await callback.answer()
    campanas = await db.get_campaigns()
    alianzas = await db.get_alliances()
    n = 0
    for c in campanas:
        if c["active"]:
            await db.set_campaign_active(c["id"], False)
            broadcaster.quitar_campana(c["id"])
            n += 1
    for a in alianzas:
        if a["active"]:
            await db.set_alliance_active(a["id"], False)
            broadcaster.quitar_alianza(a["id"])
            n += 1
    await callback.message.edit_text(
        f"⏸️ <b>Todo pausado</b>\n\n"
        f"Se han pausado {n} campañas y alianzas. No se publicará nada "
        f"hasta que reanudes. Los envíos ya programados sí se completan.",
        reply_markup=kb.volver("menu:settings"))


@router.callback_query(F.data == "set:resumeall")
async def reanudar_todo(callback: CallbackQuery):
    await callback.answer()
    campanas = await db.get_campaigns()
    alianzas = await db.get_alliances()
    n = 0
    for c in campanas:
        if not c["active"]:
            await db.set_campaign_active(c["id"], True)
            camp = await db.get_campaign(c["id"])
            broadcaster.registrar_campana(callback.bot, camp)
            n += 1
    for a in alianzas:
        if not a["active"]:
            await db.set_alliance_active(a["id"], True)
            ally = await db.get_alliance(a["id"])
            broadcaster.registrar_alianza(callback.bot, ally)
            n += 1
    await callback.message.edit_text(
        f"▶️ <b>Todo reanudado</b>\n\n"
        f"Se han reactivado {n} campañas y alianzas. Vuelven a funcionar "
        f"en sus días y horas.",
        reply_markup=kb.volver("menu:settings"))


# ---------------------------------------------------------------------------
# MODO NO MOLESTAR (silenciar avisos de bloque)
# ---------------------------------------------------------------------------
@router.callback_query(F.data == "set:quiet")
async def ver_quiet(callback: CallbackQuery):
    await callback.answer()
    actual = await db.get_setting("quiet", "0")
    estado = "🔕 SILENCIADO" if actual == "1" else "🔔 ACTIVADO"
    b = InlineKeyboardBuilder()
    if actual == "1":
        b.button(text="🔔 Volver a recibir avisos",
                 callback_data="set:quiet:off")
    else:
        b.button(text="🔕 Silenciar avisos de bloque",
                 callback_data="set:quiet:on")
    b.button(text="⬅️ Volver", callback_data="menu:settings")
    b.adjust(1)
    await callback.message.edit_text(
        f"🔕 <b>Avisos de bloque</b>\n\n"
        f"Estado actual: <b>{estado}</b>\n\n"
        f"Si lo silencias, el bot <b>no</b> te enviará el mensaje de cada "
        f"bloque enviado con éxito ni el de cada alianza publicada. "
        f"Los avisos importantes (errores, fallos, canales sin permiso, "
        f"alguien que quita el bot) <b>siempre llegan</b>.",
        reply_markup=b.as_markup())


@router.callback_query(F.data == "set:quiet:on")
async def quiet_on(callback: CallbackQuery):
    await db.set_setting("quiet", "1")
    await callback.answer("Avisos de bloque silenciados")
    await ver_quiet(callback)


@router.callback_query(F.data == "set:quiet:off")
async def quiet_off(callback: CallbackQuery):
    await db.set_setting("quiet", "0")
    await callback.answer("Avisos reactivados")
    await ver_quiet(callback)


# ---------------------------------------------------------------------------
# MODO DE DIFUSIÓN (copiar vs reenviar)
# ---------------------------------------------------------------------------
@router.callback_query(F.data == "set:mode")
async def ver_modo(callback: CallbackQuery):
    await callback.answer()
    actual = await db.get_setting("modo_difusion", "copiar")
    nombre = "📋 Copiar" if actual == "copiar" else "↪️ Reenviar"
    await callback.message.edit_text(
        f"📡 <b>Modo de difusión</b>\n\n"
        f"Modo actual: <b>{nombre}</b>\n\n"
        f"<b>📋 Copiar</b> — la publicación sale limpia, sin etiqueta. "
        f"Pero los emojis premium animados NO se ven en los canales de "
        f"las chicas (solo donde haya una cuenta Premium).\n\n"
        f"<b>↪️ Reenviar</b> — la publicación lleva una etiqueta pequeña "
        f"«Reenviado de...», pero los <b>emojis premium SÍ se ven "
        f"animados</b> en todos los canales.\n\n"
        f"⚠️ Para que «Reenviar» funcione, las promos deben estar "
        f"guardadas <b>reenviándolas desde un canal tuyo</b>, no escritas "
        f"en el chat privado.",
        reply_markup=kb.modo_difusion(actual))


@router.callback_query(F.data.startswith("setmode:"))
async def set_modo(callback: CallbackQuery):
    modo = callback.data.split(":")[1]
    await db.set_setting("modo_difusion", modo)
    nombre = "📋 Copiar" if modo == "copiar" else "↪️ Reenviar"
    await callback.answer(f"Modo: {nombre}")
    aviso = ""
    if modo == "reenviar":
        aviso = ("\n\n📌 Recuerda: las promos tienen que venir de un canal "
                 "tuyo (reenviadas al bot), no escritas en el chat privado. "
                 "Si alguna no funciona, recréala reenviándola desde tu "
                 "canal almacén.")
    await callback.message.edit_text(
        f"✅ <b>Modo de difusión cambiado a {nombre}</b>{aviso}",
        reply_markup=kb.volver("menu:settings"))
