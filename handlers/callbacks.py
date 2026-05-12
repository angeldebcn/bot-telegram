"""
Manejadores de todos los callback_query (botones inline del menú).

Cada handler:
1. Verifica que el usuario sea admin del chat objetivo.
2. Hace el cambio en BD si corresponde.
3. Redibuja el menú con edit_message_text.
4. Responde al callback con un toast (callback.answer).
"""
import logging
import time
from datetime import datetime, timedelta
from typing import Optional

from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, Message

from config import (
    ANTIDUP_OPTIONS,
    AUTOCLEAN_OPTIONS,
    COOLDOWN_OPTIONS,
    MUTE_DURATION_OPTIONS,
    NOTICE_DURATION_OPTIONS,
    PHASH_OPTIONS,
    PUNISHMENT_TYPES,
    QUEUE_OPTIONS,
    WARN_EXPIRATION_OPTIONS,
    WARN_LIMIT_OPTIONS,
)
from database import alianzas as alianzas_db
from database import posts as posts_db
from database.config_db import get_config, reset_to_defaults, update_config
from database.stats import get_recent_logs, get_stats, get_top_posters
from handlers.menu import render_main_menu_text
from keyboards.builders import (
    advanced_menu,
    alianzas_menu,
    antidup_menu,
    autoclean_menu,
    confirm_clear_alianzas,
    confirm_reset_config,
    confirm_reset_queue,
    cooldown_menu,
    main_menu,
    mute_duration_menu,
    notice_duration_menu,
    phash_menu,
    punishment_choice_menu,
    punishments_menu,
    queue_menu,
    stats_menu,
    warn_expiration_menu,
    warn_final_menu,
    warn_final_mute_menu,
    warn_limit_menu,
    warns_menu,
)
from utils.helpers import format_duration, format_minutes, safe_username
from utils.permissions import is_admin

logger = logging.getLogger(__name__)
router = Router(name="callbacks")


# === Estado para valores personalizados ===
# Cuando un usuario pulsa "✏️ Valor personalizado", guardamos aquí qué espera.
# {user_id: {"chat_id": int, "field": str, "expires_at": float}}
_pending_custom: dict[int, dict] = {}
_CUSTOM_TTL = 60.0  # segundos


# ============== Helper: verificar admin desde callback ==============
async def _check_admin_or_deny(cb: CallbackQuery, bot: Bot, chat_id: int) -> bool:
    if not cb.from_user:
        return False
    if not await is_admin(bot, chat_id, cb.from_user.id):
        await cb.answer("❌ Solo administradores.", show_alert=True)
        return False
    return True


async def _safe_edit(cb: CallbackQuery, text: str, markup) -> None:
    """edit_message_text con manejo del error 'message not modified'."""
    if cb.message is None:
        # Mensaje demasiado antiguo o inline mode (no soportado)
        await cb.answer("⚠️ Mensaje expirado. Vuelve a abrir /menu.", show_alert=True)
        return
    try:
        await cb.message.edit_text(text, reply_markup=markup)
    except TelegramBadRequest as e:
        if "message is not modified" in str(e).lower():
            return
        logger.debug("edit_message_text: %s", e)


# ============== m: menú principal ==============
@router.callback_query(F.data.startswith("m:"))
async def cb_main(cb: CallbackQuery, bot: Bot) -> None:
    chat_id = int(cb.data.split(":", 1)[1])
    if not await _check_admin_or_deny(cb, bot, chat_id):
        return
    cfg = await get_config(chat_id)
    await _safe_edit(cb, render_main_menu_text(cfg), main_menu(cfg))
    await cb.answer()


# ============== q: submenú cola ==============
@router.callback_query(F.data.startswith("q:"))
async def cb_queue(cb: CallbackQuery, bot: Bot) -> None:
    chat_id = int(cb.data.split(":", 1)[1])
    if not await _check_admin_or_deny(cb, bot, chat_id):
        return
    cfg = await get_config(chat_id)
    text = (
        "🔄 <b>Cola rotatoria</b>\n\n"
        f"Actual: <b>{cfg['queue_size']}</b> chicas\n\n"
        "Cuántas chicas DISTINTAS deben publicar antes de que una pueda repetir."
    )
    await _safe_edit(cb, text, queue_menu(chat_id, int(cfg["queue_size"])))
    await cb.answer()


