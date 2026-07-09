# -*- coding: utf-8 -*-
"""
database.py
Toda la base de datos del bot (SQLite mediante aiosqlite).
Una sola conexión compartida para todo el proceso.
"""
import os
import datetime
import aiosqlite

import config

_conn: aiosqlite.Connection | None = None

# ---------------------------------------------------------------------------
# ESQUEMA DE TABLAS
# ---------------------------------------------------------------------------
SCHEMA = """
CREATE TABLE IF NOT EXISTS channels (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id     INTEGER UNIQUE NOT NULL,
    username    TEXT,
    title       TEXT,
    ctype       TEXT DEFAULT 'channel',
    region      TEXT DEFAULT 'Sin región',
    category    TEXT DEFAULT 'Sin categoría',
    tier        TEXT DEFAULT '',
    slot        INTEGER DEFAULT 0,
    is_admin    INTEGER DEFAULT 0,
    owner_id        INTEGER DEFAULT 0,
    owner_name      TEXT DEFAULT '',
    owner_username  TEXT DEFAULT '',
    topics      TEXT DEFAULT '',
    added_at    TEXT
);

CREATE TABLE IF NOT EXISTS promos (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT,
    src_chat_id     INTEGER NOT NULL,
    src_message_id  INTEGER NOT NULL,
    created_at      TEXT
);

CREATE TABLE IF NOT EXISTS campaigns (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT,
    region          TEXT,
    category        TEXT,
    promo_ids       TEXT,
    days            TEXT,
    start_hour      INTEGER,
    start_minute    INTEGER,
    batch_size      INTEGER DEFAULT 5,
    interval_min    INTEGER DEFAULT 5,
    delete_after_h  INTEGER DEFAULT 24,
    rotate_every    INTEGER DEFAULT 0,
    tz              TEXT DEFAULT 'Europe/Madrid',
    active          INTEGER DEFAULT 1,
    created_at      TEXT
);

CREATE TABLE IF NOT EXISTS sends (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_chat_id  INTEGER,
    dest_message_id  INTEGER,
    promo_id         INTEGER,
    campaign_id      INTEGER,
    sent_at          TEXT,
    delete_at        TEXT,
    status           TEXT,
    error            TEXT,
    deleted          INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS settings (
    key    TEXT PRIMARY KEY,
    value  TEXT
);

CREATE TABLE IF NOT EXISTS removed (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id         INTEGER,
    title           TEXT,
    username        TEXT,
    owner_name      TEXT,
    owner_username  TEXT,
    region          TEXT,
    motivo          TEXT,
    removed_at      TEXT
);

CREATE TABLE IF NOT EXISTS alliances (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT,
    chat_id         INTEGER,
    promo_id        INTEGER,
    days            TEXT,
    times           TEXT,
    tz              TEXT DEFAULT 'Europe/Madrid',
    delete_after_h  INTEGER DEFAULT 24,
    topics          TEXT DEFAULT '',
    active          INTEGER DEFAULT 1,
    created_at      TEXT
);

CREATE TABLE IF NOT EXISTS repost_msgs (
    src_chat   INTEGER,
    src_msg    INTEGER,
    dest_chat  INTEGER,
    dest_msg   INTEGER,
    mgid       TEXT DEFAULT '',
    ts         INTEGER,
    PRIMARY KEY (src_chat, src_msg)
);
"""


def _now() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


# Creadoras por bloque. Es el estándar de la operación (5 chicas/bloque).
TAM_BLOQUE = 5


# ---------------------------------------------------------------------------
# INICIALIZACIÓN
# ---------------------------------------------------------------------------
async def init_db() -> None:
    """Abre la base de datos y crea las tablas si no existen."""
    global _conn
    path = config.DB_PATH
    try:
        carpeta = os.path.dirname(path)
        if carpeta:
            os.makedirs(carpeta, exist_ok=True)
    except Exception:
        # Si /data no está montado en Railway, usamos un archivo local.
        path = "bot.db"
        config.DB_PATH = path

    _conn = await aiosqlite.connect(path)
    _conn.row_factory = aiosqlite.Row
    await _conn.executescript(SCHEMA)
    # Migración suave para bases de datos antiguas.
    for tabla, columna, definicion in [
        ("campaigns", "tz", "TEXT DEFAULT 'Europe/Madrid'"),
        ("channels", "slot", "INTEGER DEFAULT 0"),
        ("channels", "owner_id", "INTEGER DEFAULT 0"),
        ("channels", "owner_name", "TEXT DEFAULT ''"),
        ("channels", "owner_username", "TEXT DEFAULT ''"),
        ("channels", "topics", "TEXT DEFAULT ''"),
        ("channels", "repost_mode", "TEXT DEFAULT 'contenido'"),
        ("channels", "repost_off", "INTEGER DEFAULT 0"),
        ("channels", "invite_link", "TEXT DEFAULT ''"),
        ("channels", "girl_username", "TEXT DEFAULT ''"),
        ("alliances", "topics", "TEXT DEFAULT ''"),
    ]:
        try:
            await _conn.execute(
                f"ALTER TABLE {tabla} ADD COLUMN {columna} {definicion}")
        except Exception:
            pass  # la columna ya existe
    await _conn.commit()


