"""Comandos individuales del bot."""
import json
import logging
from datetime import datetime, timedelta
from io import BytesIO
from typing import Optional

from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.types import BufferedInputFile, Message

from database import alianzas as alianzas_db
from database import posts as posts_db
from database import warns as warns_db
from database.config_db import (
    export_config_json,
    get_config,
    import_config_json,
)
from database.stats import (
    cache_user,
    find_user_by_username,
    get_recent_logs,
    get_stats,
    list_bot_chats,
    upsert_bot_chat,
)
from locales import es
from utils.helpers import format_minutes, safe_username, time_until
from utils.permissions import is_admin, is_exempt
from utils.punishment import manual_warn

logger = logging.getLogger(__name__)
router = Router(name="commands")


# ============== /start ==============
@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    if message.chat.type == ChatType.PRIVATE:
        await message.answer(es.START_PRIVATE)
    else:
        await upsert_bot_chat(message.chat.id, message.chat.title, message.chat.type)
        await message.answer(es.START_GROUP)


# ============== Helper para resolver usuaria objetivo ==============
async def _resolve_target_user(
    message: Message, args: Optional[str]
) -> tuple[Optional[int], Optional[str], Optional[str]]:
    """
    Devuelve (user_id, username, full_name) del usuario objetivo.
    Acepta:
    - Reply a un mensaje
    - @username como argumento
    Si no encuentra, devuelve (None, None, None).
    """
    # 1. Reply
    if message.reply_to_message and message.reply_to_message.from_user:
        u = message.reply_to_message.from_user
        # Cacheamos por si acaso
        await cache_user(message.chat.id, u.id, u.username, u.full_name)
        return u.id, u.username, u.full_name
    # 2. @username
    if args:
        token = args.strip().split()[0]
        if token.startswith("@"):
            cached = await find_user_by_username(message.chat.id, token)
            if cached:
                return cached["user_id"], cached["username"], cached.get("full_name")
    return None, None, None


def _command_args(message: Message) -> Optional[str]:
    """Devuelve el texto del comando sin el /comando inicial."""
    if not message.text:
        return None
    parts = message.text.split(maxsplit=1)
    return parts[1] if len(parts) > 1 else None


# ============== /freespam ==============
@router.message(Command("freespam"))
async def cmd_freespam(message: Message, bot: Bot) -> None:
    if message.chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        await message.reply(es.ERR_NO_GROUP)
        return
    if not message.from_user or not await is_admin(bot, message.chat.id, message.from_user.id):
        await message.reply(es.ERR_NOT_ADMIN)
        return

    args = _command_args(message)
    user_id, username, _ = await _resolve_target_user(message, args)
    if not user_id:
        await message.reply(es.ERR_REPLY_NEEDED)
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
    if message.chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        await message.reply(es.ERR_NO_GROUP)
        return
    if not message.from_user or not await is_admin(bot, message.chat.id, message.from_user.id):
        await message.reply(es.ERR_NOT_ADMIN)
        return
    args = _command_args(message)
    user_id, username, _ = await _resolve_target_user(message, args)
    if not user_id:
        await message.reply(es.ERR_REPLY_NEEDED)
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
    if message.chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        await message.reply(es.ERR_NO_GROUP)
        return
    aliados = await alianzas_db.list_alianzas(message.chat.id)
    if not aliados:
        await message.reply(es.NO_ALIANZAS)
        return
    lines = ["👥 <b>Alianzas activas</b>", ""]
    for a in aliados:
        lines.append(f"• {safe_username(a.get('username'), a['user_id'])}")
    lines.append("")
    lines.append(f"Total: {len(aliados)}")
    await message.reply("\n".join(lines))