@router.callback_query(F.data.startswith("qs:"))
async def cb_queue_set(cb: CallbackQuery, bot: Bot) -> None:
    parts = cb.data.split(":")
    chat_id, val = int(parts[1]), int(parts[2])
    if not await _check_admin_or_deny(cb, bot, chat_id):
        return
    if not (1 <= val <= 50):
        await cb.answer("Rango: 1-50", show_alert=True)
        return
    await update_config(chat_id, "queue_size", val)
    cfg = await get_config(chat_id)
    text = (
        "🔄 <b>Cola rotatoria</b>\n\n"
        f"Actual: <b>{cfg['queue_size']}</b> chicas"
    )
    await _safe_edit(cb, text, queue_menu(chat_id, val))
    await cb.answer(f"✅ Cola = {val}")


@router.callback_query(F.data.startswith("qc:"))
async def cb_queue_custom(cb: CallbackQuery, bot: Bot) -> None:
    chat_id = int(cb.data.split(":", 1)[1])
    if not await _check_admin_or_deny(cb, bot, chat_id):
        return
    _pending_custom[cb.from_user.id] = {
        "chat_id": chat_id, "field": "queue_size",
        "min": 1, "max": 50, "expires_at": time.time() + _CUSTOM_TTL,
    }
    await cb.answer(
        "✏️ Envíame un número del 1 al 50 (60s).", show_alert=True,
    )


# ============== cd: submenú cooldown ==============
@router.callback_query(F.data.startswith("cd:"))
async def cb_cooldown(cb: CallbackQuery, bot: Bot) -> None:
    chat_id = int(cb.data.split(":", 1)[1])
    if not await _check_admin_or_deny(cb, bot, chat_id):
        return
    cfg = await get_config(chat_id)
    text = (
        "⏱️ <b>Cooldown</b>\n\n"
        f"Actual: <b>{format_minutes(int(cfg['cooldown_minutes']))}</b>\n\n"
        "Tiempo mínimo entre publicaciones de la misma chica."
    )
    await _safe_edit(cb, text, cooldown_menu(chat_id, int(cfg["cooldown_minutes"])))
    await cb.answer()


@router.callback_query(F.data.startswith("cds:"))
async def cb_cooldown_set(cb: CallbackQuery, bot: Bot) -> None:
    parts = cb.data.split(":")
    chat_id, val = int(parts[1]), int(parts[2])
    if not await _check_admin_or_deny(cb, bot, chat_id):
        return
    if not (1 <= val <= 1440):
        await cb.answer("Rango: 1-1440 min", show_alert=True)
        return
    await update_config(chat_id, "cooldown_minutes", val)
    text = (
        "⏱️ <b>Cooldown</b>\n\n"
        f"Actual: <b>{format_minutes(val)}</b>"
    )
    await _safe_edit(cb, text, cooldown_menu(chat_id, val))
    await cb.answer(f"✅ Cooldown = {format_minutes(val)}")


@router.callback_query(F.data.startswith("cdc:"))
async def cb_cooldown_custom(cb: CallbackQuery, bot: Bot) -> None:
    chat_id = int(cb.data.split(":", 1)[1])
    if not await _check_admin_or_deny(cb, bot, chat_id):
        return
    _pending_custom[cb.from_user.id] = {
        "chat_id": chat_id, "field": "cooldown_minutes",
        "min": 1, "max": 1440, "expires_at": time.time() + _CUSTOM_TTL,
    }
    await cb.answer(
        "✏️ Envíame minutos (1-1440) en 60s.", show_alert=True,
    )


# ============== ad: submenú anti-duplicado ==============
@router.callback_query(F.data.startswith("ad:"))
async def cb_antidup(cb: CallbackQuery, bot: Bot) -> None:
    chat_id = int(cb.data.split(":", 1)[1])
    if not await _check_admin_or_deny(cb, bot, chat_id):
        return
    cfg = await get_config(chat_id)
    text = (
        "🖼️ <b>Anti-duplicado</b>\n\n"
        f"Ventana de detección: <b>{cfg['antidup_hours']}h</b>\n"
        f"Sensibilidad: <b>{cfg['phash_threshold']}</b>\n\n"
        "Detecta fotos/vídeos idénticos o casi idénticos publicados en las últimas horas."
    )
    await _safe_edit(cb, text, antidup_menu(chat_id, int(cfg["antidup_hours"])))
    await cb.answer()


@router.callback_query(F.data.startswith("ads:"))
async def cb_antidup_set(cb: CallbackQuery, bot: Bot) -> None:
    parts = cb.data.split(":")
    chat_id, val = int(parts[1]), int(parts[2])
    if not await _check_admin_or_deny(cb, bot, chat_id):
        return
    if not (1 <= val <= 168):
        await cb.answer("Rango: 1-168h", show_alert=True)
        return
    await update_config(chat_id, "antidup_hours", val)
    cfg = await get_config(chat_id)
    text = (
        "🖼️ <b>Anti-duplicado</b>\n\n"
        f"Ventana: <b>{val}h</b>\n"
        f"Sensibilidad: <b>{cfg['phash_threshold']}</b>"
    )
    await _safe_edit(cb, text, antidup_menu(chat_id, val))
    await cb.answer(f"✅ {val}h")


