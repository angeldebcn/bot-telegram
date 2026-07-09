# -*- coding: utf-8 -*-
"""
h_repost.py
FUNCIÓN NUEVA E INDEPENDIENTE: reenviar (repost) lo que publican las
creadoras en sus canales a unos canales "showcase" centrales.

Reglas que respeta a rajatabla:
  • NO toca el spam, ni las campañas, ni la región, ni la categoría.
    La región se sigue usando exactamente igual que siempre.
  • 3 canales de repost:
        - España  -> chicas de región España que venden contenido
        - Latam   -> chicas de Cono Sur / Caribe / Andina / México (contenido)
        - Findom  -> SOLO las chicas marcadas como "solo findom" (da igual
                     su región; siguen en su campaña normal).
  • El marcado "solo findom" es una simple excepción SOLO para el repost.

Qué se republica:
  • SOLO multimedia: fotos, vídeos, GIFs y álbumes (con o sin texto/caption
    adjunto). Los mensajes de solo texto, audios, notas de voz, stickers,
    documentos, encuestas, etc. se ignoran.

Filtro (para no colar promo de terceros en tus canales):
  • Enlaces de OnlyFans, Instagram, X, web, wishlists... -> se reenvían
    (son sus enlaces de venta, eso es lo que quieres).
  • Reenvíos de OTROS canales, enlaces t.me a otros canales/grupos,
    invitaciones (joinchat / +...), o menciones a otros canales que NO
    son de tu red -> NO se reenvía.

El listener de canales (channel_post) NO está filtrado por dueño (los
canales no escriben como tú). El resto de botones/menús sí son solo tuyos.
"""
import re
import asyncio
import logging
import random

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import (Message, CallbackQuery, InlineKeyboardButton,
                           InlineKeyboardMarkup)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import (TelegramBadRequest, TelegramForbiddenError,
                                TelegramRetryAfter)

import config
import database as db
import h_channels
from guard import IsOwner
from states import RepostSet, RepostBtn, RepostOwner

log = logging.getLogger("mala-repost")

router = Router()
# OJO: el filtro de dueño se aplica SOLO a mensajes y botones, NO a los
# channel_post (que llegan de los canales de las chicas, no de ti).
router.message.filter(IsOwner())
router.callback_query.filter(IsOwner())


# ===========================================================================
#  UTILIDADES DE DETECCIÓN (enlaces / menciones de Telegram)
# ===========================================================================
# Enlaces t.me / telegram.me y su variante tg://resolve?domain=
_TME = re.compile(
    r"(?:https?://)?(?:www\.)?(?:t\.me|telegram\.me|telegram\.dog)/"
    r"([^\s/?#]+)", re.I)
_TG_RESOLVE = re.compile(r"tg://resolve\?domain=([A-Za-z0-9_]+)", re.I)
# Menciones tipo @usuario (usuarios de Telegram: 5-32, empiezan por letra).
_MENTION = re.compile(r"(?<![\w@])@([A-Za-z][A-Za-z0-9_]{4,31})")

# Rutas de t.me que NO son promoción de un canal (se ignoran).
_TME_IGNORAR = {"share", "addstickers", "addemoji", "addtheme", "proxy",
                "socks", "login", "bg", "setlanguage", "confirmphone",
                "c", "iv"}

# Caché en memoria: @usuario -> "channel" | "user" | "none".
# (Los usernames casi nunca cambian de tipo; con la vida del proceso basta.)
_cache_tipo: dict = {}


def _urls_del_mensaje(msg: Message) -> list:
    """Todos los textos/enlaces donde puede haber un enlace de Telegram:
    el texto/caption, los enlaces ocultos (text_link) y los botones URL."""
    trozos = []
    trozos.append(msg.text or "")
    trozos.append(msg.caption or "")
    for e in (msg.entities or []) + (msg.caption_entities or []):
        if e.type == "text_link" and e.url:
            trozos.append(e.url)
    rm = msg.reply_markup
    if rm and getattr(rm, "inline_keyboard", None):
        for fila in rm.inline_keyboard:
            for btn in fila:
                if getattr(btn, "url", None):
                    trozos.append(btn.url)
                # tg://... a veces viene como login_url/url; lo cubrimos arriba.
    return trozos


def _targets_telegram(trozos: list) -> list:
    """Saca los 'destinos' de todos los enlaces de Telegram encontrados."""
    out = []
    for s in trozos:
        if not s:
            continue
        for m in _TME.finditer(s):
            out.append(m.group(1).lower())
        for m in _TG_RESOLVE.finditer(s):
            out.append(m.group(1).lower())
    return out


def _menciones(msg: Message) -> set:
    txt = (msg.text or "") + " " + (msg.caption or "")
    return {m.group(1).lower() for m in _MENTION.finditer(txt)}


def _es_multimedia(msg: Message) -> bool:
    """Solo republicamos contenido multimedia: foto, vídeo o GIF (animation).
    El texto/caption que lleven adjunto se conserva. Todo lo demás (mensajes
    de solo texto, audios, notas de voz, stickers, documentos, encuestas...)
    se ignora."""
    return bool(msg.photo or msg.video or msg.animation)


def _forward_de_otro_canal(msg: Message, permitidas: set,
                           origen_id: int) -> tuple:
    """(es_externa, motivo). Un reenvío de OTRO canal/grupo que no es el de la
    propietaria se considera promo externa. Reenvíos de personas se permiten."""
    fo = getattr(msg, "forward_origin", None)
    chat = None
    if fo is not None:
        chat = getattr(fo, "chat", None) or getattr(fo, "sender_chat", None)
    if chat is None:
        chat = getattr(msg, "forward_from_chat", None)  # respaldo
    if chat is None:
        return (False, "")
    cid = getattr(chat, "id", None)
    uname = (getattr(chat, "username", "") or "").lower()
    if cid == origen_id:
        return (False, "")                     # se reenvía a sí misma
    if uname and uname in permitidas:
        return (False, "")                     # es el canal de la propietaria
    quien = f"@{uname}" if uname else (getattr(chat, "title", "") or "otro canal")
    return (True, f"reenvío de {quien}")


async def _tipo_username(bot, uname: str) -> str:
    """Resuelve qué es un @usuario en Telegram: 'channel', 'user' o 'none'.
    'none' = no existe en Telegram (p.ej. es un handle de Instagram)."""
    if uname in _cache_tipo:
        return _cache_tipo[uname]
    tipo = "none"
    try:
        chat = await bot.get_chat("@" + uname)
        t = getattr(chat, "type", "")
        if t in ("channel", "supergroup", "group"):
            tipo = "channel"
        else:
            tipo = "user"
    except Exception:
        tipo = "none"
    _cache_tipo[uname] = tipo
    return tipo


