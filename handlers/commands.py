"""Comandos del bot."""
import logging
from datetime import datetime, timedelta
from io import BytesIO
from typing import Optional

from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.types import BufferedInputFile, Message

from config import OWNER_USERNAME
from database import alianzas as alianzas_db
from database import posts as posts_db
from database import warns as warns_db
from database.config_db import (
    export_config_json,
    get_config,
    import_config_json,
    update_config,
)
from database.stats import (
    cache_user,
    find_user_by_username,
    get_recent_logs,
    get_stats,
    upsert_bot_chat,
)
from handlers.media import grant_force_pass
from locales import es
from utils.helpers import format_minutes, safe_username, time_until
from utils.license_helpers import chat_is_allowed, is_owner
from utils.permissions import is_admin, is_exempt
from utils.punishment import manual_warn

logger = logging.getLogger(__name__)
router = Router(name="commands")


# ============== Helpers ==============
def _command_args(message: Message) -> Optional[str]:
    if not message.text:
        return None
    parts = message.text.split(maxsplit=1)
    return parts[1] if len(parts) > 1 else None


async def _resolve_target_user(
    bot: Bot,
    message: Message,
    args: Optional[str],
) -> tuple[Optional[int], Optional[str], Optional[str], Optional[str]]:
    """
    Devuelve (user_id, username, full_name, error).
    - Si va por reply: extrae del reply.
    - Si va por @username: busca en cache.
    - Si va por user_id numérico: intenta resolver vía Telegram API.
    error es un mensaje legible cuando no se pudo resolver.
    """
    # 1. Reply
    if message.reply_to_message and message.reply_to_message.from_user:
        u = message.reply_to_message.from_user
        await cache_user(message.chat.id, u.id, u.username, u.full_name)
        return u.id, u.username, u.full_name, None

    if not args:
        return (
            None, None, None,
            "❌ Debes responder al mensaje de la usuaria, o escribir el comando "
            "seguido de @su_username o de su ID numérico.\n\n"
            "Ejemplos:\n"
            "  <code>/freespam @maria</code>\n"
            "  <code>/freespam 123456789</code>"
        )

    token = args.strip().split()[0]

    # 2. @username
    if token.startswith("@"):
        cached = await find_user_by_username(message.chat.id, token)
        if cached:
            return (
                cached["user_id"], cached["username"], cached.get("full_name"), None,
            )
        return (
            None, None, None,
            f"❌ No encuentro a <b>{token}</b> en este grupo.\n\n"
            "Telegram no me permite buscar a alguien solo por @username. "
            "Soluciones:\n"
            "  • Pide a la usuaria que escriba <b>cualquier mensaje</b> en el grupo "
            "(con eso la recordaré) y vuelve a intentarlo.\n"
            "  • O responde a un mensaje suyo con el comando.\n"
            "  • O usa su <b>ID numérico</b> (lo da @userinfobot)."
        )

    # 3. user_id numérico
    if token.lstrip("-").isdigit():
        try:
            uid = int(token)
        except ValueError:
            return None, None, None, "❌ ID inválido."
        try:
            member = await bot.get_chat_member(message.chat.id, uid)
            u = member.user
            await cache_user(message.chat.id, u.id, u.username, u.full_name)
            return u.id, u.username, u.full_name, None
        except TelegramBadRequest:
            # No está en el grupo, pero podemos referirla por ID
            return uid, None, None, None

    return (
        None, None, None,
        "❌ No entendí. Usa @username o un ID numérico, o responde al mensaje "
        "de la usuaria.",
    )


def _is_in_group(message: Message) -> bool:
    return message.chat.type in (ChatType.GROUP, ChatType.SUPERGROUP)


async def _check_admin_in_group(message: Message, bot: Bot) -> bool:
    """Comprueba que el comando va en grupo y el emisor es admin. Replies con error si no."""
    if not _is_in_group(message):
        await message.reply(es.ERR_NO_GROUP)
        return False
    if not message.from_user or not await is_admin(bot, message.chat.id, message.from_user.id):
        await message.reply(es.ERR_NOT_ADMIN)
        return False
    if not await chat_is_allowed(message.chat.id):
        await message.reply(es.ERR_NOT_LICENSED)
        return False
    return True