def conn() -> aiosqlite.Connection:
    assert _conn is not None, "La base de datos no está inicializada"
    return _conn


# ---------------------------------------------------------------------------
# HILOS DE FORO (topics)
# ---------------------------------------------------------------------------
import re as _re


def extraer_topic_id(texto: str):
    """
    Saca el ID del hilo de un enlace de Telegram. Devuelve int o None.
    Acepta formas como:
      https://t.me/c/2412345678/45   -> 45
      https://t.me/migrupo/45        -> 45
      t.me/c/2412345678/45/123       -> 45  (el hilo es el primer número
                                             tras el grupo; 123 sería un
                                             mensaje dentro del hilo)
      45                              -> 45  (si pegan solo el número)
    """
    texto = (texto or "").strip()
    if texto.isdigit():
        return int(texto)
    # Buscar el patrón .../algo/NUMERO o .../c/ID/NUMERO
    m = _re.search(r"t\.me/(?:c/)?[^/]+/(\d+)", texto)
    if m:
        return int(m.group(1))
    return None


def parsear_topics(texto: str) -> list:
    """
    Convierte lo que escribe el usuario (uno o varios enlaces/números,
    separados por espacios, comas o saltos de línea) en una lista de IDs.
    """
    if not texto:
        return []
    crudo = texto.replace(",", " ").replace("\n", " ").split()
    ids = []
    for trozo in crudo:
        tid = extraer_topic_id(trozo)
        if tid and tid not in ids:
            ids.append(tid)
    return ids


def topics_a_texto(topics_str: str) -> list:
    """Devuelve la lista de IDs guardada en la BD (campo 'topics')."""
    if not topics_str:
        return []
    return [int(x) for x in str(topics_str).split(",") if x.strip().isdigit()]


async def close_db() -> None:
    """Cierra la conexión (necesario antes de restaurar un backup)."""
    global _conn
    if _conn is not None:
        try:
            await _conn.close()
        except Exception:
            pass
        _conn = None


def db_file_path() -> str:
    """Ruta real del archivo de base de datos en uso."""
    return config.DB_PATH


# ---------------------------------------------------------------------------
# AJUSTES (clave/valor)
# ---------------------------------------------------------------------------
async def get_setting(key: str, default: str = "") -> str:
    cur = await conn().execute("SELECT value FROM settings WHERE key=?", (key,))
    row = await cur.fetchone()
    return row["value"] if row else default


