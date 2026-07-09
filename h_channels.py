# -*- coding: utf-8 -*-
"""
h_channels.py
Gestión de canales: añadir (cualquier formato), importar en lote,
listar, etiquetar por región/categoría, verificar permisos, suscriptores.
Incluye la captura AUTOMÁTICA: si añades el bot como admin a un canal,
ese canal se registra solo.
"""
import re
import asyncio
import logging

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, ChatMemberUpdated

import keyboards as kb
import database as db
import config
import broadcaster
from guard import IsOwner
from states import (AddChannel, BulkImport, MoveChannel, SearchChannel,
                    ChannelTopics)

router = Router()
router.message.filter(IsOwner())
router.callback_query.filter(IsOwner())

log = logging.getLogger("mala-bot.channels")


# ---------------------------------------------------------------------------
# UTILIDADES
# ---------------------------------------------------------------------------
async def resolver_chat(bot, texto: str):
    """
    Convierte lo que pegue el usuario en un chat real de Telegram.
    Acepta: @usuario, t.me/usuario, ID numérico -100...
    Los enlaces de invitación privados (t.me/+...) NO se pueden resolver:
    en ese caso hay que añadir el bot como admin (se captura solo).
    Devuelve (chat, error_texto).
    """
    t = texto.strip()
    if not t:
        return None, "vacío"

    if "t.me/+" in t or "joinchat" in t:
        return None, ("Es un enlace de invitación privado. Añade el bot "
                      "como administrador a ese canal y aparecerá solo.")

    objetivo = None
    if re.fullmatch(r"-?\d{5,}", t):
        objetivo = int(t)
    elif t.startswith("@"):
        objetivo = t
    elif "t.me/" in t:
        usuario = t.split("t.me/")[-1].split("/")[0].split("?")[0]
        objetivo = "@" + usuario
    else:
        objetivo = "@" + t.lstrip("@")

    try:
        chat = await bot.get_chat(objetivo)
        return chat, None
    except Exception as e:
        return None, f"No se pudo acceder: {e}"


async def verificar_permisos(bot, chat_id: int, exigir_borrado: bool = True):
    """
    Comprueba si el bot puede PUBLICAR en el chat.
    - En CANALES: necesita ser admin con permiso de publicar. El permiso
      de borrar solo se exige si exigir_borrado=True (autoborrado >48h o
      canales de las chicas, donde sí se borra).
    - En GRUPOS/supergrupos: con ser miembro basta para publicar; el
      autoborrado de menos de 48h también funciona sin ser admin.
    """
    try:
        miembro = await bot.get_chat_member(chat_id, bot.id)
    except Exception as e:
        return False, f"el bot no está en el canal ({e})"

    status = getattr(miembro, "status", "")
    if status in ("left", "kicked"):
        return False, "el bot no está en el chat"

    # Averiguar si es grupo o canal.
    es_grupo = False
    try:
        chat = await bot.get_chat(chat_id)
        es_grupo = getattr(chat, "type", "") in ("group", "supergroup")
    except Exception:
        # Si no podemos saberlo, nos guiamos por lo guardado en la BD.
        ch = await db.get_channel(chat_id)
        if ch and ch["ctype"] in ("group", "supergroup"):
            es_grupo = True

    if es_grupo:
        # En grupos, ser miembro (o admin) ya permite publicar.
        return True, "OK (grupo: basta con ser miembro)"

    # --- A partir de aquí, es un CANAL ---
    if status != "administrator":
        return False, "el bot NO es administrador"
    puede_publicar = getattr(miembro, "can_post_messages", None)
    puede_borrar = getattr(miembro, "can_delete_messages", None)
    faltan = []
    if puede_publicar is False:
        faltan.append("Publicar mensajes")
    if exigir_borrado and puede_borrar is False:
        faltan.append("Eliminar mensajes")
    if faltan:
        return False, "faltan permisos: " + ", ".join(faltan)
    return True, "OK"


async def verificar_con_reintento(bot, chat_id: int, intentos: int = 3):
    """
    Igual que verificar_permisos pero reintenta unos segundos si falla.
    Telegram tarda a veces en registrar al bot como miembro de un
    supergrupo recién configurado, y da un "no es miembro" falso.
    Reintentando con pausa evitamos ese susto.
    """
    ok, motivo = await verificar_permisos(bot, chat_id)
    intento = 1
    while not ok and intento < intentos:
        await asyncio.sleep(4)
        ok, motivo = await verificar_permisos(bot, chat_id)
        intento += 1
    return ok, motivo


async def registrar_chat(bot, chat) -> tuple[bool, bool]:
    """Guarda un chat en la BD y verifica permisos. (nuevo, admin_ok)."""
    nuevo = await db.add_channel(
        chat.id, chat.username or "", chat.title or "", chat.type)
    ok, _ = await verificar_permisos(bot, chat.id)
    await db.set_channel_admin(chat.id, ok)
    await refrescar_propietario(bot, chat.id)
    return nuevo, ok


async def refrescar_propietario(bot, chat_id: int) -> None:
    """
    Busca quién es el dueño (creador) del canal y guarda su perfil.
    Telegram no avisa cuando alguien cambia su nombre, así que esto se
    vuelve a llamar cada vez que el bot mira el canal (al verificar,
    al abrir la parrilla...). Así el perfil siempre sale actualizado.
    """
    try:
        admins = await bot.get_chat_administrators(chat_id)
    except Exception:
        return
    for m in admins:
        if getattr(m, "status", "") == "creator":
            u = getattr(m, "user", None)
            if u is None:
                return
            nombre = (getattr(u, "first_name", "") or "").strip()
            apellido = (getattr(u, "last_name", "") or "").strip()
            completo = (nombre + " " + apellido).strip()
            await db.set_channel_owner(
                chat_id, getattr(u, "id", 0) or 0,
                completo, getattr(u, "username", "") or "")
            return
    # Si nadie figura como "creator", el dueño está oculto/anónimo.
    await db.set_channel_owner(chat_id, 0, "", "")