async def _es_promo_externa(bot, msgs: list, permitidas: set,
                            owner_id: int, origen_id: int) -> tuple:
    """Devuelve (True, motivo) si el post lleva el @, mención, etiqueta,
    enlace o reenvío de ALGUIEN que NO es la propietaria del canal.
    'permitidas' = usernames en minúscula del canal y de la propietaria."""
    for msg in msgs:
        # 1) ¿Es un reenvío de otro canal (no el de la propietaria)?
        ext, motivo = _forward_de_otro_canal(msg, permitidas, origen_id)
        if ext:
            return (True, motivo)

        # 2) Enlaces t.me a otros canales/personas o invitaciones.
        for t in _targets_telegram(_urls_del_mensaje(msg)):
            if t in _TME_IGNORAR:
                continue
            if t == "joinchat" or t.startswith("+"):
                return (True, "enlace de invitación a otro canal/grupo")
            if t in permitidas:
                continue
            return (True, f"enlace a @{t} (no es la propietaria)")

        # 3) Menciones @ a CUALQUIER cuenta de Telegram que no sea la
        #    propietaria (ni un canal, ni otra persona). Resolvemos de verdad
        #    para no confundir un @instagram (que no existe en Telegram) con
        #    una cuenta real.
        revisadas = 0
        for u in _menciones(msg):
            if u in permitidas:
                continue
            if revisadas >= 6:        # tope para no saturar la API
                break
            revisadas += 1
            if await _tipo_username(bot, u) in ("channel", "user"):
                return (True, f"lleva el @ de otra persona (@{u})")

        # 4) Etiquetas a un usuario SIN @ (text_mention por ID): si no es la
        #    propietaria, fuera.
        for e in (msg.entities or []) + (msg.caption_entities or []):
            if e.type == "text_mention" and getattr(e, "user", None):
                if (e.user.id or 0) != owner_id:
                    nom = getattr(e.user, "first_name", "") or "otra persona"
                    return (True, f"etiqueta a {nom} (no es la propietaria)")

    return (False, "")


# ===========================================================================
#  BOTONES DEBAJO DE CADA PUBLICACIÓN  (perfil de la propietaria + canal)
# ===========================================================================
# Colores reales de Telegram (Bot API 9.4+): "" = normal, y primary/danger/
# success. aiogram 3.13 los deja pasar como campo extra, así que funcionan.
_STYLES = {"", "primary", "danger", "success"}
_STYLE_LABEL = {"": "⚪ Normal", "primary": "🔵 Azul",
                "danger": "🔴 Rojo", "success": "🟢 Verde"}

# Texto del mensajito que lleva los botones debajo de un ÁLBUM (no puede ser
# solo un emoji o Telegram lo agranda gigante).
_ALBUM_PIE = "𝙱𝙾𝚃𝙾𝙽𝙴𝚂:"

# Caché de enlaces de invitación de canales privados (evita llamadas repetidas).
_invite_cache: dict = {}


def _btn(text: str, url: str, style: str) -> InlineKeyboardButton:
    """Botón URL, con color si el estilo es válido."""
    if style in ("primary", "danger", "success"):
        return InlineKeyboardButton(text=text, url=url, style=style)
    return InlineKeyboardButton(text=text, url=url)


def _url_perfil(ch) -> str:
    """Enlace al perfil de la PROPIETARIA del canal.
    Prioridad: la @ que hayas asignado a mano (para canales comprados o con
    dueño distinto); si no, el propietario detectado automáticamente."""
    try:
        manual = (ch["girl_username"] or "").strip().lstrip("@")
    except Exception:
        manual = ""
    if manual:
        return f"https://t.me/{manual}"
    try:
        ou = (ch["owner_username"] or "").strip().lstrip("@")
    except Exception:
        ou = ""
    if ou:
        return f"https://t.me/{ou}"
    try:
        oid = ch["owner_id"] or 0
    except Exception:
        oid = 0
    if oid:
        return f"tg://user?id={oid}"   # abre el perfil por ID
    return ""


async def _url_canal(bot, ch, src_id: int) -> str:
    """Enlace al CANAL donde se subió la publicación.

    Para canales privados guardamos UN ÚNICO enlace de invitación por canal
    en la base de datos y lo reutilizamos siempre: nunca se crea uno nuevo por
    publicación, y sobrevive a los reinicios del bot. Tampoco se regenera el
    enlace principal de la chica (no usamos export, que lo revocaría)."""
    u = (ch["username"] or "").strip().lstrip("@")
    if u:
        return f"https://t.me/{u}"

    # 1) ¿Ya tenemos uno guardado para este canal? (lo normal tras la 1ª vez)
    if src_id in _invite_cache:
        return _invite_cache[src_id]
    guardado = await db.get_channel_invite(src_id)
    if guardado:
        _invite_cache[src_id] = guardado
        return guardado

    # 2) Primera vez: intentamos reutilizar el enlace principal que ya exista.
    link = ""
    try:
        chat = await bot.get_chat(src_id)
        link = getattr(chat, "invite_link", None) or ""
    except Exception:
        link = ""

    # 3) Si no hay ninguno, creamos UNO persistente (no revoca nada) y punto.
    if not link:
        try:
            inv = await bot.create_chat_invite_link(src_id, name="MALA Repost")
            link = getattr(inv, "invite_link", "") or ""
        except Exception:
            link = ""

    # Lo guardamos para no volver a crearlo nunca más.
    if link:
        await db.set_channel_invite(src_id, link)
        _invite_cache[src_id] = link
    return link


async def _kb_botones(bot, ch, src_id: int):
    """Los 2 botones (perfil + canal) en una MISMA fila, uno al lado del otro.
    Si algún enlace no se puede construir, ese botón se omite."""
    cfg = await db.get_repost_botones()
    fila = []
    up = _url_perfil(ch)
    if up:
        fila.append(_btn(cfg["b1_text"] or "👤 Perfil", up, cfg["b1_style"]))
    uc = await _url_canal(bot, ch, src_id)
    if uc:
        fila.append(_btn(cfg["b2_text"] or "📢 Canal", uc, cfg["b2_style"]))
    if not fila:
        return None
    return InlineKeyboardMarkup(inline_keyboard=[fila])


# ===========================================================================
#  LISTENER DE PUBLICACIONES DE LAS CREADORAS
# ===========================================================================
# Los álbumes (varias fotos) llegan como varios channel_post con el mismo
# media_group_id. Los juntamos unos segundos y los reenviamos como álbum.
_albumes: dict = {}
_ALBUM_ESPERA = 2.0


@router.channel_post()
async def on_channel_post(message: Message):
    """Entra CADA publicación de los canales donde el bot es admin."""
    try:
        await _procesar_post(message)
    except Exception as e:
        log.warning(f"Fallo procesando post de repost: {e}")
    # De vez en cuando limpiamos mapeos viejos (para que no crezca la tabla).
    if random.random() < 0.02:
        try:
            await db.prune_repost_map()
        except Exception:
            pass


@router.edited_channel_post()
async def on_edited_channel_post(message: Message):
    """Cuando una creadora EDITA una publicación (p.ej. le añade el texto
    después de subir el vídeo), actualizamos la copia del canal showcase."""
    try:
        await _procesar_edicion(message)
    except Exception as e:
        log.warning(f"Fallo procesando edición de repost: {e}")


