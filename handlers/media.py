"""
Handler de fotos, vídeos y álbumes. Aplica las 3 reglas.

Flujo por publicación:
1. Si la usuaria es admin o alianza → permitir, registrar post, fin.
2. Calcular hash perceptual (y meta para vídeos).
3. Comprobar regla 3: anti-duplicado → si infringe, castigo y NO se registra.
4. Comprobar regla 2: cooldown → idem.
5. Comprobar regla 1: cola → idem.
6. Todas pasadas → registrar post.

Álbumes: se buffer-ean ~2s con media_group_id y se tratan como UNA publicación.
"""
import logging
from datetime import datetime, timedelta
from io import BytesIO
from typing import Optional

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import Message

from database import posts as posts_db
from database.config_db import get_config, update_chat_title
from database.stats import cache_user, log_action, upsert_bot_chat
from utils.album_collector import album_collector
from utils.helpers import time_until
from utils.media_hash import phash_image, phash_video_first_frame
from utils.permissions import is_exempt
from utils.punishment import apply_punishment

logger = logging.getLogger(__name__)
router = Router(name="media")


# Filtro: foto o vídeo (no GIFs, no stickers, no video notes, no documentos)
@router.message(F.photo | F.video, F.chat.type.in_({"group", "supergroup"}))
async def handle_media(message: Message, bot: Bot) -> None:
    """Recibe foto/vídeo y delega al colector de álbumes."""
    # Ignorar mensajes de bots
    if message.from_user and message.from_user.is_bot:
        return
    await _refresh_chat_meta(message)
    await album_collector.add(
        message,
        on_complete=lambda msgs: _process_publication(bot, msgs),
    )


async def _refresh_chat_meta(message: Message) -> None:
    """Actualiza metadatos de chat y usuaria en BD."""
    try:
        await upsert_bot_chat(
            message.chat.id, message.chat.title, message.chat.type
        )
        await update_chat_title(message.chat.id, message.chat.title or "")
        if message.from_user and not message.from_user.is_bot:
            await cache_user(
                message.chat.id,
                message.from_user.id,
                message.from_user.username,
                message.from_user.full_name,
            )
    except Exception as e:
        logger.debug("refresh meta error: %s", e)


async def _process_publication(bot: Bot, messages: list[Message]) -> None:
    """
    Procesa una publicación completa (1 mensaje o álbum N mensajes).
    Aplica las 3 reglas y, si fallan, castiga.
    """
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

    # 0. Exenta? (admin o alianza) → publicar y registrar
    if await is_exempt(bot, chat_id, user_id):
        # Registramos con hash básico (foto solo del primer item para no inflar)
        await _register_post(bot, first, user_id, username, media_group_id)
        await log_action(chat_id, "post", user_id=user_id, username=username,
                         rule=None, details="exempt")
        return

    cfg = await get_config(chat_id)

    # === 1. Calcular hash del primer ítem del mensaje/álbum ===
    phash_hex, vid_size, vid_dur = await _hash_first_media(bot, first)

    # === 2. Regla 3: ANTI-DUPLICADO ===
    if phash_hex or vid_size:
        dup = await _check_duplicate(
            cfg, chat_id, phash_hex, vid_size, vid_dur
        )
        if dup:
            await apply_punishment(
                bot, chat_id, user_id, username,
                message_ids=message_ids,
                rule="antidup",
                extra_info=f"Ya se publicó hace menos de {cfg['antidup_hours']}h.",
            )
            return

    # === 3. Regla 2: COOLDOWN ===
    last_time = await posts_db.get_last_post_time(chat_id, user_id)
    if last_time is not None:
        cooldown_until = last_time + timedelta(minutes=int(cfg["cooldown_minutes"]))
        if datetime.utcnow() < cooldown_until:
            remaining = time_until(cooldown_until)
            await apply_punishment(
                bot, chat_id, user_id, username,
                message_ids=message_ids,
                rule="cooldown",
                extra_info=f"Espera {remaining}.",
            )
            return

    # === 4. Regla 1: COLA ROTATORIA ===
    if last_time is not None:
        n_distinct = await posts_db.count_distinct_users_after(
            chat_id, last_time, exclude_user_id=user_id,
        )
        queue_size = int(cfg["queue_size"])
        if n_distinct < queue_size:
            missing = queue_size - n_distinct
            await apply_punishment(
                bot, chat_id, user_id, username,
                message_ids=message_ids,
                rule="queue",
                extra_info=f"Faltan {missing} chicas por publicar antes de tu turno.",
            )
            return

    # === 5. Todas las reglas pasaron → registrar ===
    await _register_post_full(
        chat_id, user_id, username,
        message_id=first.message_id,
        media_group_id=media_group_id,
        phash=phash_hex,
        video_size=vid_size,
        video_duration=vid_dur,
    )
    await log_action(chat_id, "post", user_id=user_id, username=username,
                     rule=None, details=f"items={len(messages)}")