# ============== /status ==============
@router.message(Command("status"))
async def cmd_status(message: Message, bot: Bot) -> None:
    if message.chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        await message.reply(es.ERR_NO_GROUP)
        return
    cfg = await get_config(message.chat.id)
    stats = await get_stats(message.chat.id, hours=24)
    text = (
        f"📊 <b>Estado del grupo</b>\n\n"
        f"<b>Reglas activas:</b>\n"
        f"🔄 Cola: <b>{cfg['queue_size']}</b> chicas\n"
        f"⏱️ Cooldown: <b>{format_minutes(int(cfg['cooldown_minutes']))}</b>\n"
        f"🖼️ Anti-duplicado: <b>{cfg['antidup_hours']}h</b> (sens. {cfg['phash_threshold']})\n\n"
        f"<b>Últimas 24h:</b>\n"
        f"📸 Publicaciones: {stats['total_posts']}\n"
        f"👤 Chicas distintas: {stats['distinct_users']}\n"
        f"🚫 Borrados cola: {stats['deletes']['queue']}\n"
        f"🚫 Borrados cooldown: {stats['deletes']['cooldown']}\n"
        f"🚫 Borrados duplicado: {stats['deletes']['antidup']}"
    )
    await message.reply(text)


# ============== /myturn ==============
@router.message(Command("myturn"))
async def cmd_myturn(message: Message, bot: Bot) -> None:
    if message.chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        await message.reply(es.ERR_NO_GROUP)
        return
    if not message.from_user:
        return
    user_id = message.from_user.id
    chat_id = message.chat.id

    if await is_exempt(bot, chat_id, user_id):
        await message.reply("✨ Eres admin o alianza: puedes publicar cuando quieras.")
        return

    cfg = await get_config(chat_id)
    last = await posts_db.get_last_post_time(chat_id, user_id)
    if last is None:
        await message.reply("✅ Aún no has publicado. Puedes hacerlo ahora.")
        return

    # Cooldown restante
    cd_until = last + timedelta(minutes=int(cfg["cooldown_minutes"]))
    cd_left = time_until(cd_until)
    # Cola restante
    n_distinct = await posts_db.count_distinct_users_after(
        chat_id, last, exclude_user_id=user_id
    )
    queue_size = int(cfg["queue_size"])
    cola_left = max(0, queue_size - n_distinct)

    cooldown_ok = datetime.utcnow() >= cd_until
    cola_ok = cola_left == 0
    if cooldown_ok and cola_ok:
        await message.reply("✅ Puedes publicar ahora mismo.")
        return

    lines = ["⏳ <b>Cuándo te toca</b>", ""]
    if not cooldown_ok:
        lines.append(f"⏱️ Cooldown: faltan <b>{cd_left}</b>")
    else:
        lines.append("⏱️ Cooldown: ✅ listo")
    if not cola_ok:
        lines.append(f"🔄 Cola: faltan <b>{cola_left}</b> chicas por publicar")
    else:
        lines.append("🔄 Cola: ✅ listo")
    await message.reply("\n".join(lines))


# ============== /whocanpost ==============
@router.message(Command("whocanpost"))
async def cmd_whocanpost(message: Message, bot: Bot) -> None:
    if message.chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        await message.reply(es.ERR_NO_GROUP)
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
        cd_ok = (now - last).total_seconds() >= cooldown_min * 60
        n_distinct = await posts_db.count_distinct_users_after(
            message.chat.id, last, exclude_user_id=poster["user_id"]
        )
        cola_ok = n_distinct >= queue_size
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
    lines.append(f"🚫 En espera: {len(cannot_post)}")
    await message.reply("\n".join(lines))


