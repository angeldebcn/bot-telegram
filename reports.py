"""
=====================================================================
SISTEMA DE REPORTES
=====================================================================

FLUJO COMPLETO:

1. Cualquiera en el GRUPO DE VERIFICADAS escribe:
       /reporte @usuario razón
   adjuntando (o respondiendo a) una foto/vídeo/álbum/gif como prueba.

2. El bot:
   - Valida que se usa en el grupo de verificadas.
   - Resuelve a quién se reporta (@ o id o el autor del mensaje respondido).
   - Copia la prueba al GRUPO DE STAFF.
   - Publica en el grupo de staff una ficha del reporte + 3 botones:
       [⚠️ Warn leve] [⛔ Warn grave] [🚫 Ban]
   - Confirma al que reportó que su reporte se envió.

3. El staff pulsa un botón:
   - Se aplica la sanción al reportado (en todos los grupos marcados).
   - El aviso público sale en TODOS los grupos donde esté el reportado.
   - El mensaje del reporte en el grupo de staff se edita para mostrar
     quién lo resolvió y con qué acción (y desaparecen los botones).

LÍMITES DE TELEGRAM (ya gestionados):
- Si el @ no se puede resolver (persona nunca vista), se avisa y no se crea
  el reporte, pidiendo responder al mensaje o usar ID.
- Los álbumes se agrupan con el album_collector (2s) y el comando va en el
  pie de la primera foto.
"""
import logging
from typing import Optional

from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from config import OWNER_USER_ID
import sanctions_actions
import sanctions_db
import roles_db
from album_collector import AlbumCollector
from sanctions_text import clean_reason_short
from stats import cache_user

logger = logging.getLogger(__name__)
router = Router(name="reports")

# Colector de álbumes propio para reportes (independiente del de media)
_report_albums = AlbumCollector()


# ===========================================================================
# HELPERS
# ===========================================================================
def _is_in_group(message: Message) -> bool:
    return message.chat.type in (ChatType.GROUP, ChatType.SUPERGROUP)


def _report_args(message: Message) -> Optional[str]:
    """
    Texto que sigue al comando /reporte. Puede venir en text o en caption
    (cuando el reporte lleva una foto con pie de foto).
    """
    raw = message.text or message.caption
    if not raw:
        return None
    parts = raw.split(maxsplit=1)
    return parts[1] if len(parts) > 1 else None


async def _resolve_reported_user(
    bot: Bot, message: Message, args: Optional[str],
) -> tuple[Optional[int], Optional[str], Optional[str], Optional[str], Optional[str]]:
    """
    Resuelve a quién se reporta.
    Devuelve (user_id, username, full_name, reason, error).
    """
    # Reply -> el reportado es el autor del mensaje respondido
    if message.reply_to_message and message.reply_to_message.from_user:
        u = message.reply_to_message.from_user
        await cache_user(message.chat.id, u.id, u.username, u.full_name)
        reason = args.strip() if args else ""
        return u.id, u.username, u.full_name, reason, None

    if not args:
        return None, None, None, None, (
            "❌ Uso: <code>/reporte @usuario razón</code> adjuntando la prueba "
            "(foto/vídeo), o responde a un mensaje suyo con <code>/reporte razón</code>."
        )

    tokens = args.strip().split(maxsplit=1)
    target_token = tokens[0]
    reason = tokens[1] if len(tokens) > 1 else ""

    # @username
    if target_token.startswith("@"):
        found = await sanctions_db.resolve_username_global(target_token)
        if found:
            return (found["user_id"], found.get("username"),
                    found.get("full_name"), reason, None)
        return None, None, None, None, (
            f"❌ No encuentro a <b>{target_token}</b> en ningún grupo donde yo esté.\n\n"
            "Para poder reportarle:\n"
            "• Responde a un mensaje suyo con <code>/reporte razón</code>, o\n"
            "• Usa su ID numérico (lo da @userinfobot)."
        )

    # ID numérico
    if target_token.lstrip("-").isdigit():
        uid = int(target_token)
        info = await sanctions_db.get_sanctioned_user_info(uid)
        if info:
            return uid, info.get("username"), info.get("full_name"), reason, None
        try:
            member = await bot.get_chat_member(message.chat.id, uid)
            u = member.user
            await cache_user(message.chat.id, u.id, u.username, u.full_name)
            return uid, u.username, u.full_name, reason, None
        except TelegramBadRequest:
            return uid, None, None, reason, None

    return None, None, None, None, (
        "❌ No entendí a quién reportas. Usa @usuario, un ID, o responde a un "
        "mensaje suyo."
    )


def _report_buttons(report_id: int) -> InlineKeyboardMarkup:
    """Los 3 botones de acción para un reporte."""
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="⚠️ Warn leve", callback_data=f"rep:leve:{report_id}"),
        InlineKeyboardButton(text="⛔ Warn grave", callback_data=f"rep:grave:{report_id}"),
        InlineKeyboardButton(text="🚫 Ban", callback_data=f"rep:ban:{report_id}"),
    ]])