# ============== /start ==============
@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    if message.chat.type == ChatType.PRIVATE:
        await message.answer(es.START_PRIVATE.format(owner=OWNER_USERNAME))
    else:
        await upsert_bot_chat(message.chat.id, message.chat.title, message.chat.type)
        if await chat_is_allowed(message.chat.id):
            await message.answer(es.START_GROUP)
        else:
            await message.answer(es.START_GROUP_NOT_LICENSED.format(owner=OWNER_USERNAME))


# ============== /help ==============
@router.message(Command("help", "ayuda"))
async def cmd_help(message: Message, bot: Bot) -> None:
    """Lista de todos los comandos disponibles."""
    is_priv = message.chat.type == ChatType.PRIVATE
    owner_section = ""
    if is_owner(message.from_user.id if message.from_user else None):
        owner_section = (
            "\n\n👑 <b>COMANDOS DE OWNER</b> (solo tú)\n"
            "<code>/admin</code> — Panel de licencias y suscripciones\n"
            "<code>/admin help</code> — Más comandos de admin"
        )
    if is_priv:
        text = (
            "📚 <b>COMANDOS DISPONIBLES</b>\n\n"
            "🗂️ <b>EN PRIVADO CONMIGO</b>\n"
            "<code>/menu</code> — Configurar uno de mis grupos\n"
            "<code>/start</code> — Información del bot\n"
            "<code>/help</code> — Esta ayuda\n\n"
            "💡 <i>Para configurar un grupo, escribe /menu aquí. "
            "Te listaré los grupos donde estoy y eres admin.</i>"
            + owner_section
        )
    else:
        text = (
            "📚 <b>COMANDOS DISPONIBLES EN ESTE GRUPO</b>\n\n"
            "🛠️ <b>Configuración</b> (admins)\n"
            "<code>/menu</code> — Menú completo de configuración\n"
            "<code>/status</code> — Estado y estadísticas 24h\n"
            "<code>/reload</code> — Recargar lista de admins\n"
            "<code>/lock</code> / <code>/unlock</code> — Pausar/reanudar el bot\n"
            "<code>/export</code> — Exportar config a JSON\n"
            "<code>/import</code> — Importar config (responde a un .json)\n\n"
            "👥 <b>Alianzas</b> (admins)\n"
            "<code>/freespam @user</code> — Eximir a usuaria de las reglas\n"
            "<code>/unfreespam @user</code> — Retirar exención\n"
            "<code>/alianzas</code> — Lista de exentas\n\n"
            "⚠️ <b>Advertencias</b> (admins)\n"
            "<code>/warn @user motivo</code> — Advertir\n"
            "<code>/unwarn @user</code> — Quitar último warn\n"
            "<code>/warns @user</code> — Ver warns activos\n\n"
            "⚡ <b>Atajos</b> (admins)\n"
            "<code>/forcepost @user</code> — Pase libre próxima publicación\n"
            "<code>/logs</code> — Últimas 20 acciones del bot\n\n"
            "✨ <b>Para todas</b>\n"
            "<code>/myturn</code> — Cuándo me toca a mí publicar\n"
            "<code>/whocanpost</code> — Quién puede publicar ahora\n"
            "<code>/help</code> — Esta ayuda"
            + owner_section
        )
    await message.reply(text)


# ============== /freespam ==============
@router.message(Command("freespam"))
async def cmd_freespam(message: Message, bot: Bot) -> None:
    if not await _check_admin_in_group(message, bot):
        return
    args = _command_args(message)
    user_id, username, _full, error = await _resolve_target_user(bot, message, args)
    if error:
        await message.reply(error)
        return
    if not user_id:
        await message.reply(es.ERR_USER_NOT_FOUND)
        return
    mention = safe_username(username, user_id)
    added = await alianzas_db.add_alianza(message.chat.id, user_id, username)
    if added:
        await message.reply(es.OK_ALIANZA_ADDED.format(mention=mention))
    else:
        await message.reply(es.OK_ALIANZA_ALREADY.format(mention=mention))


# ============== /unfreespam ==============
@router.message(Command("unfreespam"))
async def cmd_unfreespam(message: Message, bot: Bot) -> None:
    if not await _check_admin_in_group(message, bot):
        return
    args = _command_args(message)
    user_id, username, _full, error = await _resolve_target_user(bot, message, args)
    if error:
        await message.reply(error)
        return
    if not user_id:
        await message.reply(es.ERR_USER_NOT_FOUND)
        return
    mention = safe_username(username, user_id)
    removed = await alianzas_db.remove_alianza(message.chat.id, user_id)
    if removed:
        await message.reply(es.OK_ALIANZA_REMOVED.format(mention=mention))
    else:
        await message.reply(es.OK_ALIANZA_NOT_FOUND.format(mention=mention))