async def _hash_first_media(
    bot: Bot, message: Message
) -> tuple[Optional[str], Optional[int], Optional[int]]:
    """
    Descarga el primer media y calcula hash.
    Devuelve (phash_hex, video_size_bytes, video_duration_seconds).
    Para fotos: phash, None, None.
    Para vídeos: phash_del_primer_frame, file_size, duration.
    """
    try:
        if message.photo:
            # Tomamos la versión de mayor resolución
            photo = message.photo[-1]
            file = await bot.get_file(photo.file_id)
            buf = BytesIO()
            await bot.download_file(file.file_path, destination=buf)
            data = buf.getvalue()
            phash = await phash_image(data)
            return phash, None, None
        if message.video:
            video = message.video
            file = await bot.get_file(video.file_id)
            buf = BytesIO()
            await bot.download_file(file.file_path, destination=buf)
            data = buf.getvalue()
            phash = await phash_video_first_frame(data)
            return phash, video.file_size, video.duration
    except TelegramBadRequest as e:
        # Archivo demasiado grande para descargar via Bot API (>20MB)
        logger.warning("No se pudo descargar media: %s", e)
        if message.video:
            return None, message.video.file_size, message.video.duration
    except Exception as e:
        logger.exception("Error hasheando media: %s", e)
    return None, None, None


async def _check_duplicate(
    cfg: dict,
    chat_id: int,
    phash_hex: Optional[str],
    vid_size: Optional[int],
    vid_dur: Optional[int],
) -> Optional[dict]:
    """Devuelve el post duplicado encontrado, o None."""
    threshold = int(cfg["phash_threshold"])
    hours = int(cfg["antidup_hours"])
    if vid_size and vid_dur:
        return await posts_db.find_duplicate_video(
            chat_id, phash_hex, vid_size, vid_dur, threshold, hours
        )
    if phash_hex:
        return await posts_db.find_duplicate_photo(
            chat_id, phash_hex, threshold, hours
        )
    return None


async def _register_post(
    bot: Bot, message: Message, user_id: int, username: Optional[str],
    media_group_id: Optional[str],
) -> None:
    """Registra un post mínimo (admin/alianza) calculando hash para detección futura."""
    phash, vid_size, vid_dur = await _hash_first_media(bot, message)
    await posts_db.insert_post(
        chat_id=message.chat.id,
        user_id=user_id,
        username=username,
        message_id=message.message_id,
        media_group_id=media_group_id,
        phash=phash,
        video_size=vid_size,
        video_duration=vid_dur,
    )


async def _register_post_full(
    chat_id: int, user_id: int, username: Optional[str],
    message_id: int, media_group_id: Optional[str],
    phash: Optional[str], video_size: Optional[int], video_duration: Optional[int],
) -> None:
    await posts_db.insert_post(
        chat_id=chat_id, user_id=user_id, username=username,
        message_id=message_id, media_group_id=media_group_id,
        phash=phash, video_size=video_size, video_duration=video_duration,
    )


# === EVENTO: bot añadido/quitado de un chat ===
@router.my_chat_member()
async def on_bot_chat_member(event, bot: Bot) -> None:
    """Actualiza bot_chats cuando el bot entra o sale de un chat."""
    chat = event.chat
    try:
        new_status = event.new_chat_member.status
        if new_status in ("left", "kicked"):
            from database.stats import remove_bot_chat
            await remove_bot_chat(chat.id)
            logger.info("👋 Bot expulsado/salido de %s", chat.id)
        else:
            await upsert_bot_chat(chat.id, chat.title, chat.type)
            logger.info("✅ Bot añadido/actualizado en %s (%s)", chat.id, chat.title)
    except Exception as e:
        logger.exception("Error procesando my_chat_member: %s", e)