async def _procesar_edicion(message: Message):
    if not await db.repost_enabled():
        return
    src_id = message.chat.id
    if src_id in await db.repost_destino_ids():
        return
    fila = await db.get_repost_map(src_id, message.message_id)
    if not fila:
        return   # esa publicación no la reposteamos (o ya se limpió)

    ch = await db.get_channel(src_id)
    if not ch:
        return
    dest_chat = fila["dest_chat"]
    dest_msg = fila["dest_msg"]
    mgid = fila["mgid"] or ""

    # Recalcular quién es la propietaria (para el filtro).
    owner_username = (ch["owner_username"] or "").strip().lower().lstrip("@")
    owner_id = ch["owner_id"] or 0
    permitidas = set()
    cu = (ch["username"] or "").strip().lower().lstrip("@")
    if cu:
        permitidas.add(cu)
    if owner_username:
        permitidas.add(owner_username)

    # Si al editar AÑADIÓ promo de otra persona/canal -> quitamos la copia.
    externa, motivo = await _es_promo_externa(
        message.bot, [message], permitidas, owner_id, src_id)
    if externa:
        await _borrar_copia(message.bot, src_id, message.message_id,
                            dest_chat, dest_msg, mgid)
        if await db.repost_notif():
            await _avisar_dueño(
                message.bot,
                f"🗑️ Quité una publicación ya reposteada porque al editarla "
                f"se añadió: {motivo}.")
        return

    # Actualizamos el texto (caption) de la copia, conservando su formato.
    nuevo_caption = message.caption or ""
    # En un álbum los botones van aparte (el elemento no admite botones);
    # en un post suelto conservamos los 2 botones al editar.
    kb_edit = None if mgid else await _kb_botones(message.bot, ch, src_id)
    try:
        await message.bot.edit_message_caption(
            chat_id=dest_chat, message_id=dest_msg,
            caption=nuevo_caption,
            caption_entities=message.caption_entities,
            parse_mode=None,               # usamos las entities tal cual
            reply_markup=kb_edit)
    except TelegramBadRequest as e:
        t = str(e).lower()
        if "not modified" in t or "there is no caption" in t \
                or "message can't be edited" in t:
            pass   # sin cambios reales o no editable: lo dejamos
        else:
            log.warning(f"No pude actualizar el caption de la copia: {e}")
    except Exception as e:
        log.warning(f"Edición de caption: error inesperado: {e}")


async def _borrar_copia(bot, src_id: int, src_msg: int, dest_chat: int,
                        dest_msg: int, mgid: str):
    """Borra la(s) copia(s) del canal showcase y limpia el mapeo."""
    borrar = []
    if mgid:
        for f in await db.get_repost_group(src_id, mgid):
            borrar.append((f["dest_chat"], f["dest_msg"]))
        await db.del_repost_group(src_id, mgid)
    else:
        borrar.append((dest_chat, dest_msg))
        await db.del_repost_map(src_id, src_msg)
    for dc, dm in borrar:
        try:
            await bot.delete_message(dc, dm)
        except Exception:
            pass


async def _procesar_post(message: Message):
    # Apagado global -> no hacemos nada (coste casi cero).
    if not await db.repost_enabled():
        return

    src_id = message.chat.id

    # Anti-bucle: nunca reenviamos desde los propios canales showcase.
    if src_id in await db.repost_destino_ids():
        return

    # ¿Es un canal de una creadora registrada?
    ch = await db.get_channel(src_id)
    if not ch:
        return

    # ¿A qué canal showcase va? (según región o marca findom)
    etiqueta, dest_id = await db.repost_destino(ch)
    if not dest_id:
        return   # región no enrutable (Alianza/Sin región) o canal sin poner

    # --- Álbum: acumular y procesar una sola vez ---
    mgid = message.media_group_id
    if mgid:
        # Solo nos interesan los álbumes de fotos/vídeos/GIFs. Si un elemento
        # no es multimedia (p.ej. un álbum de audios), lo ignoramos.
        if not _es_multimedia(message):
            return
        reg = _albumes.get(mgid)
        if reg is None:
            reg = {"msgs": [], "src": src_id, "dest": dest_id,
                   "bot": message.bot, "task": None, "ch": ch}
            _albumes[mgid] = reg
        reg["msgs"].append(message)
        if reg["task"]:
            reg["task"].cancel()
        reg["task"] = asyncio.create_task(_flush_album(mgid))
        return

    # --- Post suelto ---
    # Solo multimedia: nada de mensajes de solo texto, audios, voz, etc.
    if not _es_multimedia(message):
        return
    await _evaluar_y_reenviar(message.bot, ch, src_id, dest_id, [message])


async def _flush_album(mgid: str):
    try:
        await asyncio.sleep(_ALBUM_ESPERA)
    except asyncio.CancelledError:
        return
    reg = _albumes.pop(mgid, None)
    if not reg or not reg["msgs"]:
        return
    # Por si acaso, nos quedamos solo con los elementos multimedia.
    medios = [m for m in reg["msgs"] if _es_multimedia(m)]
    if not medios:
        return
    await _evaluar_y_reenviar(
        reg["bot"], reg["ch"], reg["src"], reg["dest"], medios)


async def _evaluar_y_reenviar(bot, ch, src_id: int, dest_id: int,
                              msgs: list):
    # Nos fijamos a fondo en quién es la PROPIETARIA. Si no la tenemos
    # guardada, la buscamos ahora (mira los admins del canal).
    owner_username = (ch["owner_username"] or "").strip().lower().lstrip("@")
    owner_id = ch["owner_id"] or 0
    if not owner_username or not owner_id:
        try:
            await h_channels.refrescar_propietario(bot, src_id)
            ch = await db.get_channel(src_id) or ch
            owner_username = (ch["owner_username"] or "").strip().lower().lstrip("@")
            owner_id = ch["owner_id"] or 0
        except Exception:
            pass

    # Lo único permitido: el @ del canal, el @ de la propietaria (detectada)
    # y el @ que hayas asignado a mano (canales comprados/con otro dueño).
    permitidas = set()
    cu = (ch["username"] or "").strip().lower().lstrip("@")
    if cu:
        permitidas.add(cu)
    if owner_username:
        permitidas.add(owner_username)
    try:
        manual = (ch["girl_username"] or "").strip().lower().lstrip("@")
    except Exception:
        manual = ""
    if manual:
        permitidas.add(manual)

    externa, motivo = await _es_promo_externa(
        bot, msgs, permitidas, owner_id, src_id)
    if externa:
        if await db.repost_notif():
            nombre = ch["title"] or (("@" + ch["username"]) if ch["username"]
                                     else str(src_id))
            await _avisar_dueño(
                bot,
                f"⏭️ <b>Post NO reenviado</b>\n"
                f"📡 De: <b>{nombre}</b>\n"
                f"Motivo: {motivo}.\n\n"
                f"(Llevaba algo de otra persona/canal. Si crees que me "
                f"equivoqué, dímelo y ajusto el filtro.)")
        return

    await _reenviar(bot, dest_id, src_id, msgs, ch)