@router.callback_query(F.data.startswith("adc:"))
async def cb_antidup_custom(cb: CallbackQuery, bot: Bot) -> None:
    chat_id = int(cb.data.split(":", 1)[1])
    if not await _check_admin_or_deny(cb, bot, chat_id):
        return
    _pending_custom[cb.from_user.id] = {
        "chat_id": chat_id, "field": "antidup_hours",
        "min": 1, "max": 168, "expires_at": time.time() + _CUSTOM_TTL,
    }
    await cb.answer("✏️ Envíame horas (1-168) en 60s.", show_alert=True)


# ============== ph: sensibilidad pHash ==============
@router.callback_query(F.data.startswith("ph:"))
async def cb_phash(cb: CallbackQuery, bot: Bot) -> None:
    chat_id = int(cb.data.split(":", 1)[1])
    if not await _check_admin_or_deny(cb, bot, chat_id):
        return
    cfg = await get_config(chat_id)
    text = (
        "🎯 <b>Sensibilidad anti-duplicado</b>\n\n"
        f"Actual: <b>{cfg['phash_threshold']}</b>\n\n"
        "🔴 Estricta: solo detecta imágenes casi idénticas.\n"
        "🟢 Normal: recomendado.\n"
        "🟡 Tolerante: detecta más variaciones.\n"
        "🔵 Agresiva: también detecta recortes/filtros (puede dar falsos positivos)."
    )
    await _safe_edit(cb, text, phash_menu(chat_id, int(cfg["phash_threshold"])))
    await cb.answer()


@router.callback_query(F.data.startswith("phs:"))
async def cb_phash_set(cb: CallbackQuery, bot: Bot) -> None:
    parts = cb.data.split(":")
    chat_id, val = int(parts[1]), int(parts[2])
    if not await _check_admin_or_deny(cb, bot, chat_id):
        return
    await update_config(chat_id, "phash_threshold", val)
    cfg = await get_config(chat_id)
    await _safe_edit(
        cb,
        f"🎯 <b>Sensibilidad anti-duplicado</b>\n\nActual: <b>{val}</b>",
        phash_menu(chat_id, val),
    )
    await cb.answer(f"✅ Sensibilidad {val}")


# ============== al: alianzas ==============
@router.callback_query(F.data.startswith("al:"))
async def cb_alianzas(cb: CallbackQuery, bot: Bot) -> None:
    chat_id = int(cb.data.split(":", 1)[1])
    if not await _check_admin_or_deny(cb, bot, chat_id):
        return
    items = await alianzas_db.list_alianzas(chat_id)
    lines = ["👥 <b>Alianzas</b>", ""]
    if not items:
        lines.append("<i>No hay alianzas todavía.</i>")
    else:
        for a in items[:30]:
            lines.append(f"• {safe_username(a.get('username'), a['user_id'])}")
        if len(items) > 30:
            lines.append(f"<i>... y {len(items) - 30} más</i>")
    lines.append("")
    lines.append("Añade alianzas con <code>/freespam</code> en respuesta a la usuaria.")
    lines.append("Quítalas con <code>/unfreespam</code>.")
    await _safe_edit(cb, "\n".join(lines), alianzas_menu(chat_id, len(items)))
    await cb.answer()


@router.callback_query(F.data.startswith("alclr:"))
async def cb_alianzas_clear_confirm(cb: CallbackQuery, bot: Bot) -> None:
    chat_id = int(cb.data.split(":", 1)[1])
    if not await _check_admin_or_deny(cb, bot, chat_id):
        return
    await _safe_edit(
        cb,
        "⚠️ <b>¿Eliminar TODAS las alianzas?</b>\n\nEsta acción no se puede deshacer.",
        confirm_clear_alianzas(chat_id),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("alclrok:"))
async def cb_alianzas_clear_ok(cb: CallbackQuery, bot: Bot) -> None:
    chat_id = int(cb.data.split(":", 1)[1])
    if not await _check_admin_or_deny(cb, bot, chat_id):
        return
    n = await alianzas_db.clear_alianzas(chat_id)
    await cb.answer(f"🗑️ {n} alianzas eliminadas.", show_alert=True)
    # Redibujamos el submenú de alianzas
    await cb_alianzas(cb, bot)


