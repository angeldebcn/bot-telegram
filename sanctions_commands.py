"""
=====================================================================
COMANDOS MANUALES DE SANCIÓN (solo staff + owner)
=====================================================================

Comandos que puede usar el staff en CUALQUIER grupo donde esté el bot:

  /warnleve   [reply|@|id] razón   -> warn leve (1 punto)
  /warngrave  [reply|@|id] razón   -> warn grave (2 puntos)
  /ban        [reply|@|id] razón   -> ban directo
  /mute7      [reply|@|id] razón   -> silencia 7 días
  /mute       [reply|@|id] Xd/Xh razón -> silencia duración libre

  /unwarnleve  [reply|@|id]  -> quita el último warn leve
  /unwarngrave [reply|@|id]  -> quita el último warn grave
  /unban       [reply|@|id]  -> quita el ban
  /unmute      [reply|@|id]  -> quita el silencio

Comportamiento común:
- Solo staff (lista blanca) o el owner pueden usarlos.
- La sanción (puntos, mute, ban) se aplica en TODOS los grupos marcados.
- El aviso público sale SOLO en el grupo donde se escribió el comando.
- El bot borra el comando del staff (limpieza) y publica el aviso.
- La razón que escribe el staff se usa tal cual en el aviso; en la lista
  aparecerá la versión corta/profesional.
"""
import logging
from typing import Optional

from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import Message

from config import OWNER_USER_ID
import sanctions_actions
import sanctions_db
import roles_db
from stats import cache_user, find_user_by_username

logger = logging.getLogger(__name__)
router = Router(name="sanctions_commands")


# ===========================================================================
# HELPERS
# ===========================================================================
def _is_in_group(message: Message) -> bool:
    return message.chat.type in (ChatType.GROUP, ChatType.SUPERGROUP)


async def _is_staff_or_owner(user_id: int) -> bool:
    if OWNER_USER_ID is not None and user_id == OWNER_USER_ID:
        return True
    return await roles_db.is_staff(user_id)


def _split_args(message: Message) -> Optional[str]:
    """Todo lo que va después del comando."""
    if not message.text:
        return None
    parts = message.text.split(maxsplit=1)
    return parts[1] if len(parts) > 1 else None


async def _resolve_target_global(
    bot: Bot, message: Message, args: Optional[str],
) -> tuple[Optional[int], Optional[str], Optional[str], Optional[str], Optional[str]]:
    """
    Resuelve a quién va dirigida la sanción, de forma GLOBAL.
    Devuelve (user_id, username, full_name, reason, error).

    - Reply: saca el usuario del mensaje respondido; la razón es `args` entero.
    - @username: busca primero global (todos los grupos), la razón es el resto.
    - id numérico: intenta resolver; la razón es el resto.
    """
    # 1. Reply -> el target es el autor del mensaje respondido
    if message.reply_to_message and message.reply_to_message.from_user:
        u = message.reply_to_message.from_user
        await cache_user(message.chat.id, u.id, u.username, u.full_name)
        reason = args.strip() if args else ""
        return u.id, u.username, u.full_name, reason, None

    if not args:
        return None, None, None, None, (
            "❌ Responde al mensaje de la persona, o escribe el comando seguido "
            "de @usuario o su ID y luego la razón.\n\n"
            "Ejemplo: <code>/warngrave @fulanito insultó a una modelo</code>"
        )

    tokens = args.strip().split(maxsplit=1)
    target_token = tokens[0]
    reason = tokens[1] if len(tokens) > 1 else ""

    # 2. @username
    if target_token.startswith("@"):
        # Buscar global (todos los grupos)
        found = await sanctions_db.resolve_username_global(target_token)
        if found:
            return (
                found["user_id"], found.get("username"),
                found.get("full_name"), reason, None,
            )
        return None, None, None, None, (
            f"❌ No encuentro a <b>{target_token}</b> en ningún grupo donde yo esté.\n\n"
            "Telegram no me deja buscar a alguien solo por @ si nunca lo he visto. "
            "Soluciones:\n"
            "• Responde a un mensaje suyo con el comando.\n"
            "• O usa su ID numérico (lo da @userinfobot).\n"
            "• O pídele que escriba algo en algún grupo y reintenta."
        )

    # 3. ID numérico
    if target_token.lstrip("-").isdigit():
        uid = int(target_token)
        # Intentar enriquecer con datos si lo conocemos
        info = await sanctions_db.get_sanctioned_user_info(uid)
        if info:
            return uid, info.get("username"), info.get("full_name"), reason, None
        # Intentar sacar del grupo actual
        try:
            member = await bot.get_chat_member(message.chat.id, uid)
            u = member.user
            await cache_user(message.chat.id, u.id, u.username, u.full_name)
            return uid, u.username, u.full_name, reason, None
        except TelegramBadRequest:
            return uid, None, None, reason, None

    return None, None, None, None, (
        "❌ No entendí a quién te refieres. Usa @usuario, un ID numérico, "
        "o responde a un mensaje suyo."
    )


