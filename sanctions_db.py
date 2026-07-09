"""
=====================================================================
SISTEMA DE SANCIONES DE COMUNIDAD — Base de datos y motor de puntos
=====================================================================

Este módulo es el CORAZÓN del sistema de reputación/sanciones que
funciona a nivel de TODA la comunidad (todos los grupos donde está el
bot), independientemente del sistema de las 3 reglas (cola/cooldown/
antidup) que sigue viviendo en posts.py y media.py.

--------------------------------------------------------------------
MOTOR DE PUNTOS (la lógica central)
--------------------------------------------------------------------
- Warn leve  = 1 punto, caduca a los 90 días.
- Warn grave = 2 puntos, caduca a los 6 meses (180 días).
- Al alcanzar 2 puntos ACTIVOS  -> silencio automático de 7 días.
- Al alcanzar 3 puntos ACTIVOS  -> ban automático en los grupos marcados.
- Cuando un warn caduca, sus puntos dejan de contar automáticamente
  (no se borra la fila: se marca como expirada, para tener histórico).
- El ban es permanente hasta que se use /unban.

El contador de puntos SIEMPRE refleja solo los warns activos (no
caducados y no revocados) en el momento de consultarlo.

--------------------------------------------------------------------
TABLAS
--------------------------------------------------------------------
sanctions        -> cada warn/mute/ban aplicado (el histórico completo)
reports          -> reportes creados con /reporte (pendientes/resueltos)
group_roles      -> rol de cada grupo (verificadas / staff / aplica reglas / aplica sanciones)
staff            -> lista blanca de quién puede usar los comandos de sanción
sanctioned_users -> caché del último estado conocido de cada usuario sancionado
                    (nombre, username) para poder mostrarlo en la lista aunque
                    ahora mismo no esté visible en ningún grupo

Nota: NO creamos aquí una tabla de "usuarios globales" nueva; reutilizamos
users_cache (que ya rastrea a todos los usuarios vistos en cada grupo).
"""
import logging
import time
from datetime import datetime, timedelta
from typing import Optional

import aiosqlite

from db import get_db

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# CONSTANTES DEL MOTOR
# ---------------------------------------------------------------------------
POINTS_LEVE = 1
POINTS_GRAVE = 2
POINTS_MUTE_THRESHOLD = 2      # a 2 puntos -> mute automático
POINTS_BAN_THRESHOLD = 3       # a 3 puntos -> ban automático

EXPIRY_LEVE_DAYS = 90          # warn leve caduca a 90 días
EXPIRY_GRAVE_DAYS = 180        # warn grave caduca a 6 meses
AUTO_MUTE_DAYS = 7             # mute automático al llegar al umbral

# Tipos de sanción (columna `kind` en la tabla sanctions)
KIND_LEVE = "warnleve"
KIND_GRAVE = "warngrave"
KIND_BAN = "ban"
KIND_MUTE = "mute"

# Estados de una sanción
STATUS_ACTIVE = "active"
STATUS_EXPIRED = "expired"
STATUS_REVOKED = "revoked"     # quitada manualmente (/unwarnleve, etc.)

# Estados de un reporte
REPORT_PENDING = "pending"
REPORT_RESOLVED = "resolved"

# Roles de grupo (flags en group_roles)
# is_verified_group  -> es el grupo de "solo verificadas" donde se usa /reporte
# is_staff_group     -> es el grupo de staff donde llegan los reportes + botones
# applies_rules      -> aplican las 3 reglas (cola/cooldown/antidup) aquí
# applies_sanctions  -> se ejecutan mutes/bans aquí


