"""Conexión a SQLite y creación/migración del esquema."""
import logging
from contextlib import asynccontextmanager

import aiosqlite

from config import DB_PATH, DEFAULTS

logger = logging.getLogger(__name__)


SCHEMA = """
-- Configuración por chat
CREATE TABLE IF NOT EXISTS chat_config (
    chat_id              INTEGER PRIMARY KEY,
    chat_title           TEXT,
    queue_size           INTEGER NOT NULL DEFAULT 5,
    cooldown_minutes     INTEGER NOT NULL DEFAULT 30,
    antidup_hours        INTEGER NOT NULL DEFAULT 12,
    phash_threshold      INTEGER NOT NULL DEFAULT 5,
    queue_enabled        INTEGER NOT NULL DEFAULT 1,
    cooldown_enabled     INTEGER NOT NULL DEFAULT 1,
    antidup_enabled      INTEGER NOT NULL DEFAULT 1,
    punishment_queue     INTEGER NOT NULL DEFAULT 2,
    punishment_cooldown  INTEGER NOT NULL DEFAULT 2,
    punishment_antidup   INTEGER NOT NULL DEFAULT 2,
    notice_queue_seconds    INTEGER NOT NULL DEFAULT 15,
    notice_cooldown_seconds INTEGER NOT NULL DEFAULT 15,
    notice_antidup_seconds  INTEGER NOT NULL DEFAULT 30,
    mute_queue_seconds      INTEGER NOT NULL DEFAULT 3600,
    mute_cooldown_seconds   INTEGER NOT NULL DEFAULT 3600,
    mute_antidup_seconds    INTEGER NOT NULL DEFAULT 3600,
    warn_limit              INTEGER NOT NULL DEFAULT 3,
    warn_expiration_days    INTEGER NOT NULL DEFAULT 7,
    warn_final_action       INTEGER NOT NULL DEFAULT 4,
    warn_final_mute_seconds INTEGER NOT NULL DEFAULT 3600,
    admin_only_menu         INTEGER NOT NULL DEFAULT 1,
    autoclean_days          INTEGER NOT NULL DEFAULT 30,
    silence_mode            INTEGER NOT NULL DEFAULT 0,
    locked                  INTEGER NOT NULL DEFAULT 0,
    delete_service_messages INTEGER NOT NULL DEFAULT 0,
    delete_notice_seconds   INTEGER NOT NULL DEFAULT 60,
    -- Filtros (todos a 0 = Off por defecto)
    filter_photo            INTEGER NOT NULL DEFAULT 0,
    filter_video            INTEGER NOT NULL DEFAULT 0,
    filter_gif              INTEGER NOT NULL DEFAULT 0,
    filter_sticker          INTEGER NOT NULL DEFAULT 0,
    filter_sticker_animated INTEGER NOT NULL DEFAULT 0,
    filter_document         INTEGER NOT NULL DEFAULT 0,
    filter_voice            INTEGER NOT NULL DEFAULT 0,
    filter_audio            INTEGER NOT NULL DEFAULT 0,
    filter_video_note       INTEGER NOT NULL DEFAULT 0,
    filter_poll             INTEGER NOT NULL DEFAULT 0,
    filter_contact          INTEGER NOT NULL DEFAULT 0,
    filter_location         INTEGER NOT NULL DEFAULT 0,
    filter_giveaway         INTEGER NOT NULL DEFAULT 0,
    filter_via_bot          INTEGER NOT NULL DEFAULT 0,
    filter_forwarded        INTEGER NOT NULL DEFAULT 0,
    filter_caps             INTEGER NOT NULL DEFAULT 0,
    filter_links            INTEGER NOT NULL DEFAULT 0,
    -- Tipos sujetos a las 3 reglas (1 = sí, 0 = no)
    count_photo             INTEGER NOT NULL DEFAULT 1,
    count_video             INTEGER NOT NULL DEFAULT 1,
    count_gif               INTEGER NOT NULL DEFAULT 0,
    count_sticker           INTEGER NOT NULL DEFAULT 0,
    count_sticker_animated  INTEGER NOT NULL DEFAULT 0,
    count_voice             INTEGER NOT NULL DEFAULT 0,
    count_audio             INTEGER NOT NULL DEFAULT 0,
    count_video_note        INTEGER NOT NULL DEFAULT 0,
    count_document          INTEGER NOT NULL DEFAULT 0,
    created_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

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
    posted_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    deleted_at      TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_posts_chat_user    ON posts(chat_id, user_id);
CREATE INDEX IF NOT EXISTS idx_posts_chat_posted  ON posts(chat_id, posted_at);
CREATE INDEX IF NOT EXISTS idx_posts_chat_phash   ON posts(chat_id, phash);
CREATE INDEX IF NOT EXISTS idx_posts_chat_msg     ON posts(chat_id, message_id);
-- Nota: idx_posts_deleted se crea en _migrate_posts (después de garantizar la columna)

CREATE TABLE IF NOT EXISTS alianzas (
    chat_id    INTEGER NOT NULL,
    user_id    INTEGER NOT NULL,
    username   TEXT,
    added_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (chat_id, user_id)
);

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

CREATE TABLE IF NOT EXISTS bot_chats (
    chat_id    INTEGER PRIMARY KEY,
    chat_title TEXT,
    chat_type  TEXT,
    last_seen  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS users_cache (
    chat_id    INTEGER NOT NULL,
    user_id    INTEGER NOT NULL,
    username   TEXT,
    full_name  TEXT,
    last_seen  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (chat_id, user_id)
);
CREATE INDEX IF NOT EXISTS idx_users_username ON users_cache(chat_id, username);

-- Sistema de licencias por chat
CREATE TABLE IF NOT EXISTS licenses (
    chat_id              INTEGER PRIMARY KEY,
    status               TEXT NOT NULL DEFAULT 'pending',
    expires_at           TIMESTAMP,
    activated_at         TIMESTAMP,
    activated_by         INTEGER,
    added_by_user_id     INTEGER,
    added_by_username    TEXT,
    notes                TEXT,
    notified_expiry_warn INTEGER NOT NULL DEFAULT 0,
    created_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_licenses_status ON licenses(status);
CREATE INDEX IF NOT EXISTS idx_licenses_expires ON licenses(expires_at);
"""