async def _reenviar(bot, dest_id: int, src_id: int, msgs: list, ch):
    kb_botones = await _kb_botones(bot, ch, src_id)
    single = (len(msgs) == 1)
    mgid = msgs[0].media_group_id or ""

    # --- Copiar (con reintentos), guardando qué copia corresponde a qué
    #     publicación (para poder actualizarla si la editan) ---
    copiado = False
    for intento in range(3):
        try:
            if single:
                m = msgs[0]
                res = await bot.copy_message(
                    chat_id=dest_id, from_chat_id=src_id,
                    message_id=m.message_id, reply_markup=kb_botones)
                dmid = getattr(res, "message_id", None)
                if dmid:
                    await db.add_repost_map(src_id, m.message_id, dest_id,
                                            dmid, "")
            else:
                ids = sorted(mm.message_id for mm in msgs)
                res = await bot.copy_messages(
                    chat_id=dest_id, from_chat_id=src_id, message_ids=ids)
                try:
                    for smid, r in zip(ids, res or []):
                        dmid = getattr(r, "message_id", None)
                        if dmid:
                            await db.add_repost_map(src_id, smid, dest_id,
                                                    dmid, mgid)
                except Exception:
                    pass
            copiado = True
            break
        except TelegramRetryAfter as e:
            await asyncio.sleep(e.retry_after + 1)
        except (TelegramForbiddenError, TelegramBadRequest) as e:
            t = str(e).lower()
            if ("not enough rights" in t or "need administrator" in t
                    or "chat_admin_required" in t or "forbidden" in t):
                if await db.repost_notif():
                    await _avisar_dueño(
                        bot,
                        "⚠️ <b>No pude publicar en un canal de repost.</b>\n"
                        "El bot necesita ser <b>administrador</b> con permiso "
                        "de <b>Publicar mensajes</b> en ese canal.\n\n"
                        f"Detalle: {str(e)[:80]}")
                return
            log.warning(f"Repost falló ({e})")
            return
        except Exception as e:
            log.warning(f"Repost error inesperado: {e}")
            return

    if not copiado:
        return
    await asyncio.sleep(config.SEND_DELAY)

    # Álbum: los botones van en un mensajito aparte (Telegram no deja botones
    # dentro de un álbum). Usamos un texto corto (no un emoji solo, que saldría
    # gigante) y guardamos ese mensaje para poder actualizarlo/borrarlo luego.
    if not single and kb_botones:
        try:
            primer_id = min(mm.message_id for mm in msgs)
            f = await bot.send_message(dest_id, _ALBUM_PIE,
                                       reply_markup=kb_botones)
            fid = getattr(f, "message_id", None)
            if fid:
                await db.add_repost_map(src_id, -primer_id, dest_id, fid, mgid)
        except Exception:
            pass


async def _avisar_dueño(bot, texto: str):
    try:
        await bot.send_message(config.OWNER_ID, texto)
    except Exception:
        pass


# ===========================================================================
#  PANEL DE CONTROL (menú Repost)
# ===========================================================================
async def _nombre_canal(bot, cid: int) -> str:
    if not cid:
        return "— sin configurar"
    try:
        c = await bot.get_chat(cid)
        base = c.title or (("@" + c.username) if c.username else str(cid))
        return base
    except Exception:
        return f"id {cid} · ⚠️ mete el bot de admin ahí"


async def _panel_texto(bot) -> str:
    on = await db.repost_enabled()
    notif = await db.repost_notif()
    canales = await db.get_repost_channels()
    es = await _nombre_canal(bot, canales["es"])
    la = await _nombre_canal(bot, canales["latam"])
    fi = await _nombre_canal(bot, canales["findom"])
    n_fd = len(await db.channels_por_modo_repost("findom"))
    n_ex = len(await db.channels_excluidos())
    estado = "🟢 ENCENDIDO" if on else "🔴 APAGADO"
    avisos = "ON" if notif else "OFF"
    return (
        f"🔁 <b>Repost · publicaciones de las creadoras</b>\n\n"
        f"Estado: <b>{estado}</b>\n"
        f"Avisos cuando salta el filtro: <b>{avisos}</b>\n\n"
        f"📥 <b>Canales showcase</b>\n"
        f"🇪🇸 España: {es}\n"
        f"🌎 Latam: {la}\n"
        f"🔗 Findom: {fi}\n\n"
        f"👀 Solo findom: <b>{n_fd}</b>   ·   🚫 Excluidos: <b>{n_ex}</b>\n\n"
        f"ℹ️ Solo se republica <b>multimedia</b> (fotos, vídeos, GIFs y "
        f"álbumes, con o sin texto). No cambia nada del spam ni de las "
        f"campañas; solo reenvía a estos canales lo que las chicas suben en "
        f"los suyos, filtrando la promo de terceros."
    )


def _panel_kb(on: bool, notif: bool):
    b = InlineKeyboardBuilder()
    b.button(text=("🔴 Apagar repost" if on else "🟢 Encender repost"),
             callback_data="rp:onoff")
    b.button(text="🇪🇸 Canal España", callback_data="rp:set:es")
    b.button(text="🌎 Canal Latam", callback_data="rp:set:latam")
    b.button(text="🔗 Canal Findom", callback_data="rp:set:findom")
    b.button(text="📋 Gestionar canales", callback_data="rp:list:0")
    b.button(text="✏️ Botones", callback_data="rp:btns")
    b.button(text="👀 Chicas solo-findom", callback_data="rp:findomlist")
    b.button(text="🔄 Actualizar botones (ya subidas)",
             callback_data="rp:refresh")
    b.button(text=(f"🔔 Avisos: {'ON' if notif else 'OFF'}"),
             callback_data="rp:notif")
    b.button(text="⬅️ Volver", callback_data="menu:home")
    b.adjust(1, 3, 1, 2, 1, 1, 1)
    return b.as_markup()


async def _mostrar_panel(target):
    bot = target.bot
    texto = await _panel_texto(bot)
    on = await db.repost_enabled()
    notif = await db.repost_notif()
    kb_panel = _panel_kb(on, notif)
    msg = target.message if isinstance(target, CallbackQuery) else target
    try:
        await msg.edit_text(texto, reply_markup=kb_panel)
    except Exception:
        await msg.answer(texto, reply_markup=kb_panel)


@router.message(Command("repost"))
async def cmd_repost(message: Message, state: FSMContext):
    await state.clear()
    await _mostrar_panel(message)


