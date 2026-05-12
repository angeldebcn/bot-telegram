"""
Constructores de teclados inline para todos los menús.

Esquema de callback_data (compacto, < 64 bytes):
  m:{chat_id}         → menú principal del chat
  q/cd/ad/ph:{chat_id} → submenús de regla
  qs/cds/ads/phs:{chat_id}:{val} → set valor
  qc/cdc/adc:{chat_id} → pedir valor personalizado (estado conversacional)
  al:{chat_id}        → submenú alianzas
  alclr/alclrok:{chat_id}
  st:{chat_id}        → submenú estadísticas
  pun:{chat_id}       → menú de castigos
  punq/puncd/punad:{chat_id} → submenús de castigo por regla
  punqs/puncds/punads:{chat_id}:{val} → set castigo
  nq/ncd/nad:{chat_id}        → duración aviso por regla
  nqs/ncds/nads:{chat_id}:{val}
  mq/mcd/mad:{chat_id}        → duración mute por regla
  mqs/mcds/mads:{chat_id}:{val}
  wn:{chat_id}                → menú warns
  wnlim/wnexp/wnfin/wnfmute:{chat_id}:{val}
  adv:{chat_id}               → opciones avanzadas
  advt:{chat_id}:{field}      → toggle bool
  advac:{chat_id}             → autoclean submenú
  advacs:{chat_id}:{val}
  rstq/rstqok:{chat_id}       → reset cola
  reset/resetok:{chat_id}     → reset config
  selg:{chat_id}              → seleccionar este grupo (en privado)
  cls                         → cerrar menú
"""
from typing import Any

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

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

# === Helpers internos ===

def _btn(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data)


def _rows(buttons: list[InlineKeyboardButton], per_row: int = 4) -> list[list[InlineKeyboardButton]]:
    return [buttons[i:i + per_row] for i in range(0, len(buttons), per_row)]


def _check(active: bool) -> str:
    return " ✓" if active else ""


def _back(chat_id: int, text: str = "🔙 Volver al menú") -> InlineKeyboardButton:
    return _btn(text, f"m:{chat_id}")


def _close() -> InlineKeyboardButton:
    return _btn("❌ Cerrar", "cls")


# === MENÚ PRINCIPAL ===

def main_menu(cfg: dict[str, Any]) -> InlineKeyboardMarkup:
    chat_id = cfg["chat_id"]
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn(f"🔄 Cola · {cfg['queue_size']} chicas", f"q:{chat_id}")],
        [_btn(f"⏱️ Cooldown · {_human_min(cfg['cooldown_minutes'])}", f"cd:{chat_id}")],
        [_btn(f"🖼️ Anti-duplicado · {cfg['antidup_hours']}h", f"ad:{chat_id}")],
        [_btn("⚖️ Castigos", f"pun:{chat_id}")],
        [_btn("⚠️ Sistema de warns", f"wn:{chat_id}")],
        [_btn("👥 Alianzas", f"al:{chat_id}")],
        [_btn("📊 Estadísticas", f"st:{chat_id}")],
        [_btn("⚙️ Opciones avanzadas", f"adv:{chat_id}")],
        [_close()],
    ])


def _human_min(minutes: int) -> str:
    if minutes < 60:
        return f"{minutes} min"
    if minutes % 60 == 0:
        return f"{minutes // 60}h"
    return f"{minutes // 60}h{minutes % 60}m"


# === SUBMENÚ COLA ===

def queue_menu(chat_id: int, current: int) -> InlineKeyboardMarkup:
    btns = [_btn(f"{v}{_check(v == current)}", f"qs:{chat_id}:{v}") for v in QUEUE_OPTIONS]
    return InlineKeyboardMarkup(inline_keyboard=[
        *_rows(btns, per_row=4),
        [_btn("✏️ Valor personalizado (1-50)", f"qc:{chat_id}")],
        [_back(chat_id)],
    ])


# === SUBMENÚ COOLDOWN ===

def cooldown_menu(chat_id: int, current: int) -> InlineKeyboardMarkup:
    btns = [_btn(f"{_human_min(v)}{_check(v == current)}", f"cds:{chat_id}:{v}") for v in COOLDOWN_OPTIONS]
    return InlineKeyboardMarkup(inline_keyboard=[
        *_rows(btns, per_row=4),
        [_btn("✏️ Valor personalizado (1-1440 min)", f"cdc:{chat_id}")],
        [_back(chat_id)],
    ])


# === SUBMENÚ ANTI-DUPLICADO ===

def antidup_menu(chat_id: int, current_hours: int) -> InlineKeyboardMarkup:
    btns = [_btn(f"{v}h{_check(v == current_hours)}", f"ads:{chat_id}:{v}") for v in ANTIDUP_OPTIONS]
    return InlineKeyboardMarkup(inline_keyboard=[
        *_rows(btns, per_row=4),
        [_btn("✏️ Valor personalizado (1-168h)", f"adc:{chat_id}")],
        [_btn("🎯 Ajustar sensibilidad", f"ph:{chat_id}")],
        [_back(chat_id)],
    ])