async def set_setting(key: str, value: str) -> None:
    await conn().execute(
        "INSERT INTO settings(key,value) VALUES(?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )
    await conn().commit()


# ---------------------------------------------------------------------------
# CANALES
# ---------------------------------------------------------------------------
async def add_channel(chat_id: int, username: str, title: str,
                      ctype: str = "channel") -> bool:
    """
    Inserta o actualiza un canal de forma ATÓMICA.
    Gracias a ON CONFLICT(chat_id) es IMPOSIBLE que el mismo canal
    cree dos filas, aunque Telegram mande el evento dos veces seguidas.
    Devuelve True si el canal era nuevo.
    """
    cur = await conn().execute(
        "SELECT id FROM channels WHERE chat_id=?", (chat_id,))
    existe = await cur.fetchone()
    await conn().execute(
        "INSERT INTO channels(chat_id,username,title,ctype,added_at) "
        "VALUES(?,?,?,?,?) "
        "ON CONFLICT(chat_id) DO UPDATE SET "
        "username=excluded.username, title=excluded.title, "
        "ctype=excluded.ctype",
        (chat_id, username, title, ctype, _now()),
    )
    await conn().commit()
    return existe is None


async def update_channel_tags(chat_id: int, region: str | None = None,
                               category: str | None = None,
                               tier: str | None = None) -> None:
    campos, valores = [], []
    if region is not None:
        campos.append("region=?"); valores.append(region)
    if category is not None:
        campos.append("category=?"); valores.append(category)
    if tier is not None:
        campos.append("tier=?"); valores.append(tier)
    if not campos:
        return
    valores.append(chat_id)
    await conn().execute(
        f"UPDATE channels SET {','.join(campos)} WHERE chat_id=?", valores)
    await conn().commit()


async def set_channel_admin(chat_id: int, is_admin: bool) -> None:
    await conn().execute(
        "UPDATE channels SET is_admin=? WHERE chat_id=?",
        (1 if is_admin else 0, chat_id),
    )
    await conn().commit()


async def set_channel_owner(chat_id: int, owner_id: int, owner_name: str,
                            owner_username: str) -> None:
    """Guarda el perfil del dueño/creador del canal."""
    await conn().execute(
        "UPDATE channels SET owner_id=?, owner_name=?, owner_username=? "
        "WHERE chat_id=?",
        (owner_id, owner_name, owner_username, chat_id),
    )
    await conn().commit()


async def set_channel_topics(chat_id: int, topics: list) -> None:
    """Guarda los hilos de foro de un canal/grupo (lista de IDs)."""
    texto = ",".join(str(t) for t in topics)
    await conn().execute(
        "UPDATE channels SET topics=? WHERE chat_id=?", (texto, chat_id))
    await conn().commit()


async def set_alliance_topics(ally_id: int, topics: list) -> None:
    """Guarda los hilos de foro de una alianza (lista de IDs)."""
    texto = ",".join(str(t) for t in topics)
    await conn().execute(
        "UPDATE alliances SET topics=? WHERE id=?", (texto, ally_id))
    await conn().commit()


# ---------------------------------------------------------------------------
# CANALES QUE HAN ECHADO EL BOT (historial de expulsiones)
# ---------------------------------------------------------------------------
async def add_removed(chat_id: int, title: str, username: str,
                      owner_name: str, owner_username: str, region: str,
                      motivo: str) -> None:
    """Registra que un canal/grupo ha quitado el bot."""
    await conn().execute(
        "INSERT INTO removed(chat_id,title,username,owner_name,"
        "owner_username,region,motivo,removed_at) VALUES(?,?,?,?,?,?,?,?)",
        (chat_id, title, username, owner_name, owner_username, region,
         motivo, _now()))
    await conn().commit()


async def get_removed(limite: int = 50) -> list:
    """Lista de canales que han echado el bot, del más reciente al más viejo."""
    cur = await conn().execute(
        "SELECT * FROM removed ORDER BY id DESC LIMIT ?", (limite,))
    return list(await cur.fetchall())


async def count_removed() -> int:
    cur = await conn().execute("SELECT COUNT(*) c FROM removed")
    row = await cur.fetchone()
    return row["c"]


async def clear_removed() -> int:
    """Vacía la lista de expulsados. Devuelve cuántos había."""
    n = await count_removed()
    await conn().execute("DELETE FROM removed")
    await conn().commit()
    return n


async def get_channels(region: str | None = None,
                        category: str | None = None) -> list:
    sql = "SELECT * FROM channels"
    cond, val = [], []
    if region and region != "Todas":
        cond.append("region=?"); val.append(region)
    if category and category != "Todas":
        cond.append("category=?"); val.append(category)
    if cond:
        sql += " WHERE " + " AND ".join(cond)
    sql += " ORDER BY id ASC"
    cur = await conn().execute(sql, val)
    return list(await cur.fetchall())


async def get_channel(chat_id: int):
    cur = await conn().execute(
        "SELECT * FROM channels WHERE chat_id=?", (chat_id,))
    return await cur.fetchone()


async def delete_channel(chat_id: int) -> None:
    await conn().execute("DELETE FROM channels WHERE chat_id=?", (chat_id,))
    await conn().commit()


async def count_channels() -> int:
    cur = await conn().execute("SELECT COUNT(*) c FROM channels")
    row = await cur.fetchone()
    return row["c"]


async def clean_duplicates() -> dict:
    """
    Busca canales duplicados y deja uno solo de cada uno.
    Detecta duplicados por TRES vías:
      1) mismo chat_id (no debería pasar, pero por si hay datos viejos),
      2) mismo @usuario,
      3) mismo título Y mismo propietario (para canales privados sin @).
    Se queda con el que tenga permisos OK; si empatan, el más antiguo.
    """
    cur = await conn().execute("SELECT * FROM channels ORDER BY id ASC")
    todos = list(await cur.fetchall())

    def huella(ch):
        # Cómo identificamos que dos filas son "el mismo canal".
        if ch["username"]:
            return ("user", ch["username"].lower())
        if ch["title"] and ch["owner_id"]:
            return ("titlowner", ch["title"].strip().lower(),
                    ch["owner_id"])
        return ("id", ch["chat_id"])

    # Primero agrupamos por chat_id exacto (duplicado real de datos viejos).
    por_id: dict = {}
    for ch in todos:
        por_id.setdefault(ch["chat_id"], []).append(ch)

    grupos: dict = {}
    for ch in todos:
        grupos.setdefault(huella(ch), []).append(ch)
    # Añadir los grupos por chat_id que tengan más de uno.
    for cid, lista in por_id.items():
        if len(lista) > 1:
            grupos[("id", cid)] = lista

    borrados, conservados = 0, 0
    detalle = []
    ya_borrados = set()
    for clave, lista in grupos.items():
        lista = [c for c in lista if c["id"] not in ya_borrados]
        if len(lista) < 2:
            continue
        # El "bueno": primero los que tienen permisos OK, y el más antiguo.
        lista_ord = sorted(
            lista, key=lambda c: (0 if c["is_admin"] else 1, c["id"]))
        bueno = lista_ord[0]
        conservados += 1
        for ch in lista_ord[1:]:
            # Heredar región/bloque si el bueno no los tenía.
            if ch["slot"] and not bueno["slot"]:
                await conn().execute(
                    "UPDATE channels SET region=?, category=?, slot=? "
                    "WHERE id=?",
                    (ch["region"], ch["category"], ch["slot"], bueno["id"]))
            await conn().execute(
                "DELETE FROM channels WHERE id=?", (ch["id"],))
            ya_borrados.add(ch["id"])
            borrados += 1
        detalle.append(bueno["title"] or str(bueno["chat_id"]))
    await conn().commit()
    return {"borrados": borrados, "grupos": conservados, "detalle": detalle}


async def distinct_values(campo: str) -> list:
    cur = await conn().execute(
        f"SELECT DISTINCT {campo} v FROM channels ORDER BY v")
    return [r["v"] for r in await cur.fetchall()]


# ---------------------------------------------------------------------------
# REPOST  (reenvío de las publicaciones de las creadoras a canales showcase)
#
# IMPORTANTE: esto es TOTALMENTE independiente. NO toca región, ni categoría,
# ni bloque, ni campañas, ni el spam. Solo decide a qué canal de repost va el
# contenido de cada creadora. La región se sigue usando igual que siempre.
# ---------------------------------------------------------------------------

# Regiones que se agrupan como "Latinoamérica" para el repost.
# (España va a su canal; estas cuatro van al canal Latam.)
LATAM_REGIONS = {"Cono Sur", "Caribe", "Andina", "México"}

# Claves de ajustes donde se guardan los 3 canales showcase y los toggles.
RP_ON = "repost_on"                 # "1" / "0"
RP_NOTIF = "repost_notif"           # "1" / "0" (avisarme cuando salte un post)
RP_CH_ES = "repost_ch_es"           # chat_id del canal España
RP_CH_LATAM = "repost_ch_latam"     # chat_id del canal Latam
RP_CH_FINDOM = "repost_ch_findom"   # chat_id del canal Findom hispano

# Botones que van debajo de cada publicación reenviada.
RP_B1_TEXT = "repost_b1_text"       # texto del botón 1 (perfil propietaria)
RP_B1_STYLE = "repost_b1_style"     # "" normal | primary | danger | success
RP_B2_TEXT = "repost_b2_text"       # texto del botón 2 (canal)
RP_B2_STYLE = "repost_b2_style"


async def get_repost_botones() -> dict:
    """Config de los 2 botones (texto + estilo de color)."""
    return {
        "b1_text": await get_setting(RP_B1_TEXT, "👤 Perfil"),
        "b1_style": await get_setting(RP_B1_STYLE, ""),
        "b2_text": await get_setting(RP_B2_TEXT, "📢 Canal"),
        "b2_style": await get_setting(RP_B2_STYLE, ""),
    }


async def set_repost_mode(chat_id: int, modo: str) -> None:
    """modo = 'contenido' (por defecto) o 'findom' (solo findom)."""
    if modo not in ("contenido", "findom"):
        modo = "contenido"
    await conn().execute(
        "UPDATE channels SET repost_mode=? WHERE chat_id=?", (modo, chat_id))
    await conn().commit()


async def set_repost_off(chat_id: int, off: bool) -> None:
    """Excluir (True) o incluir (False) un canal en el repost. Es
    independiente de la marca findom: excluir no borra su modo."""
    await conn().execute(
        "UPDATE channels SET repost_off=? WHERE chat_id=?",
        (1 if off else 0, chat_id))
    await conn().commit()


async def is_repost_off(chat_id: int) -> bool:
    ch = await get_channel(chat_id)
    if not ch:
        return False
    try:
        return bool(ch["repost_off"])
    except Exception:
        return False


async def channels_excluidos() -> list:
    """Canales excluidos del repost."""
    cur = await conn().execute(
        "SELECT * FROM channels WHERE repost_off=1 ORDER BY id ASC")
    return list(await cur.fetchall())


async def get_channel_invite(chat_id: int) -> str:
    """Enlace de invitación guardado de un canal (uno por canal, persistente)."""
    ch = await get_channel(chat_id)
    if not ch:
        return ""
    try:
        return ch["invite_link"] or ""
    except Exception:
        return ""


async def set_channel_invite(chat_id: int, link: str) -> None:
    await conn().execute(
        "UPDATE channels SET invite_link=? WHERE chat_id=?", (link, chat_id))
    await conn().commit()


# --- Mapa de publicaciones reenviadas (para actualizar ediciones) ---
def _epoch() -> int:
    return int(datetime.datetime.now().timestamp())


async def add_repost_map(src_chat: int, src_msg: int, dest_chat: int,
                         dest_msg: int, mgid: str = "") -> None:
    await conn().execute(
        "INSERT OR REPLACE INTO repost_msgs "
        "(src_chat, src_msg, dest_chat, dest_msg, mgid, ts) "
        "VALUES (?,?,?,?,?,?)",
        (src_chat, src_msg, dest_chat, dest_msg, mgid or "", _epoch()))
    await conn().commit()


async def get_repost_map(src_chat: int, src_msg: int):
    cur = await conn().execute(
        "SELECT * FROM repost_msgs WHERE src_chat=? AND src_msg=?",
        (src_chat, src_msg))
    return await cur.fetchone()


async def get_repost_group(src_chat: int, mgid: str) -> list:
    if not mgid:
        return []
    cur = await conn().execute(
        "SELECT * FROM repost_msgs WHERE src_chat=? AND mgid=?",
        (src_chat, mgid))
    return list(await cur.fetchall())


async def del_repost_map(src_chat: int, src_msg: int) -> None:
    await conn().execute(
        "DELETE FROM repost_msgs WHERE src_chat=? AND src_msg=?",
        (src_chat, src_msg))
    await conn().commit()


async def del_repost_group(src_chat: int, mgid: str) -> None:
    if not mgid:
        return
    await conn().execute(
        "DELETE FROM repost_msgs WHERE src_chat=? AND mgid=?",
        (src_chat, mgid))
    await conn().commit()


async def prune_repost_map(dias: int = 30) -> None:
    """Borra mapeos antiguos para que la tabla no crezca sin fin."""
    limite = _epoch() - dias * 86400
    await conn().execute("DELETE FROM repost_msgs WHERE ts < ?", (limite,))
    await conn().commit()


async def repost_con_botones() -> list:
    """Copias que LLEVAN botones: posts sueltos (mgid vacío) y los pies de
    álbum (src_msg negativo). A esas se les puede refrescar el teclado.
    Los elementos de un álbum en sí no llevan botones, así que se excluyen."""
    cur = await conn().execute(
        "SELECT * FROM repost_msgs "
        "WHERE mgid='' OR mgid IS NULL OR src_msg < 0")
    return list(await cur.fetchall())


async def repost_maps_for_channel(src_chat: int) -> list:
    """Todas las copias (elementos, sueltos y pies) de un canal."""
    cur = await conn().execute(
        "SELECT * FROM repost_msgs WHERE src_chat=?", (src_chat,))
    return list(await cur.fetchall())


async def count_repost_channel(src_chat: int) -> int:
    cur = await conn().execute(
        "SELECT COUNT(*) c FROM repost_msgs WHERE src_chat=?", (src_chat,))
    row = await cur.fetchone()
    return row["c"] if row else 0


async def del_repost_channel(src_chat: int) -> None:
    await conn().execute(
        "DELETE FROM repost_msgs WHERE src_chat=?", (src_chat,))
    await conn().commit()


async def set_girl_username(chat_id: int, username: str) -> None:
    """Asigna a mano la @ de la propietaria real de un canal (para el botón
    de perfil y el filtro). Cadena vacía para quitarla."""
    u = (username or "").strip().lstrip("@")
    await conn().execute(
        "UPDATE channels SET girl_username=? WHERE chat_id=?", (u, chat_id))
    await conn().commit()


async def get_repost_mode(chat_id: int) -> str:
    ch = await get_channel(chat_id)
    if not ch:
        return "contenido"
    try:
        return ch["repost_mode"] or "contenido"
    except Exception:
        return "contenido"


async def repost_enabled() -> bool:
    return (await get_setting(RP_ON, "0")) == "1"


async def repost_notif() -> bool:
    return (await get_setting(RP_NOTIF, "0")) == "1"


async def get_repost_channels() -> dict:
    """Devuelve {'es': id|0, 'latam': id|0, 'findom': id|0}."""
    def _int(v):
        try:
            return int(v)
        except Exception:
            return 0
    return {
        "es": _int(await get_setting(RP_CH_ES, "0")),
        "latam": _int(await get_setting(RP_CH_LATAM, "0")),
        "findom": _int(await get_setting(RP_CH_FINDOM, "0")),
    }


async def set_repost_channel(bucket: str, chat_id: int) -> None:
    clave = {"es": RP_CH_ES, "latam": RP_CH_LATAM,
             "findom": RP_CH_FINDOM}.get(bucket)
    if clave:
        await set_setting(clave, str(chat_id))


async def repost_destino(ch) -> tuple[str, int]:
    """
    Decide a qué canal showcase va el contenido de esta creadora.
    Devuelve (etiqueta, chat_id_destino). chat_id_destino=0 si no aplica
    o si ese canal aún no está configurado.

    Prioridad:
      1) Si está marcada como 'solo findom'  -> canal Findom (da igual región).
      2) Si su región es España              -> canal España.
      3) Si su región es Latam (las 4)       -> canal Latam.
      4) Cualquier otra cosa (Alianza, Sin región...) -> no se reenvía.
    """
    canales = await get_repost_channels()
    try:
        modo = ch["repost_mode"] or "contenido"
    except Exception:
        modo = "contenido"
    # Canal excluido del repost: no se reenvía nada.
    try:
        if ch["repost_off"]:
            return ("🚫 Excluido", 0)
    except Exception:
        pass
    region = ch["region"] if ch else ""

    if modo == "findom":
        return ("Findom", canales["findom"])
    if region == "España":
        return ("España", canales["es"])
    if region in LATAM_REGIONS:
        return ("Latam", canales["latam"])
    return ("—", 0)


async def afiliadas_usernames() -> set:
    """
    Conjunto de @usuarios (en minúscula, sin @) que SON de la red MALA:
    tanto el @ del canal como el @ del propietario de cada canal registrado.
    Se usa para el filtro: un enlace/mención a uno de estos NO es promo
    externa (es gente tuya).
    """
    cur = await conn().execute(
        "SELECT username, owner_username FROM channels")
    filas = await cur.fetchall()
    s = set()
    for f in filas:
        for campo in ("username", "owner_username"):
            v = (f[campo] or "").strip().lower().lstrip("@")
            if v:
                s.add(v)
    return s


async def repost_destino_ids() -> set:
    """Los chat_id de los 3 canales showcase (para evitar bucles)."""
    c = await get_repost_channels()
    return {v for v in c.values() if v}


async def channels_por_modo_repost(modo: str) -> list:
    """Lista de canales marcados con un modo de repost concreto."""
    cur = await conn().execute(
        "SELECT * FROM channels WHERE repost_mode=? ORDER BY id ASC", (modo,))
    return list(await cur.fetchall())


# ---------------------------------------------------------------------------
# SLOTS / BLOQUES  (posición fija de cada canal dentro de su región)
# ---------------------------------------------------------------------------
async def next_free_slot(region: str) -> int:
    """Devuelve el primer bloque de esa región con hueco libre.
    Si una creadora se va, su hueco queda libre y lo ocupa la siguiente."""
    cur = await conn().execute(
        "SELECT slot, COUNT(*) c FROM channels "
        "WHERE region=? AND slot>0 GROUP BY slot", (region,))
    cuenta = {r["slot"]: r["c"] for r in await cur.fetchall()}
    bloque = 1
    while cuenta.get(bloque, 0) >= TAM_BLOQUE:
        bloque += 1
    return bloque


async def assign_region(chat_id: int, region: str) -> int:
    """Asigna región a un canal y le da un bloque fijo (el primer hueco
    libre). Devuelve el número de bloque asignado, o 0 si el canal ya
    no existe."""
    cur = await conn().execute(
        "SELECT id FROM channels WHERE chat_id=?", (chat_id,))
    if not await cur.fetchone():
        return 0
    slot = await next_free_slot(region)
    await conn().execute(
        "UPDATE channels SET region=?, slot=? WHERE chat_id=?",
        (region, slot, chat_id))
    await conn().commit()
    # Comprobamos que de verdad quedó guardado.
    cur = await conn().execute(
        "SELECT region, slot FROM channels WHERE chat_id=?", (chat_id,))
    row = await cur.fetchone()
    if row and row["region"] == region and row["slot"] == slot:
        return slot
    return 0


async def set_channel_slot(chat_id: int, slot: int) -> None:
    """Mueve un canal a otro bloque concreto."""
    await conn().execute(
        "UPDATE channels SET slot=? WHERE chat_id=?", (slot, chat_id))
    await conn().commit()


async def channels_by_block(region: str, category: str) -> dict:
    """Devuelve {numero_de_bloque: [canales]} ordenado por bloque."""
    canales = await get_channels(region, category)
    bloques: dict = {}
    for ch in canales:
        s = ch["slot"] or 0
        if s <= 0:
            continue
        bloques.setdefault(s, []).append(ch)
    return dict(sorted(bloques.items()))


# ---------------------------------------------------------------------------
# ALIANZAS
# ---------------------------------------------------------------------------
async def add_alliance(data: dict) -> int:
    cur = await conn().execute(
        "INSERT INTO alliances(name,chat_id,promo_id,days,times,tz,"
        "delete_after_h,active,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
        (data["name"], data["chat_id"], data["promo_id"], data["days"],
         data["times"], data.get("tz", "Europe/Madrid"),
         data["delete_after_h"], 1, _now()),
    )
    await conn().commit()
    return cur.lastrowid


async def get_alliances() -> list:
    cur = await conn().execute("SELECT * FROM alliances ORDER BY id ASC")
    return list(await cur.fetchall())


async def get_alliance(ally_id: int):
    cur = await conn().execute(
        "SELECT * FROM alliances WHERE id=?", (ally_id,))
    return await cur.fetchone()


async def update_alliance(ally_id: int, **campos) -> None:
    """Actualiza uno o varios campos de una alianza."""
    if not campos:
        return
    sets = ",".join(f"{k}=?" for k in campos)
    valores = list(campos.values()) + [ally_id]
    await conn().execute(
        f"UPDATE alliances SET {sets} WHERE id=?", valores)
    await conn().commit()


async def set_alliance_active(ally_id: int, active: bool) -> None:
    await conn().execute(
        "UPDATE alliances SET active=? WHERE id=?",
        (1 if active else 0, ally_id))
    await conn().commit()


async def delete_alliance(ally_id: int) -> None:
    await conn().execute("DELETE FROM alliances WHERE id=?", (ally_id,))
    await conn().commit()


# ---------------------------------------------------------------------------
# PROMOS (mensajes maestros)
# ---------------------------------------------------------------------------
async def add_promo(name: str, src_chat_id: int, src_message_id: int) -> int:
    cur = await conn().execute(
        "INSERT INTO promos(name,src_chat_id,src_message_id,created_at) "
        "VALUES(?,?,?,?)",
        (name, src_chat_id, src_message_id, _now()),
    )
    await conn().commit()
    return cur.lastrowid


async def get_promos() -> list:
    cur = await conn().execute("SELECT * FROM promos ORDER BY id ASC")
    return list(await cur.fetchall())


async def get_promo(promo_id: int):
    cur = await conn().execute("SELECT * FROM promos WHERE id=?", (promo_id,))
    return await cur.fetchone()


async def update_promo(promo_id: int, name: str | None = None,
                       src_chat_id: int | None = None,
                       src_message_id: int | None = None) -> None:
    """Actualiza el nombre y/o el mensaje maestro de una promo."""
    campos, valores = [], []
    if name is not None:
        campos.append("name=?"); valores.append(name)
    if src_chat_id is not None:
        campos.append("src_chat_id=?"); valores.append(src_chat_id)
    if src_message_id is not None:
        campos.append("src_message_id=?"); valores.append(src_message_id)
    if not campos:
        return
    valores.append(promo_id)
    await conn().execute(
        f"UPDATE promos SET {','.join(campos)} WHERE id=?", valores)
    await conn().commit()


async def delete_promo(promo_id: int) -> None:
    await conn().execute("DELETE FROM promos WHERE id=?", (promo_id,))
    await conn().commit()


async def promo_en_uso(promo_id: int) -> dict:
    """Devuelve qué campañas y alianzas usan una promo (para avisar
    antes de borrarla y no dejar nada huérfano)."""
    usada = {"campaigns": [], "alliances": []}
    for c in await get_campaigns():
        ids = [int(x) for x in str(c["promo_ids"]).split(",") if x]
        if promo_id in ids:
            usada["campaigns"].append(c["name"])
    for a in await get_alliances():
        if a["promo_id"] == promo_id:
            usada["alliances"].append(a["name"])
    return usada


# ---------------------------------------------------------------------------
# CAMPAÑAS
# ---------------------------------------------------------------------------
async def add_campaign(data: dict) -> int:
    cur = await conn().execute(
        "INSERT INTO campaigns(name,region,category,promo_ids,days,"
        "start_hour,start_minute,batch_size,interval_min,delete_after_h,"
        "rotate_every,tz,active,created_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            data["name"], data["region"], data["category"],
            data["promo_ids"], data["days"], data["start_hour"],
            data["start_minute"], data["batch_size"], data["interval_min"],
            data["delete_after_h"], data["rotate_every"],
            data.get("tz", "Europe/Madrid"), 1, _now(),
        ),
    )
    await conn().commit()
    return cur.lastrowid