def _mention(user_id: int, username: Optional[str], full_name: Optional[str]) -> str:
    if full_name:
        name = full_name
    elif username:
        name = f"@{username}"
    else:
        name = f"id {user_id}"
    name = name.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return f'<a href="tg://user?id={user_id}">{name}</a>'


def _build_report_card(
    report_id: int,
    reporter_id: int, reporter_user: Optional[str], reporter_name: Optional[str],
    target_id: Optional[int], target_user: Optional[str], target_name: Optional[str],
    reason: str,
) -> str:
    """Ficha del reporte que se publica en el grupo de staff."""
    reporter_m = _mention(reporter_id, reporter_user, reporter_name)
    if target_id:
        target_m = _mention(target_id, target_user, target_name)
        target_line = f"👤 <b>Reportado:</b> {target_m}"
        if target_user:
            target_line += f" ({'@'+target_user})"
        target_line += f"\n🆔 <code>{target_id}</code>"
    else:
        target_line = "👤 <b>Reportado:</b> (no identificado)"

    return (
        f"🚨 <b>NUEVO REPORTE</b> #{report_id}\n\n"
        f"{target_line}\n\n"
        f"📝 <b>Motivo:</b> {reason}\n\n"
        f"🗣️ <b>Reporta:</b> {reporter_m}\n\n"
        f"👇 Elige una acción:"
    )


# ===========================================================================
# COMANDO /reporte
# ===========================================================================
@router.message(Command("reporte", "report", "reportar"))
async def cmd_reporte(message: Message, bot: Bot) -> None:
    # Álbum: agrupar y procesar como uno
    if message.media_group_id:
        await _report_albums.add(
            message,
            on_complete=lambda msgs: _process_report(bot, msgs),
        )
        return
    await _process_report(bot, [message])


async def _process_report(bot: Bot, messages: list[Message]) -> None:
    """
    Procesa un reporte (posiblemente con álbum). El comando y su texto están
    en el PRIMER mensaje (el que tiene el caption con /reporte).
    """
    # Buscar el mensaje que contiene el comando (el que tiene text/caption con /reporte)
    command_msg = None
    for m in messages:
        raw = m.text or m.caption or ""
        low = raw.lower()
        if low.startswith("/reporte") or low.startswith("/report") or low.startswith("/reportar"):
            command_msg = m
            break
    if command_msg is None:
        command_msg = messages[0]

    message = command_msg

    if not _is_in_group(message):
        await message.reply("❌ El comando /reporte se usa dentro del grupo.")
        return

    # Solo en el grupo de verificadas
    if not await roles_db.is_verified_group(message.chat.id):
        await message.reply(
            "❌ El comando /reporte solo se puede usar en el grupo de verificadas."
        )
        return

    # ¿Hay grupo de staff configurado?
    staff_chat = await roles_db.get_staff_group()
    if staff_chat is None:
        await message.reply(
            "❌ No hay ningún grupo de staff configurado todavía. "
            "El dueño debe marcarlo desde el panel."
        )
        return

    if not message.from_user:
        return

    # Resolver a quién se reporta
    args = _report_args(message)
    target_id, target_user, target_name, reason, error = await _resolve_reported_user(
        bot, message, args,
    )
    if error:
        await message.reply(error)
        return

    reason = (reason or "").strip()
    if not reason:
        reason = "(sin motivo escrito)"

    reporter = message.from_user

    # Crear el reporte en la BD
    report_id = await sanctions_db.create_report(
        reporter_id=reporter.id,
        reporter_name=reporter.full_name,
        reporter_user=reporter.username,
        target_id=target_id,
        target_name=target_name,
        target_user=target_user,
        reason=reason,
        origin_chat=message.chat.id,
        origin_msg_id=message.message_id,
    )

    # Recordar al reportado para la lista
    if target_id:
        await sanctions_db.remember_sanctioned_user(target_id, target_user, target_name)

    # Copiar la(s) prueba(s) al grupo de staff
    prueba_ok = await _copy_evidence_to_staff(bot, messages, staff_chat)

    # Publicar la ficha con botones en el grupo de staff
    card = _build_report_card(
        report_id, reporter.id, reporter.username, reporter.full_name,
        target_id, target_user, target_name, reason,
    )
    try:
        sent = await bot.send_message(
            staff_chat, card, reply_markup=_report_buttons(report_id),
            disable_web_page_preview=True,
        )
        await sanctions_db.set_report_staff_message(report_id, staff_chat, sent.message_id)
    except (TelegramBadRequest, TelegramForbiddenError) as e:
        logger.warning("No se pudo publicar reporte en staff %s: %s", staff_chat, e)
        await message.reply(
            "⚠️ Registré el reporte pero no pude enviarlo al grupo de staff. "
            "Avisa al dueño de que revise que el bot está en el grupo de staff."
        )
        return

    # Confirmar al que reportó
    nota = "" if prueba_ok else " (no pude copiar la prueba, pero el reporte llegó)"
    try:
        await message.reply(
            f"✅ Reporte enviado al staff{nota}. Gracias, lo revisaremos."
        )
    except TelegramBadRequest:
        pass