# ============== /alianzas ==============
@router.message(Command("alianzas"))
async def cmd_alianzas(message: Message, bot: Bot) -> None:
    if not _is_in_group(message):
        await message.reply(es.ERR_NO_GROUP)
        return
    if not await chat_is_allowed(message.chat.id):
        await message.reply(es.ERR_NOT_LICENSED)
        return
    aliados = await alianzas_db.list_alianzas(message.chat.id)
    if not aliados:
        await message.reply(es.NO_ALIANZAS)
        return
    lines = ["👥 <b>Alianzas activas</b>", ""]
    for a in aliados:
        lines.append(f"• {safe_username(a.get('username'), a['user_id'])}")
    lines.append("")
    lines.append(f"Total: <b>{len(aliados)}</b>")
    await message.reply("\n".join(lines))


# ============== /status ==============
@router.message(Command("status"))
async def cmd_status(message: Message, bot: Bot) -> None:
    if not _is_in_group(message):
        await message.reply(es.ERR_NO_GROUP)
        return
    if not await chat_is_allowed(message.chat.id):
        await message.reply(es.ERR_NOT_LICENSED)
        return
    cfg = await get_config(message.chat.id)
    stats = await get_stats(message.chat.id, hours=24)
    locked = int(cfg.get("locked", 0))
    rule_state = lambda key: "✅" if int(cfg.get(key, 1)) else "❌"
    text = (
        f"📊 <b>Estado del grupo</b>\n\n"
    )
    if locked:
        text += "🔕 <b>BOT EN PAUSA</b> (/unlock para reanudar)\n\n"
    text += (
        f"<b>Reglas activas:</b>\n"
        f"{rule_state('queue_enabled')} Cola: <b>{cfg['queue_size']}</b> chicas\n"
        f"{rule_state('cooldown_enabled')} Cooldown: <b>{format_minutes(int(cfg['cooldown_minutes']))}</b>\n"
        f"{rule_state('antidup_enabled')} Anti-duplicado: <b>{cfg['antidup_hours']}h</b>\n\n"
        f"<b>Últimas 24h:</b>\n"
        f"📸 Publicaciones: {stats['total_posts']}\n"
        f"👤 Chicas distintas: {stats['distinct_users']}\n"
        f"🚫 Borrados cola: {stats['deletes']['queue']}\n"
        f"🚫 Borrados cooldown: {stats['deletes']['cooldown']}\n"
        f"🚫 Borrados duplicado: {stats['deletes']['antidup']}"
    )
    await message.reply(text)


# ============== /lock ==============
@router.message(Command("lock"))
async def cmd_lock(message: Message, bot: Bot) -> None:
    if not await _check_admin_in_group(message, bot):
        return
    await update_config(message.chat.id, "locked", 1)
    await message.reply(
        "🔕 <b>Bot pausado</b>\n\n"
        "No aplicaré ninguna regla hasta que escribas <code>/unlock</code>.\n"
        "Tu configuración se mantiene intacta."
    )


# ============== /unlock ==============
@router.message(Command("unlock"))
async def cmd_unlock(message: Message, bot: Bot) -> None:
    if not await _check_admin_in_group(message, bot):
        return
    await update_config(message.chat.id, "locked", 0)
    await message.reply(
        "✅ <b>Bot reactivado</b>\n\n"
        "Las reglas vuelven a aplicarse normalmente."
    )


# ============== /forcepost ==============
@router.message(Command("forcepost", "freepass"))
async def cmd_forcepost(message: Message, bot: Bot) -> None:
    if not await _check_admin_in_group(message, bot):
        return
    args = _command_args(message)
    user_id, username, _full, error = await _resolve_target_user(bot, message, args)
    if error:
        await message.reply(error)
        return
    if not user_id:
        await message.reply(es.ERR_USER_NOT_FOUND)
        return
    grant_force_pass(message.chat.id, user_id)
    mention = safe_username(username, user_id)
    await message.reply(
        f"⚡ {mention} tiene <b>pase libre</b> para su próxima publicación.\n"
        f"Las 3 reglas se ignorarán solo en ese mensaje."
    )