# ============== st: estadísticas ==============
@router.callback_query(F.data.startswith("st:"))
async def cb_stats(cb: CallbackQuery, bot: Bot) -> None:
    chat_id = int(cb.data.split(":", 1)[1])
    if not await _check_admin_or_deny(cb, bot, chat_id):
        return
    s24 = await get_stats(chat_id, hours=24)
    s7d = await get_stats(chat_id, hours=24 * 7)
    top = await get_top_posters(chat_id, hours=24 * 7, limit=5)
    lines = [
        "📊 <b>Estadísticas</b>",
        "",
        "<b>Últimas 24h:</b>",
        f"  📸 {s24['total_posts']} publicaciones",
        f"  👤 {s24['distinct_users']} chicas distintas",
        f"  🚫 {s24['deletes']['queue']} borradas por cola",
        f"  🚫 {s24['deletes']['cooldown']} borradas por cooldown",
        f"  🚫 {s24['deletes']['antidup']} borradas por duplicado",
        "",
        "<b>Últimos 7 días:</b>",
        f"  📸 {s7d['total_posts']} publicaciones",
        f"  👤 {s7d['distinct_users']} chicas distintas",
    ]
    if top:
        lines.append("")
        lines.append("<b>Top publicadoras (7d):</b>")
        for t in top:
            mention = safe_username(t.get("username"), t["user_id"])
            lines.append(f"  • {mention}: {t['n']} posts")
    await _safe_edit(cb, "\n".join(lines), stats_menu(chat_id))
    await cb.answer()


# ============== pun: castigos ==============
@router.callback_query(F.data.startswith("pun:"))
async def cb_punishments(cb: CallbackQuery, bot: Bot) -> None:
    chat_id = int(cb.data.split(":", 1)[1])
    if not await _check_admin_or_deny(cb, bot, chat_id):
        return
    cfg = await get_config(chat_id)
    text = (
        "⚖️ <b>Castigos por regla</b>\n\n"
        "Cada regla tiene su propio castigo. Toca para configurar:"
    )
    await _safe_edit(cb, text, punishments_menu(cfg))
    await cb.answer()


async def _render_punishment_choice(cb: CallbackQuery, bot: Bot, rule_key: str) -> None:
    """rule_key ∈ {'punq', 'puncd', 'punad'}"""
    chat_id = int(cb.data.split(":", 1)[1])
    if not await _check_admin_or_deny(cb, bot, chat_id):
        return
    cfg = await get_config(chat_id)
    field_map = {"punq": "punishment_queue", "puncd": "punishment_cooldown", "punad": "punishment_antidup"}
    rule_label = {"punq": "Cola", "puncd": "Cooldown", "punad": "Anti-duplicado"}
    field = field_map[rule_key]
    current = int(cfg[field])
    emoji, label = PUNISHMENT_TYPES[current]
    text = (
        f"⚖️ <b>Castigo para {rule_label[rule_key]}</b>\n\n"
        f"Actual: {emoji} {label}\n\n"
        "Elige el castigo que se aplicará cuando se infrinja esta regla:"
    )
    await _safe_edit(cb, text, punishment_choice_menu(chat_id, rule_key, current))
    await cb.answer()


@router.callback_query(F.data.startswith("punq:"))
async def cb_pun_queue(cb: CallbackQuery, bot: Bot) -> None:
    await _render_punishment_choice(cb, bot, "punq")


@router.callback_query(F.data.startswith("puncd:"))
async def cb_pun_cooldown(cb: CallbackQuery, bot: Bot) -> None:
    await _render_punishment_choice(cb, bot, "puncd")


@router.callback_query(F.data.startswith("punad:"))
async def cb_pun_antidup(cb: CallbackQuery, bot: Bot) -> None:
    await _render_punishment_choice(cb, bot, "punad")


async def _set_punishment(cb: CallbackQuery, bot: Bot, field: str, rule_key: str) -> None:
    parts = cb.data.split(":")
    chat_id, val = int(parts[1]), int(parts[2])
    if not await _check_admin_or_deny(cb, bot, chat_id):
        return
    if val not in PUNISHMENT_TYPES:
        await cb.answer("Castigo inválido", show_alert=True)
        return
    await update_config(chat_id, field, val)
    emoji, label = PUNISHMENT_TYPES[val]
    await cb.answer(f"✅ {emoji} {label}")
    # Redibujamos el submenú de elección con el nuevo valor seleccionado
    cb.data = f"{rule_key}:{chat_id}"  # truco para reutilizar _render_punishment_choice
    await _render_punishment_choice(cb, bot, rule_key)


@router.callback_query(F.data.startswith("punqs:"))
async def cb_pun_queue_set(cb: CallbackQuery, bot: Bot) -> None:
    await _set_punishment(cb, bot, "punishment_queue", "punq")


@router.callback_query(F.data.startswith("puncds:"))
async def cb_pun_cooldown_set(cb: CallbackQuery, bot: Bot) -> None:
    await _set_punishment(cb, bot, "punishment_cooldown", "puncd")


