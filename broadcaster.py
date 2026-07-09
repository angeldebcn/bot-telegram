# -*- coding: utf-8 -*-
"""
broadcaster.py
El "motor" del bot:
  - Difunde una promo a una lista de canales usando copy_message
    (copy_message conserva imagen, texto, formato Y emojis premium).
  - Programa el autoborrado de cada publicación.
  - Ejecuta las campañas automáticas (lotes escalonados + rotación).
"""
import asyncio
import logging
import datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler

try:
    # Excepciones de aiogram para distinguir tipos de error de Telegram.
    from aiogram.exceptions import (TelegramRetryAfter,
                                    TelegramForbiddenError,
                                    TelegramBadRequest)
except Exception:  # por si cambia la ruta en otra versión
    class TelegramRetryAfter(Exception):
        retry_after = 5
    class TelegramForbiddenError(Exception):
        pass
    class TelegramBadRequest(Exception):
        pass

import config
import database as db

log = logging.getLogger("mala-bot.broadcaster")

TZ = ZoneInfo(config.DEFAULT_TZ)

# Único planificador de tareas de todo el bot.
# Configuración robusta del planificador:
#  - misfire_grace_time: si una tarea se "pierde" porque el bot estaba
#    reiniciándose (p. ej. al subir cambios a Railway), se ejecuta igual
#    cuando el bot vuelve, siempre que no hayan pasado más de 30 minutos.
#  - coalesce: si se acumulan varias ejecuciones perdidas, las junta en
#    una sola (no manda la promo 3 veces seguidas).
scheduler = AsyncIOScheduler(
    timezone=TZ,
    job_defaults={
        "misfire_grace_time": 1800,   # 30 minutos de margen
        "coalesce": True,
    },
)

# Mapa de días de la semana (texto -> formato APScheduler).
DIAS_VALIDOS = {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}

# Zona horaria local de cada región. Así, al crear una campaña, escribes
# SIEMPRE la hora local (21:30) y el bot la convierte solo. Cada zona
# tiene su propio horario de verano, así que esto es exacto todo el año.
TZ_REGION = {
    "España": "Europe/Madrid",
    "Cono Sur": "America/Argentina/Buenos_Aires",
    "Caribe": "America/Caracas",
    "Andina": "America/Bogota",
    "México": "America/Mexico_City",
    "Todas": config.DEFAULT_TZ,
}


def tz_de_region(region: str) -> str:
    """Devuelve la zona horaria que corresponde a una región."""
    return TZ_REGION.get(region, config.DEFAULT_TZ)


def ahora() -> datetime.datetime:
    return datetime.datetime.now(TZ)


def _iso(dt: datetime.datetime) -> str:
    return dt.isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# BORRADO PROGRAMADO
# ---------------------------------------------------------------------------
async def _borrar_publicacion(bot, send_id: int, chat_id: int,
                              message_id: int) -> None:
    """Borra una publicación enviada y la marca como borrada en la BD."""
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
        log.info(f"Borrada publicación {message_id} en {chat_id}")
    except Exception as e:
        log.warning(f"No se pudo borrar {message_id} en {chat_id}: {e}")
    finally:
        await db.mark_deleted(send_id)


def programar_borrado(bot, send_id: int, chat_id: int, message_id: int,
                      cuando: datetime.datetime) -> None:
    """Crea un trabajo que borrará la publicación a la hora indicada."""
    if cuando <= ahora():
        cuando = ahora() + datetime.timedelta(seconds=10)
    scheduler.add_job(
        _borrar_publicacion, "date", run_date=cuando,
        args=[bot, send_id, chat_id, message_id],
        id=f"del_{send_id}", replace_existing=True,
    )


async def _borrar_envios_de_campana(bot, camp_id: int) -> int:
    """Borra TODAS las publicaciones que esta campaña tiene aún puestas.
    Devuelve cuántas se borraron."""
    envios = await db.active_sends_of_campaign(camp_id)
    n = 0
    for s in envios:
        try:
            await bot.delete_message(chat_id=s["channel_chat_id"],
                                     message_id=s["dest_message_id"])
        except Exception:
            pass
        await db.mark_deleted(s["id"])
        n += 1
        await asyncio.sleep(0.2)
    return n