def texto_canal(ch) -> str:
    """Nombre del canal + perfil del propietario, para mostrar en listas."""
    nombre = ch["title"] or (("@" + ch["username"]) if ch["username"]
                             else str(ch["chat_id"]))
    owner = ""
    try:
        on = ch["owner_name"]
        ou = ch["owner_username"]
    except Exception:
        on, ou = "", ""
    if ou:
        owner = f" · 👤 {on or '—'} (@{ou})"
    elif on:
        owner = f" · 👤 {on}"
    else:
        owner = " · 👤 oculto"
    return f"{nombre}{owner}"


# ---------------------------------------------------------------------------
# CAPTURA AUTOMÁTICA  (bot añadido/ascendido en un canal)
# ---------------------------------------------------------------------------
# Cuando una creadora añade el bot, Telegram manda VARIOS eventos seguidos
# (uno al entrar, otro al darle permisos de admin). Para no procesar el
# mismo canal varias veces (ni avisarte por duplicado ni duplicar el
# registro), juntamos todos los eventos del mismo canal: esperamos unos
# segundos y procesamos UNA sola vez, ya con el estado final.
_pendientes: dict = {}          # chat_id -> "marca de tiempo" del último evento
_ESPERA_AGRUPACION = 6          # segundos que esperamos a que lleguen todos


@router.my_chat_member()
async def bot_aniadido(event: ChatMemberUpdated):
    """Detecta cambios del bot en un canal/grupo."""
    estado_nuevo = event.new_chat_member.status
    estado_viejo = event.old_chat_member.status
    chat = event.chat
    titulo = chat.title or chat.username or str(chat.id)

    # --- Expulsado / eliminado del canal ---
    if estado_nuevo in ("left", "kicked"):
        # Recuperamos los datos del canal ANTES de borrarlo, para el aviso
        # y para guardarlo en la lista de expulsados.
        ch = await db.get_channel(chat.id)
        if ch:
            nombre = ch["title"] or (("@" + ch["username"]) if ch["username"]
                                     else str(chat.id))
            if ch["owner_username"]:
                dueno = f"{ch['owner_name'] or '—'} (@{ch['owner_username']})"
            elif ch["owner_name"]:
                dueno = ch["owner_name"]
            else:
                dueno = "oculto"
            region = ch["region"]
            await db.add_removed(
                chat.id, ch["title"] or "", ch["username"] or "",
                ch["owner_name"] or "", ch["owner_username"] or "",
                region, "quitó el bot")
        else:
            nombre = chat.title or chat.username or str(chat.id)
            dueno = "—"
            region = "—"
            await db.add_removed(chat.id, chat.title or "",
                                 chat.username or "", "", "", "—",
                                 "quitó el bot")
        await db.delete_channel(chat.id)
        await _avisar(event.bot,
                      f"🚫 <b>Te han quitado el bot</b>\n\n"
                      f"📡 Canal: <b>{nombre}</b>\n"
                      f"👤 Propietario: {dueno}\n"
                      f"📍 Estaba en: {region}\n\n"
                      f"Lo he borrado de tu lista y lo he apuntado en "
                      f"📡 Canales → 🚷 Expulsados.")
        return

    # --- Sigue dentro pero ya NO es administrador ---
    if estado_viejo == "administrator" and estado_nuevo == "member":
        await db.set_channel_admin(chat.id, False)
        await _avisar(event.bot,
                      f"⚠️ <b>El bot ya no es administrador</b>\n"
                      f"En el canal <b>{titulo}</b> han quitado al bot los "
                      f"permisos de admin. No podrá publicar ahí hasta que "
                      f"se los devuelvan.")
        return

    # --- Añadido o ascendido a administrador ---
    if estado_nuevo in ("administrator", "member"):
        # Registramos el canal YA (es atómico, no duplica), pero el AVISO
        # se procesa una sola vez tras la espera de agrupación.
        await db.add_channel(chat.id, chat.username or "",
                             chat.title or "", chat.type)
        import time
        ahora = time.monotonic()
        _pendientes[chat.id] = ahora
        await asyncio.sleep(_ESPERA_AGRUPACION)
        # Si llegó otro evento del mismo canal después de este, que lo
        # procese aquel: este se calla.
        if _pendientes.get(chat.id) != ahora:
            return
        _pendientes.pop(chat.id, None)
        await _procesar_canal_nuevo(event.bot, chat.id, titulo)