async def _migrate_chat_config(db) -> None:
    """Añade columnas nuevas a chat_config si no existen."""
    cur = await db.execute("PRAGMA table_info(chat_config)")
    cols = {row[1] for row in await cur.fetchall()}
    missing = [k for k in DEFAULTS if k not in cols]
    for field in missing:
        default = DEFAULTS[field]
        try:
            await db.execute(
                f"ALTER TABLE chat_config ADD COLUMN {field} INTEGER NOT NULL DEFAULT {default}"
            )
            logger.info("Migración: añadida columna chat_config.%s", field)
        except aiosqlite.Error as e:
            logger.warning("No se pudo migrar columna %s: %s", field, e)
    if missing:
        await db.commit()


async def _migrate_posts(db) -> None:
    """
    Añade la columna deleted_at a posts si no existe y crea su índice.

    IMPORTANTE: esto se ejecuta DESPUÉS del executescript del SCHEMA, para
    poder crear el índice idx_posts_deleted con seguridad incluso cuando
    la tabla ya existía (de versiones anteriores) sin la columna.
    """
    cur = await db.execute("PRAGMA table_info(posts)")
    cols = {row[1] for row in await cur.fetchall()}
    if "deleted_at" not in cols:
        try:
            await db.execute("ALTER TABLE posts ADD COLUMN deleted_at TIMESTAMP")
            await db.commit()
            logger.info("Migración: añadida columna posts.deleted_at")
        except aiosqlite.Error as e:
            logger.warning("No se pudo migrar posts.deleted_at: %s", e)
            return
    # Crear el índice (idempotente)
    try:
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_posts_deleted ON posts(deleted_at)"
        )
        await db.commit()
    except aiosqlite.Error as e:
        logger.warning("No se pudo crear idx_posts_deleted: %s", e)


async def init_db() -> None:
    """Inicializa la BD y aplica migraciones automáticas.

    Si el SCHEMA falla (por ej. al pasar de una versión vieja), intentamos
    igualmente las migraciones para reparar la BD.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.executescript(SCHEMA)
            await db.commit()
        except aiosqlite.Error as e:
            logger.warning(
                "SCHEMA falló (probablemente migración necesaria): %s. "
                "Intento migrar igualmente.", e,
            )
        # Migraciones (idempotentes y defensivas)
        try:
            await _migrate_chat_config(db)
        except Exception as e:
            logger.warning("Fallo migrando chat_config: %s", e)
        try:
            await _migrate_posts(db)
        except Exception as e:
            logger.warning("Fallo migrando posts: %s", e)
        # Tras migración, re-ejecutar SCHEMA por si quedó algún CREATE pendiente
        try:
            await db.executescript(SCHEMA)
            await db.commit()
        except aiosqlite.Error as e:
            logger.warning("Re-aplicación de SCHEMA falló: %s", e)
    logger.info("✅ Base de datos inicializada en %s", DB_PATH)


@asynccontextmanager
async def get_db():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        yield db
