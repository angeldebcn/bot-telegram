"""Constantes y carga de variables de entorno."""
import logging
import os
from pathlib import Path

from dotenv import load_dotenv

# Cargar .env si existe (modo local)
load_dotenv()

# === TOKEN ===
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
if not BOT_TOKEN:
    raise RuntimeError(
        "❌ BOT_TOKEN no está definido. En Railway añade una variable "
        "BOT_TOKEN con el token de @BotFather. En local crea un .env "
        "con BOT_TOKEN=tu_token_aqui."
    )

# === LOGGING ===
LOG_LEVEL_STR = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_LEVEL = getattr(logging, LOG_LEVEL_STR, logging.INFO)

# === RUTAS ===
BASE_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.getenv("DB_PATH", BASE_DIR / "bot.db"))
BACKUPS_DIR = BASE_DIR / "backups"
BACKUPS_DIR.mkdir(exist_ok=True)

# === ÁLBUM ===
# Tiempo (segundos) que esperamos a que lleguen todas las medias
# de un álbum antes de procesarlo como una sola publicación.
ALBUM_COLLECT_SECONDS = 2.0

# === DEFAULTS DE NUEVO CHAT ===
# Estos valores se aplican LA PRIMERA VEZ que el bot ve un grupo nuevo.
# Después se cambian todos desde el menú en Telegram, sin tocar código.
DEFAULTS: dict[str, int] = {
    "queue_size": 5,
    "cooldown_minutes": 30,
    "antidup_hours": 12,
    "phash_threshold": 5,
    # Castigos por defecto: borrar + aviso autodestructivo
    "punishment_queue": 2,
    "punishment_cooldown": 2,
    "punishment_antidup": 2,
    # Duración del aviso autodestructivo (segundos)
    "notice_queue_seconds": 15,
    "notice_cooldown_seconds": 15,
    "notice_antidup_seconds": 30,
    # Duración del mute (segundos)
    "mute_queue_seconds": 3600,
    "mute_cooldown_seconds": 3600,
    "mute_antidup_seconds": 3600,
    # Sistema de warns
    "warn_limit": 3,
    "warn_expiration_days": 7,
    "warn_final_action": 4,  # 4=mute, 5=kick, 6=ban
    "warn_final_mute_seconds": 3600,
    # Opciones avanzadas
    "admin_only_menu": 1,
    "autoclean_days": 30,
    "silence_mode": 0,
}

# === TIPOS DE CASTIGO ===
# id -> (emoji, etiqueta corta)
PUNISHMENT_TYPES: dict[int, tuple[str, str]] = {
    1: ("🟢", "Solo borrar"),
    2: ("🟢", "Borrar + aviso"),
    3: ("🟡", "Borrar + warn"),
    4: ("🟠", "Borrar + mute"),
    5: ("🔴", "Borrar + kick"),
    6: ("⚫", "Borrar + ban"),
}

# === OPCIONES DEL MENÚ (selectores rápidos) ===
QUEUE_OPTIONS: list[int] = [1, 3, 5, 7, 10, 15, 20, 25]
COOLDOWN_OPTIONS: list[int] = [5, 10, 15, 30, 45, 60, 120, 180, 360, 720, 1440]
ANTIDUP_OPTIONS: list[int] = [1, 3, 6, 12, 24, 36, 48, 72, 96, 120, 168]
PHASH_OPTIONS: list[tuple[int, str]] = [
    (3, "🔴 Estricta"),
    (5, "🟢 Normal"),
    (8, "🟡 Tolerante"),
    (12, "🔵 Agresiva"),
]
NOTICE_DURATION_OPTIONS: list[int] = [5, 10, 15, 20, 30, 45, 60]
# Duraciones de mute en segundos
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
AUTOCLEAN_OPTIONS: list[int] = [7, 14, 30, 60, 90, 180]

# === ETIQUETAS DE REGLAS (para mensajes) ===
RULE_LABELS = {
    "queue": "cola rotatoria",
    "cooldown": "cooldown",
    "antidup": "anti-duplicado",
}
