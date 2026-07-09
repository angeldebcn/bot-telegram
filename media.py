"""
Handler de mensajes en grupos. Aplica:
1. Licencia (si no está activada, ignora todo).
2. /lock (si activo, ignora todo).
3. Filtros de tipo de contenido (estilo GroupHelp).
4. /forcepost (si la chica tiene pase libre, registra y sale).
5. Reglas de cola/cooldown/anti-duplicado (cada una con su toggle).

Álbumes (media_group_id): se buffer-ean ~2s y se procesan como UNA publicación.
"""
import logging
from datetime import datetime, timedelta
from io import BytesIO
from typing import Optional

from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import ChatMemberUpdated, Message

from config import OWNER_USER_ID, OWNER_USERNAME
import licenses as licenses_db
import posts as posts_db
from config_db import get_config, update_chat_title
from stats import cache_user, log_action, remove_bot_chat, upsert_bot_chat
from album_collector import album_collector
from filters import apply_filter_action, detect_message_type
from helpers import time_until
from license_helpers import (
    chat_is_allowed,
    is_owner,
    notify_owner,
    subscription_pitch,
)
from media_hash import phash_image, phash_video_first_frame
from permissions import is_admin, is_exempt
from punishment import apply_punishment, delete_messages_safe

logger = logging.getLogger(__name__)
router = Router(name="media")


# /forcepost: pase libre temporal en memoria
# {chat_id: {user_id, ...}}
_force_pass: dict[int, set[int]] = {}


def grant_force_pass(chat_id: int, user_id: int) -> None:
    """Concede un pase libre para la próxima publicación."""
    _force_pass.setdefault(chat_id, set()).add(user_id)


def _consume_force_pass(chat_id: int, user_id: int) -> bool:
    """Devuelve True si el usuario tenía pase, y lo consume."""
    s = _force_pass.get(chat_id)
    if s and user_id in s:
        s.discard(user_id)
        if not s:
            _force_pass.pop(chat_id, None)
        return True
    return False


# === Auto-borrado de mensajes de servicio ===
@router.message(
    F.chat.type.in_({"group", "supergroup"}),
    F.new_chat_members | F.left_chat_member | F.new_chat_title
    | F.new_chat_photo | F.delete_chat_photo | F.pinned_message
    | F.group_chat_created | F.supergroup_chat_created | F.channel_chat_created
    | F.message_auto_delete_timer_changed
    | F.video_chat_started | F.video_chat_ended
    | F.video_chat_participants_invited,
)
async def handle_service_messages(message: Message, bot: Bot) -> None:
    """Borra mensajes de servicio si la opción está activada."""
    if not await chat_is_allowed(message.chat.id):
        return
    cfg = await get_config(message.chat.id)
    if not int(cfg.get("delete_service_messages", 0)):
        return
    try:
        await bot.delete_message(message.chat.id, message.message_id)
    except TelegramBadRequest:
        pass


# === Handler principal de mensajes en grupos ===
@router.message(F.chat.type.in_({"group", "supergroup"}), F.from_user)
async def handle_group_message(message: Message, bot: Bot) -> None:
    """Punto de entrada de todo mensaje en grupo."""
    # Refrescar metadata
    await _refresh_chat_meta(message)

    # Ignorar mensajes de bots
    if message.from_user.is_bot:
        return

    # 1. Licencia: si el chat no está autorizado, salir
    if not await chat_is_allowed(message.chat.id):
        return

    # 2. Lock: si el grupo está locked, no aplicar nada
    cfg = await get_config(message.chat.id)
    if int(cfg.get("locked", 0)):
        return

    # 2b. Roles de grupo: si este grupo NO aplica las 3 reglas
    # (ej. grupo de verificadas o de staff), no moderar aquí.
    import roles_db
    if not await roles_db.group_applies_rules(message.chat.id):
        return

    # 3. Si es admin o alianza, dejar pasar sin tocar
    user_id = message.from_user.id
    if await is_exempt(bot, message.chat.id, user_id):
        # Si es foto/video, registramos para detección futura de duplicados
        # (los demás tipos no se registran porque no aplica antidup)
        if message.photo or message.video:
            await album_collector.add(
                message,
                on_complete=lambda msgs: _process_publication(bot, msgs, exempt=True),
            )
        return

    # 4. Detectar tipo del mensaje
    msg_type = detect_message_type(message)

    # 5. ¿Es un tipo "contable" (sujeto a las 3 reglas)?
    # Mapeo de campo filter_X (detección) → campo count_X (toggle de reglas)
    count_field = _filter_to_count_field(msg_type) if msg_type else None
    is_countable = count_field is not None and int(cfg.get(count_field, 0)) == 1

    if not is_countable:
        # El bot ignora completamente este tipo
        return

    # 6. Buffer de álbum y aplicar las 3 reglas
    await album_collector.add(
        message,
        on_complete=lambda msgs: _process_publication(bot, msgs, exempt=False),
    )


