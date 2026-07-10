"""
=====================================================================
EJECUCIÓN DE SANCIONES EN TELEGRAM
=====================================================================

Este módulo es la capa que EJECUTA en Telegram lo que el motor de puntos
(sanctions_db) decide. Necesita el objeto Bot, por eso está separado.

Responsabilidades:
- Aplicar un warn (leve/grave): registra en BD, y si se cruzan umbrales,
  ejecuta mute (2 pts) y/o ban (3 pts) en todos los grupos marcados.
- Aplicar un ban directo: banea en todos los grupos marcados.
- Aplicar un mute (manual o automático): silencia en todos los grupos
  marcados durante X tiempo.
- Publicar el aviso público etiquetando a la persona con la razón corta,
  puntos y tiempo de expiración.
- Quitar sanciones (unban, unmute) en todos los grupos.

El "alcance" del aviso público lo decide quien llama:
- Comando manual en un grupo -> aviso SOLO en ese grupo.
- Botón desde el grupo de staff -> aviso en TODOS los grupos donde se
  haya visto a la persona.
"""
import logging
from datetime import datetime, timedelta
from typing import Optional

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import ChatPermissions

import sanctions_db
import roles_db
from sanctions_text import (
    clean_reason_short,
    format_points_status,
    format_time_left,
)

logger = logging.getLogger(__name__)

# Permisos de silencio total (mismo criterio que el sistema de reglas)
MUTED_PERMISSIONS = ChatPermissions(
    can_send_messages=False,
    can_send_audios=False,
    can_send_documents=False,
    can_send_photos=False,
    can_send_videos=False,
    can_send_video_notes=False,
    can_send_voice_notes=False,
    can_send_polls=False,
    can_send_other_messages=False,
    can_add_web_page_previews=False,
    can_change_info=False,
    can_invite_users=False,
    can_pin_messages=False,
    can_manage_topics=False,
)


def mention_html(user_id: int, username: Optional[str] = None,
                 full_name: Optional[str] = None) -> str:
    """Mención clicable que notifica aunque el grupo esté silenciado."""
    if full_name:
        name = full_name
    elif username:
        name = f"@{username}"
    else:
        name = "usuario"
    name = name.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return f'<a href="tg://user?id={user_id}">{name}</a>'


# ===========================================================================
# EJECUCIÓN EN TELEGRAM (bajo nivel)
# ===========================================================================
async def _ban_everywhere(bot: Bot, user_id: int) -> int:
    """Banea al usuario en todos los grupos con applies_sanctions=1."""
    groups = await roles_db.get_sanction_groups()
    ok = 0
    for chat_id in groups:
        try:
            await bot.ban_chat_member(chat_id, user_id)
            ok += 1
        except (TelegramBadRequest, TelegramForbiddenError) as e:
            logger.debug("No se pudo banear a %s en %s: %s", user_id, chat_id, e)
    return ok


async def _unban_everywhere(bot: Bot, user_id: int) -> int:
    """Quita el ban del usuario en todos los grupos con applies_sanctions=1."""
    groups = await roles_db.get_sanction_groups()
    ok = 0
    for chat_id in groups:
        try:
            await bot.unban_chat_member(chat_id, user_id, only_if_banned=True)
            ok += 1
        except (TelegramBadRequest, TelegramForbiddenError) as e:
            logger.debug("No se pudo desbanear a %s en %s: %s", user_id, chat_id, e)
    return ok


async def _mute_everywhere(bot: Bot, user_id: int, until: datetime) -> int:
    """Silencia al usuario en todos los grupos con applies_sanctions=1."""
    groups = await roles_db.get_sanction_groups()
    ok = 0
    for chat_id in groups:
        try:
            await bot.restrict_chat_member(
                chat_id=chat_id,
                user_id=user_id,
                permissions=MUTED_PERMISSIONS,
                until_date=until,
            )
            ok += 1
        except (TelegramBadRequest, TelegramForbiddenError) as e:
            logger.debug("No se pudo mutear a %s en %s: %s", user_id, chat_id, e)
    return ok


