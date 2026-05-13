"""
Manejadores de todos los callback_query (botones inline).

Cobertura:
- Menú principal y reglas (queue/cooldown/antidup + sus toggles enabled)
- Castigos (con duración aviso/mute)
- Warns
- Avanzadas (incluido borrar mensajes de servicio)
- Filtros de tipos de contenido (estilo GroupHelp)
- Alianzas (limpiar)
- Stats (refrescar)
- Reset
- Lock toggle
- Ayuda
- Selector de grupo en privado
- Panel /admin del owner: dashboard, listas filtradas, acciones de licencia
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
    FILTER_ACTIONS,
    FILTER_TYPES,
    MUTE_DURATION_OPTIONS,
    NOTICE_DURATION_OPTIONS,
    OWNER_USERNAME,
    PHASH_OPTIONS,
    PUNISHMENT_TYPES,
    QUEUE_OPTIONS,
    WARN_EXPIRATION_OPTIONS,
    WARN_LIMIT_OPTIONS,
)
from database import alianzas as alianzas_db
from database import licenses as licenses_db
from database import posts as posts_db
from database.config_db import get_config, reset_to_defaults, update_config
from database.stats import get_recent_logs, get_stats, get_top_posters
from handlers.menu import render_main_menu_text
from keyboards.admin_builders import (
    admin_main_menu,
    license_actions_menu,
    license_list_menu,
)
from keyboards.builders import (
    advanced_menu,
    alianzas_menu,
    antidup_menu,
    autoclean_menu,
    confirm_clear_alianzas,
    confirm_reset_config,
    confirm_reset_queue,
    cooldown_menu,
    filter_action_menu,
    filter_main_menu,
    help_menu_keyboard,
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
from utils.license_helpers import (
    chat_is_allowed,
    format_license_status,
    is_owner,
    subscription_pitch,
)
from utils.permissions import is_admin

logger = logging.getLogger(__name__)
router = Router(name="callbacks")


# === Estado para valores personalizados ===
_pending_custom: dict[int, dict] = {}
_CUSTOM_TTL = 60.0


async def _check_admin_or_deny(cb: CallbackQuery, bot: Bot, chat_id: int) -> bool:
    if not cb.from_user:
        return False
    if not await is_admin(bot, chat_id, cb.from_user.id):
        await cb.answer("❌ Solo administradores.", show_alert=True)
        return False
    return True


async def _check_license_or_deny(cb: CallbackQuery, chat_id: int) -> bool:
    """Bloquea callbacks de configuración en chats no licenciados."""
    if await chat_is_allowed(chat_id):
        return True
    await cb.answer(
        f"⚠️ Suscripción no activa. Contacta @{OWNER_USERNAME}",
        show_alert=True,
    )
    return False


async def _safe_edit(cb: CallbackQuery, text: str, reply_markup=None) -> None:
    try:
        await cb.message.edit_text(
            text, reply_markup=reply_markup, disable_web_page_preview=True,
        )
    except TelegramBadRequest as e:
        if "message is not modified" in str(e).lower():
            return
        logger.debug("edit_text falló (%s), intentando reenviar", e)
        try:
            await cb.message.answer(text, reply_markup=reply_markup)
        except TelegramBadRequest as e2:
            logger.warning("No se pudo reenviar el mensaje: %s", e2)


# === MENÚ PRINCIPAL ===
@router.callback_query(F.data.startswith("m:"))
async def cb_main(cb: CallbackQuery, bot: Bot) -> None:
    chat_id = int(cb.data.split(":")[1])
    if not await _check_admin_or_deny(cb, bot, chat_id):
        return
    if not await _check_license_or_deny(cb, chat_id):
        return
    cfg = await get_config(chat_id)
    text = await render_main_menu_text(bot, chat_id, cfg)
    await _safe_edit(cb, text, main_menu(cfg))
    await cb.answer()


# === COLA ===
@router.callback_query(F.data.startswith("q:"))
async def cb_queue(cb: CallbackQuery, bot: Bot) -> None:
    chat_id = int(cb.data.split(":")[1])
    if not await _check_admin_or_deny(cb, bot, chat_id):
        return
    cfg = await get_config(chat_id)
    text = _menu_text_queue(cfg)
    await _safe_edit(cb, text, queue_menu(chat_id, int(cfg["queue_size"]), bool(int(cfg.get("queue_enabled", 1)))))
    await cb.answer()


@router.callback_query(F.data.startswith("qs:"))
async def cb_queue_set(cb: CallbackQuery, bot: Bot) -> None:
    parts = cb.data.split(":")
    chat_id, value = int(parts[1]), int(parts[2])
    if not await _check_admin_or_deny(cb, bot, chat_id):
        return
    await update_config(chat_id, "queue_size", value)
    cfg = await get_config(chat_id)
    await _safe_edit(cb, _menu_text_queue(cfg), queue_menu(chat_id, value, bool(int(cfg.get("queue_enabled", 1)))))
    await cb.answer(f"✅ Cola: {value} chicas")


@router.callback_query(F.data.startswith("qen:"))
async def cb_queue_toggle(cb: CallbackQuery, bot: Bot) -> None:
    chat_id = int(cb.data.split(":")[1])
    if not await _check_admin_or_deny(cb, bot, chat_id):
        return
    cfg = await get_config(chat_id)
    new_value = 0 if int(cfg.get("queue_enabled", 1)) else 1
    await update_config(chat_id, "queue_enabled", new_value)
    cfg = await get_config(chat_id)
    await _safe_edit(cb, _menu_text_queue(cfg), queue_menu(chat_id, int(cfg["queue_size"]), bool(new_value)))
    await cb.answer("✅ Activada" if new_value else "❌ Desactivada")


@router.callback_query(F.data.startswith("qc:"))
async def cb_queue_custom(cb: CallbackQuery, bot: Bot) -> None:
    chat_id = int(cb.data.split(":")[1])
    if not await _check_admin_or_deny(cb, bot, chat_id):
        return
    _pending_custom[cb.from_user.id] = {
        "chat_id": chat_id, "field": "queue_size",
        "expires_at": time.time() + _CUSTOM_TTL, "min": 1, "max": 50,
    }
    await cb.answer(
        "✏️ Envía aquí un número entre 1 y 50 (tienes 60s).",
        show_alert=True,
    )


# === COOLDOWN ===
@router.callback_query(F.data.startswith("cd:"))
async def cb_cooldown(cb: CallbackQuery, bot: Bot) -> None:
    chat_id = int(cb.data.split(":")[1])
    if not await _check_admin_or_deny(cb, bot, chat_id):
        return
    cfg = await get_config(chat_id)
    await _safe_edit(
        cb, _menu_text_cooldown(cfg),
        cooldown_menu(chat_id, int(cfg["cooldown_minutes"]), bool(int(cfg.get("cooldown_enabled", 1)))),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("cds:"))
async def cb_cooldown_set(cb: CallbackQuery, bot: Bot) -> None:
    parts = cb.data.split(":")
    chat_id, value = int(parts[1]), int(parts[2])
    if not await _check_admin_or_deny(cb, bot, chat_id):
        return
    await update_config(chat_id, "cooldown_minutes", value)
    cfg = await get_config(chat_id)
    await _safe_edit(
        cb, _menu_text_cooldown(cfg),
        cooldown_menu(chat_id, value, bool(int(cfg.get("cooldown_enabled", 1)))),
    )
    await cb.answer(f"✅ Cooldown: {format_minutes(value)}")


@router.callback_query(F.data.startswith("cden:"))
async def cb_cooldown_toggle(cb: CallbackQuery, bot: Bot) -> None:
    chat_id = int(cb.data.split(":")[1])
    if not await _check_admin_or_deny(cb, bot, chat_id):
        return
    cfg = await get_config(chat_id)
    new_value = 0 if int(cfg.get("cooldown_enabled", 1)) else 1
    await update_config(chat_id, "cooldown_enabled", new_value)
    cfg = await get_config(chat_id)
    await _safe_edit(
        cb, _menu_text_cooldown(cfg),
        cooldown_menu(chat_id, int(cfg["cooldown_minutes"]), bool(new_value)),
    )
    await cb.answer("✅ Activado" if new_value else "❌ Desactivado")


@router.callback_query(F.data.startswith("cdc:"))
async def cb_cooldown_custom(cb: CallbackQuery, bot: Bot) -> None:
    chat_id = int(cb.data.split(":")[1])
    if not await _check_admin_or_deny(cb, bot, chat_id):
        return
    _pending_custom[cb.from_user.id] = {
        "chat_id": chat_id, "field": "cooldown_minutes",
        "expires_at": time.time() + _CUSTOM_TTL, "min": 1, "max": 1440,
    }
    await cb.answer(
        "✏️ Envía aquí un número de minutos (1-1440). Tienes 60s.",
        show_alert=True,
    )


# === ANTIDUP ===
@router.callback_query(F.data.startswith("ad:"))
async def cb_antidup(cb: CallbackQuery, bot: Bot) -> None:
    chat_id = int(cb.data.split(":")[1])
    if not await _check_admin_or_deny(cb, bot, chat_id):
        return
    cfg = await get_config(chat_id)
    await _safe_edit(
        cb, _menu_text_antidup(cfg),
        antidup_menu(chat_id, int(cfg["antidup_hours"]), bool(int(cfg.get("antidup_enabled", 1)))),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("ads:"))
async def cb_antidup_set(cb: CallbackQuery, bot: Bot) -> None:
    parts = cb.data.split(":")
    chat_id, value = int(parts[1]), int(parts[2])
    if not await _check_admin_or_deny(cb, bot, chat_id):
        return
    await update_config(chat_id, "antidup_hours", value)
    cfg = await get_config(chat_id)
    await _safe_edit(
        cb, _menu_text_antidup(cfg),
        antidup_menu(chat_id, value, bool(int(cfg.get("antidup_enabled", 1)))),
    )
    await cb.answer(f"✅ Antidup: {value}h")


@router.callback_query(F.data.startswith("aden:"))
async def cb_antidup_toggle(cb: CallbackQuery, bot: Bot) -> None:
    chat_id = int(cb.data.split(":")[1])
    if not await _check_admin_or_deny(cb, bot, chat_id):
        return
    cfg = await get_config(chat_id)
    new_value = 0 if int(cfg.get("antidup_enabled", 1)) else 1
    await update_config(chat_id, "antidup_enabled", new_value)
    cfg = await get_config(chat_id)
    await _safe_edit(
        cb, _menu_text_antidup(cfg),
        antidup_menu(chat_id, int(cfg["antidup_hours"]), bool(new_value)),
    )
    await cb.answer("✅ Activado" if new_value else "❌ Desactivado")


@router.callback_query(F.data.startswith("adc:"))
async def cb_antidup_custom(cb: CallbackQuery, bot: Bot) -> None:
    chat_id = int(cb.data.split(":")[1])
    if not await _check_admin_or_deny(cb, bot, chat_id):
        return
    _pending_custom[cb.from_user.id] = {
        "chat_id": chat_id, "field": "antidup_hours",
        "expires_at": time.time() + _CUSTOM_TTL, "min": 1, "max": 168,
    }
    await cb.answer(
        "✏️ Envía aquí un número de horas (1-168). Tienes 60s.",
        show_alert=True,
    )


# === PHASH ===
@router.callback_query(F.data.startswith("ph:"))
async def cb_phash(cb: CallbackQuery, bot: Bot) -> None:
    chat_id = int(cb.data.split(":")[1])
    if not await _check_admin_or_deny(cb, bot, chat_id):
        return
    cfg = await get_config(chat_id)
    text = (
        "🎯 <b>Sensibilidad anti-duplicado</b>\n\n"
        "🔴 Estricta: rechaza casi cualquier parecido.\n"
        "🟢 Normal: equilibrado (recomendado).\n"
        "🟡 Tolerante: solo duplicados muy obvios.\n"
        "🔵 Agresiva: solo idénticas.\n\n"
        "Valores menores = más estricto."
    )
    await _safe_edit(cb, text, phash_menu(chat_id, int(cfg["phash_threshold"])))
    await cb.answer()


@router.callback_query(F.data.startswith("phs:"))
async def cb_phash_set(cb: CallbackQuery, bot: Bot) -> None:
    parts = cb.data.split(":")
    chat_id, value = int(parts[1]), int(parts[2])
    if not await _check_admin_or_deny(cb, bot, chat_id):
        return
    await update_config(chat_id, "phash_threshold", value)
    await cb.answer(f"✅ Sensibilidad: {value}")
    cfg = await get_config(chat_id)
    await _safe_edit(
        cb, _menu_text_antidup(cfg),
        antidup_menu(chat_id, int(cfg["antidup_hours"]), bool(int(cfg.get("antidup_enabled", 1)))),
    )


# === CASTIGOS ===
@router.callback_query(F.data.startswith("pun:"))
async def cb_punishments(cb: CallbackQuery, bot: Bot) -> None:
    chat_id = int(cb.data.split(":")[1])
    if not await _check_admin_or_deny(cb, bot, chat_id):
        return
    cfg = await get_config(chat_id)
    text = (
        "⚖️ <b>Castigos por regla</b>\n\n"
        "Elige qué hace el bot cuando alguien rompe cada regla.\n\n"
        "🟢 Solo borrar · sin notificación\n"
        "🟢 Borrar + aviso · mensaje autodestructivo\n"
        "🟡 Borrar + warn · acumula advertencia\n"
        "🟠 Borrar + mute · silencia temporalmente\n"
        "🔴 Borrar + kick · expulsa (puede volver)\n"
        "⚫ Borrar + ban · banea permanente"
    )
    await _safe_edit(cb, text, punishments_menu(cfg))
    await cb.answer()


@router.callback_query(F.data.startswith("punq:") | F.data.startswith("puncd:") | F.data.startswith("punad:"))
async def cb_punishment_open(cb: CallbackQuery, bot: Bot) -> None:
    parts = cb.data.split(":")
    rule_key, chat_id = parts[0], int(parts[1])
    if not await _check_admin_or_deny(cb, bot, chat_id):
        return
    cfg = await get_config(chat_id)
    field = {"punq": "punishment_queue", "puncd": "punishment_cooldown", "punad": "punishment_antidup"}[rule_key]
    label = {"punq": "🔄 Cola rotatoria", "puncd": "⏱️ Cooldown", "punad": "🖼️ Anti-duplicado"}[rule_key]
    text = f"⚖️ <b>Castigo para {label}</b>\n\nElige la acción cuando se rompe esta regla:"
    await _safe_edit(cb, text, punishment_choice_menu(chat_id, rule_key, int(cfg[field])))
    await cb.answer()


@router.callback_query(F.data.startswith("punqs:") | F.data.startswith("puncds:") | F.data.startswith("punads:"))
async def cb_punishment_set(cb: CallbackQuery, bot: Bot) -> None:
    parts = cb.data.split(":")
    rule_key = parts[0][:-1]  # quitar 's' final
    chat_id, value = int(parts[1]), int(parts[2])
    if not await _check_admin_or_deny(cb, bot, chat_id):
        return
    field = {"punq": "punishment_queue", "puncd": "punishment_cooldown", "punad": "punishment_antidup"}[rule_key]
    await update_config(chat_id, field, value)
    emoji, label = PUNISHMENT_TYPES[value]
    cfg = await get_config(chat_id)
    label_rule = {"punq": "🔄 Cola", "puncd": "⏱️ Cooldown", "punad": "🖼️ Antidup"}[rule_key]
    text = f"⚖️ <b>Castigo para {label_rule}</b>\n\nAhora: {emoji} <b>{label}</b>"
    await _safe_edit(cb, text, punishment_choice_menu(chat_id, rule_key, value))
    await cb.answer(f"✅ {label}")


@router.callback_query(F.data.startswith("nq:") | F.data.startswith("ncd:") | F.data.startswith("nad:"))
async def cb_notice_open(cb: CallbackQuery, bot: Bot) -> None:
    parts = cb.data.split(":")
    rule_key, chat_id = parts[0], int(parts[1])
    if not await _check_admin_or_deny(cb, bot, chat_id):
        return
    cfg = await get_config(chat_id)
    field = {"nq": "notice_queue_seconds", "ncd": "notice_cooldown_seconds", "nad": "notice_antidup_seconds"}[rule_key]
    text = "⏲️ <b>Duración del aviso</b>\n\nTras cuántos segundos se autodestruye el mensaje de aviso."
    await _safe_edit(cb, text, notice_duration_menu(chat_id, rule_key, int(cfg[field])))
    await cb.answer()


@router.callback_query(F.data.startswith("nqs:") | F.data.startswith("ncds:") | F.data.startswith("nads:"))
async def cb_notice_set(cb: CallbackQuery, bot: Bot) -> None:
    parts = cb.data.split(":")
    setter, chat_id, value = parts[0], int(parts[1]), int(parts[2])
    if not await _check_admin_or_deny(cb, bot, chat_id):
        return
    field = {"nqs": "notice_queue_seconds", "ncds": "notice_cooldown_seconds", "nads": "notice_antidup_seconds"}[setter]
    await update_config(chat_id, field, value)
    cfg = await get_config(chat_id)
    rule_key = setter[:-1]
    await _safe_edit(cb, "⏲️ <b>Duración del aviso</b>", notice_duration_menu(chat_id, rule_key, value))
    await cb.answer(f"✅ {value}s")


@router.callback_query(F.data.startswith("mq:") | F.data.startswith("mcd:") | F.data.startswith("mad:"))
async def cb_mute_open(cb: CallbackQuery, bot: Bot) -> None:
    parts = cb.data.split(":")
    rule_key, chat_id = parts[0], int(parts[1])
    if not await _check_admin_or_deny(cb, bot, chat_id):
        return
    cfg = await get_config(chat_id)
    field = {"mq": "mute_queue_seconds", "mcd": "mute_cooldown_seconds", "mad": "mute_antidup_seconds"}[rule_key]
    text = "⏲️ <b>Duración del mute</b>\n\nCuánto tiempo se silencia tras romper esta regla."
    await _safe_edit(cb, text, mute_duration_menu(chat_id, rule_key, int(cfg[field])))
    await cb.answer()


@router.callback_query(F.data.startswith("mqs:") | F.data.startswith("mcds:") | F.data.startswith("mads:"))
async def cb_mute_set(cb: CallbackQuery, bot: Bot) -> None:
    parts = cb.data.split(":")
    setter, chat_id, value = parts[0], int(parts[1]), int(parts[2])
    if not await _check_admin_or_deny(cb, bot, chat_id):
        return
    field = {"mqs": "mute_queue_seconds", "mcds": "mute_cooldown_seconds", "mads": "mute_antidup_seconds"}[setter]
    await update_config(chat_id, field, value)
    cfg = await get_config(chat_id)
    rule_key = setter[:-1]
    await _safe_edit(cb, "⏲️ <b>Duración del mute</b>", mute_duration_menu(chat_id, rule_key, value))
    await cb.answer(f"✅ {format_duration(value)}")


# === WARNS ===
@router.callback_query(F.data.startswith("wn:"))
async def cb_warns(cb: CallbackQuery, bot: Bot) -> None:
    chat_id = int(cb.data.split(":")[1])
    if not await _check_admin_or_deny(cb, bot, chat_id):
        return
    cfg = await get_config(chat_id)
    text = (
        "⚠️ <b>Sistema de warns</b>\n\n"
        f"• Límite: <b>{cfg['warn_limit']}</b> warns\n"
        f"• Expiración: <b>{cfg['warn_expiration_days']}</b> días\n"
        f"• Acción al alcanzar el límite: "
        f"{PUNISHMENT_TYPES[int(cfg['warn_final_action'])][0]} "
        f"<b>{PUNISHMENT_TYPES[int(cfg['warn_final_action'])][1]}</b>\n\n"
        "Al alcanzar el límite, los warns activos se reinician."
    )
    await _safe_edit(cb, text, warns_menu(cfg))
    await cb.answer()


@router.callback_query(F.data.startswith("wnlim:"))
async def cb_warn_limit(cb: CallbackQuery, bot: Bot) -> None:
    parts = cb.data.split(":")
    chat_id, value = int(parts[1]), int(parts[2])
    if not await _check_admin_or_deny(cb, bot, chat_id):
        return
    if value == 0:
        cfg = await get_config(chat_id)
        await _safe_edit(cb, "⚠️ <b>Límite de warns</b>", warn_limit_menu(chat_id, int(cfg["warn_limit"])))
    else:
        await update_config(chat_id, "warn_limit", value)
        await _safe_edit(cb, "⚠️ <b>Límite de warns</b>", warn_limit_menu(chat_id, value))
        await cb.answer(f"✅ Límite: {value}")
        return
    await cb.answer()


@router.callback_query(F.data.startswith("wnexp:"))
async def cb_warn_exp(cb: CallbackQuery, bot: Bot) -> None:
    parts = cb.data.split(":")
    chat_id, value = int(parts[1]), int(parts[2])
    if not await _check_admin_or_deny(cb, bot, chat_id):
        return
    if value == 0:
        cfg = await get_config(chat_id)
        await _safe_edit(cb, "📅 <b>Expiración de warns</b>", warn_expiration_menu(chat_id, int(cfg["warn_expiration_days"])))
    else:
        await update_config(chat_id, "warn_expiration_days", value)
        await _safe_edit(cb, "📅 <b>Expiración de warns</b>", warn_expiration_menu(chat_id, value))
        await cb.answer(f"✅ {value}d")
        return
    await cb.answer()


@router.callback_query(F.data.startswith("wnfin:"))
async def cb_warn_final(cb: CallbackQuery, bot: Bot) -> None:
    parts = cb.data.split(":")
    chat_id, value = int(parts[1]), int(parts[2])
    if not await _check_admin_or_deny(cb, bot, chat_id):
        return
    if value == 0:
        cfg = await get_config(chat_id)
        await _safe_edit(cb, "🚨 <b>Acción al alcanzar el límite</b>", warn_final_menu(chat_id, int(cfg["warn_final_action"])))
    else:
        await update_config(chat_id, "warn_final_action", value)
        await _safe_edit(cb, "🚨 <b>Acción al alcanzar el límite</b>", warn_final_menu(chat_id, value))
        await cb.answer(f"✅ {PUNISHMENT_TYPES[value][1]}")
        return
    await cb.answer()


@router.callback_query(F.data.startswith("wnfmute:"))
async def cb_warn_final_mute(cb: CallbackQuery, bot: Bot) -> None:
    parts = cb.data.split(":")
    chat_id, value = int(parts[1]), int(parts[2])
    if not await _check_admin_or_deny(cb, bot, chat_id):
        return
    if value == 0:
        cfg = await get_config(chat_id)
        await _safe_edit(cb, "⏲️ <b>Duración del mute final</b>",
                         warn_final_mute_menu(chat_id, int(cfg["warn_final_mute_seconds"])))
    else:
        await update_config(chat_id, "warn_final_mute_seconds", value)
        await _safe_edit(cb, "⏲️ <b>Duración del mute final</b>",
                         warn_final_mute_menu(chat_id, value))
        await cb.answer(f"✅ {format_duration(value)}")
        return
    await cb.answer()


# === ALIANZAS (menú) ===
@router.callback_query(F.data.startswith("al:"))
async def cb_alianzas(cb: CallbackQuery, bot: Bot) -> None:
    chat_id = int(cb.data.split(":")[1])
    if not await _check_admin_or_deny(cb, bot, chat_id):
        return
    items = await alianzas_db.list_alianzas(chat_id)
    text = ["👥 <b>Alianzas</b>", ""]
    if items:
        for a in items[:20]:
            text.append(f"• {safe_username(a.get('username'), a['user_id'])}")
        if len(items) > 20:
            text.append(f"<i>... y {len(items) - 20} más</i>")
        text.append("")
        text.append(f"Total: <b>{len(items)}</b>")
    else:
        text.append("<i>No hay alianzas todavía.</i>")
    text.append("")
    text.append("Usa /freespam para añadir.")
    await _safe_edit(cb, "\n".join(text), alianzas_menu(chat_id, len(items)))
    await cb.answer()


@router.callback_query(F.data.startswith("alclr:"))
async def cb_alianzas_clear(cb: CallbackQuery, bot: Bot) -> None:
    chat_id = int(cb.data.split(":")[1])
    if not await _check_admin_or_deny(cb, bot, chat_id):
        return
    await _safe_edit(
        cb, "⚠️ ¿Limpiar <b>TODAS</b> las alianzas? Esta acción no se puede deshacer.",
        confirm_clear_alianzas(chat_id),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("alclrok:"))
async def cb_alianzas_clear_ok(cb: CallbackQuery, bot: Bot) -> None:
    chat_id = int(cb.data.split(":")[1])
    if not await _check_admin_or_deny(cb, bot, chat_id):
        return
    n = await alianzas_db.clear_alianzas(chat_id)
    await cb.answer(f"✅ {n} alianzas eliminadas")
    await _safe_edit(
        cb, f"✅ Se eliminaron <b>{n}</b> alianzas.",
        alianzas_menu(chat_id, 0),
    )


# === STATS ===
@router.callback_query(F.data.startswith("st:"))
async def cb_stats(cb: CallbackQuery, bot: Bot) -> None:
    chat_id = int(cb.data.split(":")[1])
    if not await _check_admin_or_deny(cb, bot, chat_id):
        return
    stats = await get_stats(chat_id, hours=24)
    top = await get_top_posters(chat_id, hours=168, limit=5)
    lines = [
        "📊 <b>Estadísticas</b>",
        "",
        "<b>Últimas 24h:</b>",
        f"📸 Total publicaciones: <b>{stats['total_posts']}</b>",
        f"👤 Chicas distintas: <b>{stats['distinct_users']}</b>",
        "",
        "<b>Borrados últimas 24h:</b>",
        f"🚫 Cola: <b>{stats['deletes']['queue']}</b>",
        f"🚫 Cooldown: <b>{stats['deletes']['cooldown']}</b>",
        f"🚫 Duplicado: <b>{stats['deletes']['antidup']}</b>",
        "",
    ]
    if top:
        lines.append("<b>Top 5 últimos 7 días:</b>")
        for i, p in enumerate(top, 1):
            mention = safe_username(p.get("username"), p["user_id"])
            lines.append(f"  {i}. {mention} · {p['n']} posts")
    await _safe_edit(cb, "\n".join(lines), stats_menu(chat_id))
    await cb.answer()


# === AVANZADAS ===
@router.callback_query(F.data.startswith("adv:"))
async def cb_advanced(cb: CallbackQuery, bot: Bot) -> None:
    chat_id = int(cb.data.split(":")[1])
    if not await _check_admin_or_deny(cb, bot, chat_id):
        return
    cfg = await get_config(chat_id)
    text = (
        "⚙️ <b>Opciones avanzadas</b>\n\n"
        "🔒 <i>Solo admins en menú</i>: si está activo, solo los admins pueden usar /menu.\n"
        "🤫 <i>Modo silencio</i>: borra sin enviar ningún aviso.\n"
        "🧹 <i>Borrar mensajes de servicio</i>: borra automáticamente \"X se unió\", \"foto cambiada\", etc.\n"
        "🗂️ <i>Auto-limpieza</i>: borra posts antiguos de la BD."
    )
    await _safe_edit(cb, text, advanced_menu(cfg))
    await cb.answer()


@router.callback_query(F.data.startswith("advt:"))
async def cb_advanced_toggle(cb: CallbackQuery, bot: Bot) -> None:
    parts = cb.data.split(":")
    chat_id, field = int(parts[1]), parts[2]
    if not await _check_admin_or_deny(cb, bot, chat_id):
        return
    valid_fields = {"admin_only_menu", "silence_mode", "delete_service_messages"}
    if field not in valid_fields:
        await cb.answer("Campo inválido")
        return
    cfg = await get_config(chat_id)
    new = 0 if int(cfg.get(field, 0)) else 1
    await update_config(chat_id, field, new)
    cfg = await get_config(chat_id)
    text = (
        "⚙️ <b>Opciones avanzadas</b>\n\n"
        "🔒 Solo admins en menú\n"
        "🤫 Modo silencio total\n"
        "🧹 Borrar mensajes de servicio\n"
        "🗂️ Auto-limpieza"
    )
    await _safe_edit(cb, text, advanced_menu(cfg))
    await cb.answer("✅ Activado" if new else "❌ Desactivado")


@router.callback_query(F.data.startswith("advac:"))
async def cb_advanced_autoclean(cb: CallbackQuery, bot: Bot) -> None:
    chat_id = int(cb.data.split(":")[1])
    if not await _check_admin_or_deny(cb, bot, chat_id):
        return
    cfg = await get_config(chat_id)
    text = (
        "🗂️ <b>Auto-limpieza de la BD</b>\n\n"
        "Tras cuántos días borrar registros antiguos para mantener la BD ligera. "
        "Pulsa <b>Nunca</b> para desactivar.\n\n"
        "<i>Recomendado: 30 días.</i>"
    )
    await _safe_edit(cb, text, autoclean_menu(chat_id, int(cfg["autoclean_days"])))
    await cb.answer()


@router.callback_query(F.data.startswith("advacs:"))
async def cb_advanced_autoclean_set(cb: CallbackQuery, bot: Bot) -> None:
    parts = cb.data.split(":")
    chat_id, value = int(parts[1]), int(parts[2])
    if not await _check_admin_or_deny(cb, bot, chat_id):
        return
    await update_config(chat_id, "autoclean_days", value)
    label = "Nunca" if value == 0 else f"{value} días"
    await _safe_edit(cb, "🗂️ <b>Auto-limpieza</b>", autoclean_menu(chat_id, value))
    await cb.answer(f"✅ {label}")


@router.callback_query(F.data.startswith("rstq:"))
async def cb_reset_queue(cb: CallbackQuery, bot: Bot) -> None:
    chat_id = int(cb.data.split(":")[1])
    if not await _check_admin_or_deny(cb, bot, chat_id):
        return
    await _safe_edit(
        cb,
        "🔄 <b>¿Vaciar la cola actual?</b>\n\n"
        "Olvidará quién publicó recientemente, todas podrán publicar otra vez.\n"
        "La configuración no se toca.",
        confirm_reset_queue(chat_id),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("rstqok:"))
async def cb_reset_queue_ok(cb: CallbackQuery, bot: Bot) -> None:
    chat_id = int(cb.data.split(":")[1])
    if not await _check_admin_or_deny(cb, bot, chat_id):
        return
    n = await posts_db.reset_queue(chat_id)
    await cb.answer(f"✅ Cola vaciada ({n} registros)")
    cfg = await get_config(chat_id)
    text = await render_main_menu_text(bot, chat_id, cfg)
    await _safe_edit(cb, text, main_menu(cfg))


@router.callback_query(F.data.startswith("reset:"))
async def cb_reset_config(cb: CallbackQuery, bot: Bot) -> None:
    chat_id = int(cb.data.split(":")[1])
    if not await _check_admin_or_deny(cb, bot, chat_id):
        return
    await _safe_edit(
        cb,
        "⚠️ <b>Restaurar valores por defecto</b>\n\n"
        "Volverá toda la configuración a sus valores originales: "
        "cola 5, cooldown 30min, antidup 12h, todos los castigos en aviso, "
        "todos los filtros en Off, todas las reglas activadas.\n\n"
        "Las alianzas y los warns NO se tocan.",
        confirm_reset_config(chat_id),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("resetok:"))
async def cb_reset_config_ok(cb: CallbackQuery, bot: Bot) -> None:
    chat_id = int(cb.data.split(":")[1])
    if not await _check_admin_or_deny(cb, bot, chat_id):
        return
    await reset_to_defaults(chat_id)
    cfg = await get_config(chat_id)
    text = await render_main_menu_text(bot, chat_id, cfg)
    await _safe_edit(cb, text, main_menu(cfg))
    await cb.answer("✅ Configuración restaurada")


# === LOCK TOGGLE (botón en el menú) ===
@router.callback_query(F.data.startswith("lk:"))
async def cb_lock_toggle(cb: CallbackQuery, bot: Bot) -> None:
    chat_id = int(cb.data.split(":")[1])
    if not await _check_admin_or_deny(cb, bot, chat_id):
        return
    cfg = await get_config(chat_id)
    new = 0 if int(cfg.get("locked", 0)) else 1
    await update_config(chat_id, "locked", new)
    cfg = await get_config(chat_id)
    text = await render_main_menu_text(bot, chat_id, cfg)
    await _safe_edit(cb, text, main_menu(cfg))
    await cb.answer("🔕 Bot pausado" if new else "✅ Bot reactivado")


# === FILTROS DE CONTENIDO ===
@router.callback_query(F.data.startswith("filt:"))
async def cb_filters_main(cb: CallbackQuery, bot: Bot) -> None:
    parts = cb.data.split(":")
    chat_id = int(parts[1])
    page = int(parts[2]) if len(parts) > 2 else 0
    if not await _check_admin_or_deny(cb, bot, chat_id):
        return
    cfg = await get_config(chat_id)
    total = len(FILTER_TYPES)
    total_pages = (total + 8 - 1) // 8
    text = (
        "🎯 <b>Filtros de tipos de contenido</b>\n\n"
        "Define qué hace el bot para cada tipo de mensaje.\n\n"
        "✅ Off · permitido\n"
        "🗑️ Borrar · solo borra\n"
        "⚠️ Warn · borra + advertencia\n"
        "🔇 Mute · borra + silenciar\n"
        "👢 Kick · borra + expulsar\n"
        "⛔ Ban · borra + banear\n\n"
        f"<i>Página {page + 1}/{total_pages}</i>"
    )
    await _safe_edit(cb, text, filter_main_menu(cfg, page=page))
    await cb.answer()


@router.callback_query(F.data.startswith("filtt:"))
async def cb_filter_type(cb: CallbackQuery, bot: Bot) -> None:
    parts = cb.data.split(":")
    chat_id, field = int(parts[1]), parts[2]
    if not await _check_admin_or_deny(cb, bot, chat_id):
        return
    cfg = await get_config(chat_id)
    if field not in cfg:
        await cb.answer("Campo inválido")
        return
    # Buscar etiqueta bonita
    label = field
    for emoji, lab, fld in FILTER_TYPES:
        if fld == field:
            label = f"{emoji} {lab}"
            break
    # Detectar página actual para volver bien
    page = 0
    idx = next((i for i, (_, _, f) in enumerate(FILTER_TYPES) if f == field), 0)
    page = idx // 8
    current = int(cfg[field])
    text = (
        f"🎯 <b>{label}</b>\n\n"
        f"Acción actual: {FILTER_ACTIONS[current][0]} <b>{FILTER_ACTIONS[current][1]}</b>\n\n"
        "Elige qué hago cuando alguien envía este tipo de contenido:"
    )
    await _safe_edit(cb, text, filter_action_menu(chat_id, field, current, page=page))
    await cb.answer()


@router.callback_query(F.data.startswith("filts:"))
async def cb_filter_set(cb: CallbackQuery, bot: Bot) -> None:
    parts = cb.data.split(":")
    chat_id, field, action = int(parts[1]), parts[2], int(parts[3])
    if not await _check_admin_or_deny(cb, bot, chat_id):
        return
    if action not in FILTER_ACTIONS:
        await cb.answer("Acción inválida")
        return
    await update_config(chat_id, field, action)
    cfg = await get_config(chat_id)
    label = field
    for emoji, lab, fld in FILTER_TYPES:
        if fld == field:
            label = f"{emoji} {lab}"
            break
    page = 0
    idx = next((i for i, (_, _, f) in enumerate(FILTER_TYPES) if f == field), 0)
    page = idx // 8
    text = (
        f"🎯 <b>{label}</b>\n\n"
        f"Acción: {FILTER_ACTIONS[action][0]} <b>{FILTER_ACTIONS[action][1]}</b>"
    )
    await _safe_edit(cb, text, filter_action_menu(chat_id, field, action, page=page))
    await cb.answer(f"✅ {FILTER_ACTIONS[action][1]}")


# === TIPOS SUJETOS A LAS 3 REGLAS ===
@router.callback_query(F.data.startswith("cnt:"))
async def cb_countable_menu(cb: CallbackQuery, bot: Bot) -> None:
    """Abre el menú de tipos sujetos a las reglas."""
    chat_id = int(cb.data.split(":")[1])
    if not await _check_admin_or_deny(cb, bot, chat_id):
        return
    cfg = await get_config(chat_id)
    from config import COUNTABLE_TYPES
    from keyboards.builders import countable_menu
    active_count = sum(1 for _, _, f, _ in COUNTABLE_TYPES if int(cfg.get(f, 0)))
    text = (
        "🎯 <b>Tipos sujetos a las 3 reglas</b>\n\n"
        "Decide qué tipos de contenido cuentan como <b>publicación</b>. "
        "Los que actives pasarán por cola, cooldown y anti-duplicado "
        "como lo hacen las fotos y vídeos.\n\n"
        "✅ <b>Activo</b> · cuenta como publicación\n"
        "⬜ <b>Inactivo</b> · el bot lo ignora\n\n"
        f"<i>Activos ahora: <b>{active_count}/{len(COUNTABLE_TYPES)}</b></i>\n\n"
        "<i>* = soporta anti-duplicado (foto/vídeo/gif/video redondo)</i>"
    )
    await _safe_edit(cb, text, countable_menu(cfg))
    await cb.answer()


@router.callback_query(F.data.startswith("cntt:"))
async def cb_countable_toggle(cb: CallbackQuery, bot: Bot) -> None:
    """Cambia el estado ON/OFF de un tipo."""
    parts = cb.data.split(":")
    chat_id, field = int(parts[1]), parts[2]
    if not await _check_admin_or_deny(cb, bot, chat_id):
        return
    cfg = await get_config(chat_id)
    if field not in cfg:
        await cb.answer("Campo inválido")
        return
    current = int(cfg.get(field, 0))
    new = 0 if current else 1
    await update_config(chat_id, field, new)
    # Re-render el menú
    cfg = await get_config(chat_id)
    from config import COUNTABLE_TYPES
    from keyboards.builders import countable_menu
    active_count = sum(1 for _, _, f, _ in COUNTABLE_TYPES if int(cfg.get(f, 0)))
    label = field
    for emoji, lab, fld, _supp in COUNTABLE_TYPES:
        if fld == field:
            label = f"{emoji} {lab}"
            break
    text = (
        "🎯 <b>Tipos sujetos a las 3 reglas</b>\n\n"
        "Decide qué tipos de contenido cuentan como <b>publicación</b>. "
        "Los que actives pasarán por cola, cooldown y anti-duplicado "
        "como lo hacen las fotos y vídeos.\n\n"
        "✅ <b>Activo</b> · cuenta como publicación\n"
        "⬜ <b>Inactivo</b> · el bot lo ignora\n\n"
        f"<i>Activos ahora: <b>{active_count}/{len(COUNTABLE_TYPES)}</b></i>\n\n"
        "<i>* = soporta anti-duplicado (foto/vídeo/gif/video redondo)</i>"
    )
    await _safe_edit(cb, text, countable_menu(cfg))
    await cb.answer(f"{'✅ Activado' if new else '⬜ Desactivado'}: {label}")


# === AYUDA (botón "📚 Ayuda y comandos" del menú) ===
@router.callback_query(F.data == "hlp")
async def cb_help_menu(cb: CallbackQuery, bot: Bot) -> None:
    text = (
        "📚 <b>AYUDA RÁPIDA</b>\n\n"
        "🛠️ <b>Comandos en el grupo:</b>\n"
        "<code>/menu</code> · configuración completa\n"
        "<code>/status</code> · estado y stats\n"
        "<code>/lock</code> · pausar el bot\n"
        "<code>/unlock</code> · reanudar\n"
        "<code>/freespam @user</code> · eximir a una chica\n"
        "<code>/forcepost @user</code> · pase libre próxima publicación\n"
        "<code>/cancel</code> · anular publicación (no cuenta)\n"
        "<code>/warn @user motivo</code> · advertir\n"
        "<code>/help</code> · lista completa\n\n"
        "🗂️ <b>En privado conmigo:</b>\n"
        "<code>/menu</code> · elegir grupo y configurar\n"
        "<code>/help</code> · ayuda\n\n"
        "💡 <i>Para anular tu última publicación rápido, escribe</i> <code>/cancel</code>. "
        "<i>Para anular una concreta, responde a ella con</i> <code>/cancel</code>."
    )
    await _safe_edit(cb, text, help_menu_keyboard())
    await cb.answer()


# === CERRAR ===
@router.callback_query(F.data == "cls")
async def cb_close(cb: CallbackQuery, bot: Bot) -> None:
    try:
        await cb.message.delete()
    except TelegramBadRequest:
        await _safe_edit(cb, "✅ Menú cerrado.")
    await cb.answer()


# === SELECTOR DE GRUPO (privado) ===
@router.callback_query(F.data.startswith("selg:"))
async def cb_select_group(cb: CallbackQuery, bot: Bot) -> None:
    chat_id = int(cb.data.split(":")[1])
    if not await _check_admin_or_deny(cb, bot, chat_id):
        return
    if not await chat_is_allowed(chat_id):
        await _safe_edit(
            cb,
            f"⚠️ Este grupo no tiene suscripción activa.\n\nContacta @{OWNER_USERNAME} para activar.",
        )
        await cb.answer()
        return
    cfg = await get_config(chat_id)
    text = await render_main_menu_text(bot, chat_id, cfg)
    await _safe_edit(cb, text, main_menu(cfg))
    await cb.answer()


# ============== PANEL OWNER ==============
@router.callback_query(F.data == "admdash")
async def cb_admin_dashboard(cb: CallbackQuery, bot: Bot) -> None:
    if not is_owner(cb.from_user.id):
        await cb.answer("Solo el propietario.", show_alert=True)
        return
    counts = await licenses_db.count_by_status()
    from config import SUBSCRIPTION_PRICE_EUR
    income = counts.get("active", 0) * SUBSCRIPTION_PRICE_EUR
    text = (
        "👑 <b>PANEL DE OWNER</b>\n\n"
        "📊 <b>Resumen:</b>\n"
        f"  ✅ Activos: <b>{counts.get('active', 0)}</b>\n"
        f"  👑 Tuyos: <b>{counts.get('owner', 0)}</b>\n"
        f"  ⏳ Pendientes: <b>{counts.get('pending', 0)}</b>\n"
        f"  ❌ Expirados: <b>{counts.get('expired', 0)}</b>\n"
        f"  🚫 Vetados: <b>{counts.get('banned', 0)}</b>\n\n"
        f"💎 <b>Ingresos brutos est.</b>: {income:.2f} €/mes"
    )
    await _safe_edit(cb, text, admin_main_menu())
    await cb.answer()


@router.callback_query(F.data.startswith("adml:"))
async def cb_admin_list(cb: CallbackQuery, bot: Bot) -> None:
    if not is_owner(cb.from_user.id):
        await cb.answer("Solo el propietario.", show_alert=True)
        return
    flt = cb.data.split(":")[1]
    filter_status = None if flt == "all" else flt
    items = await licenses_db.list_licenses(filter_status)
    if not items:
        await _safe_edit(
            cb,
            f"📭 No hay grupos en estado <b>{flt}</b>.",
            admin_main_menu(),
        )
        await cb.answer()
        return
    title_map = {
        "all": "📋 Todos los grupos",
        "pending": "⏳ Grupos pendientes",
        "active": "✅ Grupos activos",
        "expired": "❌ Grupos expirados",
        "banned": "🚫 Grupos vetados",
    }
    text = f"<b>{title_map.get(flt, 'Grupos')}</b> ({len(items)})\n\nToca uno para gestionarlo:"
    await _safe_edit(cb, text, license_list_menu(items, filter_status))
    await cb.answer()


@router.callback_query(F.data.startswith("licinfo:"))
async def cb_license_info(cb: CallbackQuery, bot: Bot) -> None:
    if not is_owner(cb.from_user.id):
        await cb.answer("Solo el propietario.", show_alert=True)
        return
    chat_id = int(cb.data.split(":")[1])
    lic = await licenses_db.get_license(chat_id)
    if not lic:
        await cb.answer("Licencia no encontrada", show_alert=True)
        return
    title = lic.get("chat_title") or f"Chat {chat_id}"
    text = (
        f"📍 <b>{title}</b>\n"
        f"🆔 <code>{chat_id}</code>\n\n"
        f"{format_license_status(lic)}\n\n"
    )
    if lic.get("added_by_username"):
        text += f"👤 Añadido por: @{lic['added_by_username']}\n"
    elif lic.get("added_by_user_id"):
        text += f"👤 Añadido por ID: <code>{lic['added_by_user_id']}</code>\n"
    if lic.get("activated_at"):
        text += f"📅 Activado: <code>{str(lic['activated_at'])[:16]}</code>\n"
    if lic.get("expires_at"):
        text += f"⏰ Expira: <code>{str(lic['expires_at'])[:16]}</code>\n"
    await _safe_edit(cb, text, license_actions_menu(chat_id))
    await cb.answer()


@router.callback_query(F.data.startswith("licext:"))
async def cb_license_extend(cb: CallbackQuery, bot: Bot) -> None:
    if not is_owner(cb.from_user.id):
        await cb.answer("Solo el propietario.", show_alert=True)
        return
    parts = cb.data.split(":")
    chat_id, days = int(parts[1]), int(parts[2])
    new_exp = await licenses_db.extend(chat_id, days, activated_by=cb.from_user.id)
    await cb.answer(f"✅ Activado hasta {new_exp.strftime('%d/%m/%Y')}", show_alert=True)
    # Avisar al grupo
    await _notify_chat_activated_silent(bot, chat_id)
    # Refrescar info
    lic = await licenses_db.get_license(chat_id)
    if lic:
        title = lic.get("chat_title") or f"Chat {chat_id}"
        text = (
            f"📍 <b>{title}</b>\n"
            f"🆔 <code>{chat_id}</code>\n\n"
            f"{format_license_status(lic)}\n"
        )
        await _safe_edit(cb, text, license_actions_menu(chat_id))


@router.callback_query(F.data.startswith("liclife:"))
async def cb_license_lifetime(cb: CallbackQuery, bot: Bot) -> None:
    if not is_owner(cb.from_user.id):
        await cb.answer("Solo el propietario.", show_alert=True)
        return
    chat_id = int(cb.data.split(":")[1])
    await licenses_db.set_lifetime(chat_id, activated_by=cb.from_user.id)
    await cb.answer("♾️ Activación permanente", show_alert=True)
    await _notify_chat_activated_silent(bot, chat_id, lifetime=True)
    lic = await licenses_db.get_license(chat_id)
    if lic:
        title = lic.get("chat_title") or f"Chat {chat_id}"
        text = (
            f"📍 <b>{title}</b>\n"
            f"🆔 <code>{chat_id}</code>\n\n"
            f"{format_license_status(lic)}\n"
        )
        await _safe_edit(cb, text, license_actions_menu(chat_id))


@router.callback_query(F.data.startswith("licdeact:"))
async def cb_license_deactivate(cb: CallbackQuery, bot: Bot) -> None:
    if not is_owner(cb.from_user.id):
        await cb.answer("Solo el propietario.", show_alert=True)
        return
    chat_id = int(cb.data.split(":")[1])
    await licenses_db.set_status(chat_id, "pending")
    await cb.answer("⏳ Marcado como pendiente", show_alert=True)
    lic = await licenses_db.get_license(chat_id)
    if lic:
        title = lic.get("chat_title") or f"Chat {chat_id}"
        text = (
            f"📍 <b>{title}</b>\n"
            f"🆔 <code>{chat_id}</code>\n\n"
            f"{format_license_status(lic)}"
        )
        await _safe_edit(cb, text, license_actions_menu(chat_id))


@router.callback_query(F.data.startswith("licban:"))
async def cb_license_ban(cb: CallbackQuery, bot: Bot) -> None:
    if not is_owner(cb.from_user.id):
        await cb.answer("Solo el propietario.", show_alert=True)
        return
    chat_id = int(cb.data.split(":")[1])
    await licenses_db.set_status(chat_id, "banned")
    await cb.answer("🚫 Grupo vetado", show_alert=True)
    lic = await licenses_db.get_license(chat_id)
    if lic:
        title = lic.get("chat_title") or f"Chat {chat_id}"
        text = (
            f"📍 <b>{title}</b>\n"
            f"🆔 <code>{chat_id}</code>\n\n"
            f"{format_license_status(lic)}"
        )
        await _safe_edit(cb, text, license_actions_menu(chat_id))


@router.callback_query(F.data.startswith("licleave:"))
async def cb_license_leave(cb: CallbackQuery, bot: Bot) -> None:
    if not is_owner(cb.from_user.id):
        await cb.answer("Solo el propietario.", show_alert=True)
        return
    chat_id = int(cb.data.split(":")[1])
    try:
        await bot.leave_chat(chat_id)
        await cb.answer("🚪 Bot salido del grupo", show_alert=True)
    except Exception as e:
        await cb.answer(f"❌ Error: {e}", show_alert=True)
        return
    await _safe_edit(
        cb,
        f"🚪 Bot salido de <code>{chat_id}</code>.",
        admin_main_menu(),
    )


# === Mensajes de texto: ¿valor personalizado? ===
@router.message(F.chat.type == ChatType.PRIVATE, F.text.regexp(r"^-?\d+$"))
async def msg_custom_value(message: Message, bot: Bot) -> None:
    user_id = message.from_user.id
    pending = _pending_custom.get(user_id)
    if not pending:
        return
    if pending["expires_at"] < time.time():
        _pending_custom.pop(user_id, None)
        await message.reply("⌛ Tiempo agotado. Vuelve a pulsar el botón.")
        return
    try:
        value = int(message.text)
    except ValueError:
        return
    if not (pending["min"] <= value <= pending["max"]):
        await message.reply(
            f"❌ Fuera de rango. Tiene que estar entre {pending['min']} y {pending['max']}."
        )
        return
    chat_id = pending["chat_id"]
    field = pending["field"]
    if not await is_admin(bot, chat_id, user_id):
        await message.reply("❌ Ya no eres admin de ese grupo.")
        _pending_custom.pop(user_id, None)
        return
    await update_config(chat_id, field, value)
    _pending_custom.pop(user_id, None)
    cfg = await get_config(chat_id)
    text = await render_main_menu_text(bot, chat_id, cfg)
    await message.reply(text, reply_markup=main_menu(cfg))


# === Helpers de texto de submenús ===
def _menu_text_queue(cfg: dict) -> str:
    enabled = bool(int(cfg.get("queue_enabled", 1)))
    state = "✅ ACTIVADA" if enabled else "❌ DESACTIVADA"
    return (
        f"🔄 <b>Cola rotatoria</b> · {state}\n\n"
        "Cuántas chicas distintas deben publicar antes de que vuelvas a poder publicar tú.\n\n"
        f"Valor actual: <b>{cfg['queue_size']}</b> chicas"
    )


def _menu_text_cooldown(cfg: dict) -> str:
    enabled = bool(int(cfg.get("cooldown_enabled", 1)))
    state = "✅ ACTIVADO" if enabled else "❌ DESACTIVADO"
    return (
        f"⏱️ <b>Cooldown</b> · {state}\n\n"
        "Tiempo mínimo entre tus propias publicaciones.\n\n"
        f"Valor actual: <b>{format_minutes(int(cfg['cooldown_minutes']))}</b>"
    )


def _menu_text_antidup(cfg: dict) -> str:
    enabled = bool(int(cfg.get("antidup_enabled", 1)))
    state = "✅ ACTIVADO" if enabled else "❌ DESACTIVADO"
    sens = {3: "🔴 Estricta", 5: "🟢 Normal", 8: "🟡 Tolerante", 12: "🔵 Agresiva"}.get(
        int(cfg["phash_threshold"]), str(cfg["phash_threshold"]),
    )
    return (
        f"🖼️ <b>Anti-duplicado</b> · {state}\n\n"
        "Bloquea fotos o vídeos que ya se publicaron recientemente en el grupo.\n\n"
        f"Ventana actual: <b>{cfg['antidup_hours']}h</b>\n"
        f"Sensibilidad: <b>{sens}</b>"
    )


# === Notificación interna al chat tras activar ===
async def _notify_chat_activated_silent(
    bot: Bot, chat_id: int, lifetime: bool = False,
) -> None:
    lic = await licenses_db.get_license(chat_id)
    if not lic:
        return
    text = "✅ <b>¡Bot activado en este grupo!</b>\n\n"
    if lifetime:
        text += "♾️ Acceso <b>permanente</b>.\n\n"
    elif lic.get("expires_at"):
        text += f"📅 Suscripción válida hasta: <code>{str(lic['expires_at'])[:10]}</code>\n\n"
    text += "Usa /menu para configurar las reglas."
    try:
        await bot.send_message(chat_id, text)
    except TelegramBadRequest:
        pass