def _filter_to_count_field(filter_field: str) -> Optional[str]:
    """
    Mapea un campo filter_X (devuelto por detect_message_type) al campo count_X
    correspondiente. Devuelve None si no hay un equivalente contable.
    """
    mapping = {
        "filter_photo": "count_photo",
        "filter_video": "count_video",
        "filter_gif": "count_gif",
        "filter_sticker": "count_sticker",
        "filter_sticker_animated": "count_sticker_animated",
        "filter_voice": "count_voice",
        "filter_audio": "count_audio",
        "filter_video_note": "count_video_note",
        "filter_document": "count_document",
    }
    return mapping.get(filter_field)


async def _process_filter_album(
    bot: Bot, messages: list[Message], filter_field: str, action: int,
) -> None:
    """Aplica un filtro a un álbum entero. (Legado, ya no se usa en el flujo principal)"""
    if not messages:
        return
    first = messages[0]
    from config import FILTER_TYPES
    label = filter_field
    for emoji, lab, field in FILTER_TYPES:
        if field == filter_field:
            label = f"{emoji} {lab}"
            break
    await apply_filter_action(
        bot, first.chat.id, first.from_user.id, first.from_user.username,
        [m.message_id for m in messages], action, label,
    )


async def _refresh_chat_meta(message: Message) -> None:
    try:
        await upsert_bot_chat(message.chat.id, message.chat.title, message.chat.type)
        if message.chat.title:
            await update_chat_title(message.chat.id, message.chat.title)
        if message.from_user and not message.from_user.is_bot:
            await cache_user(
                message.chat.id, message.from_user.id,
                message.from_user.username, message.from_user.full_name,
            )
    except Exception as e:
        logger.debug("refresh meta error: %s", e)


async def _process_publication(
    bot: Bot, messages: list[Message], exempt: bool = False,
) -> None:
    """Procesa foto/video (mensaje único o álbum)."""
    if not messages:
        return
    first = messages[0]
    chat_id = first.chat.id
    user = first.from_user
    if user is None:
        return
    user_id = user.id
    username = user.username
    message_ids = [m.message_id for m in messages]
    media_group_id = first.media_group_id

    # Exenta: solo registrar para detección futura
    if exempt:
        phash_hex, vid_size, vid_dur = await _hash_first_media(bot, first)
        await posts_db.insert_post(
            chat_id=chat_id, user_id=user_id, username=username,
            message_id=first.message_id, media_group_id=media_group_id,
            phash=phash_hex, video_size=vid_size, video_duration=vid_dur,
        )
        await log_action(chat_id, "post", user_id=user_id, username=username,
                         rule=None, details="exempt")
        return

    cfg = await get_config(chat_id)

    # /forcepost: pase libre
    if _consume_force_pass(chat_id, user_id):
        phash_hex, vid_size, vid_dur = await _hash_first_media(bot, first)
        await posts_db.insert_post(
            chat_id=chat_id, user_id=user_id, username=username,
            message_id=first.message_id, media_group_id=media_group_id,
            phash=phash_hex, video_size=vid_size, video_duration=vid_dur,
        )
        await log_action(chat_id, "post", user_id=user_id, username=username,
                         rule=None, details="forcepost")
        return

    # Calcular hash (puede ser None si falla)
    phash_hex, vid_size, vid_dur = await _hash_first_media(bot, first)

    # Regla 3: ANTI-DUPLICADO (si está activada)
    if int(cfg.get("antidup_enabled", 1)) and (phash_hex or vid_size):
        dup = await _check_duplicate(cfg, chat_id, phash_hex, vid_size, vid_dur)
        if dup:
            await apply_punishment(
                bot, chat_id, user_id, username,
                message_ids=message_ids, rule="antidup",
                extra_info=f"Ya se publicó hace menos de {cfg['antidup_hours']}h.",
            )
            return

    # === LAZY CHECK ===
    # Antes de aplicar cooldown/cola, verificar que las publicaciones recientes
    # de la usuaria SIGUEN EXISTIENDO en Telegram. Si alguien (la propia chica,
    # un admin, el dueño del mensaje) las borró manualmente, las anulamos en BD
    # y dejamos de contarlas. Así si la chica borra y vuelve a publicar, puede.
    await _sweep_deleted_posts(bot, chat_id, user_id)

    # Regla 2: COOLDOWN
    last_time = await posts_db.get_last_post_time(chat_id, user_id)
    if int(cfg.get("cooldown_enabled", 1)) and last_time is not None:
        cooldown_until = last_time + timedelta(minutes=int(cfg["cooldown_minutes"]))
        if datetime.utcnow() < cooldown_until:
            remaining = time_until(cooldown_until)
            await apply_punishment(
                bot, chat_id, user_id, username,
                message_ids=message_ids, rule="cooldown",
                extra_info=f"Espera {remaining}.",
            )
            return

    # Regla 1: COLA
    if int(cfg.get("queue_enabled", 1)) and last_time is not None:
        n_distinct = await posts_db.count_distinct_users_after(
            chat_id, last_time, exclude_user_id=user_id,
        )
        queue_size = int(cfg["queue_size"])
        if n_distinct < queue_size:
            missing = queue_size - n_distinct
            await apply_punishment(
                bot, chat_id, user_id, username,
                message_ids=message_ids, rule="queue",
                extra_info=f"Faltan {missing} chicas por publicar antes de tu turno.",
            )
            return

    # Todas las reglas pasaron: registrar
    await posts_db.insert_post(
        chat_id=chat_id, user_id=user_id, username=username,
        message_id=first.message_id, media_group_id=media_group_id,
        phash=phash_hex, video_size=vid_size, video_duration=vid_dur,
    )
    await log_action(chat_id, "post", user_id=user_id, username=username,
                     rule=None, details=f"items={len(messages)}")