async def _unmute_everywhere(bot: Bot, user_id: int) -> int:
    """Devuelve permisos normales al usuario en todos los grupos."""
    groups = await roles_db.get_sanction_groups()
    full_perms = ChatPermissions(
        can_send_messages=True,
        can_send_audios=True,
        can_send_documents=True,
        can_send_photos=True,
        can_send_videos=True,
        can_send_video_notes=True,
        can_send_voice_notes=True,
        can_send_polls=True,
        can_send_other_messages=True,
        can_add_web_page_previews=True,
        can_invite_users=True,
    )
    ok = 0
    for chat_id in groups:
        try:
            await bot.restrict_chat_member(
                chat_id=chat_id, user_id=user_id, permissions=full_perms,
            )
            ok += 1
        except (TelegramBadRequest, TelegramForbiddenError) as e:
            logger.debug("No se pudo desmutear a %s en %s: %s", user_id, chat_id, e)
    return ok


# ===========================================================================
# AVISOS PÚBLICOS
# ===========================================================================
def build_sanction_notice(
    action_label: str,
    mention: str,
    reason_short: str,
    status: dict,
) -> str:
    """
    Construye el texto del aviso público de una sanción.

    action_label: "advertido (leve)", "advertido (grave)", "baneado", etc.
    status: dict de get_user_status (para puntos y expiración).
    """
    lines = [f"🛡️ {mention} ha sido <b>{action_label}</b>."]
    lines.append(f"\n📋 <b>Motivo:</b> {reason_short}")

    if status["banned"]:
        lines.append("\n🚫 <b>Baneado permanentemente</b> de la comunidad.")
    else:
        lines.append(f"\n{format_points_status(status['points'], status['banned'])}")
        if status["next_expiry"]:
            tleft = format_time_left(status["next_expiry"])
            if tleft and tleft != "expirado":
                lines.append(f"⏳ Expira en: <b>{tleft}</b> si mantiene buen comportamiento.")
    return "".join(lines) if len(lines) == 1 else "\n".join(
        [lines[0]] + [l.lstrip("\n") for l in lines[1:]]
    )


async def _post_notice_in_chat(
    bot: Bot, chat_id: int, text: str,
) -> None:
    try:
        await bot.send_message(chat_id, text, disable_web_page_preview=True)
    except (TelegramBadRequest, TelegramForbiddenError) as e:
        logger.debug("No se pudo publicar aviso en %s: %s", chat_id, e)


async def _post_notice_everywhere(
    bot: Bot, user_id: int, text: str, exclude_chat: Optional[int] = None,
) -> int:
    """Publica el aviso en todos los grupos donde se haya visto al usuario."""
    groups = await sanctions_db.get_user_groups(user_id)
    # Solo publicar en grupos que además son de la comunidad (aplican sanciones)
    sanction_groups = set(await roles_db.get_sanction_groups())
    ok = 0
    for chat_id in groups:
        if chat_id not in sanction_groups:
            continue
        if exclude_chat is not None and chat_id == exclude_chat:
            continue
        await _post_notice_in_chat(bot, chat_id, text)
        ok += 1
    return ok


# ===========================================================================
# OPERACIONES DE ALTO NIVEL (las que llaman los comandos y botones)
# ===========================================================================
async def apply_warn_action(
    bot: Bot,
    user_id: int,
    username: Optional[str],
    full_name: Optional[str],
    kind: str,                 # "warnleve" o "warngrave"
    reason_full: str,
    issued_by: Optional[int],
    issued_in_chat: int,
    notice_scope: str,         # "here" (solo issued_in_chat) o "everywhere"
) -> dict:
    """
    Aplica un warn completo: registra, cruza umbrales (mute/ban), y publica
    los avisos. Devuelve un resumen de lo ocurrido.
    """
    reason_short = clean_reason_short(reason_full)
    # Recordar al usuario para la lista
    await sanctions_db.remember_sanctioned_user(user_id, username, full_name)

    # 1. Registrar el warn y calcular umbrales
    result = await sanctions_db.add_warn(
        user_id, kind, reason_full, reason_short, issued_by, issued_in_chat,
    )

    executed_mute = False
    executed_ban = False

    # 2. Si cruzó el umbral de ban -> banear en todos los grupos
    if result["crossed_ban"]:
        await sanctions_db.add_ban(
            user_id, reason_full, reason_short, issued_by, issued_in_chat,
        )
        await _ban_everywhere(bot, user_id)
        executed_ban = True
    # 3. Si cruzó el umbral de mute (y no baneó) -> mutear 7 días
    elif result["crossed_mute"]:
        until = datetime.utcnow() + timedelta(days=sanctions_db.AUTO_MUTE_DAYS)
        await sanctions_db.add_mute_record(
            user_id, reason_full, reason_short, issued_by, issued_in_chat, until,
        )
        await _mute_everywhere(bot, user_id, until)
        executed_mute = True

    # 4. Construir el aviso con el estado actual
    status = await sanctions_db.get_user_status(user_id)
    mention = mention_html(user_id, username, full_name)

    if executed_ban:
        action_label = "baneado de la comunidad"
    elif kind == sanctions_db.KIND_GRAVE:
        action_label = "advertido gravemente" + (" y silenciado 7 días" if executed_mute else "")
    else:
        action_label = "advertido" + (" y silenciado 7 días" if executed_mute else "")

    notice = build_sanction_notice(action_label, mention, reason_short, status)

    # 5. Publicar según alcance
    if notice_scope == "everywhere":
        await _post_notice_everywhere(bot, user_id, notice)
    else:
        await _post_notice_in_chat(bot, issued_in_chat, notice)

    return {
        "kind": kind,
        "executed_mute": executed_mute,
        "executed_ban": executed_ban,
        "points": status["points"],
        "banned": status["banned"],
    }