async def _copy_evidence_to_staff(
    bot: Bot, messages: list[Message], staff_chat: int,
) -> bool:
    """
    Copia la prueba (foto/vídeo/álbum) al grupo de staff usando copy_message.
    copy_message copia el contenido SIN la etiqueta "reenviado de".
    Devuelve True si al menos una prueba se copió.
    """
    copied = False
    for m in messages:
        # Solo copiar mensajes con contenido multimedia relevante
        has_media = bool(
            m.photo or m.video or m.animation or m.document
            or m.video_note or m.voice or m.audio
        )
        if not has_media:
            continue
        try:
            await bot.copy_message(
                chat_id=staff_chat,
                from_chat_id=m.chat.id,
                message_id=m.message_id,
            )
            copied = True
        except (TelegramBadRequest, TelegramForbiddenError) as e:
            logger.debug("No se pudo copiar prueba al staff: %s", e)
    return copied


# ===========================================================================
# BOTONES DEL REPORTE (los pulsa el staff)
# ===========================================================================
@router.callback_query(F.data.startswith("rep:"))
async def cb_report_action(cb: CallbackQuery, bot: Bot) -> None:
    parts = cb.data.split(":")
    if len(parts) != 3:
        await cb.answer("Datos inválidos")
        return
    _, action, report_id_str = parts
    try:
        report_id = int(report_id_str)
    except ValueError:
        await cb.answer("ID inválido")
        return

    if not cb.from_user:
        await cb.answer()
        return

    # Solo staff (o owner) pueden resolver
    is_staff = await roles_db.is_staff(cb.from_user.id)
    is_owner = OWNER_USER_ID is not None and cb.from_user.id == OWNER_USER_ID
    if not (is_staff or is_owner):
        await cb.answer("❌ Solo el staff puede resolver reportes.", show_alert=True)
        return

    # Obtener el reporte
    report = await sanctions_db.get_report(report_id)
    if not report:
        await cb.answer("Este reporte ya no existe.", show_alert=True)
        return
    if report["status"] != sanctions_db.REPORT_PENDING:
        # Ya resuelto por otro staff
        resolver = report.get("resolved_by")
        await cb.answer("⚠️ Este reporte ya fue resuelto.", show_alert=True)
        return

    target_id = report.get("target_id")
    if not target_id:
        await cb.answer(
            "❌ No se puede sancionar: el reportado no está identificado. "
            "Usa los comandos manuales.",
            show_alert=True,
        )
        return

    target_user = report.get("target_user")
    target_name = report.get("target_name")
    reason = report.get("reason") or "Reporte del staff"

    # Marcar el reporte como resuelto (evita doble resolución)
    resolved = await sanctions_db.resolve_report(report_id, cb.from_user.id, action)
    if resolved is None:
        await cb.answer("⚠️ Otro staff acaba de resolverlo.", show_alert=True)
        return

    # Aplicar la sanción con aviso EVERYWHERE (viene de un reporte)
    accion_texto = ""
    if action == "leve":
        await sanctions_actions.apply_warn_action(
            bot, target_id, target_user, target_name,
            sanctions_db.KIND_LEVE, reason,
            issued_by=cb.from_user.id, issued_in_chat=0,
            notice_scope="everywhere",
        )
        accion_texto = "⚠️ Warn leve"
    elif action == "grave":
        await sanctions_actions.apply_warn_action(
            bot, target_id, target_user, target_name,
            sanctions_db.KIND_GRAVE, reason,
            issued_by=cb.from_user.id, issued_in_chat=0,
            notice_scope="everywhere",
        )
        accion_texto = "⛔ Warn grave"
    elif action == "ban":
        await sanctions_actions.apply_ban_action(
            bot, target_id, target_user, target_name, reason,
            issued_by=cb.from_user.id, issued_in_chat=0,
            notice_scope="everywhere",
        )
        accion_texto = "🚫 Ban"
    else:
        await cb.answer("Acción desconocida")
        return

    # Editar la ficha del reporte para reflejar quién y qué resolvió
    resolver_m = _mention(
        cb.from_user.id, cb.from_user.username, cb.from_user.full_name,
    )
    target_m = _mention(target_id, target_user, target_name)
    nueva_ficha = (
        f"✅ <b>REPORTE #{report_id} RESUELTO</b>\n\n"
        f"👤 <b>Reportado:</b> {target_m}\n"
        f"📝 <b>Motivo:</b> {reason}\n\n"
        f"⚖️ <b>Acción:</b> {accion_texto}\n"
        f"👮 <b>Resuelto por:</b> {resolver_m}"
    )
    try:
        await cb.message.edit_text(nueva_ficha, reply_markup=None)
    except TelegramBadRequest:
        # Si no se puede editar (ej. era una foto), al menos quitar botones
        try:
            await cb.message.edit_reply_markup(reply_markup=None)
        except TelegramBadRequest:
            pass

    await cb.answer(f"✅ Aplicado: {accion_texto}")
