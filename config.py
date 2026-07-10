"""Constantes y carga de variables de entorno."""
import logging
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# === TOKEN ===
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
if not BOT_TOKEN:
    raise RuntimeError(
        "❌ BOT_TOKEN no está definido. En Railway añade una variable "
        "BOT_TOKEN con el token de @BotFather."
    )

# === OWNER ===
_owner_raw = os.getenv("OWNER_USER_ID", "").strip()
try:
    OWNER_USER_ID: int | None = int(_owner_raw) if _owner_raw else None
except ValueError:
    OWNER_USER_ID = None

OWNER_USERNAME = os.getenv("OWNER_USERNAME", "lapanteraoficial").strip().lstrip("@")
SUBSCRIPTION_PRICE_EUR = float(os.getenv("SUBSCRIPTION_PRICE_EUR", "5"))
LICENSING_ENABLED = os.getenv("LICENSING_ENABLED", "true").lower() not in ("false", "0", "no")

# === LOGGING ===
LOG_LEVEL_STR = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_LEVEL = getattr(logging, LOG_LEVEL_STR, logging.INFO)

# === RUTAS ===
BASE_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.getenv("DB_PATH", BASE_DIR / "bot.db"))
BACKUPS_DIR = BASE_DIR / "backups"
BACKUPS_DIR.mkdir(exist_ok=True)

# === ÁLBUM ===
ALBUM_COLLECT_SECONDS = 2.0

# === DEFAULTS ===
DEFAULTS: dict[str, int] = {
    "queue_size": 5,
    "cooldown_minutes": 30,
    "antidup_hours": 12,
    "phash_threshold": 5,
    "queue_enabled": 1,
    "cooldown_enabled": 1,
    "antidup_enabled": 1,
    "punishment_queue": 2,
    "punishment_cooldown": 2,
    "punishment_antidup": 2,
    "notice_queue_seconds": 15,
    "notice_cooldown_seconds": 15,
    "notice_antidup_seconds": 30,
    "mute_queue_seconds": 3600,
    "mute_cooldown_seconds": 3600,
    "mute_antidup_seconds": 3600,
    "warn_limit": 3,
    "warn_expiration_days": 7,
    "warn_final_action": 4,
    "warn_final_mute_seconds": 3600,
    "admin_only_menu": 1,
    "autoclean_days": 30,
    "silence_mode": 0,
    "locked": 0,
    "delete_service_messages": 0,
    # Duración (segundos) del aviso del comando /delete. 0 = permanente.
    "delete_notice_seconds": 60,
    # Filtros: 0=Off, 1=Borrar, 2=Warn, 3=Mute, 4=Kick, 5=Ban
    "filter_photo": 0,
    "filter_video": 0,
    "filter_gif": 0,
    "filter_sticker": 0,
    "filter_sticker_animated": 0,
    "filter_document": 0,
    "filter_voice": 0,
    "filter_audio": 0,
    "filter_video_note": 0,
    "filter_poll": 0,
    "filter_contact": 0,
    "filter_location": 0,
    "filter_giveaway": 0,
    "filter_via_bot": 0,
    "filter_forwarded": 0,
    "filter_caps": 0,
    "filter_links": 0,
    # === TIPOS SUJETOS A LAS 3 REGLAS (cola/cooldown/antidup) ===
    # 1 = el bot vigila este tipo bajo las reglas. 0 = lo ignora.
    # Foto y vídeo van ON por defecto (caso principal del bot).
    # Los demás van OFF: actívalos si en tu grupo cuentan como publicación.
    "count_photo": 1,
    "count_video": 1,
    "count_gif": 0,
    "count_sticker": 0,
    "count_sticker_animated": 0,
    "count_voice": 0,
    "count_audio": 0,
    "count_video_note": 0,
    "count_document": 0,
}

PUNISHMENT_TYPES: dict[int, tuple[str, str]] = {
    1: ("🟢", "Solo borrar"),
    2: ("🟢", "Borrar + aviso"),
    3: ("🟡", "Borrar + warn"),
    4: ("🟠", "Borrar + mute"),
    5: ("🔴", "Borrar + kick"),
    6: ("⚫", "Borrar + ban"),
}