# ============== /myturn ==============
@router.message(Command("myturn"))
async def cmd_myturn(message: Message, bot: Bot) -> None:
    if not _is_in_group(message):
        await message.reply(es.ERR_NO_GROUP)
        return
    if not await chat_is_allowed(message.chat.id):
        return
    if not message.from_user:
        return
    user_id = message.from_user.id
    chat_id = message.chat.id

    if await is_exempt(bot, chat_id, user_id):
        await message.reply("✨ Eres admin o alianza: puedes publicar cuando quieras.")
        return

    cfg = await get_config(chat_id)
    if int(cfg.get("locked", 0)):
        await message.reply("🔕 El bot está en pausa, todas pueden publicar.")
        return

    last = await posts_db.get_last_post_time(chat_id, user_id)
    if last is None:
        await message.reply("✅ Aún no has publicado. Puedes hacerlo ahora.")
        return

    lines = ["⏳ <b>Cuándo te toca</b>", ""]
    if int(cfg.get("cooldown_enabled", 1)):
        cd_until = last + timedelta(minutes=int(cfg["cooldown_minutes"]))
        if datetime.utcnow() < cd_until:
            lines.append(f"⏱️ Cooldown: faltan <b>{time_until(cd_until)}</b>")
        else:
            lines.append("⏱️ Cooldown: ✅ listo")
    if int(cfg.get("queue_enabled", 1)):
        n_distinct = await posts_db.count_distinct_users_after(
            chat_id, last, exclude_user_id=user_id,
        )
        queue_size = int(cfg["queue_size"])
        cola_left = max(0, queue_size - n_distinct)
        if cola_left:
            lines.append(f"🔄 Cola: faltan <b>{cola_left}</b> chicas por publicar")
        else:
            lines.append("🔄 Cola: ✅ listo")

    if len(lines) == 2:
        await message.reply("✅ Puedes publicar ahora mismo.")
        return

    await message.reply("\n".join(lines))


# ============== /whocanpost ==============
@router.message(Command("whocanpost"))
async def cmd_whocanpost(message: Message, bot: Bot) -> None:
    if not _is_in_group(message):
        await message.reply(es.ERR_NO_GROUP)
        return
    if not await chat_is_allowed(message.chat.id):
        return
    cfg = await get_config(message.chat.id)
    recent = await posts_db.list_recent_posters(message.chat.id, hours=48)
    if not recent:
        await message.reply("✏️ Nadie ha publicado en las últimas 48h. Todas pueden publicar.")
        return
    cooldown_min = int(cfg["cooldown_minutes"])
    queue_size = int(cfg["queue_size"])
    now = datetime.utcnow()
    can_post = []
    cannot_post = []
    for poster in recent:
        last = datetime.fromisoformat(poster["last"])
        cd_ok = (
            not int(cfg.get("cooldown_enabled", 1))
            or (now - last).total_seconds() >= cooldown_min * 60
        )
        if int(cfg.get("queue_enabled", 1)):
            n_distinct = await posts_db.count_distinct_users_after(
                message.chat.id, last, exclude_user_id=poster["user_id"],
            )
            cola_ok = n_distinct >= queue_size
        else:
            cola_ok = True
        mention = safe_username(poster.get("username"), poster["user_id"])
        if cd_ok and cola_ok:
            can_post.append(mention)
        else:
            cannot_post.append(mention)

    lines = []
    if can_post:
        lines.append("✅ <b>Pueden publicar ahora:</b>")
        for m in can_post[:30]:
            lines.append(f"  • {m}")
    else:
        lines.append("⏳ Ninguna de las recientes puede publicar todavía.")
    lines.append("")
    lines.append(f"🚫 En espera: <b>{len(cannot_post)}</b>")
    await message.reply("\n".join(lines))


# ============== /warn ==============
@router.message(Command("warn"))
async def cmd_warn(message: Message, bot: Bot) -> None:
    if not await _check_admin_in_group(message, bot):
        return
    args = _command_args(message)
    user_id, username, _full, error = await _resolve_target_user(bot, message, args)
    if error:
        await message.reply(error)
        return
    if not user_id:
        await message.reply(es.ERR_USER_NOT_FOUND)
        return
    # Motivo
    if message.reply_to_message:
        reason = (args or "").strip() or "manual"
    else:
        parts = args.split(maxsplit=1) if args else []
        reason = parts[1].strip() if len(parts) > 1 else "manual"
    total = await manual_warn(bot, message.chat.id, user_id, username, reason)
    cfg = await get_config(message.chat.id)
    mention = safe_username(username, user_id)
    await message.reply(
        f"⚠️ Warn aplicado a {mention} ({total}/{cfg['warn_limit']})"
    )