# ---------------------------------------------------------------------------
# DIFUSIÓN DE UNA PROMO
# ---------------------------------------------------------------------------
def _motivo_legible(e: Exception) -> str:
    """Convierte el error técnico de Telegram en algo entendible."""
    t = str(e).lower()
    if isinstance(e, TelegramForbiddenError):
        # Forbidden puede ser por el DESTINO o por el canal de ORIGEN.
        if "bot is not a member" in t or "not a member" in t:
            return ("el bot no está en el canal de ORIGEN (el almacén de "
                    "promos) — añádelo ahí como admin")
        return "el bot no es admin del canal o fue expulsado"
    if isinstance(e, TelegramBadRequest):
        if "chat not found" in t:
            return "el canal ya no existe o el bot no lo ve"
        if ("message to copy not found" in t
                or "message to forward not found" in t
                or "message_id_invalid" in t):
            return ("la promo de origen no se encuentra (¿borraste el "
                    "mensaje del canal almacén?)")
        if "not enough rights" in t or "need administrator" in t:
            return "al bot le faltan permisos en el canal"
        if "chat_admin_required" in t:
            return "el bot necesita ser admin"
        return f"error de Telegram: {str(e)[:60]}"
    txt = str(e)
    return txt[:80] if txt else "error desconocido"


async def _publicar_una_vez(bot, chat_id, src_chat, src_msg, modo,
                            thread_id, borrar_tras_h, promo_id, campaign_id):
    """Publica la promo UNA vez en un chat (y opcionalmente en un hilo).
    Devuelve (ok, motivo). Maneja flood reintentando.
    Si el modo es 'reenviar' y falla, prueba a copiar como respaldo:
    así un problema con el canal de origen no deja sin publicar."""
    async def _intento(metodo_reenviar):
        kwargs = {"chat_id": chat_id, "from_chat_id": src_chat,
                  "message_id": src_msg}
        if thread_id:
            kwargs["message_thread_id"] = thread_id
        if metodo_reenviar:
            return await bot.forward_message(**kwargs)
        return await bot.copy_message(**kwargs)

    usar_reenviar = (modo == "reenviar")
    for intento in range(3):
        try:
            try:
                res = await _intento(usar_reenviar)
            except (TelegramForbiddenError, TelegramBadRequest) as e1:
                # Si estábamos REENVIANDO y falla, el problema suele ser el
                # canal de ORIGEN (almacén). Probamos a COPIAR como respaldo.
                if usar_reenviar:
                    log.warning(f"Reenvío falló en {chat_id} ({e1}); "
                                f"pruebo a copiar como respaldo")
                    res = await _intento(False)
                else:
                    raise
            dest_id = res.message_id
            delete_at = None
            cuando = None
            if borrar_tras_h and borrar_tras_h > 0:
                cuando = ahora() + datetime.timedelta(hours=borrar_tras_h)
                delete_at = _iso(cuando)
            await db.add_send(chat_id, dest_id, promo_id, campaign_id,
                              _iso(ahora()), delete_at, "ok", None)
            if delete_at:
                cur = await db.conn().execute(
                    "SELECT id FROM sends WHERE channel_chat_id=? "
                    "AND dest_message_id=? ORDER BY id DESC LIMIT 1",
                    (chat_id, dest_id))
                row = await cur.fetchone()
                if row:
                    programar_borrado(bot, row["id"], chat_id, dest_id,
                                      cuando)
            return True, None
        except TelegramRetryAfter as e:
            espera = getattr(e, "retry_after", 5) + 1
            log.warning(f"Flood en {chat_id}: espero {espera}s y reintento")
            await asyncio.sleep(espera)
            continue
        except Exception as e:
            motivo = _motivo_legible(e)
            await db.add_send(chat_id, None, promo_id, campaign_id,
                              _iso(ahora()), None, "error", motivo)
            log.warning(f"Fallo enviando a {chat_id} (hilo {thread_id}): "
                        f"{repr(e)}")
            return False, motivo
    motivo = "Telegram saturado (reintentar más tarde)"
    await db.add_send(chat_id, None, promo_id, campaign_id,
                      _iso(ahora()), None, "error", motivo)
    return False, motivo