FILTER_ACTIONS: dict[int, tuple[str, str]] = {
    0: ("✅", "Off"),
    1: ("🗑️", "Borrar"),
    2: ("⚠️", "Warn"),
    3: ("🔇", "Mute"),
    4: ("👢", "Kick"),
    5: ("⛔", "Ban"),
}

FILTER_TYPES: list[tuple[str, str, str]] = [
    ("📸", "Foto", "filter_photo"),
    ("🎬", "Vídeo", "filter_video"),
    ("🎞️", "GIF", "filter_gif"),
    ("🎨", "Sticker", "filter_sticker"),
    ("✨", "Sticker animado", "filter_sticker_animated"),
    ("📎", "Archivo", "filter_document"),
    ("🎤", "Mensaje de voz", "filter_voice"),
    ("🎵", "Audio", "filter_audio"),
    ("📹", "Video redondo", "filter_video_note"),
    ("📊", "Encuesta", "filter_poll"),
    ("☎️", "Contacto", "filter_contact"),
    ("📍", "Ubicación", "filter_location"),
    ("🎁", "Sorteo", "filter_giveaway"),
    ("🤖", "Vía bot", "filter_via_bot"),
    ("↪️", "Reenviado", "filter_forwarded"),
    ("🔠", "MAYÚSCULAS", "filter_caps"),
    ("🔗", "Enlaces", "filter_links"),
]

# Tipos que pueden estar sujetos a las 3 reglas (cola, cooldown, anti-dup).
# Si count_X = 1, ese tipo cuenta como publicación. Si count_X = 0, el bot lo ignora.
# (emoji, etiqueta, campo, soporta_antidup)
# `soporta_antidup` = True si tiene contenido hasheable (foto/video/gif).
COUNTABLE_TYPES: list[tuple[str, str, str, bool]] = [
    ("📸", "Foto",            "count_photo",            True),
    ("🎬", "Vídeo",           "count_video",            True),
    ("🎞️", "GIF",             "count_gif",              True),
    ("🎨", "Sticker",         "count_sticker",          False),
    ("✨", "Sticker animado", "count_sticker_animated", False),
    ("🎤", "Mensaje de voz",  "count_voice",            False),
    ("🎵", "Audio",           "count_audio",            False),
    ("📹", "Video redondo",   "count_video_note",       True),
    ("📎", "Archivo",         "count_document",         False),
]

QUEUE_OPTIONS: list[int] = [1, 3, 5, 7, 10, 15, 20, 25]
COOLDOWN_OPTIONS: list[int] = [5, 10, 15, 30, 45, 60, 120, 180, 360, 720, 1440]
ANTIDUP_OPTIONS: list[int] = [1, 3, 6, 12, 24, 36, 48, 72, 96, 120, 168]
PHASH_OPTIONS: list[tuple[int, str]] = [
    (3, "🔴 Estricta"),
    (5, "🟢 Normal"),
    (8, "🟡 Tolerante"),
    (12, "🔵 Agresiva"),
]
NOTICE_DURATION_OPTIONS: list[int] = [0, 5, 10, 15, 20, 30, 45, 60]  # 0 = permanente
# Opciones para el aviso del comando /delete (en segundos, 0 = permanente)
DELETE_NOTICE_OPTIONS: list[int] = [0, 15, 30, 60, 120, 300, 600]
MUTE_DURATION_OPTIONS: list[tuple[int, str]] = [
    (300, "5 min"),
    (900, "15 min"),
    (1800, "30 min"),
    (3600, "1 h"),
    (10800, "3 h"),
    (21600, "6 h"),
    (43200, "12 h"),
    (86400, "24 h"),
]
WARN_LIMIT_OPTIONS: list[int] = [2, 3, 4, 5, 7, 10]
WARN_EXPIRATION_OPTIONS: list[int] = [1, 3, 7, 14, 30, 90]
AUTOCLEAN_OPTIONS: list[int] = [0, 7, 14, 30, 60, 90, 180]
LICENSE_EXTEND_OPTIONS: list[int] = [7, 15, 30, 60, 90, 180, 365]

RULE_LABELS = {
    "queue": "cola rotatoria",
    "cooldown": "cooldown",
    "antidup": "anti-duplicado",
}