@router.callback_query(F.data.startswith("punads:"))
async def cb_pun_antidup_set(cb: CallbackQuery, bot: Bot) -> None:
    await _set_punishment(cb, bot, "punishment_antidup", "punad")


# ============== nX: duración aviso autodestructivo ==============
async def _render_notice_duration(cb: CallbackQuery, bot: Bot, rule_key: str) -> None:
    """rule_key ∈ {'nq', 'ncd', 'nad'}"""
    chat_id = int(cb.data.split(":", 1)[1])
    if not await _check_admin_or_deny(cb, bot, chat_id):
        return
    cfg = await get_config(chat_id)
    field_map = {"nq": "notice_queue_seconds", "ncd": "notice_cooldown_seconds", "nad": "notice_antidup_seconds"}
    rule_label = {"nq": "Cola", "ncd": "Cooldown", "nad": "Duplicado"}
    field = field_map[rule_key]
    current = int(cfg[field])
    text = (
        f"⏲️ <b>Duración del aviso · {rule_label[rule_key]}</b>\n\n"
        f"Actual: <b>{current}s</b>\n\n"
        "El aviso se autodestruye tras este tiempo:"
    )
    await _safe_edit(cb, text, notice_duration_menu(chat_id, rule_key, current))
    await cb.answer()


@router.callback_query(F.data.startswith("nq:"))
async def cb_notice_queue(cb: CallbackQuery, bot: Bot) -> None:
    await _render_notice_duration(cb, bot, "nq")


@router.callback_query(F.data.startswith("ncd:"))
async def cb_notice_cd(cb: CallbackQuery, bot: Bot) -> None:
    await _render_notice_duration(cb, bot, "ncd")


@router.callback_query(F.data.startswith("nad:"))
async def cb_notice_ad(cb: CallbackQuery, bot: Bot) -> None:
    await _render_notice_duration(cb, bot, "nad")


async def _set_notice_duration(cb: CallbackQuery, bot: Bot, field: str, rule_key: str) -> None:
    parts = cb.data.split(":")
    chat_id, val = int(parts[1]), int(parts[2])
    if not await _check_admin_or_deny(cb, bot, chat_id):
        return
    if val not in NOTICE_DURATION_OPTIONS:
        await cb.answer("Valor inválido", show_alert=True)
        return
    await update_config(chat_id, field, val)
    await cb.answer(f"✅ {val}s")
    cb.data = f"{rule_key}:{chat_id}"
    await _render_notice_duration(cb, bot, rule_key)


@router.callback_query(F.data.startswith("nqs:"))
async def cb_notice_queue_set(cb: CallbackQuery, bot: Bot) -> None:
    await _set_notice_duration(cb, bot, "notice_queue_seconds", "nq")


@router.callback_query(F.data.startswith("ncds:"))
async def cb_notice_cd_set(cb: CallbackQuery, bot: Bot) -> None:
    await _set_notice_duration(cb, bot, "notice_cooldown_seconds", "ncd")


@router.callback_query(F.data.startswith("nads:"))
async def cb_notice_ad_set(cb: CallbackQuery, bot: Bot) -> None:
    await _set_notice_duration(cb, bot, "notice_antidup_seconds", "nad")


# ============== mX: duración mute ==============
async def _render_mute_duration(cb: CallbackQuery, bot: Bot, rule_key: str) -> None:
    """rule_key ∈ {'mq', 'mcd', 'mad'}"""
    chat_id = int(cb.data.split(":", 1)[1])
    if not await _check_admin_or_deny(cb, bot, chat_id):
        return
    cfg = await get_config(chat_id)
    field_map = {"mq": "mute_queue_seconds", "mcd": "mute_cooldown_seconds", "mad": "mute_antidup_seconds"}
    rule_label = {"mq": "Cola", "mcd": "Cooldown", "mad": "Duplicado"}
    field = field_map[rule_key]
    current = int(cfg[field])
    text = (
        f"⏲️ <b>Duración del mute · {rule_label[rule_key]}</b>\n\n"
        f"Actual: <b>{format_duration(current)}</b>"
    )
    await _safe_edit(cb, text, mute_duration_menu(chat_id, rule_key, current))
    await cb.answer()


@router.callback_query(F.data.startswith("mq:"))
async def cb_mute_queue(cb: CallbackQuery, bot: Bot) -> None:
    await _render_mute_duration(cb, bot, "mq")


@router.callback_query(F.data.startswith("mcd:"))
async def cb_mute_cd(cb: CallbackQuery, bot: Bot) -> None:
    await _render_mute_duration(cb, bot, "mcd")