async def _copiar_a_canal(bot, ch, promo, borrar_tras_h, campaign_id):
    """Publica la promo en UN canal/grupo. Devuelve (ok, motivo).
    Si el destino es un foro con hilos configurados, publica en CADA
    hilo elegido. Si no, publica normal (va a #General o al canal)."""
    chat_id = ch["chat_id"]
    src_chat = promo["src_chat_id"]
    src_msg = promo["src_message_id"]
    try:
        modo = await db.get_setting("modo_difusion", "copiar")
    except Exception:
        modo = "copiar"
    # ¿Tiene hilos configurados este destino?
    try:
        hilos = db.topics_a_texto(ch["topics"])
    except Exception:
        hilos = []

    if not hilos:
        # Publicación normal (sin hilo): va a #General o al canal.
        return await _publicar_una_vez(
            bot, chat_id, src_chat, src_msg, modo, None,
            borrar_tras_h, promo["id"], campaign_id)

    # Publicar en cada hilo elegido. Basta con que UNO salga bien para
    # contar el canal como OK; si fallan todos, devolvemos el motivo.
    algun_ok = False
    ultimo_motivo = None
    for tid in hilos:
        bien, motivo = await _publicar_una_vez(
            bot, chat_id, src_chat, src_msg, modo, tid,
            borrar_tras_h, promo["id"], campaign_id)
        if bien:
            algun_ok = True
        else:
            ultimo_motivo = motivo
        await asyncio.sleep(config.SEND_DELAY)
    return (True, None) if algun_ok else (False, ultimo_motivo)


async def difundir(bot, promo, canales: list, borrar_tras_h: int,
                   campaign_id=None) -> dict:
    """
    Copia el mensaje maestro de 'promo' a cada canal de la lista.
    borrar_tras_h: horas hasta el autoborrado (0 = no borrar).
    Maneja el límite de Telegram (flood) esperando y reintentando.
    Devuelve un resumen con enviados, fallidos y detalles.
    """
    ok, fallidos = 0, []
    for ch in canales:
        bien, motivo = await _copiar_a_canal(
            bot, ch, promo, borrar_tras_h, campaign_id)
        if bien:
            ok += 1
        else:
            nombre = ch["title"] or ch["username"] or str(ch["chat_id"])
            fallidos.append((ch["chat_id"], nombre, motivo))
        await asyncio.sleep(config.SEND_DELAY)
    return {"ok": ok, "fallidos": fallidos, "total": len(canales)}