async def _procesar_canal_nuevo(bot, chat_id: int, titulo: str) -> None:
    """Procesa UNA sola vez un canal recién añadido: verifica permisos,
    limpia duplicados y manda un único aviso."""
    ok, motivo = await verificar_con_reintento(bot, chat_id)
    await db.set_channel_admin(chat_id, ok)
    await refrescar_propietario(bot, chat_id)
    # Limpiar duplicados (mismo ID, mismo @usuario o mismo título+dueño).
    await db.clean_duplicates()
    ch_actual = await db.get_channel(chat_id)
    if not ch_actual:
        return
    ya_ubicado = bool(ch_actual["slot"])
    es_grupo = ch_actual["ctype"] in ("group", "supergroup")
    tipo = "Grupo" if es_grupo else "Canal"

    try:
        if not ok:
            if es_grupo:
                # En un grupo, lo único que puede fallar es que el bot no
                # esté dentro. No hace falta admin.
                aviso_permiso = (
                    f"🚫 <b>El bot no está dentro del grupo.</b>\n"
                    f"Motivo: {motivo}\n\n"
                    f"En un grupo NO hace falta hacerlo admin: basta con "
                    f"que el bot sea <b>miembro</b>. Pídele a la chica que "
                    f"lo añada al grupo y que deje publicar al bot.")
            else:
                aviso_permiso = (
                    f"🚫 <b>El bot NO podrá publicar aquí.</b>\n"
                    f"Motivo: {motivo}\n\n"
                    f"La creadora debe entrar en su canal → Administradores "
                    f"→ y dar al bot permisos de <b>Publicar mensajes</b> y "
                    f"<b>Eliminar mensajes</b>.")
            await bot.send_message(
                config.OWNER_ID,
                f"⚠️⚠️ <b>ATENCIÓN — REVISAR</b> ⚠️⚠️\n\n"
                f"📡 {tipo}: <b>{titulo}</b>\n\n{aviso_permiso}\n\n"
                f"Cuando esté listo, pulsa el botón para recomprobar 👇",
                reply_markup=kb.recomprobar_canal(chat_id))
        elif ya_ubicado:
            await bot.send_message(
                config.OWNER_ID,
                f"✅ <b>{tipo} detectado</b>: <b>{titulo}</b>\n"
                f"Listo para publicar.\n\n"
                f"Ya estaba en la región <b>{ch_actual['region']}</b>, "
                f"bloque {ch_actual['slot']}. No hay que hacer nada.")
        else:
            nota = ""
            if es_grupo:
                nota = ("\n\nℹ️ Es un <b>grupo</b>: con que el bot sea "
                        "miembro basta, no necesita ser admin.")
            await bot.send_message(
                config.OWNER_ID,
                f"✅ <b>{tipo} detectado</b>: <b>{titulo}</b>\n"
                f"Listo para publicar.{nota}\n\n"
                f"👇 Elige ya su <b>franja horaria</b>. Se añadirá solo "
                f"a la campaña de esa región, en el primer bloque con "
                f"hueco:",
                reply_markup=kb.elegir_region_aviso(chat_id))
    except Exception:
        pass


async def _avisar(bot, texto: str) -> None:
    """Envía un aviso al dueño del bot."""
    try:
        await bot.send_message(config.OWNER_ID, texto)
    except Exception as e:
        log.warning(f"No se pudo avisar al dueño: {e}")