@router.callback_query(F.data == "menu:repost")
async def cb_menu_repost(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    await _mostrar_panel(callback)


@router.callback_query(F.data == "rp:onoff")
async def cb_onoff(callback: CallbackQuery):
    nuevo = "0" if await db.repost_enabled() else "1"
    await db.set_setting(db.RP_ON, nuevo)
    await callback.answer("Repost encendido" if nuevo == "1"
                          else "Repost apagado")
    await _mostrar_panel(callback)


@router.callback_query(F.data == "rp:notif")
async def cb_notif(callback: CallbackQuery):
    nuevo = "0" if await db.repost_notif() else "1"
    await db.set_setting(db.RP_NOTIF, nuevo)
    await callback.answer("Avisos ON" if nuevo == "1" else "Avisos OFF")
    await _mostrar_panel(callback)


# ---------- Configurar uno de los 3 canales showcase ----------
_ETIQUETA = {"es": "🇪🇸 España", "latam": "🌎 Latam", "findom": "🔗 Findom"}


@router.callback_query(F.data.startswith("rp:set:"))
async def cb_set_canal(callback: CallbackQuery, state: FSMContext):
    bucket = callback.data.split(":")[-1]
    if bucket not in _ETIQUETA:
        await callback.answer("Opción no válida", show_alert=True)
        return
    await callback.answer()
    await state.set_state(RepostSet.esperando_canal)
    await state.update_data(bucket=bucket)
    await callback.message.edit_text(
        f"📥 <b>Canal de repost — {_ETIQUETA[bucket]}</b>\n\n"
        f"Dime cuál es el canal (uno de TUS canales showcase, donde el bot "
        f"debe ser admin):\n\n"
        f"• <b>Reenvíame un mensaje</b> de ese canal (lo más fácil), o\n"
        f"• pega su <code>@usuario</code>, su enlace <code>t.me/...</code> "
        f"o su <code>ID -100...</code>\n\n"
        f"/cancel para salir.")


@router.message(RepostSet.esperando_canal)
async def recibir_canal(message: Message, state: FSMContext):
    datos = await state.get_data()
    bucket = datos.get("bucket")
    if bucket not in _ETIQUETA:
        await state.clear()
        await message.answer("Algo fue mal, reintenta desde 🔁 Repost.")
        return

    cid, titulo = await _resolver_canal(message)
    if cid is None:
        await message.answer(
            "❌ No pude identificar ese canal. Reenvíame un mensaje de él, "
            "o pega su @usuario / enlace / ID. /cancel para salir.")
        return

    await state.clear()

    # Comprobar que el bot es admin ahí.
    aviso_admin = ""
    try:
        miembro = await message.bot.get_chat_member(cid, message.bot.id)
        if getattr(miembro, "status", "") not in ("administrator", "creator"):
            aviso_admin = ("\n\n⚠️ Ojo: el bot todavía <b>no es admin</b> en "
                           "ese canal. Hazlo admin con permiso de "
                           "<b>Publicar mensajes</b> o no podrá reenviar.")
    except Exception:
        aviso_admin = ("\n\n⚠️ No pude comprobar los permisos. Asegúrate de "
                       "que el bot es <b>admin</b> en ese canal.")

    # Si ese canal estaba en tu lista de creadoras, lo sacamos: un canal de
    # repost NO debe recibir el spam de las campañas (ni crear bucles).
    aviso_creadora = ""
    ya = await db.get_channel(cid)
    if ya:
        await db.delete_channel(cid)
        aviso_creadora = ("\n\nℹ️ Ese canal estaba en tus creadoras; lo he "
                          "sacado de las campañas (un canal de repost no debe "
                          "recibir spam).")

    await db.set_repost_channel(bucket, cid)

    await message.answer(
        f"✅ <b>{_ETIQUETA[bucket]}</b> configurado:\n"
        f"📡 <b>{titulo}</b>\n"
        f"<code>{cid}</code>{aviso_admin}{aviso_creadora}")
    await _mostrar_panel(message)


async def _resolver_canal(message: Message) -> tuple:
    """Devuelve (chat_id, titulo) del canal indicado, o (None, None)."""
    # 1) ¿Reenvió un mensaje de un canal?
    fo = getattr(message, "forward_origin", None)
    chat = None
    if fo is not None:
        chat = getattr(fo, "chat", None) or getattr(fo, "sender_chat", None)
    if chat is None:
        chat = getattr(message, "forward_from_chat", None)
    if chat is not None and getattr(chat, "id", None) is not None:
        titulo = getattr(chat, "title", "") or (
            ("@" + chat.username) if getattr(chat, "username", None)
            else str(chat.id))
        return (chat.id, titulo)

    # 2) Texto: ID, @usuario o enlace t.me
    txt = (message.text or "").strip()
    if not txt:
        return (None, None)

    # ID directo (-100...)
    limpio = txt.replace(" ", "")
    if re.fullmatch(r"-?\d{5,}", limpio):
        cid = int(limpio)
        try:
            c = await message.bot.get_chat(cid)
            titulo = c.title or (("@" + c.username) if c.username else str(cid))
            return (cid, titulo)
        except Exception:
            return (cid, str(cid))

    # @usuario o t.me/usuario
    uname = None
    m = _TME.search(txt)
    if m:
        uname = m.group(1)
    elif txt.startswith("@"):
        uname = txt[1:]
    else:
        uname = txt
    uname = uname.strip().lstrip("@")
    if not uname or uname in _TME_IGNORAR or uname.startswith("+") \
            or uname == "joinchat":
        return (None, None)
    try:
        c = await message.bot.get_chat("@" + uname)
        titulo = c.title or (("@" + c.username) if c.username else str(c.id))
        return (c.id, titulo)
    except Exception:
        return (None, None)


# ---------- Selector de modo repost desde la ficha ----------
def _mode_kb(chat_id: int):
    b = InlineKeyboardBuilder()
    b.button(text="🛍️ Vende contenido",
             callback_data=f"rp:setmode:{chat_id}:contenido")
    b.button(text="🔗 Solo findom",
             callback_data=f"rp:setmode:{chat_id}:findom")
    b.button(text="🚫 Excluir del repost",
             callback_data=f"rp:setmode:{chat_id}:off")
    b.button(text="🗑️ Borrar sus publicaciones del repost",
             callback_data=f"rp:wipe:{chat_id}")
    b.button(text="⬅️ Volver a la ficha",
             callback_data=f"ch:open:{chat_id}")
    b.adjust(1)
    return b.as_markup()


@router.callback_query(F.data.startswith("rp:mode:"))
async def cb_mode(callback: CallbackQuery):
    """Abre el selector de modo repost (desde la ficha del canal)."""
    chat_id = int(callback.data.split(":")[-1])
    ch = await db.get_channel(chat_id)
    if not ch:
        await callback.answer("Canal no encontrado", show_alert=True)
        return
    await callback.answer()
    try:
        excl = bool(ch["repost_off"])
        modo = ch["repost_mode"] or "contenido"
    except Exception:
        excl, modo = False, "contenido"
    if excl:
        actual = "🚫 Excluido (no se republica)"
    elif modo == "findom":
        actual = "🔗 Solo findom → canal Findom"
    else:
        actual = "🛍️ Vende contenido → canal de su región"
    nombre = ch["title"] or (("@" + ch["username"]) if ch["username"]
                             else str(chat_id))
    await callback.message.edit_text(
        f"🔁 <b>Modo repost — {nombre}</b>\n\n"
        f"Ahora mismo: <b>{actual}</b>\n\n"
        f"¿Qué quieres para este canal?\n"
        f"• 🛍️ <b>Vende contenido</b>: sus publicaciones van al repost de "
        f"su región (España/Latam).\n"
        f"• 🔗 <b>Solo findom</b>: van al repost Findom.\n"
        f"• 🚫 <b>Excluir</b>: sus publicaciones NO aparecen en ningún "
        f"repost (sigue en campañas y spam igual).",
        reply_markup=_mode_kb(chat_id))


@router.callback_query(F.data.startswith("rp:setmode:"))
async def cb_setmode(callback: CallbackQuery):
    """Aplica el modo elegido. Sirve tanto para el alta de un canal nuevo
    como para el selector de la ficha."""
    partes = callback.data.split(":")
    # rp:setmode:<chat_id>:<modo>   (modo = contenido | findom | off)
    chat_id = int(partes[2])
    modo = partes[3]

    if modo == "off":
        await db.set_repost_off(chat_id, True)
        await callback.answer("Excluido del repost")
        n = await db.count_repost_channel(chat_id)
        b = InlineKeyboardBuilder()
        if n > 0:
            b.button(text=f"🗑️ Borrar también sus publicaciones ya subidas",
                     callback_data=f"rp:wipe:{chat_id}")
        b.button(text="⬅️ Volver a la ficha",
                 callback_data=f"ch:open:{chat_id}")
        b.adjust(1)
        extra = ("¿Quieres borrar también las que ya subió a tu canal de "
                 "repost?" if n > 0 else "No hay publicaciones suyas "
                 "guardadas para borrar.")
        await callback.message.edit_text(
            f"🚫 Canal <b>excluido</b> del repost. Sus nuevas publicaciones "
            f"ya no aparecerán.\n\nSigue igual en sus campañas y spam.\n\n"
            f"{extra}",
            reply_markup=b.as_markup())
        return

    # incluir + fijar modo
    await db.set_repost_off(chat_id, False)
    await db.set_repost_mode(chat_id, modo)
    ch = await db.get_channel(chat_id)
    etiqueta, dest_id = await db.repost_destino(ch)
    if modo == "findom":
        detalle = "🔗 Su canal irá al repost <b>Findom</b>."
    else:
        detalle = f"🛍️ Su canal irá al repost de <b>{etiqueta}</b>."
    falta = "" if dest_id else ("\n\n⚠️ Ese canal de repost aún no está "
                                "configurado (menú 🔁 Repost).")
    aviso = (f"✅ Listo. {detalle}{falta}\n\nEsto no cambia su región "
             f"ni su campaña.")
    await callback.answer("Guardado")
    try:
        await h_channels.cb_ficha_directo(callback, chat_id)
        await callback.message.answer(aviso)
    except Exception:
        await callback.message.edit_text(aviso)


# ---------- Borrar todas las publicaciones de un canal en el repost ----------
async def _borrar_reposts_canal(bot, src_chat: int) -> int:
    rows = await db.repost_maps_for_channel(src_chat)
    ok = 0
    for r in rows:
        for intento in range(3):
            try:
                await bot.delete_message(r["dest_chat"], r["dest_msg"])
                ok += 1
                break
            except TelegramRetryAfter as e:
                await asyncio.sleep(e.retry_after + 1)
            except Exception:
                break   # ya no existe / demasiado antigua / sin permiso
        await asyncio.sleep(0.2)
    await db.del_repost_channel(src_chat)
    return ok


@router.callback_query(F.data.startswith("rp:wipe:"))
async def cb_wipe(callback: CallbackQuery):
    chat_id = int(callback.data.split(":")[-1])
    await callback.answer()
    n = await db.count_repost_channel(chat_id)
    ch = await db.get_channel(chat_id)
    nombre = (ch["title"] if ch else str(chat_id))
    if n == 0:
        b = InlineKeyboardBuilder()
        b.button(text="⬅️ Volver a la ficha", callback_data=f"ch:open:{chat_id}")
        await callback.message.edit_text(
            f"No hay publicaciones de <b>{nombre}</b> guardadas en tu repost "
            f"para borrar.\n\n(Solo se pueden borrar las de los últimos ~30 "
            f"días, que es lo que el bot recuerda.)",
            reply_markup=b.as_markup())
        return
    b = InlineKeyboardBuilder()
    b.button(text=f"✅ Sí, borrar {n}", callback_data=f"rp:wipe2:{chat_id}")
    b.button(text="❌ No, dejarlas", callback_data=f"ch:open:{chat_id}")
    b.adjust(1)
    await callback.message.edit_text(
        f"🗑️ ¿Borrar <b>{n}</b> mensajes de <b>{nombre}</b> de tu canal de "
        f"repost?\n\nEsto no se puede deshacer. (Las muy antiguas quizá no se "
        f"puedan borrar por el límite de Telegram.)",
        reply_markup=b.as_markup())


@router.callback_query(F.data.startswith("rp:wipe2:"))
async def cb_wipe2(callback: CallbackQuery):
    chat_id = int(callback.data.split(":")[-1])
    await callback.answer("Borrando… te aviso al terminar 👍", show_alert=True)

    async def tarea():
        try:
            n = await _borrar_reposts_canal(callback.bot, chat_id)
            await callback.bot.send_message(
                config.OWNER_ID,
                f"🗑️ Borradas <b>{n}</b> publicaciones de ese canal en tu "
                f"repost.")
        except Exception as e:
            log.warning(f"wipe canal: {e}")

    asyncio.create_task(tarea())
    try:
        await callback.message.edit_text(
            "🗑️ Borrando sus publicaciones del repost… te aviso al terminar.")
    except Exception:
        pass


# ---------- Ver las chicas marcadas como solo findom ----------
@router.callback_query(F.data == "rp:findomlist")
async def cb_findomlist(callback: CallbackQuery):
    await callback.answer()
    chicas = await db.channels_por_modo_repost("findom")
    b = InlineKeyboardBuilder()
    if not chicas:
        texto = ("👀 <b>Chicas solo findom</b>\n\n"
                 "Todavía no has marcado a ninguna. Se marcan desde la ficha "
                 "de cada canal (📡 Canales → abrir canal → 🔁 Modo repost), "
                 "o al dar de alta un canal nuevo.")
    else:
        texto = ("👀 <b>Chicas solo findom</b> (su contenido va al canal "
                 "Findom)\n\nToca una para abrir su ficha y cambiarla si hace "
                 "falta:")
        for ch in chicas[:40]:
            nombre = ch["title"] or (("@" + ch["username"]) if ch["username"]
                                     else str(ch["chat_id"]))
            b.button(text=f"🔗 {nombre[:28]}",
                     callback_data=f"ch:open:{ch['chat_id']}")
        b.adjust(1)
    b.button(text="⬅️ Volver", callback_data="menu:repost")
    await callback.message.edit_text(texto, reply_markup=b.as_markup())


# ===========================================================================
#  SUBMENÚ: EDITAR LOS 2 BOTONES (texto + color)
# ===========================================================================
def _btns_kb():
    b = InlineKeyboardBuilder()
    b.button(text="✏️ Texto botón 1", callback_data="rp:btntext:1")
    b.button(text="🎨 Color botón 1", callback_data="rp:btncolor:1")
    b.button(text="✏️ Texto botón 2", callback_data="rp:btntext:2")
    b.button(text="🎨 Color botón 2", callback_data="rp:btncolor:2")
    b.button(text="👁️ Previsualizar", callback_data="rp:btnprev")
    b.button(text="⬅️ Volver", callback_data="menu:repost")
    b.adjust(2, 2, 1, 1)
    return b.as_markup()


async def _btns_texto() -> str:
    cfg = await db.get_repost_botones()
    return (
        f"✏️ <b>Botones del repost</b>\n\n"
        f"Aparecen <b>juntos</b> (uno al lado del otro) debajo de cada "
        f"publicación reenviada.\n\n"
        f"1️⃣ <b>Perfil de la propietaria</b>\n"
        f"   Texto: «{cfg['b1_text']}»\n"
        f"   Color: {_STYLE_LABEL.get(cfg['b1_style'], '⚪ Normal')}\n\n"
        f"2️⃣ <b>Canal</b>\n"
        f"   Texto: «{cfg['b2_text']}»\n"
        f"   Color: {_STYLE_LABEL.get(cfg['b2_style'], '⚪ Normal')}\n\n"
        f"ℹ️ En un álbum los botones salen en un mensajito justo debajo "
        f"(Telegram no deja botones dentro de un álbum)."
    )


@router.callback_query(F.data == "rp:btns")
async def cb_btns(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    await callback.message.edit_text(await _btns_texto(),
                                     reply_markup=_btns_kb())


# ---- Editar texto ----
@router.callback_query(F.data.startswith("rp:btntext:"))
async def cb_btntext(callback: CallbackQuery, state: FSMContext):
    n = callback.data.split(":")[-1]
    if n not in ("1", "2"):
        await callback.answer("Opción no válida", show_alert=True)
        return
    await callback.answer()
    await state.set_state(RepostBtn.esperando_texto)
    await state.update_data(btn=n)
    cual = "perfil de la propietaria" if n == "1" else "canal"
    await callback.message.edit_text(
        f"✏️ Escribe el <b>nuevo texto</b> para el botón {n} ({cual}).\n\n"
        f"Puedes incluir un emoji, p.ej.:  <code>👤 Mi perfil</code>  o  "
        f"<code>📢 Únete al canal</code>\n\n"
        f"(máx. 60 caracteres) · /cancel para salir.")


@router.message(RepostBtn.esperando_texto)
async def recibir_texto_boton(message: Message, state: FSMContext):
    texto = (message.text or "").strip()
    if not texto:
        await message.answer("❌ Mándame el texto del botón (o /cancel).")
        return
    if len(texto) > 60:
        await message.answer("❌ Demasiado largo (máx. 60). Prueba otra vez.")
        return
    datos = await state.get_data()
    await state.clear()
    n = datos.get("btn")
    clave = db.RP_B1_TEXT if n == "1" else db.RP_B2_TEXT
    await db.set_setting(clave, texto)
    await message.answer(f"✅ Texto del botón {n} actualizado a: «{texto}»")
    await message.answer(await _btns_texto(), reply_markup=_btns_kb())


# ---- Editar color ----
def _color_kb(n: str):
    b = InlineKeyboardBuilder()
    b.button(text="⚪ Normal", callback_data=f"rp:setcolor:{n}:normal")
    b.button(text="🔵 Azul", callback_data=f"rp:setcolor:{n}:primary")
    b.button(text="🔴 Rojo", callback_data=f"rp:setcolor:{n}:danger")
    b.button(text="🟢 Verde", callback_data=f"rp:setcolor:{n}:success")
    b.button(text="⬅️ Volver", callback_data="rp:btns")
    b.adjust(2, 2, 1)
    return b.as_markup()


@router.callback_query(F.data.startswith("rp:btncolor:"))
async def cb_btncolor(callback: CallbackQuery):
    n = callback.data.split(":")[-1]
    if n not in ("1", "2"):
        await callback.answer("Opción no válida", show_alert=True)
        return
    await callback.answer()
    cual = "perfil de la propietaria" if n == "1" else "canal"
    await callback.message.edit_text(
        f"🎨 Elige el <b>color</b> del botón {n} ({cual}):\n\n"
        f"Son los 4 colores de Telegram. Toca uno y luego pulsa "
        f"«👁️ Previsualizar» para verlo.",
        reply_markup=_color_kb(n))


@router.callback_query(F.data.startswith("rp:setcolor:"))
async def cb_setcolor(callback: CallbackQuery):
    # rp:setcolor:<n>:<estilo>
    partes = callback.data.split(":")
    n = partes[2]
    estilo = partes[3]
    estilo = "" if estilo == "normal" else estilo
    if estilo not in _STYLES:
        await callback.answer("Color no válido", show_alert=True)
        return
    clave = db.RP_B1_STYLE if n == "1" else db.RP_B2_STYLE
    await db.set_setting(clave, estilo)
    await callback.answer(f"Color: {_STYLE_LABEL.get(estilo, '⚪ Normal')}")
    await callback.message.edit_text(await _btns_texto(),
                                     reply_markup=_btns_kb())


# ---- Previsualizar ----
@router.callback_query(F.data == "rp:btnprev")
async def cb_btnprev(callback: CallbackQuery):
    await callback.answer("Te mando una vista previa 👇")
    cfg = await db.get_repost_botones()
    # Enlaces de ejemplo solo para la vista previa (el color sí es real).
    fila = [
        _btn(cfg["b1_text"] or "👤 Perfil", "https://t.me/telegram",
             cfg["b1_style"]),
        _btn(cfg["b2_text"] or "📢 Canal", "https://t.me/telegram",
             cfg["b2_style"]),
    ]
    kb_prev = InlineKeyboardMarkup(inline_keyboard=[fila])
    try:
        await callback.bot.send_message(
            config.OWNER_ID,
            "👁️ <b>Vista previa</b> de los botones (así saldrán debajo de "
            "cada publicación):", reply_markup=kb_prev)
    except Exception as e:
        await callback.message.answer(f"No pude mandar la vista previa: {e}")


# ===========================================================================
#  GESTOR DE CANALES  (excluir / incluir del repost con un toque)
# ===========================================================================
_PAGE = 8


async def _render_lista(callback: CallbackQuery, page: int):
    canales = await db.get_channels()   # todos los canales registrados
    total = len(canales)
    b = InlineKeyboardBuilder()
    if total == 0:
        await callback.message.edit_text(
            "📋 <b>Gestionar canales</b>\n\nAún no hay canales registrados.",
            reply_markup=InlineKeyboardBuilder()
            .button(text="⬅️ Volver", callback_data="menu:repost")
            .as_markup())
        return
    paginas = max(1, (total + _PAGE - 1) // _PAGE)
    page = max(0, min(page, paginas - 1))
    trozo = canales[page * _PAGE:(page + 1) * _PAGE]

    filas = []
    for ch in trozo:
        try:
            excl = bool(ch["repost_off"])
        except Exception:
            excl = False
        try:
            modo = ch["repost_mode"] or "contenido"
        except Exception:
            modo = "contenido"
        emo = "🚫" if excl else ("🔗" if modo == "findom" else "🛍️")
        nombre = ch["title"] or (("@" + ch["username"]) if ch["username"]
                                 else str(ch["chat_id"]))
        filas.append([InlineKeyboardButton(
            text=f"{emo} {nombre[:26]}",
            callback_data=f"rp:xoff:{ch['chat_id']}:{page}")])

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(
            text="◀️", callback_data=f"rp:list:{page - 1}"))
    nav.append(InlineKeyboardButton(
        text=f"{page + 1}/{paginas}", callback_data="rp:noop"))
    if page < paginas - 1:
        nav.append(InlineKeyboardButton(
            text="▶️", callback_data=f"rp:list:{page + 1}"))
    filas.append(nav)
    filas.append([InlineKeyboardButton(
        text="⬅️ Volver", callback_data="menu:repost")])

    texto = (
        "📋 <b>Gestionar canales del repost</b>\n\n"
        "Toca un canal para <b>excluirlo</b> o volver a <b>incluirlo</b>.\n"
        "🛍️ vende contenido  ·  🔗 solo findom  ·  🚫 excluido (no aparece)\n\n"
        f"Página {page + 1}/{paginas} · {total} canales")
    await callback.message.edit_text(
        texto, reply_markup=InlineKeyboardMarkup(inline_keyboard=filas))


@router.callback_query(F.data.startswith("rp:list:"))
async def cb_lista(callback: CallbackQuery):
    await callback.answer()
    page = int(callback.data.split(":")[-1])
    await _render_lista(callback, page)


@router.callback_query(F.data.startswith("rp:xoff:"))
async def cb_xoff(callback: CallbackQuery):
    # rp:xoff:<chat_id>:<page>
    partes = callback.data.split(":")
    chat_id = int(partes[2])
    page = int(partes[3])
    actual = await db.is_repost_off(chat_id)
    await db.set_repost_off(chat_id, not actual)
    await callback.answer("🚫 Excluido del repost" if not actual
                          else "✅ Incluido de nuevo")
    await _render_lista(callback, page)


@router.callback_query(F.data == "rp:noop")
async def cb_noop(callback: CallbackQuery):
    await callback.answer()


# ===========================================================================
#  PROPIETARIA MANUAL  (para canales comprados o con dueño distinto)
# ===========================================================================
def _sacar_username(message: Message) -> str:
    """Saca una @ válida de un mensaje: reenvío de su cuenta, o @/enlace."""
    # 1) ¿Reenvió un mensaje de la cuenta de la chica?
    fo = getattr(message, "forward_origin", None)
    user = getattr(fo, "sender_user", None) if fo else None
    if user is None:
        user = getattr(message, "forward_from", None)
    if user is not None:
        un = getattr(user, "username", None)
        if un:
            return un.lstrip("@")
    # 2) Texto: @usuario o t.me/usuario
    txt = (message.text or "").strip()
    if not txt:
        return ""
    m = _TME.search(txt)
    cand = m.group(1) if m else (txt[1:] if txt.startswith("@") else txt)
    cand = cand.strip().lstrip("@")
    if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{4,31}", cand):
        return cand
    return ""


def _owner_kb(chat_id: int, tiene: bool):
    b = InlineKeyboardBuilder()
    b.button(text=("✏️ Cambiar @" if tiene else "✏️ Poner @"),
             callback_data=f"rp:ownerset:{chat_id}")
    if tiene:
        b.button(text="🗑️ Quitar (usar automático)",
                 callback_data=f"rp:ownerclear:{chat_id}")
    b.button(text="⬅️ Volver a la ficha", callback_data=f"ch:open:{chat_id}")
    b.adjust(1)
    return b.as_markup()


@router.callback_query(F.data.startswith("rp:owner:"))
async def cb_owner(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    chat_id = int(callback.data.split(":")[-1])
    ch = await db.get_channel(chat_id)
    if not ch:
        await callback.answer("Canal no encontrado", show_alert=True)
        return
    await callback.answer()
    manual = (ch["girl_username"] or "").strip()
    auto = (ch["owner_username"] or "").strip()
    linea_auto = f"@{auto}" if auto else "no detectado"
    linea_manual = f"@{manual}" if manual else "— (ninguna, se usa la automática)"
    nombre = ch["title"] or (("@" + ch["username"]) if ch["username"]
                             else str(chat_id))
    await callback.message.edit_text(
        f"👤 <b>Propietaria — {nombre}</b>\n\n"
        f"Es la persona a la que apunta el botón de perfil y cuyo @ se "
        f"permite en el filtro. Útil en canales comprados o con dueño "
        f"distinto a quien sube el contenido.\n\n"
        f"• Detectada automáticamente: <b>{linea_auto}</b>\n"
        f"• Asignada a mano: <b>{linea_manual}</b>\n\n"
        f"Para asignarla, mándame su <code>@usuario</code> o reenvíame un "
        f"mensaje suyo.",
        reply_markup=_owner_kb(chat_id, bool(manual)))


@router.callback_query(F.data.startswith("rp:ownerset:"))
async def cb_ownerset(callback: CallbackQuery, state: FSMContext):
    chat_id = int(callback.data.split(":")[-1])
    await callback.answer()
    await state.set_state(RepostOwner.esperando)
    await state.update_data(chat_id=chat_id)
    await callback.message.edit_text(
        "👤 Mándame la <b>@ de la propietaria</b> real de este canal.\n\n"
        "Puedes:\n"
        "• escribir su <code>@usuario</code>, o\n"
        "• reenviarme un mensaje suyo (si su cuenta no está oculta).\n\n"
        "/cancel para salir.")


@router.message(RepostOwner.esperando)
async def recibir_owner(message: Message, state: FSMContext):
    datos = await state.get_data()
    chat_id = datos.get("chat_id")
    uname = _sacar_username(message)
    if not uname:
        await message.answer(
            "❌ No pude sacar una @ válida. Escríbela como <code>@usuario</code> "
            "o reenvíame un mensaje suyo. /cancel para salir.")
        return
    await state.clear()
    await db.set_girl_username(chat_id, uname)
    ch = await db.get_channel(chat_id)
    nombre = ch["title"] if ch else str(chat_id)
    await message.answer(
        f"✅ Propietaria de <b>{nombre}</b> asignada: <b>@{uname}</b>\n\n"
        f"El botón de perfil apuntará a ella y su @ ya no se filtrará.\n"
        f"Estoy actualizando sus publicaciones ya subidas… 🔄")
    # Actualiza los botones de sus publicaciones ya reposteadas (en 2º plano).
    asyncio.create_task(_refrescar_botones(message.bot, solo_src=chat_id))


@router.callback_query(F.data.startswith("rp:ownerclear:"))
async def cb_ownerclear(callback: CallbackQuery):
    chat_id = int(callback.data.split(":")[-1])
    await db.set_girl_username(chat_id, "")
    await callback.answer("Quitada. Se usará la propietaria automática.")
    asyncio.create_task(_refrescar_botones(callback.bot, solo_src=chat_id))
    try:
        await h_channels.cb_ficha_directo(callback, chat_id)
    except Exception:
        await callback.message.edit_text(
            "✅ Quitada la propietaria manual. Se usará la automática.")


# ===========================================================================
#  ACTUALIZAR BOTONES DE PUBLICACIONES YA SUBIDAS
# ===========================================================================
async def _refrescar_botones(bot, solo_src=None) -> int:
    """Re-pone/actualiza los 2 botones en las copias ya publicadas (posts
    sueltos y pies de álbum). Sirve para que aparezca el botón del canal en
    publicaciones anteriores una vez que activas el permiso de invitar, o al
    cambiar la propietaria."""
    rows = await db.repost_con_botones()
    kb_cache = {}
    ok = 0
    for r in rows:
        src = r["src_chat"]
        if solo_src is not None and src != solo_src:
            continue
        if src not in kb_cache:
            ch = await db.get_channel(src)
            kb_cache[src] = (await _kb_botones(bot, ch, src)) if ch else None
        kb = kb_cache[src]
        if not kb:
            continue
        exito = False
        for intento in range(4):
            try:
                await bot.edit_message_reply_markup(
                    chat_id=r["dest_chat"], message_id=r["dest_msg"],
                    reply_markup=kb)
                exito = True
                break
            except TelegramRetryAfter as e:
                # Telegram pide frenar: esperamos y reintentamos (así no se
                # quedan sin actualizar como pasaba antes).
                await asyncio.sleep(e.retry_after + 1)
            except TelegramBadRequest as e:
                if "not modified" in str(e).lower():
                    exito = True   # ya tenía los botones correctos
                break
            except Exception as e:
                log.warning(f"refrescar botón inesperado: {e}")
                break
        if exito:
            ok += 1
        await asyncio.sleep(0.4)   # amable con los límites de Telegram
    return ok


@router.callback_query(F.data == "rp:refresh")
async def cb_refresh(callback: CallbackQuery):
    await callback.answer(
        "Actualizando botones de las publicaciones ya subidas… te aviso al "
        "terminar 👍", show_alert=True)

    async def tarea():
        try:
            n = await _refrescar_botones(callback.bot)
            await callback.bot.send_message(
                config.OWNER_ID,
                f"✅ Botones actualizados en <b>{n}</b> publicaciones ya "
                f"subidas.\n\n(Si algún canal privado sigue sin botón de "
                f"canal, revisa que el bot tenga el permiso «Añadir "
                f"suscriptores» ahí.)")
        except Exception as e:
            log.warning(f"refresh masivo: {e}")

    asyncio.create_task(tarea())
