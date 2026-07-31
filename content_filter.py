"""
=====================================================================
FILTRO DE CONTENIDO — Palabras prohibidas y reenviados
=====================================================================

Dos protecciones para reducir la "reportabilidad" de los grupos:

1. FILTRO DE PALABRAS PROHIBIDAS
   Si un mensaje (texto normal o pie de foto/vídeo) contiene una palabra
   EXACTA de la lista negra, se borra, se etiqueta a la persona y se le pide
   que use una versión censurada (con * o números). No cuenta como
   publicación en la cola.

2. BLOQUEO DE REENVIADOS
   Si alguien reenvía un mensaje mostrando el origen, se borra, se etiqueta y
   se le pide que oculte el remitente en los ajustes de reenvío. Los reenvíos
   con remitente oculto pasan (Telegram ya no los marca como reenviados).

Ambos se activan por grupo (flags filter_words / block_forwards en roles).
Ambos están DESACTIVADOS por defecto.

DETECCIÓN DE PALABRAS: por palabra COMPLETA exacta. "polla" salta, pero
"pollastre" no. Las versiones censuradas (p0lla, p*lla) pasan, que es
justo lo que queremos que use la gente.
"""
import logging
import re
import unicodedata
from typing import Optional

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import Message

import sanctions_db
import roles_db

logger = logging.getLogger(__name__)

# Cache de palabras prohibidas (se refresca cada X segundos para no consultar
# la BD en cada mensaje). Estructura: {"words": set, "ts": float}
_words_cache: dict = {"words": set(), "ts": 0.0}
_CACHE_TTL = 30.0  # segundos


def _strip_accents(text: str) -> str:
    """Quita acentos para comparar (coño == cono, así no se escapan por tildes)."""
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _normalize(text: str) -> str:
    return _strip_accents(text.lower())


async def _get_words() -> set:
    """Devuelve el set de palabras prohibidas (normalizadas), con cache."""
    import time
    now = time.time()
    if now - _words_cache["ts"] < _CACHE_TTL and _words_cache["words"]:
        return _words_cache["words"]
    words = await sanctions_db.get_banned_words()
    normalized = {_normalize(w) for w in words}
    _words_cache["words"] = normalized
    _words_cache["ts"] = now
    return normalized


def invalidate_words_cache() -> None:
    """Fuerza recargar la lista en la próxima comprobación (tras añadir/quitar)."""
    _words_cache["ts"] = 0.0


def _find_banned_word(text: str, banned: set) -> Optional[str]:
    """
    Busca si el texto contiene alguna palabra/combinación prohibida EXACTA
    (como palabra completa). Devuelve la palabra encontrada o None.

    - Para palabras sueltas: usa límites de palabra (no salta dentro de otra).
    - Para combinaciones (varias palabras): busca la secuencia como frase.
    """
    if not text:
        return None
    norm_text = _normalize(text)

    for w in banned:
        if not w:
            continue
        if " " in w:
            # Combinación de palabras: buscar la frase con límites al inicio/fin
            pattern = r"(?<!\w)" + re.escape(w) + r"(?!\w)"
        else:
            # Palabra suelta: límites de palabra para no saltar dentro de otra
            pattern = r"(?<!\w)" + re.escape(w) + r"(?!\w)"
        if re.search(pattern, norm_text):
            return w
    return None