# ===========================================================================
# ESQUEMA — se ejecuta al iniciar (idempotente)
# ===========================================================================
SANCTIONS_SCHEMA = """
CREATE TABLE IF NOT EXISTS sanctions (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id        INTEGER NOT NULL,
    kind           TEXT NOT NULL,          -- warnleve / warngrave / ban / mute
    points         INTEGER NOT NULL DEFAULT 0,
    reason_full    TEXT,                   -- la razón cruda escrita por el staff
    reason_short   TEXT,                   -- versión corta/profesional para la lista
    status         TEXT NOT NULL DEFAULT 'active',  -- active/expired/revoked
    issued_by      INTEGER,                -- user_id del staff que la puso
    issued_in_chat INTEGER,               -- chat donde se lanzó (0 si vino de un reporte)
    created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at     TIMESTAMP,              -- cuándo caduca (NULL para ban)
    revoked_at     TIMESTAMP,
    revoked_by     INTEGER
);
CREATE INDEX IF NOT EXISTS idx_sanctions_user ON sanctions(user_id);
CREATE INDEX IF NOT EXISTS idx_sanctions_status ON sanctions(status);
CREATE INDEX IF NOT EXISTS idx_sanctions_kind ON sanctions(kind);
CREATE INDEX IF NOT EXISTS idx_sanctions_expires ON sanctions(expires_at);

CREATE TABLE IF NOT EXISTS reports (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    reporter_id     INTEGER NOT NULL,
    reporter_name   TEXT,
    reporter_user   TEXT,
    target_id       INTEGER,               -- a quién se reporta (puede ser NULL si no se resolvió el @)
    target_name     TEXT,
    target_user     TEXT,
    reason          TEXT,
    origin_chat     INTEGER,               -- grupo de verificadas donde se creó
    origin_msg_id   INTEGER,               -- id del mensaje original (para saltar a él)
    staff_chat      INTEGER,               -- grupo de staff donde se publicó
    staff_msg_id    INTEGER,               -- id del mensaje en el grupo de staff
    status          TEXT NOT NULL DEFAULT 'pending',
    resolved_by     INTEGER,
    resolved_action TEXT,                  -- warnleve/warngrave/ban
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    resolved_at     TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_reports_status ON reports(status);
CREATE INDEX IF NOT EXISTS idx_reports_target ON reports(target_id);

CREATE TABLE IF NOT EXISTS group_roles (
    chat_id            INTEGER PRIMARY KEY,
    title              TEXT,
    is_verified_group  INTEGER NOT NULL DEFAULT 0,
    is_staff_group     INTEGER NOT NULL DEFAULT 0,
    applies_rules      INTEGER NOT NULL DEFAULT 1,
    applies_sanctions  INTEGER NOT NULL DEFAULT 1,
    updated_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS staff (
    user_id     INTEGER PRIMARY KEY,
    username    TEXT,
    full_name   TEXT,
    added_by    INTEGER,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sanctioned_users (
    user_id     INTEGER PRIMARY KEY,
    username    TEXT,
    full_name   TEXT,
    updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""


async def init_sanctions_db() -> None:
    """Crea las tablas del sistema de sanciones. Idempotente y defensivo."""
    async with get_db() as db:
        try:
            await db.executescript(SANCTIONS_SCHEMA)
            await db.commit()
            logger.info("✅ Tablas del sistema de sanciones inicializadas")
        except aiosqlite.Error as e:
            logger.warning("Error creando tablas de sanciones: %s", e)


# ===========================================================================
# UTILIDADES INTERNAS
# ===========================================================================
def _now() -> datetime:
    return datetime.utcnow()


def _parse_ts(value) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except (ValueError, TypeError):
        return None


def points_for_kind(kind: str) -> int:
    if kind == KIND_LEVE:
        return POINTS_LEVE
    if kind == KIND_GRAVE:
        return POINTS_GRAVE
    return 0


def expiry_for_kind(kind: str) -> Optional[datetime]:
    """Fecha de caducidad según el tipo. Ban y mute no usan esto aquí."""
    if kind == KIND_LEVE:
        return _now() + timedelta(days=EXPIRY_LEVE_DAYS)
    if kind == KIND_GRAVE:
        return _now() + timedelta(days=EXPIRY_GRAVE_DAYS)
    return None


# ===========================================================================
# EXPIRACIÓN AUTOMÁTICA
# ===========================================================================
async def expire_old_sanctions() -> int:
    """
    Marca como 'expired' todos los warns activos cuya fecha de caducidad ya
    pasó. Devuelve cuántos se expiraron. Se llama desde el scheduler y también
    de forma defensiva antes de contar puntos.
    """
    now_iso = _now().isoformat(sep=" ")
    async with get_db() as db:
        cur = await db.execute(
            "UPDATE sanctions SET status = ? "
            "WHERE status = ? AND expires_at IS NOT NULL AND expires_at <= ? "
            "AND kind IN (?, ?)",
            (STATUS_EXPIRED, STATUS_ACTIVE, now_iso, KIND_LEVE, KIND_GRAVE),
        )
        await db.commit()
        return cur.rowcount


# ===========================================================================
# CONSULTA DE ESTADO DE UN USUARIO
# ===========================================================================
async def get_active_points(user_id: int) -> int:
    """Suma de puntos de los warns ACTIVOS (no caducados, no revocados)."""
    await expire_old_sanctions()
    async with get_db() as db:
        cur = await db.execute(
            "SELECT COALESCE(SUM(points), 0) AS pts FROM sanctions "
            "WHERE user_id = ? AND status = ? AND kind IN (?, ?)",
            (user_id, STATUS_ACTIVE, KIND_LEVE, KIND_GRAVE),
        )
        row = await cur.fetchone()
        return int(row["pts"] or 0)


async def is_banned(user_id: int) -> bool:
    """True si el usuario tiene un ban activo."""
    async with get_db() as db:
        cur = await db.execute(
            "SELECT 1 FROM sanctions WHERE user_id = ? AND kind = ? "
            "AND status = ? LIMIT 1",
            (user_id, KIND_BAN, STATUS_ACTIVE),
        )
        return await cur.fetchone() is not None


async def get_active_sanctions(user_id: int) -> list[dict]:
    """Todas las sanciones activas de un usuario (para su ficha)."""
    await expire_old_sanctions()
    async with get_db() as db:
        cur = await db.execute(
            "SELECT * FROM sanctions WHERE user_id = ? AND status = ? "
            "ORDER BY created_at DESC",
            (user_id, STATUS_ACTIVE),
        )
        return [dict(r) for r in await cur.fetchall()]


async def get_user_status(user_id: int) -> dict:
    """
    Estado completo de un usuario, listo para mostrar en avisos y fichas.
    Devuelve:
      - points: puntos activos
      - banned: bool
      - points_to_ban: cuántos puntos faltan para el ban (0 si ya baneado)
      - active: lista de sanciones activas
      - next_expiry: la fecha de caducidad más próxima (o None)
    """
    banned = await is_banned(user_id)
    points = await get_active_points(user_id)
    active = await get_active_sanctions(user_id)

    points_to_ban = max(0, POINTS_BAN_THRESHOLD - points) if not banned else 0

    # Buscar la caducidad más próxima entre los warns activos
    next_expiry = None
    for s in active:
        if s["kind"] in (KIND_LEVE, KIND_GRAVE):
            exp = _parse_ts(s["expires_at"])
            if exp and (next_expiry is None or exp < next_expiry):
                next_expiry = exp

    return {
        "user_id": user_id,
        "points": points,
        "banned": banned,
        "points_to_ban": points_to_ban,
        "active": active,
        "next_expiry": next_expiry,
    }


# ===========================================================================
# APLICAR SANCIONES
# ===========================================================================
async def add_warn(
    user_id: int,
    kind: str,
    reason_full: Optional[str],
    reason_short: Optional[str],
    issued_by: Optional[int],
    issued_in_chat: int = 0,
) -> dict:
    """
    Registra un warn (leve o grave). Devuelve un dict con el resultado y qué
    umbrales se cruzaron:
      {
        "sanction_id": int,
        "points_before": int,
        "points_after": int,
        "crossed_mute": bool,   # si al aplicar este warn se llegó/superó 2 puntos
        "crossed_ban": bool,    # si al aplicar este warn se llegó/superó 3 puntos
      }
    IMPORTANTE: este método SOLO registra el warn y calcula umbrales. La
    ejecución real del mute/ban en Telegram la hace la capa superior
    (sanctions_actions), porque necesita el objeto Bot.
    """
    assert kind in (KIND_LEVE, KIND_GRAVE), "kind debe ser warnleve o warngrave"
    points_before = await get_active_points(user_id)
    pts = points_for_kind(kind)
    expires = expiry_for_kind(kind)

    async with get_db() as db:
        cur = await db.execute(
            "INSERT INTO sanctions "
            "(user_id, kind, points, reason_full, reason_short, status, "
            " issued_by, issued_in_chat, expires_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (user_id, kind, pts, reason_full, reason_short, STATUS_ACTIVE,
             issued_by, issued_in_chat,
             expires.isoformat(sep=" ") if expires else None),
        )
        await db.commit()
        sanction_id = cur.lastrowid or 0

    points_after = points_before + pts
    crossed_mute = (points_before < POINTS_MUTE_THRESHOLD <= points_after)
    crossed_ban = (points_after >= POINTS_BAN_THRESHOLD)

    return {
        "sanction_id": sanction_id,
        "points_before": points_before,
        "points_after": points_after,
        "crossed_mute": crossed_mute,
        "crossed_ban": crossed_ban,
    }


async def add_ban(
    user_id: int,
    reason_full: Optional[str],
    reason_short: Optional[str],
    issued_by: Optional[int],
    issued_in_chat: int = 0,
) -> int:
    """Registra un ban permanente. Devuelve el id de la sanción."""
    # Si ya está baneado, no duplicar
    if await is_banned(user_id):
        async with get_db() as db:
            cur = await db.execute(
                "SELECT id FROM sanctions WHERE user_id = ? AND kind = ? "
                "AND status = ? LIMIT 1",
                (user_id, KIND_BAN, STATUS_ACTIVE),
            )
            row = await cur.fetchone()
            return int(row["id"]) if row else 0
    async with get_db() as db:
        cur = await db.execute(
            "INSERT INTO sanctions "
            "(user_id, kind, points, reason_full, reason_short, status, "
            " issued_by, issued_in_chat, expires_at) "
            "VALUES (?, ?, 0, ?, ?, ?, ?, ?, NULL)",
            (user_id, KIND_BAN, reason_full, reason_short, STATUS_ACTIVE,
             issued_by, issued_in_chat),
        )
        await db.commit()
        return cur.lastrowid or 0


async def add_mute_record(
    user_id: int,
    reason_full: Optional[str],
    reason_short: Optional[str],
    issued_by: Optional[int],
    issued_in_chat: int,
    until: datetime,
) -> int:
    """
    Registra un mute en el histórico (la restricción real en Telegram la
    hace la capa de acciones). No suma puntos.
    """
    async with get_db() as db:
        cur = await db.execute(
            "INSERT INTO sanctions "
            "(user_id, kind, points, reason_full, reason_short, status, "
            " issued_by, issued_in_chat, expires_at) "
            "VALUES (?, ?, 0, ?, ?, ?, ?, ?, ?)",
            (user_id, KIND_MUTE, reason_full, reason_short, STATUS_ACTIVE,
             issued_by, issued_in_chat, until.isoformat(sep=" ")),
        )
        await db.commit()
        return cur.lastrowid or 0


# ===========================================================================
# REVOCAR SANCIONES (los /un... )
# ===========================================================================
async def revoke_last(user_id: int, kind: str, revoked_by: Optional[int]) -> Optional[dict]:
    """
    Revoca (marca como 'revoked') el warn ACTIVO más reciente de ese tipo.
    Devuelve la sanción revocada o None si no había ninguna.
    Usado por /unwarnleve y /unwarngrave.
    """
    now_iso = _now().isoformat(sep=" ")
    async with get_db() as db:
        cur = await db.execute(
            "SELECT * FROM sanctions WHERE user_id = ? AND kind = ? "
            "AND status = ? ORDER BY created_at DESC LIMIT 1",
            (user_id, kind, STATUS_ACTIVE),
        )
        row = await cur.fetchone()
        if not row:
            return None
        await db.execute(
            "UPDATE sanctions SET status = ?, revoked_at = ?, revoked_by = ? "
            "WHERE id = ?",
            (STATUS_REVOKED, now_iso, revoked_by, row["id"]),
        )
        await db.commit()
        return dict(row)


async def revoke_ban(user_id: int, revoked_by: Optional[int]) -> bool:
    """Revoca el ban activo de un usuario. Devuelve True si había uno."""
    now_iso = _now().isoformat(sep=" ")
    async with get_db() as db:
        cur = await db.execute(
            "SELECT id FROM sanctions WHERE user_id = ? AND kind = ? "
            "AND status = ? LIMIT 1",
            (user_id, KIND_BAN, STATUS_ACTIVE),
        )
        row = await cur.fetchone()
        if not row:
            return False
        await db.execute(
            "UPDATE sanctions SET status = ?, revoked_at = ?, revoked_by = ? "
            "WHERE id = ?",
            (STATUS_REVOKED, now_iso, revoked_by, row["id"]),
        )
        await db.commit()
        return True


async def revoke_active_mutes(user_id: int, revoked_by: Optional[int]) -> int:
    """Revoca todos los registros de mute activos de un usuario (para /unmute)."""
    now_iso = _now().isoformat(sep=" ")
    async with get_db() as db:
        cur = await db.execute(
            "UPDATE sanctions SET status = ?, revoked_at = ?, revoked_by = ? "
            "WHERE user_id = ? AND kind = ? AND status = ?",
            (STATUS_REVOKED, now_iso, revoked_by, user_id, KIND_MUTE, STATUS_ACTIVE),
        )
        await db.commit()
        return cur.rowcount


# ===========================================================================
# CACHÉ DE USUARIOS SANCIONADOS (para la lista)
# ===========================================================================
async def remember_sanctioned_user(
    user_id: int, username: Optional[str], full_name: Optional[str]
) -> None:
    """Guarda el último nombre/username conocido de un usuario sancionado."""
    async with get_db() as db:
        await db.execute(
            "INSERT INTO sanctioned_users (user_id, username, full_name) "
            "VALUES (?, ?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET "
            "username = COALESCE(excluded.username, sanctioned_users.username), "
            "full_name = COALESCE(excluded.full_name, sanctioned_users.full_name), "
            "updated_at = CURRENT_TIMESTAMP",
            (user_id, username, full_name),
        )
        await db.commit()


async def get_sanctioned_user_info(user_id: int) -> Optional[dict]:
    async with get_db() as db:
        cur = await db.execute(
            "SELECT user_id, username, full_name FROM sanctioned_users "
            "WHERE user_id = ?",
            (user_id,),
        )
        row = await cur.fetchone()
        return dict(row) if row else None


# ===========================================================================
# RESOLVER @usuario -> user_id DE FORMA GLOBAL (todos los grupos)
# ===========================================================================
async def resolve_username_global(username: str) -> Optional[dict]:
    """
    Busca un usuario por @username en TODOS los grupos (users_cache global).
    Devuelve {user_id, username, full_name} o None.
    Clave para poder sancionar por @ aunque la persona esté en otro grupo.
    """
    uname = username.lstrip("@").lower()
    async with get_db() as db:
        cur = await db.execute(
            "SELECT user_id, username, full_name FROM users_cache "
            "WHERE LOWER(username) = ? ORDER BY last_seen DESC LIMIT 1",
            (uname,),
        )
        row = await cur.fetchone()
        if row:
            return dict(row)
        # También mirar en sanctioned_users por si ya lo conocíamos
        cur = await db.execute(
            "SELECT user_id, username, full_name FROM sanctioned_users "
            "WHERE LOWER(username) = ? LIMIT 1",
            (uname,),
        )
        row = await cur.fetchone()
        return dict(row) if row else None


async def get_user_groups(user_id: int) -> list[int]:
    """
    Devuelve la lista de chat_id donde el bot ha visto a este usuario.
    Sirve para publicar avisos en todos los grupos donde esté (avisos de
    sanciones que vienen de reportes) y para ejecutar el ban en todos.
    """
    async with get_db() as db:
        cur = await db.execute(
            "SELECT DISTINCT chat_id FROM users_cache WHERE user_id = ?",
            (user_id,),
        )
        return [int(r["chat_id"]) for r in await cur.fetchall()]