@router.callback_query(F.data.startswith("mad:"))
async def cb_mute_ad(cb: CallbackQuery, bot: Bot) -> None:
    await _render_mute_duration(cb, bot, "mad")


async def _set_mute_duration(cb: CallbackQuery, bot: Bot, field: str, rule_key: str) -> None:
    parts = cb.data.split(":")
    chat_id, val = int(parts[1]), int(parts[2])
    if not await _check_admin_or_deny(cb, bot, chat_id):
        return
    valid = {v for v, _ in MUTE_DURATION_OPTIONS}
    if val not in valid:
        await cb.answer("Valor inválido", show_alert=True)
        return
    await update_config(chat_id, field, val)
    await cb.answer(f"✅ {format_duration(val)}")
    cb.data = f"{rule_key}:{chat_id}"
    await _render_mute_duration(cb, bot, rule_key)


@router.callback_query(F.data.startswith("mqs:"))
async def cb_mute_queue_set(cb: CallbackQuery, bot: Bot) -> None:
    await _set_mute_duration(cb, bot, "mute_queue_seconds", "mq")


@router.callback_query(F.data.startswith("mcds:"))
async def cb_mute_cd_set(cb: CallbackQuery, bot: Bot) -> None:
    await _set_mute_duration(cb, bot, "mute_cooldown_seconds", "mcd")


@router.callback_query(F.data.startswith("mads:"))
async def cb_mute_ad_set(cb: CallbackQuery, bot: Bot) -> None:
    await _set_mute_duration(cb, bot, "mute_antidup_seconds", "mad")


# ============== wn: warns ==============
@router.callback_query(F.data.startswith("wn:"))
async def cb_warns(cb: CallbackQuery, bot: Bot) -> None:
    chat_id = int(cb.data.split(":", 1)[1])
    if not await _check_admin_or_deny(cb, bot, chat_id):
        return
    cfg = await get_config(chat_id)
    final = PUNISHMENT_TYPES[int(cfg["warn_final_action"])]
    text = (
        "⚠️ <b>Sistema de warns</b>\n\n"
        f"📌 Límite: <b>{cfg['warn_limit']}</b> warns\n"
        f"📅 Expiración: <b>{cfg['warn_expiration_days']} días</b>\n"
        f"🚨 Acción final: <b>{final[0]} {final[1]}</b>\n"
    )
    if int(cfg["warn_final_action"]) == 4:
        text += f"   • Duración mute final: <b>{format_duration(int(cfg['warn_final_mute_seconds']))}</b>\n"
    text += "\nCuando una chica llega al límite de warns, se aplica la acción final automáticamente."
    await _safe_edit(cb, text, warns_menu(cfg))
    await cb.answer()


@router.callback_query(F.data.startswith("wnlim:"))
async def cb_warn_limit(cb: CallbackQuery, bot: Bot) -> None:
    parts = cb.data.split(":")
    chat_id, val = int(parts[1]), int(parts[2])
    if not await _check_admin_or_deny(cb, bot, chat_id):
        return
    if val == 0:
        # Solo mostrar selector
        cfg = await get_config(chat_id)
        await _safe_edit(
            cb,
            f"⚠️ <b>Límite de warns</b>\n\nActual: <b>{cfg['warn_limit']}</b>",
            warn_limit_menu(chat_id, int(cfg["warn_limit"])),
        )
        await cb.answer()
        return
    if val not in WARN_LIMIT_OPTIONS:
        await cb.answer("Valor inválido", show_alert=True)
        return
    await update_config(chat_id, "warn_limit", val)
    await cb.answer(f"✅ Límite = {val}")
    cb.data = f"wn:{chat_id}"
    await cb_warns(cb, bot)


@router.callback_query(F.data.startswith("wnexp:"))
async def cb_warn_exp(cb: CallbackQuery, bot: Bot) -> None:
    parts = cb.data.split(":")
    chat_id, val = int(parts[1]), int(parts[2])
    if not await _check_admin_or_deny(cb, bot, chat_id):
        return
    if val == 0:
        cfg = await get_config(chat_id)
        await _safe_edit(
            cb,
            f"📅 <b>Expiración de warns</b>\n\nActual: <b>{cfg['warn_expiration_days']} días</b>",
            warn_expiration_menu(chat_id, int(cfg["warn_expiration_days"])),
        )
        await cb.answer()
        return
    if val not in WARN_EXPIRATION_OPTIONS:
        await cb.answer("Valor inválido", show_alert=True)
        return
    await update_config(chat_id, "warn_expiration_days", val)
    await cb.answer(f"✅ {val} días")
    cb.data = f"wn:{chat_id}"
    await cb_warns(cb, bot)