def phash_menu(chat_id: int, current: int) -> InlineKeyboardMarkup:
    rows = [[_btn(f"{label} ({v}){_check(v == current)}", f"phs:{chat_id}:{v}")] for v, label in PHASH_OPTIONS]
    rows.append([_btn("🔙 Volver", f"ad:{chat_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# === SUBMENÚ ALIANZAS ===

def alianzas_menu(chat_id: int, n_alianzas: int) -> InlineKeyboardMarkup:
    rows = []
    if n_alianzas > 0:
        rows.append([_btn("🗑️ Limpiar todas las alianzas", f"alclr:{chat_id}")])
    rows.append([_back(chat_id)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def confirm_clear_alianzas(chat_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("✅ Sí, limpiar todas", f"alclrok:{chat_id}")],
        [_btn("❌ Cancelar", f"al:{chat_id}")],
    ])


# === SUBMENÚ ESTADÍSTICAS ===

def stats_menu(chat_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("🔄 Actualizar", f"st:{chat_id}")],
        [_back(chat_id)],
    ])


# === MENÚ DE CASTIGOS ===

def punishments_menu(cfg: dict) -> InlineKeyboardMarkup:
    chat_id = cfg["chat_id"]
    pq = PUNISHMENT_TYPES[cfg["punishment_queue"]]
    pc = PUNISHMENT_TYPES[cfg["punishment_cooldown"]]
    pa = PUNISHMENT_TYPES[cfg["punishment_antidup"]]
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn(f"🔄 Cola · {pq[0]} {pq[1]}", f"punq:{chat_id}")],
        [_btn(f"⏱️ Cooldown · {pc[0]} {pc[1]}", f"puncd:{chat_id}")],
        [_btn(f"🖼️ Duplicado · {pa[0]} {pa[1]}", f"punad:{chat_id}")],
        [_back(chat_id)],
    ])