async def get_campaigns() -> list:
    cur = await conn().execute("SELECT * FROM campaigns ORDER BY id ASC")
    return list(await cur.fetchall())


async def get_campaign(camp_id: int):
    cur = await conn().execute(
        "SELECT * FROM campaigns WHERE id=?", (camp_id,))
    return await cur.fetchone()


async def update_campaign(camp_id: int, **campos) -> None:
    """Actualiza uno o varios campos de una campaña."""
    if not campos:
        return
    sets = ",".join(f"{k}=?" for k in campos)
    valores = list(campos.values()) + [camp_id]
    await conn().execute(
        f"UPDATE campaigns SET {sets} WHERE id=?", valores)
    await conn().commit()


async def set_campaign_active(camp_id: int, active: bool) -> None:
    await conn().execute(
        "UPDATE campaigns SET active=? WHERE id=?",
        (1 if active else 0, camp_id),
    )
    await conn().commit()


async def delete_campaign(camp_id: int) -> None:
    await conn().execute("DELETE FROM campaigns WHERE id=?", (camp_id,))
    await conn().commit()


# ---------------------------------------------------------------------------
# ENVÍOS (historial y borrado programado)
# ---------------------------------------------------------------------------
async def add_send(channel_chat_id: int, dest_message_id, promo_id,
                   campaign_id, sent_at: str, delete_at,
                   status: str, error) -> None:
    await conn().execute(
        "INSERT INTO sends(channel_chat_id,dest_message_id,promo_id,"
        "campaign_id,sent_at,delete_at,status,error,deleted) "
        "VALUES(?,?,?,?,?,?,?,?,0)",
        (channel_chat_id, dest_message_id, promo_id, campaign_id,
         sent_at, delete_at, status, error),
    )
    await conn().commit()