def _parse_duration(text: str) -> Optional[int]:
    """
    Parsea una duración tipo '7d', '12h', '30m' -> segundos.
    Devuelve None si no es válida.
    """
    text = text.strip().lower()
    if not text:
        return None
    unit = text[-1]
    num = text[:-1]
    if not num.isdigit():
        return None
    n = int(num)
    if n <= 0:
        return None
    if unit == "d":
        return n * 86400
    if unit == "h":
        return n * 3600
    if unit == "m":
        return n * 60
    return None


async def _delete_command_msg(bot: Bot, message: Message) -> None:
    """Borra el mensaje del comando del staff (limpieza)."""
    try:
        await bot.delete_message(message.chat.id, message.message_id)
    except TelegramBadRequest:
        pass


async def _deny_not_staff(message: Message) -> None:
    """Responde brevemente cuando alguien sin permiso intenta un comando."""
    try:
        await message.reply("❌ No tienes permiso para usar este comando.")
    except TelegramBadRequest:
        pass


# ===========================================================================
# /warnleve  /warngrave
# ===========================================================================
async def _handle_warn(message: Message, bot: Bot, kind: str) -> None:
    if not _is_in_group(message):
        await message.reply("❌ Este comando se usa dentro de un grupo.")
        return
    if not message.from_user or not await _is_staff_or_owner(message.from_user.id):
        await _deny_not_staff(message)
        return

    args = _split_args(message)
    uid, username, full_name, reason, error = await _resolve_target_global(bot, message, args)
    if error:
        await message.reply(error)
        return
    if not reason or not reason.strip():
        tipo = "leve" if kind == sanctions_db.KIND_LEVE else "grave"
        await message.reply(
            f"❌ Falta la razón.\n\nEjemplo: <code>/warn{tipo} @usuario motivo del warn</code>"
        )
        return

    # No permitir auto-sanción del owner por error
    if OWNER_USER_ID is not None and uid == OWNER_USER_ID:
        await message.reply("❌ No puedo sancionar al dueño del bot.")
        return

    await _delete_command_msg(bot, message)
    await sanctions_actions.apply_warn_action(
        bot, uid, username, full_name, kind, reason.strip(),
        issued_by=message.from_user.id, issued_in_chat=message.chat.id,
        notice_scope="here",
    )


@router.message(Command("warnleve"))
async def cmd_warnleve(message: Message, bot: Bot) -> None:
    await _handle_warn(message, bot, sanctions_db.KIND_LEVE)


@router.message(Command("warngrave"))
async def cmd_warngrave(message: Message, bot: Bot) -> None:
    await _handle_warn(message, bot, sanctions_db.KIND_GRAVE)


# ===========================================================================
# /ban
# ===========================================================================
@router.message(Command("ban"))
async def cmd_ban(message: Message, bot: Bot) -> None:
    if not _is_in_group(message):
        await message.reply("❌ Este comando se usa dentro de un grupo.")
        return
    if not message.from_user or not await _is_staff_or_owner(message.from_user.id):
        await _deny_not_staff(message)
        return

    args = _split_args(message)
    uid, username, full_name, reason, error = await _resolve_target_global(bot, message, args)
    if error:
        await message.reply(error)
        return
    if not reason or not reason.strip():
        await message.reply(
            "❌ Falta la razón.\n\nEjemplo: <code>/ban @usuario spam reiterado</code>"
        )
        return
    if OWNER_USER_ID is not None and uid == OWNER_USER_ID:
        await message.reply("❌ No puedo sancionar al dueño del bot.")
        return

    await _delete_command_msg(bot, message)
    await sanctions_actions.apply_ban_action(
        bot, uid, username, full_name, reason.strip(),
        issued_by=message.from_user.id, issued_in_chat=message.chat.id,
        notice_scope="here",
    )


# ===========================================================================
# /mute7  y  /mute Xd/Xh
# ===========================================================================
@router.message(Command("mute7"))
async def cmd_mute7(message: Message, bot: Bot) -> None:
    if not _is_in_group(message):
        await message.reply("❌ Este comando se usa dentro de un grupo.")
        return
    if not message.from_user or not await _is_staff_or_owner(message.from_user.id):
        await _deny_not_staff(message)
        return

    args = _split_args(message)
    uid, username, full_name, reason, error = await _resolve_target_global(bot, message, args)
    if error:
        await message.reply(error)
        return
    if OWNER_USER_ID is not None and uid == OWNER_USER_ID:
        await message.reply("❌ No puedo sancionar al dueño del bot.")
        return

    reason = (reason or "").strip() or "Silenciado por el staff"
    await _delete_command_msg(bot, message)
    await sanctions_actions.apply_mute_action(
        bot, uid, username, full_name, reason,
        issued_by=message.from_user.id, issued_in_chat=message.chat.id,
        seconds=7 * 86400, notice_scope="here",
    )