async def _hash_first_media(
    bot: Bot, message: Message,
) -> tuple[Optional[str], Optional[int], Optional[int]]:
    """Devuelve (phash_hex, video_size, video_duration). None si no hasheable."""
    try:
        if message.photo:
            photo = message.photo[-1]
            file = await bot.get_file(photo.file_id)
            buf = BytesIO()
            await bot.download_file(file.file_path, destination=buf)
            phash = await phash_image(buf.getvalue())
            return phash, None, None
        if message.video:
            video = message.video
            file = await bot.get_file(video.file_id)
            buf = BytesIO()
            await bot.download_file(file.file_path, destination=buf)
            phash = await phash_video_first_frame(buf.getvalue())
            return phash, video.file_size, video.duration
        if message.animation:  # GIF
            anim = message.animation
            try:
                file = await bot.get_file(anim.file_id)
                buf = BytesIO()
                await bot.download_file(file.file_path, destination=buf)
                phash = await phash_video_first_frame(buf.getvalue())
                return phash, anim.file_size, anim.duration
            except Exception:
                return None, anim.file_size, anim.duration
        if message.video_note:  # vídeo redondo
            vn = message.video_note
            try:
                file = await bot.get_file(vn.file_id)
                buf = BytesIO()
                await bot.download_file(file.file_path, destination=buf)
                phash = await phash_video_first_frame(buf.getvalue())
                return phash, vn.file_size, vn.duration
            except Exception:
                return None, vn.file_size, vn.duration
    except TelegramBadRequest as e:
        logger.warning("No se pudo descargar media: %s", e)
        if message.video:
            return None, message.video.file_size, message.video.duration
    except Exception as e:
        logger.exception("Error hasheando media: %s", e)
    return None, None, None


async def _post_still_exists(bot: Bot, chat_id: int, message_id: int) -> bool:
    """
    Verifica si un mensaje SIGUE existiendo en Telegram (sin modificarlo).
    Usa bot.edit_message_reply_markup con markup vacío: si el mensaje existe
    es un no-op silencioso; si fue borrado, Telegram devuelve error.
    """
    try:
        await bot.edit_message_reply_markup(
            chat_id=chat_id, message_id=message_id, reply_markup=None,
        )
        return True
    except TelegramBadRequest as e:
        s = str(e).lower()
        # Mensaje borrado / no existe
        if any(k in s for k in (
            "message to edit not found",
            "message_id_invalid",
            "message not found",
            "message can't be edited",  # demasiado antiguo: asumimos que existe
        )):
            # "can't be edited" suele ser por antigüedad, NO porque esté borrado
            if "can't be edited" in s or "too old" in s:
                return True
            return False
        return True  # cualquier otro error: ser conservadores
    except Exception:
        return True


async def _sweep_deleted_posts(bot: Bot, chat_id: int, user_id: int) -> int:
    """
    Verifica las últimas publicaciones del usuario y anula las que ya no
    existan en Telegram. Devuelve cuántas se anularon.

    Estrategia: comprobamos las 3 más recientes (suficiente: si la chica
    publicó 5 veces y borró las 3 últimas, queremos detectarlo). No
    barremos más de 3 para no saturar la API.
    """
    recent = await posts_db.get_recent_posts(chat_id, user_id, limit=3)
    if not recent:
        return 0
    anuladas = 0
    seen_albums: set[str] = set()
    for post in recent:
        # Saltar si ya tratamos este álbum
        mg = post.get("media_group_id")
        if mg and mg in seen_albums:
            continue
        if mg:
            seen_albums.add(mg)
        message_id = post.get("message_id")
        if not message_id:
            continue
        exists = await _post_still_exists(bot, chat_id, message_id)
        if not exists:
            await posts_db.mark_deleted_by_message_id(chat_id, message_id)
            anuladas += 1
            logger.info(
                "🗑️ Post auto-anulado (borrado manual detectado): "
                "chat=%s user=%s message_id=%s",
                chat_id, user_id, message_id,
            )
    return anuladas