# ===========================================================================
# COMPROBACIÓN PRINCIPAL — llamada desde media.py por cada mensaje
# ===========================================================================
async def check_message(message: Message, bot: Bot) -> bool:
    """
    Revisa un mensaje contra los filtros activos del grupo.

    Devuelve True si el mensaje fue BORRADO por un filtro (y por tanto el
    resto de la moderación NO debe seguir procesándolo).
    Devuelve False si el mensaje está limpio (sigue el flujo normal).
    """
    chat_id = message.chat.id
    if not message.from_user:
        return False
    user = message.from_user

    # --- 1. BLOQUEO DE REENVIADOS ---
    if await roles_db.group_blocks_forwards(chat_id):
        if _is_visible_forward(message):
            await _delete_and_warn(
                message, bot,
                "🔁 {mention}, no se permiten <b>reenviados</b> que muestren de dónde vienen.\n\n"
                "Tu publicación no cuenta, puedes volver a subir. Para compartir sin que "
                "aparezca «Reenviado», tienes 3 opciones:\n\n"
                "1️⃣ <b>Mensajes guardados</b>: en la lupa 🔍 de Telegram busca "
                "«Mensajes guardados», guarda ahí tu contenido y reenvíalo desde ese "
                "chat a uno o varios grupos (no aparece el origen). Incluso puedes "
                "programarlo.\n\n"
                "2️⃣ <b>Programar mensajes</b> directamente en el chat del grupo.\n\n"
                "3️⃣ <b>Graph Messenger</b> (app asociada a Telegram): reenvía el mismo "
                "mensaje a varios grupos sin que salga «Reenviado», desactivando la "
                "opción de <b>«Citar»</b>.",
            )
            return True

    # --- 2. FILTRO DE PALABRAS ---
    # Solo se aplica a publicaciones CON foto o vídeo (el pie de foto/vídeo).
    # Las frases sueltas de solo texto NO se filtran: lo reportable de verdad
    # es una imagen/vídeo explícito con palabras fuertes, no una frase suelta.
    # Esto además deja libres a los clientes, que suelen escribir solo texto.
    if await roles_db.group_filters_words(chat_id):
        has_media = bool(message.photo or message.video or message.animation)
        if has_media:
            text = message.caption or ""
            if text:
                banned = await _get_words()
                found = _find_banned_word(text, banned)
                if found:
                    await _delete_and_warn(
                        message, bot,
                        "🚫 {mention}, tu publicación se ha eliminado porque contiene una "
                        "palabra no permitida.\n\n"
                        "Usa una palabra parecida o censúrala con <b>*</b> o números "
                        "(por ejemplo: p*lla, c0ño). Tu publicación no cuenta, "
                        "puedes volver a subir.",
                    )
                    return True

    return False


def _is_visible_forward(message: Message) -> bool:
    """
    True si el mensaje es un reenvío que MUESTRA su origen.

    Telegram marca los reenvíos con forward_origin (aiogram 3.7+) o con los
    campos antiguos forward_from / forward_from_chat / forward_sender_name.
    Si el remitente está oculto, estos campos no vienen (o vienen sin datos
    útiles), así que ese caso NO se bloquea (que es lo que queremos).
    """
    # aiogram moderno: forward_origin
    origin = getattr(message, "forward_origin", None)
    if origin is not None:
        return True
    # Campos clásicos (por compatibilidad)
    if getattr(message, "forward_from", None) is not None:
        return True
    if getattr(message, "forward_from_chat", None) is not None:
        return True
    if getattr(message, "forward_sender_name", None):
        return True
    return False


def _mention_html(user) -> str:
    """Mención clicable de un usuario."""
    name = user.full_name or (f"@{user.username}" if user.username else "usuario")
    name = name.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return f'<a href="tg://user?id={user.id}">{name}</a>'


async def _delete_and_warn(message: Message, bot: Bot, template: str) -> None:
    """
    Borra el mensaje infractor y publica un aviso etiquetando a la persona.

    En foros (grupos con temas/hilos), el aviso se publica EN EL MISMO HILO
    donde se borró el mensaje, no en #General. Así la persona lo ve donde
    estaba publicando, aunque tenga #General oculto.
    """
    # Borrar el mensaje (o todos los del álbum si es media group)
    try:
        await bot.delete_message(message.chat.id, message.message_id)
    except (TelegramBadRequest, TelegramForbiddenError):
        pass

    mention = _mention_html(message.from_user)
    text = template.format(mention=mention)

    # Detectar el hilo del foro donde estaba el mensaje (si es un foro)
    thread_id = getattr(message, "message_thread_id", None)
    # Solo pasar thread_id si el mensaje realmente venía de un tema del foro.
    # (is_topic_message evita mandar a #General por error en grupos normales)
    is_topic = getattr(message, "is_topic_message", False)

    kwargs = {"disable_web_page_preview": True}
    if thread_id is not None and is_topic:
        kwargs["message_thread_id"] = thread_id

    try:
        await bot.send_message(message.chat.id, text, **kwargs)
    except (TelegramBadRequest, TelegramForbiddenError) as e:
        # Si falla por el hilo (ej. tema cerrado), reintentar sin hilo
        if "message_thread_id" in kwargs:
            try:
                await bot.send_message(
                    message.chat.id, text, disable_web_page_preview=True,
                )
            except (TelegramBadRequest, TelegramForbiddenError):
                pass
        else:
            logger.debug("No se pudo avisar del filtro en %s: %s", message.chat.id, e)