@router.callback_query(F.data.startswith("wnfin:"))
async def cb_warn_final(cb: CallbackQuery, bot: Bot) -> None:
    parts = cb.data.split(":")
    chat_id, val = int(parts[1]), int(parts[2])
    if not await _check_admin_or_deny(cb, bot, chat_id):
        return
    if val == 0:
        cfg = await get_config(chat_id)
        await _safe_edit(
            cb,
            "🚨 <b>Acción final al alcanzar el límite</b>\n\n"
            f"Actual: <b>{PUNISHMENT_TYPES[int(cfg['warn_final_action'])][1]}</b>",
            warn_final_menu(chat_id, int(cfg["warn_final_action"])),
        )
        await cb.answer()
        return
    if val not in (4, 5, 6):
        await cb.answer("Valor inválido", show_alert=True)
        return
    await update_config(chat_id, "warn_final_action", val)
    await cb.answer(f"✅ {PUNISHMENT_TYPES[val][1]}")
    cb.data = f"wn:{chat_id}"
    await cb_warns(cb, bot)


@router.callback_query(F.data.startswith("wnfmute:"))
async def cb_warn_final_mute(cb: CallbackQuery, bot: Bot) -> None:
    """Duración del mute cuando la acción final del sistema de warns es mute."""
    parts = cb.data.split(":")
    chat_id, val = int(parts[1]), int(parts[2])
    if not await _check_admin_or_deny(cb, bot, chat_id):
        return
    if val == 0:
        cfg = await get_config(chat_id)
        text = (
            "⏲️ <b>Duración del mute final</b>\n\n"
            f"Actual: <b>{format_duration(int(cfg['warn_final_mute_seconds']))}</b>\n\n"
            "Cuando una chica alcanza el límite de warns, será silenciada "
            "durante este tiempo."
        )
        await _safe_edit(
            cb,
            text,
            warn_final_mute_menu(chat_id, int(cfg["warn_final_mute_seconds"])),
        )
        await cb.answer()
        return
    valid = {v for v, _ in MUTE_DURATION_OPTIONS}
    if val not in valid:
        await cb.answer("Valor inválido", show_alert=True)
        return
    await update_config(chat_id, "warn_final_mute_seconds", val)
    await cb.answer(f"✅ {format_duration(val)}")
    cb.data = f"wn:{chat_id}"
    await cb_warns(cb, bot)


# ============== adv: opciones avanzadas ==============
@router.callback_query(F.data.startswith("adv:"))
async def cb_advanced(cb: CallbackQuery, bot: Bot) -> None:
    chat_id = int(cb.data.split(":", 1)[1])
    if not await _check_admin_or_deny(cb, bot, chat_id):
        return
    cfg = await get_config(chat_id)
    text = (
        "⚙️ <b>Opciones avanzadas</b>\n\n"
        f"🔒 Menú solo para admins: {'✅' if cfg['admin_only_menu'] else '❌'}\n"
        f"🤫 Modo silencio (sin avisos): {'✅' if cfg['silence_mode'] else '❌'}\n"
        f"🗂️ Auto-limpieza: cada {cfg['autoclean_days']} días\n"
    )
    await _safe_edit(cb, text, advanced_menu(cfg))
    await cb.answer()


@router.callback_query(F.data.startswith("advt:"))
async def cb_advanced_toggle(cb: CallbackQuery, bot: Bot) -> None:
    parts = cb.data.split(":")
    chat_id, field = int(parts[1]), parts[2]
    if not await _check_admin_or_deny(cb, bot, chat_id):
        return
    if field not in ("admin_only_menu", "silence_mode"):
        await cb.answer("Campo inválido", show_alert=True)
        return
    cfg = await get_config(chat_id)
    new_val = 0 if int(cfg[field]) else 1
    await update_config(chat_id, field, new_val)
    await cb.answer("✅" if new_val else "❌")
    cb.data = f"adv:{chat_id}"
    await cb_advanced(cb, bot)


@router.callback_query(F.data.startswith("advac:"))
async def cb_autoclean(cb: CallbackQuery, bot: Bot) -> None:
    chat_id = int(cb.data.split(":", 1)[1])
    if not await _check_admin_or_deny(cb, bot, chat_id):
        return
    cfg = await get_config(chat_id)
    text = (
        "🗂️ <b>Auto-limpieza de BD</b>\n\n"
        f"Actual: cada <b>{cfg['autoclean_days']} días</b>\n\n"
        "Borra publicaciones antiguas para mantener la BD ligera. "
        "No afecta a la cola actual."
    )
    await _safe_edit(cb, text, autoclean_menu(chat_id, int(cfg["autoclean_days"])))
    await cb.answer()