# ---------------------------------------------------------------------------
# MENÚ CANALES
# ---------------------------------------------------------------------------
@router.callback_query(F.data == "menu:channels")
async def cb_menu_canales(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    total = await db.count_channels()
    await callback.message.edit_text(
        f"📡 <b>Canales</b>\n\nTienes <b>{total}</b> canales guardados.\n"
        f"Elige una opción:", reply_markup=kb.menu_canales())


# ---------- Añadir canal ----------
@router.callback_query(F.data == "ch:add")
async def cb_add(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(AddChannel.esperando_identificador)
    await callback.message.edit_text(
        "➕ <b>Añadir canal</b>\n\n"
        "Envíame el canal en cualquiera de estos formatos:\n"
        "• <code>@nombredelcanal</code>\n"
        "• <code>https://t.me/nombredelcanal</code>\n"
        "• <code>-1001234567890</code> (ID)\n\n"
        "💡 Si es un canal privado, mejor añade el bot como administrador "
        "y se guardará solo.\n\n/cancel para salir.",
        reply_markup=kb.volver("menu:channels"))
@router.message(AddChannel.esperando_identificador)
async def recibir_canal(message: Message, state: FSMContext):
    await state.clear()
    chat, error = await resolver_chat(message.bot, message.text or "")
    if error:
        await message.answer(f"❌ {error}", reply_markup=kb.menu_canales())
        return
    nuevo, ok = await registrar_chat(message.bot, chat)
    estado = "nuevo" if nuevo else "actualizado"
    permiso = "✅ Permisos OK" if ok else "⚠️ Falta hacer al bot admin"
    await message.answer(
        f"📡 Canal {estado}: <b>{chat.title}</b>\n{permiso}",
        reply_markup=kb.menu_canales())


# ---------- Importar en lote ----------
@router.callback_query(F.data == "ch:bulk")
async def cb_bulk(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(BulkImport.esperando_lista)
    await callback.message.edit_text(
        "📥 <b>Importar lista</b>\n\n"
        "Pega varios canales separados por saltos de línea, comas o espacios. "
        "Se aceptan @usuarios, enlaces o IDs.\n\n/cancel para salir.",
        reply_markup=kb.volver("menu:channels"))
@router.message(BulkImport.esperando_lista)
async def recibir_lista(message: Message, state: FSMContext):
    await state.clear()
    piezas = re.split(r"[\s,]+", (message.text or "").strip())
    piezas = [p for p in piezas if p]
    if not piezas:
        await message.answer("❌ Lista vacía.", reply_markup=kb.menu_canales())
        return
    aviso = await message.answer(f"⏳ Importando {len(piezas)} canales...")
    nuevos, actualizados, errores = 0, 0, 0
    for p in piezas:
        chat, error = await resolver_chat(message.bot, p)
        if error:
            errores += 1
            continue
        nuevo, _ = await registrar_chat(message.bot, chat)
        if nuevo:
            nuevos += 1
        else:
            actualizados += 1
    await aviso.edit_text(
        f"📥 <b>Importación terminada</b>\n"
        f"• Nuevos: {nuevos}\n• Actualizados: {actualizados}\n"
        f"• Errores: {errores}")
    await message.answer("Listo.", reply_markup=kb.menu_canales())


# ---------- Listar / etiquetar ----------
@router.callback_query(F.data.startswith("ch:list:"))
@router.callback_query(F.data.startswith("ch:taglist:"))
async def cb_listar(callback: CallbackQuery):
    await callback.answer()
    pagina = int(callback.data.split(":")[-1])
    canales = await db.get_channels()
    if not canales:
        await callback.message.edit_text(
            "📋 No tienes canales todavía.", reply_markup=kb.menu_canales())
        return
    await callback.message.edit_text(
        f"📋 <b>Canales</b> ({len(canales)})\n"
        f"✅ = permisos OK · ⚠️ = revisar\n"
        f"Toca uno para editarlo:",
        reply_markup=kb.lista_canales(canales, pagina, "open"))
@router.callback_query(F.data.startswith("ch:open:"))
async def cb_ficha(callback: CallbackQuery):
    await callback.answer()
    chat_id = int(callback.data.split(":")[-1])
    ch = await db.get_channel(chat_id)
    if not ch:
        await callback.answer("Canal no encontrado", show_alert=True)
        return
    permiso = "✅ OK" if ch["is_admin"] else "⚠️ revisar permisos"
    # Refrescamos el perfil del dueño al abrir la ficha.
    await refrescar_propietario(callback.bot, chat_id)
    ch = await db.get_channel(chat_id)
    bloque = ch["slot"] if ch["slot"] else "— (sin región)"
    if ch["owner_username"]:
        dueno = f"{ch['owner_name'] or '—'} (@{ch['owner_username']})"
    elif ch["owner_name"]:
        dueno = ch["owner_name"]
    else:
        dueno = "oculto / anónimo"
    modo_txt, destino_txt = await _texto_repost(ch)
    await callback.message.edit_text(
        f"📡 <b>{ch['title']}</b>\n"
        f"• Usuario: @{ch['username'] or '—'}\n"
        f"• 👤 Propietario: {dueno}\n"
        f"• ID: <code>{ch['chat_id']}</code>\n"
        f"• Región: {ch['region']}\n"
        f"• Categoría: {ch['category']}\n"
        f"• Bloque: {bloque}\n"
        f"• Permisos: {permiso}\n"
        f"• 🔁 Repost: {modo_txt} → {destino_txt}",
        reply_markup=kb.ficha_canal(chat_id))


@router.callback_query(F.data.startswith("ch:del:"))
async def cb_borrar_canal(callback: CallbackQuery):
    """Pide confirmación antes de borrar el canal."""
    await callback.answer()
    chat_id = int(callback.data.split(":")[-1])
    ch = await db.get_channel(chat_id)
    nombre = ch["title"] if ch else chat_id
    await callback.message.edit_text(
        f"🗑️ <b>¿Eliminar este canal?</b>\n\n«{nombre}»\n\n"
        f"Se quitará de tu lista y su hueco quedará libre. Esta acción no "
        f"se puede deshacer.",
        reply_markup=kb.confirmar_borrado("delch", chat_id, "menu:channels"))


@router.callback_query(F.data.startswith("delch:yes:"))
async def cb_borrar_canal_ok(callback: CallbackQuery):
    await callback.answer("Canal eliminado")
    chat_id = int(callback.data.split(":")[-1])
    await db.delete_channel(chat_id)
    canales = await db.get_channels()
    if canales:
        await callback.message.edit_text(
            f"✅ Canal eliminado.\n\n📋 <b>Canales</b> ({len(canales)})",
            reply_markup=kb.lista_canales(canales, 0, "open"))
    else:
        await callback.message.edit_text(
            "✅ Canal eliminado.\n\n📋 No quedan canales.",
            reply_markup=kb.menu_canales())


# ---------- Etiquetar región / categoría ----------
@router.callback_query(F.data.startswith("tag:region:"))
async def cb_tag_region(callback: CallbackQuery):
    await callback.answer()
    chat_id = int(callback.data.split(":")[-1])
    await callback.message.edit_text(
        "🏷️ Elige la <b>región</b>:",
        reply_markup=kb.elegir_region(chat_id))
@router.callback_query(F.data.startswith("tag:cat:"))
async def cb_tag_cat(callback: CallbackQuery):
    await callback.answer()
    chat_id = int(callback.data.split(":")[-1])
    await callback.message.edit_text(
        "🏷️ Elige la <b>categoría</b>:",
        reply_markup=kb.elegir_categoria(chat_id))
@router.callback_query(F.data.startswith("setregion:"))
async def cb_set_region(callback: CallbackQuery):
    _, chat_id, region = callback.data.split(":", 2)
    chat_id = int(chat_id)
    # Asignar región le da también un BLOQUE fijo (el primer hueco libre).
    slot = await db.assign_region(chat_id, region)
    await callback.answer(f"Región: {region} · bloque {slot}")
    await cb_ficha_directo(callback, chat_id)


@router.callback_query(F.data.startswith("setcat:"))
async def cb_set_cat(callback: CallbackQuery):
    _, chat_id, cat = callback.data.split(":", 2)
    await db.update_channel_tags(int(chat_id), category=cat)
    await callback.answer(f"Categoría: {cat}")
    await cb_ficha_directo(callback, int(chat_id))


# ---------- Región elegida desde el AVISO de canal detectado ----------
@router.callback_query(F.data.startswith("avregion:"))
async def cb_av_region(callback: CallbackQuery):
    _, chat_id, region = callback.data.split(":", 2)
    chat_id = int(chat_id)
    ch = await db.get_channel(chat_id)
    if not ch:
        await callback.answer("Ese canal ya no está", show_alert=True)
        return
    if region == "Alianza":
        # Las alianzas no llevan región: se gestionan en el menú Alianzas.
        await callback.answer("Marcado como alianza")
        await callback.message.edit_text(
            f"🤝 <b>{ch['title']}</b> queda como grupo de alianza.\n\n"
            f"No entrará en las campañas por región. Ve a "
            f"🤝 <b>Alianzas → ➕ Nueva alianza</b> para programarle "
            f"sus horas.")
        return
    slot = await db.assign_region(chat_id, region)
    if slot == 0:
        await callback.answer("⚠️ No se pudo guardar, reintenta", show_alert=True)
        await callback.message.edit_text(
            f"⚠️ No se pudo asignar la región a <b>{ch['title']}</b>.\n"
            f"Ábrelo en 📡 Canales y ponle la región a mano.")
        return
    await callback.answer(f"Región: {region}")
    # Tras fijar la región, preguntamos para el REPOST: ¿vende contenido o
    # solo findom? Esto NO afecta a la región ni a la campaña (que ya están
    # hechas arriba); solo decide a qué canal de repost irá su contenido.
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    b = InlineKeyboardBuilder()
    b.button(text="🛍️ Vende contenido",
             callback_data=f"rp:setmode:{chat_id}:contenido")
    b.button(text="🔗 Solo findom",
             callback_data=f"rp:setmode:{chat_id}:findom")
    b.adjust(1)
    await callback.message.edit_text(
        f"✅ <b>{ch['title']}</b> añadido.\n"
        f"• Región: <b>{region}</b>\n"
        f"• Bloque asignado: <b>{slot}</b>\n\n"
        f"Ya entra solo en la campaña de {region} (esto no cambia).\n\n"
        f"🔁 <b>Para el repost</b>: ¿esta chica vende contenido o "
        f"<b>solo</b> hace findom?\n"
        f"• <b>Vende contenido</b> → su canal va al repost de su región "
        f"(España/Latam).\n"
        f"• <b>Solo findom</b> → su canal va al repost Findom aparte.\n\n"
        f"Puedes cambiarlo cuando quieras desde su ficha.",
        reply_markup=b.as_markup())


async def _texto_repost(ch) -> tuple[str, str]:
    """Devuelve (modo_legible, destino_legible) para mostrar en la ficha."""
    try:
        excluido = bool(ch["repost_off"])
    except Exception:
        excluido = False
    try:
        modo = ch["repost_mode"] or "contenido"
    except Exception:
        modo = "contenido"
    if excluido:
        return ("🚫 Excluido", "no se republica")
    modo_txt = "🔗 Solo findom" if modo == "findom" else "🛍️ Vende contenido"
    etiqueta, dest_id = await db.repost_destino(ch)
    if etiqueta == "—":
        destino_txt = "no se reenvía"
    elif dest_id:
        destino_txt = f"canal {etiqueta}"
    else:
        destino_txt = f"{etiqueta} (canal sin configurar)"
    return modo_txt, destino_txt


async def cb_ficha_directo(callback: CallbackQuery, chat_id: int):
    ch = await db.get_channel(chat_id)
    if not ch:
        return
    permiso = "✅ OK" if ch["is_admin"] else "⚠️ revisar permisos"
    bloque = ch["slot"] if ch["slot"] else "— (sin región)"
    modo_txt, destino_txt = await _texto_repost(ch)
    await callback.message.edit_text(
        f"📡 <b>{ch['title']}</b>\n"
        f"• Usuario: @{ch['username'] or '—'}\n"
        f"• ID: <code>{ch['chat_id']}</code>\n"
        f"• Región: {ch['region']}\n"
        f"• Categoría: {ch['category']}\n"
        f"• Bloque: {bloque}\n"
        f"• Permisos: {permiso}\n"
        f"• 🔁 Repost: {modo_txt} → {destino_txt}",
        reply_markup=kb.ficha_canal(chat_id))


# ---------- Mover un canal a otro bloque ----------
@router.callback_query(F.data.startswith("ch:move:"))
async def cb_mover(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    chat_id = int(callback.data.split(":")[-1])
    ch = await db.get_channel(chat_id)
    if not ch or not ch["slot"]:
        await callback.message.edit_text(
            "🔀 Este canal aún no tiene región/bloque. Asígnale primero "
            "una región.", reply_markup=kb.volver("menu:channels"))
        return
    await state.set_state(MoveChannel.esperando_bloque)
    await state.update_data(chat_id=chat_id)
    await callback.message.edit_text(
        f"🔀 <b>Mover «{ch['title']}»</b>\n\n"
        f"Está en el <b>bloque {ch['slot']}</b> (región {ch['region']}).\n\n"
        f"Escribe el <b>número de bloque</b> al que quieres moverlo.\n"
        f"Recuerda: bloque 1 = la hora de inicio, bloque 2 = +1 intervalo, "
        f"etc.\n\n/cancel para salir.")


@router.message(MoveChannel.esperando_bloque)
async def recibir_bloque(message: Message, state: FSMContext):
    texto = (message.text or "").strip()
    if not texto.isdigit() or int(texto) < 1:
        await message.answer("❌ Escribe un número de bloque válido (1, 2, "
                              "3...).")
        return
    datos = await state.get_data()
    await state.clear()
    chat_id = datos["chat_id"]
    await db.set_channel_slot(chat_id, int(texto))
    ch = await db.get_channel(chat_id)
    await message.answer(
        f"✅ «{ch['title']}» movido al <b>bloque {texto}</b>.",
        reply_markup=kb.menu_canales())


# ---------- Ver parrilla (lista por bloques y horas) ----------
@router.callback_query(F.data == "ch:grid")
async def cb_grid_menu(callback: CallbackQuery):
    await callback.answer()
    await callback.message.edit_text(
        "🗓️ <b>Ver parrilla</b>\n\nElige la región cuya parrilla "
        "quieres ver:", reply_markup=kb.ver_parrilla_region())


@router.callback_query(F.data.startswith("grid:"))
async def cb_grid(callback: CallbackQuery):
    await callback.answer()
    region = callback.data.split(":", 1)[1]
    bloques = await db.channels_by_block(region, "Todas")
    if not bloques:
        await callback.message.edit_text(
            f"🗓️ <b>Parrilla · {region}</b>\n\n"
            f"Todavía no hay canales en esta región.",
            reply_markup=kb.ver_parrilla_region())
        return

    # Refrescar el perfil del dueño de cada canal de la región, para que
    # la parrilla muestre siempre los nombres de perfil actualizados.
    for num in bloques:
        for ch in bloques[num]:
            await refrescar_propietario(callback.bot, ch["chat_id"])
    bloques = await db.channels_by_block(region, "Todas")

    # Buscar la campaña de esa región para calcular horas y promos.
    camp = None
    for c in await db.get_campaigns():
        if c["region"] == region:
            camp = c
            break

    import datetime as _dt
    lineas = [f"🗓️ <b>Parrilla · {region}</b>"]
    if camp:
        promo_ids = [int(x) for x in str(camp["promo_ids"]).split(",") if x]
        rotar = camp["rotate_every"] or 0
        lineas.append(
            f"Campaña «{camp['name']}» · inicio "
            f"{camp['start_hour']:02d}:{camp['start_minute']:02d} "
            f"(hora local de {region})\n")
    else:
        promo_ids, rotar = [], 0
        lineas.append("⚠️ Sin campaña en esta región todavía.\n")

    # Cuántas veces se ha publicado con éxito en cada canal.
    conteo = await db.sends_count_by_channel()

    for num in sorted(bloques.keys()):
        canales = bloques[num]
        if camp:
            base = _dt.datetime(2000, 1, 1, camp["start_hour"],
                                camp["start_minute"])
            hora = (base + _dt.timedelta(
                minutes=(num - 1) * camp["interval_min"])).strftime("%H:%M")
            cabecera = f"⏰ <b>Bloque {num}</b> · {hora}"
            if promo_ids:
                if rotar and len(promo_ids) > 1:
                    p_idx = ((num - 1) // rotar) % len(promo_ids)
                else:
                    p_idx = 0
                p = await db.get_promo(promo_ids[p_idx])
                if p:
                    cabecera += f" · promo «{p['name']}»"
        else:
            cabecera = f"<b>Bloque {num}</b>"
        # Aviso si el bloque tiene menos de 5 canales (hueco sin rellenar).
        if len(canales) < db.TAM_BLOQUE:
            libres = db.TAM_BLOQUE - len(canales)
            cabecera += f"  ⚠️ {libres} hueco(s) libre(s)"
        lineas.append(cabecera)
        for ch in canales:
            veces = conteo.get(ch["chat_id"], 0)
            marca_admin = "" if ch["is_admin"] else " ⚠️"
            lineas.append(
                f"   • {texto_canal(ch)} · 📤{veces}{marca_admin}")
        lineas.append("")

    texto = "\n".join(lineas)
    if len(texto) > 3900:
        texto = texto[:3900] + "\n…(lista recortada)"
    try:
        await callback.message.edit_text(
            texto, reply_markup=kb.ver_parrilla_region())
    except Exception:
        # Si Telegram dice "message is not modified" u otro error de
        # edición, lo ignoramos: el contenido ya está a la vista.
        pass


# ---------- Verificar permisos de todos ----------
@router.callback_query(F.data == "ch:verify")
@router.message(Command("verify"))
async def verificar_todos(evento):
    es_msg = isinstance(evento, Message)
    bot = evento.bot
    if not es_msg:
        await evento.answer("Verificando...")
    canales = await db.get_channels()
    ok, mal = 0, 0
    detalle_mal = []
    for ch in canales:
        bien, motivo = await verificar_permisos(bot, ch["chat_id"])
        await db.set_channel_admin(ch["chat_id"], bien)
        if bien:
            # Aprovechamos para actualizar el perfil del dueño.
            await refrescar_propietario(bot, ch["chat_id"])
            ok += 1
        else:
            mal += 1
            detalle_mal.append(f"• {ch['title']}: {motivo}")
    texto = (f"🛂 <b>Verificación de permisos</b>\n\n"
             f"✅ Correctos: {ok}\n⚠️ Con problemas: {mal}")
    if detalle_mal:
        texto += "\n\n" + "\n".join(detalle_mal[:25])
    if es_msg:
        await evento.answer(texto, reply_markup=kb.menu_canales())
    else:
        await evento.message.edit_text(texto, reply_markup=kb.menu_canales())


# ---------- Suscriptores ----------
@router.callback_query(F.data == "ch:subs")
async def cb_subs(callback: CallbackQuery):
    await callback.answer("Contando suscriptores...")
    canales = await db.get_channels()
    lineas, total = [], 0
    for ch in canales[:40]:
        try:
            n = await callback.bot.get_chat_member_count(ch["chat_id"])
        except Exception:
            n = 0
        total += n
        lineas.append(f"• {ch['title']}: {n}")
    texto = (f"📶 <b>Suscriptores</b>\n\n" + "\n".join(lineas)
             + f"\n\n<b>Total mostrado: {total}</b>")
    if len(canales) > 40:
        texto += f"\n(Se muestran 40 de {len(canales)})"
    await callback.message.edit_text(texto, reply_markup=kb.menu_canales())
@router.message(Command("list"))
@router.message(Command("canales"))
async def cmd_list(message: Message):
    canales = await db.get_channels()
    await message.answer(
        f"📋 Tienes <b>{len(canales)}</b> canales.",
        reply_markup=kb.menu_canales())


# ---------- Buscar canal por nombre ----------
@router.callback_query(F.data == "ch:search")
async def cb_buscar(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(SearchChannel.esperando_texto)
    await callback.message.edit_text(
        "🔍 <b>Buscar canal</b>\n\n"
        "Escribe parte del nombre, del @usuario o del nombre del "
        "propietario. Te mostraré los que coincidan.\n\n/cancel para salir.")


@router.message(SearchChannel.esperando_texto)
async def recibir_busqueda(message: Message, state: FSMContext):
    await state.clear()
    texto = (message.text or "").strip().lower()
    if not texto:
        await message.answer("❌ Búsqueda vacía.",
                             reply_markup=kb.menu_canales())
        return
    todos = await db.get_channels()
    encontrados = []
    for ch in todos:
        campos = " ".join(str(x).lower() for x in [
            ch["title"] or "", ch["username"] or "",
            ch["owner_name"] or "", ch["owner_username"] or "",
            ch["chat_id"]])
        if texto in campos:
            encontrados.append(ch)
    if not encontrados:
        await message.answer(
            f"🔍 Sin resultados para «{texto}».",
            reply_markup=kb.menu_canales())
        return
    await message.answer(
        f"🔍 <b>{len(encontrados)} resultado(s)</b> para «{texto}».\n"
        f"Toca uno para abrirlo:",
        reply_markup=kb.lista_canales(encontrados, 0, "open"))


# ---------- Limpiar canales duplicados ----------
@router.callback_query(F.data == "ch:dedup")
async def cb_dedup(callback: CallbackQuery):
    await callback.answer("Buscando duplicados...")
    res = await db.clean_duplicates()
    if res["borrados"] == 0:
        await callback.message.edit_text(
            "🧹 <b>Limpiar duplicados</b>\n\n"
            "✅ No hay canales duplicados. Tu lista está limpia.",
            reply_markup=kb.menu_canales())
        return
    nombres = "\n".join(f"  • {n}" for n in res["detalle"][:20])
    await callback.message.edit_text(
        f"🧹 <b>Duplicados eliminados</b>\n\n"
        f"Se han quitado <b>{res['borrados']}</b> canales repetidos.\n"
        f"Se conservó uno bueno (con permisos ✅) de cada uno de estos:\n"
        f"{nombres}\n\n"
        f"Si un duplicado tenía región/bloque y el bueno no, se le pasó.",
        reply_markup=kb.menu_canales())


# ---------- Recomprobar permisos de un canal concreto ----------
@router.callback_query(F.data.startswith("ch:recheck:"))
async def cb_recheck(callback: CallbackQuery):
    await callback.answer("Comprobando...")
    chat_id = int(callback.data.split(":")[-1])
    ch = await db.get_channel(chat_id)
    if not ch:
        await callback.message.edit_text(
            "⚠️ Este canal ya no está en tu lista.")
        return
    # Avisamos de que puede tardar unos segundos (reintenta solo).
    try:
        await callback.message.edit_text(
            "🔄 Comprobando permisos... (espera unos segundos)")
    except Exception:
        pass
    ok, motivo = await verificar_con_reintento(callback.bot, chat_id)
    await db.set_channel_admin(chat_id, ok)
    await refrescar_propietario(callback.bot, chat_id)
    titulo = ch["title"] or str(chat_id)
    if ok:
        ya = ch["slot"]
        if ya:
            await callback.message.edit_text(
                f"✅ <b>¡Permisos correctos!</b>\n\n"
                f"El canal <b>{titulo}</b> ya puede recibir publicaciones. "
                f"Está en {ch['region']}, bloque {ch['slot']}.")
        else:
            await callback.message.edit_text(
                f"✅ <b>¡Permisos correctos!</b>\n\n"
                f"El canal <b>{titulo}</b> ya puede publicar.\n"
                f"👇 Elige ahora su <b>franja horaria</b>:",
                reply_markup=kb.elegir_region_aviso(chat_id))
    else:
        await callback.message.edit_text(
            f"🚫 <b>Todavía faltan permisos</b>\n\n"
            f"Canal: <b>{titulo}</b>\nMotivo: {motivo}\n\n"
            f"La creadora aún no le ha dado al bot los permisos de "
            f"<b>Publicar mensajes</b> y <b>Eliminar mensajes</b> como "
            f"administrador. Cuando lo haga, vuelve a pulsar 👇",
            reply_markup=kb.recomprobar_canal(chat_id))


# ---------- Hilos de foro de un canal/grupo ----------
AYUDA_HILOS = (
    "🧵 <b>Hilos de foro (temas)</b>\n\n"
    "Si este grupo tiene <b>temas</b> activados, puedo publicar en el "
    "hilo que tú quieras en vez de en #General.\n\n"
    "<b>Cómo conseguir el enlace de un hilo:</b>\n"
    "1. Entra en el grupo y abre el tema.\n"
    "2. Mantén pulsado el nombre del tema (o un mensaje del tema) → "
    "<b>Copiar enlace</b>.\n"
    "3. Pégalo aquí. Tiene esta forma:\n"
    "<code>https://t.me/c/2412345678/45</code>\n\n"
    "<b>Para añadir VARIOS hilos a la vez:</b> pega varios enlaces "
    "separados por un espacio o un salto de línea. Ejemplo:\n"
    "<code>https://t.me/c/2412345678/45 https://t.me/c/2412345678/12</code>"
)


def _texto_hilos_actuales(ch) -> str:
    hilos = db.topics_a_texto(ch["topics"])
    if not hilos:
        return "Ahora mismo publico en <b>#General</b> (sin hilo)."
    lista = ", ".join(f"#{h}" for h in hilos)
    return f"Hilos actuales: <b>{lista}</b> ({len(hilos)})."


@router.callback_query(F.data.startswith("ch:topics:"))
async def cb_topics(callback: CallbackQuery):
    await callback.answer()
    chat_id = int(callback.data.split(":")[-1])
    ch = await db.get_channel(chat_id)
    if not ch:
        await callback.answer("No existe", show_alert=True)
        return
    hilos = db.topics_a_texto(ch["topics"])
    await callback.message.edit_text(
        f"🧵 <b>Hilos de «{ch['title']}»</b>\n\n"
        f"{_texto_hilos_actuales(ch)}\n\n"
        f"¿Qué quieres hacer?",
        reply_markup=kb.gestion_topics(chat_id, bool(hilos), "ch"))


@router.callback_query(F.data.startswith("chtop:add:"))
async def cb_topics_add(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    chat_id = int(callback.data.split(":")[-1])
    await state.set_state(ChannelTopics.esperando)
    await state.update_data(chat_id=chat_id, modo="add")
    await callback.message.edit_text(
        AYUDA_HILOS + "\n\n➕ Envíame el/los enlace(s) a <b>añadir</b>.\n"
        "/cancel para salir.")


@router.callback_query(F.data.startswith("chtop:set:"))
async def cb_topics_set(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    chat_id = int(callback.data.split(":")[-1])
    await state.set_state(ChannelTopics.esperando)
    await state.update_data(chat_id=chat_id, modo="set")
    await callback.message.edit_text(
        AYUDA_HILOS + "\n\n✏️ Envíame el/los enlace(s). Esto <b>reemplaza</b> "
        "todos los hilos anteriores.\n/cancel para salir.")


@router.callback_query(F.data.startswith("chtop:clear:"))
async def cb_topics_clear(callback: CallbackQuery):
    await callback.answer("Hilos quitados")
    chat_id = int(callback.data.split(":")[-1])
    await db.set_channel_topics(chat_id, [])
    ch = await db.get_channel(chat_id)
    await callback.message.edit_text(
        f"🧵 <b>Hilos de «{ch['title']}»</b>\n\n"
        f"✅ Quitados. Ahora publico en <b>#General</b>.\n\n¿Algo más?",
        reply_markup=kb.gestion_topics(chat_id, False, "ch"))


@router.message(ChannelTopics.esperando)
async def recibir_topics(message: Message, state: FSMContext):
    data = await state.get_data()
    await state.clear()
    chat_id = data["chat_id"]
    modo = data["modo"]
    nuevos = db.parsear_topics(message.text or "")
    if not nuevos:
        await message.answer(
            "❌ No reconocí ningún enlace de hilo válido. "
            "Asegúrate de pegar el enlace completo (t.me/c/.../número).",
            reply_markup=kb.gestion_topics(chat_id, False, "ch"))
        return
    ch = await db.get_channel(chat_id)
    actuales = db.topics_a_texto(ch["topics"])
    if modo == "add":
        final = actuales + [t for t in nuevos if t not in actuales]
    else:  # set
        final = nuevos
    await db.set_channel_topics(chat_id, final)
    ch = await db.get_channel(chat_id)
    lista = ", ".join(f"#{h}" for h in final)
    await message.answer(
        f"✅ <b>Hilos guardados</b> para «{ch['title']}».\n"
        f"Publicaré en: <b>{lista}</b> ({len(final)} hilo(s)).",
        reply_markup=kb.gestion_topics(chat_id, True, "ch"))


# ---------- Sección de canales expulsados (que han echado el bot) ----------
@router.callback_query(F.data == "ch:removed")
async def cb_removed(callback: CallbackQuery):
    await callback.answer()
    lista = await db.get_removed(50)
    if not lista:
        await callback.message.edit_text(
            "🚷 <b>Expulsados</b>\n\n"
            "Ningún canal o grupo ha quitado el bot. 🎉",
            reply_markup=kb.expulsados_acciones(False))
        return
    lineas = [f"🚷 <b>Expulsados</b> ({len(lista)})\n",
              "Canales/grupos que han quitado el bot:\n"]
    for r in lista:
        cuando = (r["removed_at"] or "")[5:16].replace("T", " ")
        nombre = r["title"] or (("@" + r["username"]) if r["username"]
                                else str(r["chat_id"]))
        if r["owner_username"]:
            dueno = f" · 👤 {r['owner_name'] or '—'} (@{r['owner_username']})"
        elif r["owner_name"]:
            dueno = f" · 👤 {r['owner_name']}"
        else:
            dueno = ""
        reg = f" · 📍{r['region']}" if r["region"] and r["region"] != "—" else ""
        lineas.append(f"• {cuando} — <b>{nombre}</b>{dueno}{reg}")
    texto = "\n".join(lineas)
    if len(texto) > 3900:
        texto = texto[:3900] + "\n…(lista recortada)"
    await callback.message.edit_text(
        texto, reply_markup=kb.expulsados_acciones(True))


@router.callback_query(F.data == "ch:removed_clear")
async def cb_removed_clear(callback: CallbackQuery):
    n = await db.clear_removed()
    await callback.answer(f"Lista limpiada ({n})", show_alert=True)
    await callback.message.edit_text(
        f"🧽 <b>Lista de expulsados limpiada</b>\n\n"
        f"Se borraron {n} registros. La sección está vacía.",
        reply_markup=kb.expulsados_acciones(False))