# ============== /unwarn ==============
@router.message(Command("unwarn"))
async def cmd_unwarn(message: Message, bot: Bot) -> None:
    if not await _check_admin_in_group(message, bot):
        return
    args = _command_args(message)
    user_id, username, _full, error = await _resolve_target_user(bot, message, args)
    if error:
        await message.reply(error)
        return
    if not user_id:
        await message.reply(es.ERR_USER_NOT_FOUND)
        return
    removed = await warns_db.remove_last_warn(message.chat.id, user_id)
    mention = safe_username(username, user_id)
    if removed:
        await message.reply(f"✅ Warn quitado de {mention}.")
    else:
        await message.reply(f"ℹ️ {mention} no tenía warns activos.")


# ============== /warns ==============
@router.message(Command("warns"))
async def cmd_warns(message: Message, bot: Bot) -> None:
    if not _is_in_group(message):
        await message.reply(es.ERR_NO_GROUP)
        return
    if not await chat_is_allowed(message.chat.id):
        return
    args = _command_args(message)
    user_id, username, _full, error = await _resolve_target_user(bot, message, args)
    if error:
        await message.reply(error)
        return
    if not user_id:
        await message.reply(es.ERR_USER_NOT_FOUND)
        return
    items = await warns_db.list_warns(message.chat.id, user_id)
    mention = safe_username(username, user_id)
    if not items:
        await message.reply(f"✅ {mention} no tiene warns activos.")
        return
    cfg = await get_config(message.chat.id)
    lines = [f"⚠️ <b>Warns de {mention}</b> ({len(items)}/{cfg['warn_limit']})", ""]
    for w in items:
        lines.append(f"• <code>{w['warned_at'][:16]}</code>: {w['reason']}")
    await message.reply("\n".join(lines))


# ============== /logs ==============
@router.message(Command("logs"))
async def cmd_logs(message: Message, bot: Bot) -> None:
    if not await _check_admin_in_group(message, bot):
        return
    logs = await get_recent_logs(message.chat.id, limit=20)
    if not logs:
        await message.reply("📜 No hay acciones registradas todavía.")
        return
    lines = ["📜 <b>Últimas 20 acciones</b>", ""]
    for log in logs:
        u = safe_username(log.get("username"), log.get("user_id") or 0)
        rule = log.get("rule") or "-"
        lines.append(f"<code>{log['timestamp'][:16]}</code> {log['action']}/{rule} {u}")
    await message.reply("\n".join(lines))


# ============== /reload ==============
@router.message(Command("reload"))
async def cmd_reload(message: Message, bot: Bot) -> None:
    if not await _check_admin_in_group(message, bot):
        return
    from utils.permissions import invalidate_admin_cache
    invalidate_admin_cache(message.chat.id)
    await message.reply("🔄 Lista de admins recargada.")


# ============== /export ==============
@router.message(Command("export"))
async def cmd_export(message: Message, bot: Bot) -> None:
    if not await _check_admin_in_group(message, bot):
        return
    raw = await export_config_json(message.chat.id)
    file = BufferedInputFile(raw.encode("utf-8"), filename=f"config_{message.chat.id}.json")
    await message.reply_document(
        file,
        caption=(
            "💾 Configuración exportada.\n\n"
            "Para importarla en otro grupo: reenvía este archivo allí "
            "y responde a él con <code>/import</code>"
        ),
    )


# ============== /import ==============
@router.message(Command("import"))
async def cmd_import(message: Message, bot: Bot) -> None:
    if not await _check_admin_in_group(message, bot):
        return
    target_msg = message.reply_to_message
    if not target_msg or not target_msg.document:
        await message.reply("❌ Responde con /import al archivo JSON exportado.")
        return
    try:
        file = await bot.get_file(target_msg.document.file_id)
        buf = BytesIO()
        await bot.download_file(file.file_path, destination=buf)
        raw = buf.getvalue().decode("utf-8")
    except (TelegramBadRequest, UnicodeDecodeError) as e:
        await message.reply(f"❌ No se pudo leer el archivo: {e}")
        return
    ok, msg = await import_config_json(message.chat.id, raw)
    await message.reply(msg)