async def _check_duplicate(
    cfg: dict, chat_id: int,
    phash_hex: Optional[str], vid_size: Optional[int], vid_dur: Optional[int],
) -> Optional[dict]:
    threshold = int(cfg["phash_threshold"])
    hours = int(cfg["antidup_hours"])
    if vid_size and vid_dur:
        return await posts_db.find_duplicate_video(
            chat_id, phash_hex, vid_size, vid_dur, threshold, hours,
        )
    if phash_hex:
        return await posts_db.find_duplicate_photo(chat_id, phash_hex, threshold, hours)
    return None


# === Evento my_chat_member: bot añadido/quitado de un chat ===
@router.my_chat_member()
async def on_bot_chat_member(event: ChatMemberUpdated, bot: Bot) -> None:
    """
    Cuando el bot entra o sale de un chat:
    - Si entra a un grupo nuevo, crea licencia 'pending' (o 'owner' si es nuestro chat)
      y manda mensaje al grupo + DM al owner.
    - Si sale, borra la licencia.
    """
    chat = event.chat
    new_status = event.new_chat_member.status

    if new_status in ("left", "kicked"):
        await remove_bot_chat(chat.id)
        await licenses_db.delete_license(chat.id)
        logger.info("👋 Bot expulsado/salido de %s (%s)", chat.id, chat.title)
        return

    if chat.type not in ("group", "supergroup"):
        return

    await upsert_bot_chat(chat.id, chat.title, chat.type)

    # Si ya existe licencia, solo upgrade (admin etc.), no hacer más
    existing = await licenses_db.get_license(chat.id)
    if existing is not None:
        return

    # Detectar quién lo añadió
    actor = event.from_user
    actor_id = actor.id if actor else None
    actor_username = actor.username if actor else None
    actor_name = actor.full_name if actor else "alguien"

    # ¿Lo añadió el owner?
    if is_owner(actor_id):
        await licenses_db.create_license(
            chat_id=chat.id, status="owner",
            added_by_user_id=actor_id, added_by_username=actor_username,
            activated_by=actor_id,
        )
        try:
            await bot.send_message(
                chat.id,
                "👑 <b>Bot activado en este grupo (propietario)</b>\n\n"
                "Tienes acceso completo. Usa /menu para configurarme.",
            )
        except TelegramBadRequest:
            pass
        return

    # Pending
    await licenses_db.create_license(
        chat_id=chat.id, status="pending",
        added_by_user_id=actor_id, added_by_username=actor_username,
    )

    # Mensaje en el grupo
    try:
        await bot.send_message(chat.id, subscription_pitch(chat.title))
    except TelegramBadRequest as e:
        logger.warning("No se pudo enviar pitch en %s: %s", chat.id, e)

    # Aviso al owner
    members_str = ""
    try:
        n_members = await bot.get_chat_member_count(chat.id)
        members_str = f"👥 Miembros: {n_members}\n"
    except TelegramBadRequest:
        pass

    actor_str = f'<a href="tg://user?id={actor_id}">{actor_name}</a>'
    if actor_username:
        actor_str = f"@{actor_username} (id <code>{actor_id}</code>)"

    text = (
        "🆕 <b>NUEVO GRUPO DETECTADO</b>\n\n"
        f"📍 Grupo: <b>{chat.title}</b>\n"
        f"🆔 Chat ID: <code>{chat.id}</code>\n"
        f"👤 Añadido por: {actor_str}\n"
        f"{members_str}\n"
        "Estado: ⏳ <b>Pendiente</b>\n\n"
        f"Usa /admin para activarlo cuando cobres."
    )

    # Botones rápidos para el owner
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Activar 30 días", callback_data=f"licext:{chat.id}:30")],
        [InlineKeyboardButton(text="✅ Activar 90 días", callback_data=f"licext:{chat.id}:90")],
        [InlineKeyboardButton(text="♾️ Activación permanente", callback_data=f"liclife:{chat.id}")],
        [InlineKeyboardButton(text="🚫 Vetar grupo", callback_data=f"licban:{chat.id}")],
        [InlineKeyboardButton(text="📋 Ver detalles", callback_data=f"licinfo:{chat.id}")],
    ])
    await notify_owner(bot, text, reply_markup=keyboard)