# ============== /warn ==============
@router.message(Command("warn"))
async def cmd_warn(message: Message, bot: Bot) -> None:
    if message.chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        await message.reply(es.ERR_NO_GROUP)
        return
    if not message.from_user or not await is_admin(bot, message.chat.id, message.from_user.id):
        await message.reply(es.ERR_NOT_ADMIN)
        return
    args = _command_args(message)
    user_id, username, _ = await _resolve_target_user(message, args)
    if not user_id:
        await message.reply(es.ERR_REPLY_NEEDED)
        return
    # Extraer motivo:
    # - Si hay reply, todos los args son el motivo
    # - Si no, el primer token es @username, el resto es el motivo
    if message.reply_to_message:
        reason = (args or "").strip() or "manual"
    else:
        parts = args.split(maxsplit=1) if args else []
        reason = parts[1].strip() if len(parts) > 1 else "manual"
    total = await manual_warn(
        bot, message.chat.id, user_id, username, reason
    )
    cfg = await get_config(message.chat.id)
    mention = safe_username(username, user_id)
    await message.reply(f"⚠️ Warn aplicado a {mention} ({total}/{cfg['warn_limit']})")


# ============== /unwarn ==============
@router.message(Command("unwarn"))
async def cmd_unwarn(message: Message, bot: Bot) -> None:
    if message.chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        await message.reply(es.ERR_NO_GROUP)
        return
    if not message.from_user or not await is_admin(bot, message.chat.id, message.from_user.id):
        await message.reply(es.ERR_NOT_ADMIN)
        return
    args = _command_args(message)
    user_id, username, _ = await _resolve_target_user(message, args)
    if not user_id:
        await message.reply(es.ERR_REPLY_NEEDED)
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
    if message.chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        await message.reply(es.ERR_NO_GROUP)
        return
    args = _command_args(message)
    user_id, username, _ = await _resolve_target_user(message, args)
    if not user_id:
        await message.reply(es.ERR_REPLY_NEEDED)
        return
    items = await warns_db.list_warns(message.chat.id, user_id)
    mention = safe_username(username, user_id)
    if not items:
        await message.reply(f"✅ {mention} no tiene warns activos.")
        return
    cfg = await get_config(message.chat.id)
    lines = [f"⚠️ <b>Warns de {mention}</b> ({len(items)}/{cfg['warn_limit']})", ""]
    for w in items:
        lines.append(f"• {w['warned_at']}: {w['reason']}")
    await message.reply("\n".join(lines))


# ============== /logs ==============
@router.message(Command("logs"))
async def cmd_logs(message: Message, bot: Bot) -> None:
    if message.chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        await message.reply(es.ERR_NO_GROUP)
        return
    if not message.from_user or not await is_admin(bot, message.chat.id, message.from_user.id):
        await message.reply(es.ERR_NOT_ADMIN)
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
    if message.chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        await message.reply(es.ERR_NO_GROUP)
        return
    if not message.from_user or not await is_admin(bot, message.chat.id, message.from_user.id):
        await message.reply(es.ERR_NOT_ADMIN)
        return
    from utils.permissions import invalidate_admin_cache
    invalidate_admin_cache(message.chat.id)
    await message.reply("🔄 Configuración recargada (cache de admins limpiado).")


# ============== /export ==============
@router.message(Command("export"))
async def cmd_export(message: Message, bot: Bot) -> None:
    if message.chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        await message.reply(es.ERR_NO_GROUP)
        return
    if not message.from_user or not await is_admin(bot, message.chat.id, message.from_user.id):
        await message.reply(es.ERR_NOT_ADMIN)
        return
    raw = await export_config_json(message.chat.id)
    file = BufferedInputFile(raw.encode("utf-8"), filename=f"config_{message.chat.id}.json")
    await message.reply_document(
        file,
        caption=(
            "💾 Configuración exportada.\n\n"
            "Para importarla en otro grupo: reenvía este archivo allí "
            "respondiendo a él con /import"
        ),
    )


# ============== /import ==============
@router.message(Command("import"))
async def cmd_import(message: Message, bot: Bot) -> None:
    if message.chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        await message.reply(es.ERR_NO_GROUP)
        return
    if not message.from_user or not await is_admin(bot, message.chat.id, message.from_user.id):
        await message.reply(es.ERR_NOT_ADMIN)
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


# El cacheo pasivo de usuarias y chats se hace mediante middleware en bot.py
# (no como handler aquí, para no consumir mensajes y romper la propagación).