@router.callback_query(F.data.startswith("advacs:"))
async def cb_autoclean_set(cb: CallbackQuery, bot: Bot) -> None:
    parts = cb.data.split(":")
    chat_id, val = int(parts[1]), int(parts[2])
    if not await _check_admin_or_deny(cb, bot, chat_id):
        return
    if val not in AUTOCLEAN_OPTIONS:
        await cb.answer("Valor inválido", show_alert=True)
        return
    await update_config(chat_id, "autoclean_days", val)
    await cb.answer(f"✅ {val}d")
    cb.data = f"advac:{chat_id}"
    await cb_autoclean(cb, bot)


# ============== Reset cola actual ==============
@router.callback_query(F.data.startswith("rstq:"))
async def cb_reset_queue(cb: CallbackQuery, bot: Bot) -> None:
    chat_id = int(cb.data.split(":", 1)[1])
    if not await _check_admin_or_deny(cb, bot, chat_id):
        return
    await _safe_edit(
        cb,
        "🔄 <b>¿Vaciar la cola actual?</b>\n\n"
        "Esto borrará el registro de las últimas publicaciones.\n"
        "Todas las chicas podrán publicar inmediatamente.",
        confirm_reset_queue(chat_id),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("rstqok:"))
async def cb_reset_queue_ok(cb: CallbackQuery, bot: Bot) -> None:
    chat_id = int(cb.data.split(":", 1)[1])
    if not await _check_admin_or_deny(cb, bot, chat_id):
        return
    n = await posts_db.reset_queue(chat_id)
    await cb.answer(f"🔄 Cola vaciada ({n} registros).", show_alert=True)
    cb.data = f"adv:{chat_id}"
    await cb_advanced(cb, bot)


# ============== Reset config ==============
@router.callback_query(F.data.startswith("reset:"))
async def cb_reset(cb: CallbackQuery, bot: Bot) -> None:
    chat_id = int(cb.data.split(":", 1)[1])
    if not await _check_admin_or_deny(cb, bot, chat_id):
        return
    await _safe_edit(
        cb,
        "⚠️ <b>¿Restaurar TODOS los valores a los defaults?</b>\n\n"
        "Reglas, castigos, avisos, warns... todo vuelve a sus valores recomendados.\n"
        "Las alianzas y la cola actual NO se borran.",
        confirm_reset_config(chat_id),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("resetok:"))
async def cb_reset_ok(cb: CallbackQuery, bot: Bot) -> None:
    chat_id = int(cb.data.split(":", 1)[1])
    if not await _check_admin_or_deny(cb, bot, chat_id):
        return
    await reset_to_defaults(chat_id)
    await cb.answer("✅ Defaults restaurados.", show_alert=True)
    cfg = await get_config(chat_id)
    await _safe_edit(cb, render_main_menu_text(cfg), main_menu(cfg))


# ============== Selector de grupo (desde privado) ==============
@router.callback_query(F.data.startswith("selg:"))
async def cb_select_group(cb: CallbackQuery, bot: Bot) -> None:
    chat_id = int(cb.data.split(":", 1)[1])
    if not cb.from_user:
        return
    if not await is_admin(bot, chat_id, cb.from_user.id):
        await cb.answer("❌ Ya no eres admin de ese grupo.", show_alert=True)
        return
    cfg = await get_config(chat_id)
    await _safe_edit(cb, render_main_menu_text(cfg), main_menu(cfg))
    await cb.answer()


# ============== Cerrar ==============
@router.callback_query(F.data == "cls")
async def cb_close(cb: CallbackQuery) -> None:
    if cb.message is not None:
        try:
            await cb.message.delete()
        except TelegramBadRequest:
            pass
    await cb.answer()


# ============== Captura de valores personalizados ==============
@router.message(F.text.regexp(r"^\d+$"))
async def handle_custom_value(message: Message) -> None:
    """Captura números enviados tras pulsar 'Valor personalizado'."""
    if not message.from_user:
        return
    pending = _pending_custom.get(message.from_user.id)
    if not pending:
        return
    if time.time() > pending["expires_at"]:
        _pending_custom.pop(message.from_user.id, None)
        await message.reply("⌛ El tiempo para enviar el valor expiró. Vuelve a abrir el menú.")
        return
    try:
        val = int(message.text)
    except ValueError:
        return
    if not (pending["min"] <= val <= pending["max"]):
        await message.reply(
            f"❌ Valor fuera de rango. Permitido: {pending['min']}–{pending['max']}."
        )
        return
    chat_id = pending["chat_id"]
    field = pending["field"]
    await update_config(chat_id, field, val)
    _pending_custom.pop(message.from_user.id, None)
    await message.reply(f"✅ Valor actualizado a <b>{val}</b>. Vuelve al menú para verlo.")