# ---------------------------------------------------------------------------
# CAMPAÑAS AUTOMÁTICAS
# ---------------------------------------------------------------------------
async def ejecutar_campana(bot, camp_id: int, desde_bloque: int = 1,
                           borrar_antes: bool = False) -> None:
    """
    Lanza una campaña. Los canales se agrupan por su BLOQUE FIJO, así
    cada creadora sale siempre a la misma hora pase lo que pase.
    - desde_bloque: empieza a publicar desde ese número de bloque
      (útil si un bloque falló y quieres seguir desde ahí).
    - borrar_antes: si es True, borra primero las publicaciones que esta
      campaña ya había enviado (para empezar de cero limpio).
    """
    camp = await db.get_campaign(camp_id)
    if not camp or not camp["active"]:
        return

    # Si se pide, borramos lo ya publicado por esta campaña antes de empezar.
    if borrar_antes:
        borrados = await _borrar_envios_de_campana(bot, camp_id)
        await _avisar(bot, f"🧹 Campaña «{camp['name']}»: borradas "
                           f"{borrados} publicaciones anteriores antes de "
                           f"reempezar.", rutinario=True)

    bloques = await db.channels_by_block(camp["region"], camp["category"])
    if not bloques:
        await _avisar(bot, f"⚠️ Campaña «{camp['name']}»: sin canales que "
                           f"coincidan con {camp['region']}/{camp['category']}.")
        return

    promo_ids = [int(x) for x in str(camp["promo_ids"]).split(",") if x]
    promos = []
    for pid in promo_ids:
        p = await db.get_promo(pid)
        if p:
            promos.append(p)
    if not promos:
        await _avisar(bot, f"⚠️ Campaña «{camp['name']}»: las promos ya no "
                           f"existen.")
        return

    rotar = camp["rotate_every"] or 0
    # Solo los bloques desde 'desde_bloque' en adelante.
    numeros = [n for n in sorted(bloques.keys()) if n >= desde_bloque]
    if not numeros:
        await _avisar(bot, f"⚠️ Campaña «{camp['name']}»: no hay bloque "
                           f"{desde_bloque} o superior.")
        return
    total_canales = sum(len(bloques[n]) for n in numeros)

    # Chequeo previo: avisar de canales que ya no tienen al bot como admin.
    sin_permiso = []
    for num in numeros:
        for ch in bloques[num]:
            try:
                miembro = await bot.get_chat_member(ch["chat_id"], bot.id)
                if getattr(miembro, "status", "") != "administrator":
                    sin_permiso.append(ch["title"] or str(ch["chat_id"]))
                    await db.set_channel_admin(ch["chat_id"], False)
                else:
                    await db.set_channel_admin(ch["chat_id"], True)
            except Exception:
                sin_permiso.append(ch["title"] or str(ch["chat_id"]))
                await db.set_channel_admin(ch["chat_id"], False)
    if sin_permiso:
        lista = "\n".join(f"  · {n}" for n in sin_permiso[:20])
        await _avisar(
            bot,
            f"⚠️ <b>Aviso previo · campaña «{camp['name']}»</b>\n"
            f"Estos canales NO tienen al bot como admin y seguramente "
            f"fallarán:\n{lista}\n\n"
            f"La campaña continúa con el resto.")

    for num_bloque in numeros:
        lote = bloques[num_bloque]
        # La promo depende del NÚMERO de bloque (estable).
        if rotar and len(promos) > 1:
            p_idx = ((num_bloque - 1) // rotar) % len(promos)
        else:
            p_idx = 0
        promo = promos[p_idx]
        # La hora depende de la POSICIÓN dentro de los bloques a enviar:
        # el primero sale ya, el siguiente +intervalo, etc.
        posicion = numeros.index(num_bloque)
        cuando = ahora() + datetime.timedelta(
            minutes=posicion * camp["interval_min"])
        scheduler.add_job(
            _difundir_bloque, "date", run_date=cuando,
            args=[bot, promo, lote, camp["delete_after_h"], camp_id,
                  camp["name"], num_bloque, max(numeros)],
            id=f"camp{camp_id}_b{num_bloque}_{int(cuando.timestamp())}",
            replace_existing=True,
        )

    await _avisar(
        bot,
        f"🚀 Campaña «{camp['name']}» iniciada\n"
        f"• Canales: {total_canales}\n"
        f"• Bloques: {len(numeros)}\n"
        f"• Separación: {camp['interval_min']} min entre bloques\n"
        f"• Autoborrado: {camp['delete_after_h']} h\n\n"
        f"Te iré avisando del resultado de cada bloque."
    )


async def _difundir_bloque(bot, promo, lote, borrar_h, camp_id,
                           nombre, num_bloque, total_bloques) -> None:
    """Difunde un bloque de una campaña y avisa del resultado al dueño.
    Si hay fallos, programa UN reintento automático 4 minutos después."""
    resumen = await difundir(bot, promo, lote, borrar_h, camp_id)
    texto = (
        f"📦 <b>{nombre}</b> · bloque {num_bloque}/{total_bloques}\n"
        f"• Promo usada: {promo['name']}\n"
        f"• Enviados: {resumen['ok']}/{resumen['total']}\n"
        f"• Fallidos: {len(resumen['fallidos'])}")
    if resumen["fallidos"]:
        detalle = "\n".join(
            f"  · {n}: {e}" for _, n, e in resumen["fallidos"][:10])
        texto += f"\n⚠️ Motivos:\n{detalle}"
        # Reintento automático solo de los canales que fallaron.
        ids_fallidos = [c for c, _, _ in resumen["fallidos"]]
        cuando = ahora() + datetime.timedelta(minutes=4)
        scheduler.add_job(
            _reintentar_fallidos, "date", run_date=cuando,
            args=[bot, promo["id"], ids_fallidos, borrar_h, camp_id, nombre],
            id=f"retry_{camp_id}_{num_bloque}_{int(cuando.timestamp())}",
            replace_existing=True)
        texto += "\n\n🔁 Reintentaré los fallidos en 4 minutos."
        await _avisar(bot, texto)  # con fallos: aviso importante, siempre
    else:
        await _avisar(bot, texto, rutinario=True)  # todo bien: silenciable


async def _reintentar_fallidos(bot, promo_id, ids_canales, borrar_h,
                               camp_id, nombre) -> None:
    """Segundo intento automático para los canales que fallaron."""
    promo = await db.get_promo(promo_id)
    if not promo:
        return
    canales = []
    for cid in ids_canales:
        ch = await db.get_channel(cid)
        if ch:
            canales.append(ch)
    if not canales:
        return
    resumen = await difundir(bot, promo, canales, borrar_h, camp_id)
    texto = (
        f"🔁 <b>{nombre}</b> · reintento\n"
        f"• Recuperados: {resumen['ok']}/{resumen['total']}\n"
        f"• Siguen fallando: {len(resumen['fallidos'])}")
    if resumen["fallidos"]:
        detalle = "\n".join(
            f"  · {n}: {e}" for _, n, e in resumen["fallidos"][:10])
        texto += (f"\n⚠️ Estos no se pudieron enviar (revísalos a mano):\n"
                  f"{detalle}")
    await _avisar(bot, texto)


def registrar_campana(bot, camp) -> None:
    """Crea/actualiza el trabajo recurrente (cron) de una campaña.
    Usa la zona horaria de la campaña, así la hora que pusiste es la
    hora LOCAL de esa región (21:30 en España, 21:30 en Argentina, etc.)."""
    dias = [d for d in str(camp["days"]).split(",") if d in DIAS_VALIDOS]
    if not dias or not camp["active"]:
        quitar_campana(camp["id"])
        return
    try:
        zona = ZoneInfo(camp["tz"] or config.DEFAULT_TZ)
    except Exception:
        zona = TZ
    scheduler.add_job(
        ejecutar_campana, "cron",
        day_of_week=",".join(dias),
        hour=camp["start_hour"], minute=camp["start_minute"],
        timezone=zona,
        args=[bot, camp["id"]],
        id=f"cron_camp_{camp['id']}", replace_existing=True,
    )
    log.info(f"Campaña {camp['id']} programada: {dias} "
             f"{camp['start_hour']:02d}:{camp['start_minute']:02d} "
             f"({camp['tz']})")


def quitar_campana(camp_id: int) -> None:
    try:
        scheduler.remove_job(f"cron_camp_{camp_id}")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# ALIANZAS  (publicar en UN grupo concreto, varias veces al día)
# ---------------------------------------------------------------------------
async def _difundir_alianza(bot, ally_id: int, etiqueta_hora: str) -> None:
    """Publica la promo de una alianza en su grupo, a una de sus horas.
    Si la alianza tiene hilos de foro configurados, publica en ellos."""
    ally = await db.get_alliance(ally_id)
    if not ally or not ally["active"]:
        return
    promo = await db.get_promo(ally["promo_id"])
    canal = await db.get_channel(ally["chat_id"])
    if not promo or not canal:
        await _avisar(bot, f"⚠️ Alianza «{ally['name'] if ally else ''}»: "
                           f"falta la promo o el grupo.")
        return
    # La alianza usa SUS propios hilos (no los del canal). Construimos una
    # copia del destino con los topics de la alianza.
    destino = dict(canal)
    try:
        destino["topics"] = ally["topics"]
    except Exception:
        destino["topics"] = ""
    resumen = await difundir(bot, promo, [destino], ally["delete_after_h"])
    if resumen["ok"]:
        await _avisar(bot, f"🤝 Alianza «{ally['name']}» publicada "
                           f"({etiqueta_hora}).", rutinario=True)
    else:
        motivo = resumen["fallidos"][0][2] if resumen["fallidos"] else "?"
        await _avisar(bot, f"⚠️ Alianza «{ally['name']}» NO se publicó "
                           f"({etiqueta_hora}): {motivo}")


def registrar_alianza(bot, ally) -> None:
    """Programa todas las horas de una alianza (cada día indicado)."""
    quitar_alianza(ally["id"])
    if not ally["active"]:
        return
    dias = [d for d in str(ally["days"]).split(",") if d in DIAS_VALIDOS]
    if not dias:
        return
    try:
        zona = ZoneInfo(ally["tz"] or config.DEFAULT_TZ)
    except Exception:
        zona = TZ
    horas = [t.strip() for t in str(ally["times"]).split(",") if t.strip()]
    for t in horas:
        try:
            h, m = (int(x) for x in t.split(":"))
        except Exception:
            continue
        scheduler.add_job(
            _difundir_alianza, "cron",
            day_of_week=",".join(dias), hour=h, minute=m, timezone=zona,
            args=[bot, ally["id"], t],
            id=f"ally_{ally['id']}_{t.replace(':', '')}",
            replace_existing=True,
        )
    log.info(f"Alianza {ally['id']} programada: {dias} {horas} ({ally['tz']})")


def quitar_alianza(ally_id: int) -> None:
    """Quita todos los trabajos programados de una alianza."""
    for job in list(scheduler.get_jobs()):
        if job.id.startswith(f"ally_{ally_id}_"):
            try:
                scheduler.remove_job(job.id)
            except Exception:
                pass


# ---------------------------------------------------------------------------
# RECUPERACIÓN TRAS UN REINICIO
# ---------------------------------------------------------------------------
async def restaurar(bot) -> None:
    """
    Tras un reinicio de Railway:
      - vuelve a programar los borrados pendientes,
      - vuelve a registrar las campañas y alianzas activas.
    """
    # Borrados pendientes
    for s in await db.pending_deletes():
        try:
            cuando = datetime.datetime.fromisoformat(s["delete_at"])
            if cuando.tzinfo is None:
                cuando = cuando.replace(tzinfo=TZ)
        except Exception:
            continue
        if s["dest_message_id"]:
            programar_borrado(bot, s["id"], s["channel_chat_id"],
                              s["dest_message_id"], cuando)
    # Campañas
    for camp in await db.get_campaigns():
        if camp["active"]:
            registrar_campana(bot, camp)
    # Alianzas
    for ally in await db.get_alliances():
        if ally["active"]:
            registrar_alianza(bot, ally)
    log.info("Trabajos restaurados tras el arranque.")


async def _avisar(bot, texto: str, rutinario: bool = False) -> None:
    """Envía un aviso al dueño del bot.
    Si rutinario=True y el modo silencio está activo, no se envía
    (los avisos importantes como errores siempre pasan)."""
    if rutinario:
        try:
            if (await db.get_setting("quiet", "0")) == "1":
                return
        except Exception:
            pass
    try:
        await bot.send_message(config.OWNER_ID, texto)
    except Exception as e:
        log.warning(f"No se pudo avisar al dueño: {e}")