async def apply_ban_action(
    bot: Bot,
    user_id: int,
    username: Optional[str],
    full_name: Optional[str],
    reason_full: str,
    issued_by: Optional[int],
    issued_in_chat: int,
    notice_scope: str,
) -> dict:
    """Ban directo en todos los grupos + aviso."""
    reason_short = clean_reason_short(reason_full)
    await sanctions_db.remember_sanctioned_user(user_id, username, full_name)

    await sanctions_db.add_ban(
        user_id, reason_full, reason_short, issued_by, issued_in_chat,
    )
    await _ban_everywhere(bot, user_id)

    status = await sanctions_db.get_user_status(user_id)
    mention = mention_html(user_id, username, full_name)
    notice = build_sanction_notice("baneado de la comunidad", mention, reason_short, status)

    if notice_scope == "everywhere":
        await _post_notice_everywhere(bot, user_id, notice)
    else:
        await _post_notice_in_chat(bot, issued_in_chat, notice)

    return {"banned": True}


async def apply_mute_action(
    bot: Bot,
    user_id: int,
    username: Optional[str],
    full_name: Optional[str],
    reason_full: str,
    issued_by: Optional[int],
    issued_in_chat: int,
    seconds: int,
    notice_scope: str,
) -> dict:
    """Mute manual por X segundos en todos los grupos + aviso."""
    reason_short = clean_reason_short(reason_full)
    await sanctions_db.remember_sanctioned_user(user_id, username, full_name)

    until = datetime.utcnow() + timedelta(seconds=seconds)
    await sanctions_db.add_mute_record(
        user_id, reason_full, reason_short, issued_by, issued_in_chat, until,
    )
    await _mute_everywhere(bot, user_id, until)

    # Texto del mute (no toca puntos)
    mention = mention_html(user_id, username, full_name)
    # Formatear duración legible
    if seconds % 86400 == 0:
        dur = f"{seconds // 86400} día{'s' if seconds // 86400 != 1 else ''}"
    elif seconds % 3600 == 0:
        dur = f"{seconds // 3600} hora{'s' if seconds // 3600 != 1 else ''}"
    else:
        dur = f"{seconds // 60} minuto{'s' if seconds // 60 != 1 else ''}"

    notice = (
        f"🔇 {mention} ha sido <b>silenciado</b> durante <b>{dur}</b>.\n\n"
        f"📋 <b>Motivo:</b> {reason_short}"
    )
    if notice_scope == "everywhere":
        await _post_notice_everywhere(bot, user_id, notice)
    else:
        await _post_notice_in_chat(bot, issued_in_chat, notice)

    return {"muted": True, "seconds": seconds}


# ===========================================================================
# QUITAR SANCIONES
# ===========================================================================
async def remove_warn_action(
    bot: Bot, user_id: int, kind: str, revoked_by: Optional[int],
) -> Optional[dict]:
    """Quita el warn más reciente de un tipo. Devuelve la sanción o None."""
    return await sanctions_db.revoke_last(user_id, kind, revoked_by)


async def remove_ban_action(
    bot: Bot, user_id: int, revoked_by: Optional[int],
) -> bool:
    """Quita el ban y lo desbanea en todos los grupos."""
    had = await sanctions_db.revoke_ban(user_id, revoked_by)
    if had:
        await _unban_everywhere(bot, user_id)
    return had


async def remove_mute_action(
    bot: Bot, user_id: int, revoked_by: Optional[int],
) -> int:
    """Quita mutes activos y devuelve permisos en todos los grupos."""
    n = await sanctions_db.revoke_active_mutes(user_id, revoked_by)
    await _unmute_everywhere(bot, user_id)
    return n