def punishment_choice_menu(chat_id: int, rule_key: str, current: int) -> InlineKeyboardMarkup:
    """rule_key ∈ {'punq', 'puncd', 'punad'} → genera setter correspondiente."""
    setter = {"punq": "punqs", "puncd": "puncds", "punad": "punads"}[rule_key]
    rows = []
    for code, (emoji, label) in PUNISHMENT_TYPES.items():
        rows.append([_btn(
            f"{emoji} {label}{_check(code == current)}",
            f"{setter}:{chat_id}:{code}",
        )])
    # Si el castigo actual es "aviso" (2), mostrar opción de ajustar duración
    rule_part = rule_key[3:] if rule_key != "punq" else "q"
    # Mapeo a las claves cortas de notice/mute
    notice_key = {"punq": "nq", "puncd": "ncd", "punad": "nad"}[rule_key]
    mute_key = {"punq": "mq", "puncd": "mcd", "punad": "mad"}[rule_key]
    if current == 2:
        rows.append([_btn("⏲️ Duración del aviso", f"{notice_key}:{chat_id}")])
    if current == 4:
        rows.append([_btn("⏲️ Duración del mute", f"{mute_key}:{chat_id}")])
    rows.append([_btn("🔙 Volver", f"pun:{chat_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# === DURACIÓN DEL AVISO ===

def notice_duration_menu(chat_id: int, rule_key: str, current: int) -> InlineKeyboardMarkup:
    """rule_key ∈ {'nq', 'ncd', 'nad'} → setter nqs/ncds/nads."""
    setter = {"nq": "nqs", "ncd": "ncds", "nad": "nads"}[rule_key]
    back_to = {"nq": "punq", "ncd": "puncd", "nad": "punad"}[rule_key]
    btns = [_btn(f"{v}s{_check(v == current)}", f"{setter}:{chat_id}:{v}") for v in NOTICE_DURATION_OPTIONS]
    return InlineKeyboardMarkup(inline_keyboard=[
        *_rows(btns, per_row=4),
        [_btn("🔙 Volver", f"{back_to}:{chat_id}")],
    ])


# === DURACIÓN DEL MUTE ===

def mute_duration_menu(chat_id: int, rule_key: str, current: int) -> InlineKeyboardMarkup:
    """rule_key ∈ {'mq', 'mcd', 'mad'} → setter mqs/mcds/mads."""
    setter = {"mq": "mqs", "mcd": "mcds", "mad": "mads"}[rule_key]
    back_to = {"mq": "punq", "mcd": "puncd", "mad": "punad"}[rule_key]
    rows = []
    pair = []
    for v, label in MUTE_DURATION_OPTIONS:
        pair.append(_btn(f"{label}{_check(v == current)}", f"{setter}:{chat_id}:{v}"))
        if len(pair) == 4:
            rows.append(pair)
            pair = []
    if pair:
        rows.append(pair)
    rows.append([_btn("🔙 Volver", f"{back_to}:{chat_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# === MENÚ DE WARNS ===

def warns_menu(cfg: dict) -> InlineKeyboardMarkup:
    chat_id = cfg["chat_id"]
    final_action = int(cfg["warn_final_action"])
    rows = [
        [_btn(f"⚠️ Límite · {cfg['warn_limit']} warns", f"wnlim:{chat_id}:0")],
        [_btn(f"📅 Expiración · {cfg['warn_expiration_days']} días", f"wnexp:{chat_id}:0")],
        [_btn(f"🚨 Acción final · {PUNISHMENT_TYPES[final_action][1]}", f"wnfin:{chat_id}:0")],
    ]
    # Si la acción final es mute, ofrecer ajustar duración
    if final_action == 4:
        from utils.helpers import format_duration
        rows.append([_btn(
            f"⏲️ Duración mute final · {format_duration(int(cfg['warn_final_mute_seconds']))}",
            f"wnfmute:{chat_id}:0",
        )])
    rows.append([_back(chat_id)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def warn_final_mute_menu(chat_id: int, current: int) -> InlineKeyboardMarkup:
    """Selector de duración para el mute final del sistema de warns."""
    rows = []
    pair = []
    for v, label in MUTE_DURATION_OPTIONS:
        pair.append(_btn(f"{label}{_check(v == current)}", f"wnfmute:{chat_id}:{v}"))
        if len(pair) == 4:
            rows.append(pair)
            pair = []
    if pair:
        rows.append(pair)
    rows.append([_btn("🔙 Volver", f"wn:{chat_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def warn_limit_menu(chat_id: int, current: int) -> InlineKeyboardMarkup:
    btns = [_btn(f"{v}{_check(v == current)}", f"wnlim:{chat_id}:{v}") for v in WARN_LIMIT_OPTIONS]
    return InlineKeyboardMarkup(inline_keyboard=[
        *_rows(btns, per_row=4),
        [_btn("🔙 Volver", f"wn:{chat_id}")],
    ])


def warn_expiration_menu(chat_id: int, current: int) -> InlineKeyboardMarkup:
    btns = [_btn(f"{v}d{_check(v == current)}", f"wnexp:{chat_id}:{v}") for v in WARN_EXPIRATION_OPTIONS]
    return InlineKeyboardMarkup(inline_keyboard=[
        *_rows(btns, per_row=4),
        [_btn("🔙 Volver", f"wn:{chat_id}")],
    ])


def warn_final_menu(chat_id: int, current: int) -> InlineKeyboardMarkup:
    rows = []
    for code in (4, 5, 6):
        emoji, label = PUNISHMENT_TYPES[code]
        rows.append([_btn(f"{emoji} {label}{_check(code == current)}", f"wnfin:{chat_id}:{code}")])
    rows.append([_btn("🔙 Volver", f"wn:{chat_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# === OPCIONES AVANZADAS ===

def advanced_menu(cfg: dict) -> InlineKeyboardMarkup:
    chat_id = cfg["chat_id"]
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn(f"🔒 Solo admins en menú: {'✅' if cfg['admin_only_menu'] else '❌'}",
              f"advt:{chat_id}:admin_only_menu")],
        [_btn(f"🤫 Modo silencio total: {'✅' if cfg['silence_mode'] else '❌'}",
              f"advt:{chat_id}:silence_mode")],
        [_btn(f"🗂️ Auto-limpieza: {cfg['autoclean_days']} días", f"advac:{chat_id}")],
        [_btn("🔄 Resetear cola actual", f"rstq:{chat_id}")],
        [_btn("⚠️ Restaurar valores por defecto", f"reset:{chat_id}")],
        [_back(chat_id)],
    ])


def autoclean_menu(chat_id: int, current: int) -> InlineKeyboardMarkup:
    btns = [_btn(f"{v}d{_check(v == current)}", f"advacs:{chat_id}:{v}") for v in AUTOCLEAN_OPTIONS]
    return InlineKeyboardMarkup(inline_keyboard=[
        *_rows(btns, per_row=4),
        [_btn("🔙 Volver", f"adv:{chat_id}")],
    ])


# === CONFIRMACIONES ===

def confirm_reset_queue(chat_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("✅ Sí, vaciar cola", f"rstqok:{chat_id}")],
        [_btn("❌ Cancelar", f"adv:{chat_id}")],
    ])


def confirm_reset_config(chat_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("✅ Sí, restaurar defaults", f"resetok:{chat_id}")],
        [_btn("❌ Cancelar", f"adv:{chat_id}")],
    ])


# === SELECTOR DE GRUPO (privado) ===

def group_selector(chats: list[dict]) -> InlineKeyboardMarkup:
    rows = []
    for chat in chats:
        title = (chat.get("chat_title") or f"Grupo {chat['chat_id']}")[:40]
        rows.append([_btn(f"📍 {title}", f"selg:{chat['chat_id']}")])
    rows.append([_close()])
    return InlineKeyboardMarkup(inline_keyboard=rows)
