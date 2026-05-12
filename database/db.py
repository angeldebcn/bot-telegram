"""Conexión a SQLite y creación del esquema."""
import logging
from contextlib import asynccontextmanager

import aiosqlite

from config import DB_PATH

logger = logging.getLogger(__name__)


SCHEMA = """
-- Configuración por chat. Una fila por grupo.
CREATE TABLE IF NOT EXISTS chat_config (
    chat_id              INTEGER PRIMARY KEY,
    chat_title           TEXT,
    queue_size           INTEGER NOT NULL DEFAULT 5,
    cooldown_minutes     INTEGER NOT NULL DEFAULT 30,
    antidup_hours        INTEGER NOT NULL DEFAULT 12,
    phash_threshold      INTEGER NOT NULL DEFAULT 5,
    -- Castigos por regla (1..6)
    punishment_queue     INTEGER NOT NULL DEFAULT 2,
    punishment_cooldown  INTEGER NOT NULL DEFAULT 2,
    punishment_antidup   INTEGER NOT NULL DEFAULT 2,
    -- Duración aviso autodestructivo en segundos
    notice_queue_seconds    INTEGER NOT NULL DEFAULT 15,
    notice_cooldown_seconds INTEGER NOT NULL DEFAULT 15,
    notice_antidup_seconds  INTEGER NOT NULL DEFAULT 30,
    -- Duración mute en segundos
    mute_queue_seconds      INTEGER NOT NULL DEFAULT 3600,
    mute_cooldown_seconds   INTEGER NOT NULL DEFAULT 3600,
    mute_antidup_seconds    INTEGER NOT NULL DEFAULT 3600,
    -- Sistema de warns
    warn_limit              INTEGER NOT NULL DEFAULT 3,
    warn_expiration_days    INTEGER NOT NULL DEFAULT 7,
    warn_final_action       INTEGER NOT NULL DEFAULT 4,
    warn_final_mute_seconds INTEGER NOT NULL DEFAULT 3600,
    -- Avanzadas
    admin_only_menu      INTEGER NOT NULL DEFAULT 1,
    autoclean_days       INTEGER NOT NULL DEFAULT 30,
    silence_mode         INTEGER NOT NULL DEFAULT 0,
    created_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Publicaciones permitidas (las que pasaron las 3 reglas).
-- Si una se borra, NO se inserta aquí (no cuenta para nada).
CREATE TABLE IF NOT EXISTS posts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id         INTEGER NOT NULL,
    user_id         INTEGER NOT NULL,
    username        TEXT,
    message_id      INTEGER,
    media_group_id  TEXT,
    phash           TEXT,
    video_size      INTEGER,
    video_duration  INTEGER,
    posted_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_posts_chat_user    ON posts(chat_id, user_id);
CREATE INDEX IF NOT EXISTS idx_posts_chat_posted  ON posts(chat_id, posted_at);
CREATE INDEX IF NOT EXISTS idx_posts_chat_phash   ON posts(chat_id, phash);

-- Alianzas: usuarias exentas de las 3 reglas.
CREATE TABLE IF NOT EXISTS alianzas (
    chat_id    INTEGER NOT NULL,
    user_id    INTEGER NOT NULL,
    username   TEXT,
    added_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (chat_id, user_id)
);

-- Advertencias acumulativas (sistema warns).
CREATE TABLE IF NOT EXISTS warns (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id     INTEGER NOT NULL,
    user_id     INTEGER NOT NULL,
    username    TEXT,
    reason      TEXT,
    warned_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at  TIMESTAMP NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_warns_chat_user ON warns(chat_id, user_id);
CREATE INDEX IF NOT EXISTS idx_warns_expires   ON warns(expires_at);

-- Log de acciones del bot (para /logs y estadísticas).
CREATE TABLE IF NOT EXISTS actions_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id     INTEGER NOT NULL,
    user_id     INTEGER,
    username    TEXT,
    action      TEXT NOT NULL,
    rule        TEXT,
    details     TEXT,
    timestamp   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_log_chat_ts ON actions_log(chat_id, timestamp);

-- Chats donde está el bot (para /menu en privado con selector de grupo).
CREATE TABLE IF NOT EXISTS bot_chats (
    chat_id    INTEGER PRIMARY KEY,
    chat_title TEXT,
    chat_type  TEXT,
    last_seen  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Usuarias vistas (cache de username -> user_id para resolución).
CREATE TABLE IF NOT EXISTS users_cache (
    chat_id    INTEGER NOT NULL,
    user_id    INTEGER NOT NULL,
    username   TEXT,
    full_name  TEXT,
    last_seen  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (chat_id, user_id)
);
CREATE INDEX IF NOT EXISTS idx_users_username ON users_cache(chat_id, username);
"""


_db_initialized = False


async def init_db() -> None:
    """Inicializa la BD creando el esquema si no existe."""
    global _db_initialized
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(SCHEMA)
        await db.commit()
    _db_initialized = True
    logger.info("✅ Base de datos inicializada en %s", DB_PATH)


@asynccontextmanager
async def get_db():
    """Context manager para una conexión a la BD."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        yield db