@router.message(Command("mute"))
async def cmd_mute(message: Message, bot: Bot) -> None:
    if not _is_in_group(message):
        await message.reply("❌ Este comando se usa dentro de un grupo.")
        return
    if not message.from_user or not await _is_staff_or_owner(message.from_user.id):
        await _deny_not_staff(message)
        return

    args = _split_args(message)
    # Para /mute necesitamos: target + duración + razón
    # Si es reply: primera palabra de args es la duración, resto la razón
    # Si es @/id: primera palabra el target, segunda la duración, resto razón
    if message.reply_to_message and message.reply_to_message.from_user:
        u = message.reply_to_message.from_user
        await cache_user(message.chat.id, u.id, u.username, u.full_name)
        uid, username, full_name = u.id, u.username, u.full_name
        rest = (args or "").strip()
    else:
        if not args:
            await message.reply(
                "❌ Uso: <code>/mute @usuario 3d motivo</code>\n"
                "Duraciones: <code>30m</code>, <code>12h</code>, <code>7d</code>.\n"
                "O responde a un mensaje: <code>/mute 3d motivo</code>."
            )
            return
        tokens = args.strip().split(maxsplit=1)
        target_token = tokens[0]
        rest = tokens[1] if len(tokens) > 1 else ""
        # resolver target
        _msg_args = args
        uid, username, full_name, _reason, error = await _resolve_target_global(
            bot, message, args,
        )
        if error:
            await message.reply(error)
            return

    # Ahora `rest` empieza por la duración
    dtokens = rest.split(maxsplit=1)
    if not dtokens:
        await message.reply(
            "❌ Falta la duración. Ejemplo: <code>/mute @usuario 3d motivo</code>"
        )
        return
    seconds = _parse_duration(dtokens[0])
    if seconds is None:
        await message.reply(
            "❌ Duración inválida. Usa por ejemplo <code>30m</code>, "
            "<code>12h</code> o <code>7d</code>."
        )
        return
    reason = (dtokens[1].strip() if len(dtokens) > 1 else "") or "Silenciado por el staff"

    if OWNER_USER_ID is not None and uid == OWNER_USER_ID:
        await message.reply("❌ No puedo sancionar al dueño del bot.")
        return

    await _delete_command_msg(bot, message)
    await sanctions_actions.apply_mute_action(
        bot, uid, username, full_name, reason,
        issued_by=message.from_user.id, issued_in_chat=message.chat.id,
        seconds=seconds, notice_scope="here",
    )


# ===========================================================================
# LOS /un...
# ===========================================================================
async def _resolve_target_simple(
    bot: Bot, message: Message, args: Optional[str],
) -> tuple[Optional[int], Optional[str], Optional[str], Optional[str]]:
    """Como _resolve_target_global pero sin razón (para los /un...)."""
    uid, username, full_name, _reason, error = await _resolve_target_global(
        bot, message, args,
    )
    return uid, username, full_name, error


@router.message(Command("unwarnleve"))
async def cmd_unwarnleve(message: Message, bot: Bot) -> None:
    await _handle_unwarn(message, bot, sanctions_db.KIND_LEVE)


@router.message(Command("unwarngrave"))
async def cmd_unwarngrave(message: Message, bot: Bot) -> None:
    await _handle_unwarn(message, bot, sanctions_db.KIND_GRAVE)


async def _handle_unwarn(message: Message, bot: Bot, kind: str) -> None:
    if not message.from_user or not await _is_staff_or_owner(message.from_user.id):
        await _deny_not_staff(message)
        return
    args = _split_args(message)
    uid, username, full_name, error = await _resolve_target_simple(bot, message, args)
    if error:
        await message.reply(error)
        return
    revoked = await sanctions_actions.remove_warn_action(
        bot, uid, kind, message.from_user.id,
    )
    tipo = "leve" if kind == sanctions_db.KIND_LEVE else "grave"
    if revoked:
        status = await sanctions_db.get_user_status(uid)
        await message.reply(
            f"✅ Quitado el último warn {tipo}. "
            f"Puntos actuales: <b>{status['points']}</b>."
        )
    else:
        await message.reply(f"ℹ️ Esa persona no tiene ningún warn {tipo} activo.")


@router.message(Command("unban"))
async def cmd_unban(message: Message, bot: Bot) -> None:
    if not message.from_user or not await _is_staff_or_owner(message.from_user.id):
        await _deny_not_staff(message)
        return
    args = _split_args(message)
    uid, username, full_name, error = await _resolve_target_simple(bot, message, args)
    if error:
        await message.reply(error)
        return
    had = await sanctions_actions.remove_ban_action(bot, uid, message.from_user.id)
    if had:
        await message.reply("✅ Ban retirado. La persona puede volver a los grupos.")
    else:
        await message.reply("ℹ️ Esa persona no estaba baneada.")


@router.message(Command("unmute"))
async def cmd_unmute(message: Message, bot: Bot) -> None:
    if not message.from_user or not await _is_staff_or_owner(message.from_user.id):
        await _deny_not_staff(message)
        return
    args = _split_args(message)
    uid, username, full_name, error = await _resolve_target_simple(bot, message, args)
    if error:
        await message.reply(error)
        return
    await sanctions_actions.remove_mute_action(bot, uid, message.from_user.id)
    await message.reply("✅ Silencio retirado. La persona puede volver a escribir.")