async def pending_deletes() -> list:
    """Envíos que aún tienen que borrarse (para recuperar tras reinicio)."""
    cur = await conn().execute(
        "SELECT * FROM sends WHERE deleted=0 AND status='ok' "
        "AND delete_at IS NOT NULL")
    return list(await cur.fetchall())


async def mark_deleted(send_id: int) -> None:
    await conn().execute(
        "UPDATE sends SET deleted=1 WHERE id=?", (send_id,))
    await conn().commit()


async def recent_sends(limite: int = 30) -> list:
    """Devuelve los últimos envíos para el historial."""
    cur = await conn().execute(
        "SELECT * FROM sends ORDER BY id DESC LIMIT ?", (limite,))
    return list(await cur.fetchall())


async def sends_count_by_channel() -> dict:
    """Cuántas veces se ha publicado con éxito en cada canal."""
    cur = await conn().execute(
        "SELECT channel_chat_id, COUNT(*) c FROM sends "
        "WHERE status='ok' GROUP BY channel_chat_id")
    return {r["channel_chat_id"]: r["c"] for r in await cur.fetchall()}


async def active_sends_of_campaign(camp_id: int) -> list:
    """Publicaciones de una campaña que siguen sin borrarse."""
    cur = await conn().execute(
        "SELECT * FROM sends WHERE campaign_id=? AND deleted=0 "
        "AND status='ok' AND dest_message_id IS NOT NULL", (camp_id,))
    return list(await cur.fetchall())


async def stats() -> dict:
    c = conn()
    out = {}
    for clave, sql in {
        "canales": "SELECT COUNT(*) n FROM channels",
        "canales_ok": "SELECT COUNT(*) n FROM channels WHERE is_admin=1",
        "promos": "SELECT COUNT(*) n FROM promos",
        "campanas": "SELECT COUNT(*) n FROM campaigns",
        "campanas_on": "SELECT COUNT(*) n FROM campaigns WHERE active=1",
        "alianzas": "SELECT COUNT(*) n FROM alliances",
        "alianzas_on": "SELECT COUNT(*) n FROM alliances WHERE active=1",
        "envios_ok": "SELECT COUNT(*) n FROM sends WHERE status='ok'",
        "envios_fail": "SELECT COUNT(*) n FROM sends WHERE status='error'",
        "pendientes_borrar":
            "SELECT COUNT(*) n FROM sends WHERE deleted=0 AND status='ok' "
            "AND delete_at IS NOT NULL",
    }.items():
        cur = await c.execute(sql)
        row = await cur.fetchone()
        out[clave] = row["n"]
    return out
