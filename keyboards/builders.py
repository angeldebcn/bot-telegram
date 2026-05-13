"""
Constructores de teclados inline para todos los menús.

Convención de callback_data (compacto, < 64 bytes):
  m:{chat_id}            menú principal
  q/cd/ad/ph:{chat_id}   submenús regla
  qs/cds/ads/phs         setters
  qc/cdc/adc             pedir valor personalizado
  qen/cden/aden          toggle regla activada
  al/alclr/alclrok       alianzas
  st                     stats
  pun + punq/puncd/punad  castigos
  punqs/puncds/punads
  nq/ncd/nad + nqs/ncds/nads        notice duration
  mq/mcd/mad + mqs/mcds/mads        mute duration
  wn + wnlim/wnexp/wnfin/wnfmute    warns
  adv + advt + advac + advacs       avanzadas
  rstq/rstqok                       reset cola
  reset/resetok                     reset config
  selg                              selector grupo
  filt                              menú filtros
  filtp:{chat_id}:{page}            página de filtros
  filtt:{chat_id}:{field}           submenú de un filtro
  filts:{chat_id}:{field}:{action}  setter de filtro
  hlp                               ayuda dentro del menú
  cls                               cerrar
"""
from typing import Any

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from config import (
    ANTIDUP_OPTIONS,
    AUTOCLEAN_OPTIONS,
    COOLDOWN_OPTIONS,
    FILTER_ACTIONS,
    FILTER_TYPES,
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


def _human_min(minutes: int) -> str:
    if minutes < 60:
        return f"{minutes} min"
    if minutes % 60 == 0:
        return f"{minutes // 60}h"
    return f"{minutes // 60}h{minutes % 60}m"


# === MENÚ PRINCIPAL ===

def main_menu(cfg: dict[str, Any]) -> InlineKeyboardMarkup:
    chat_id = cfg["chat_id"]
    locked = int(cfg.get("locked", 0))
    q_on = int(cfg.get("queue_enabled", 1))
    cd_on = int(cfg.get("cooldown_enabled", 1))
    ad_on = int(cfg.get("antidup_enabled", 1))

    def state(enabled: bool, label_active: str, label_off: str = "❌ Off") -> str:
        return label_active if enabled else label_off

    rows = []
    if locked:
        rows.append([_btn("🔕 BOT EN PAUSA · pulsa para reanudar", f"lk:{chat_id}")])

    queue_size = cfg["queue_size"]
    cooldown_min = int(cfg["cooldown_minutes"])
    antidup_h = cfg["antidup_hours"]
    cola_label = state(bool(q_on), f"{queue_size} chicas")
    cd_label = state(bool(cd_on), _human_min(cooldown_min))
    ad_label = state(bool(ad_on), f"{antidup_h}h")

    # Contador de tipos activos (para mostrarlo en el botón)
    from config import COUNTABLE_TYPES
    countable_on = sum(1 for _, _, field, _ in COUNTABLE_TYPES if int(cfg.get(field, 0)))
    countable_total = len(COUNTABLE_TYPES)

    rows.extend([
        [_btn(f"🔄 Cola · {cola_label}", f"q:{chat_id}")],
        [_btn(f"⏱️ Cooldown · {cd_label}", f"cd:{chat_id}")],
        [_btn(f"🖼️ Anti-duplicado · {ad_label}", f"ad:{chat_id}")],
        [_btn("⚖️ Castigos", f"pun:{chat_id}"),
         _btn("⚠️ Warns", f"wn:{chat_id}")],
        [_btn(f"🎯 Tipos sujetos a reglas · {countable_on}/{countable_total}",
              f"cnt:{chat_id}")],
        [_btn("👥 Alianzas", f"al:{chat_id}"),
         _btn("📊 Estadísticas", f"st:{chat_id}")],
        [_btn("⚙️ Opciones avanzadas", f"adv:{chat_id}")],
        [_btn("📚 Ayuda y comandos", "hlp"),
         _close()],
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# === SUBMENÚ COLA ===

def queue_menu(chat_id: int, current: int, enabled: bool) -> InlineKeyboardMarkup:
    toggle_label = "✅ Activada · pulsa para desactivar" if enabled else "❌ Desactivada · pulsa para activar"
    btns = [_btn(f"{v}{_check(v == current)}", f"qs:{chat_id}:{v}") for v in QUEUE_OPTIONS]
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn(toggle_label, f"qen:{chat_id}")],
        *_rows(btns, per_row=4),
        [_btn("✏️ Valor personalizado (1-50)", f"qc:{chat_id}")],
        [_back(chat_id)],
    ])


def cooldown_menu(chat_id: int, current: int, enabled: bool) -> InlineKeyboardMarkup:
    toggle_label = "✅ Activado · pulsa para desactivar" if enabled else "❌ Desactivado · pulsa para activar"
    btns = [_btn(f"{_human_min(v)}{_check(v == current)}", f"cds:{chat_id}:{v}") for v in COOLDOWN_OPTIONS]
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn(toggle_label, f"cden:{chat_id}")],
        *_rows(btns, per_row=4),
        [_btn("✏️ Valor personalizado (1-1440 min)", f"cdc:{chat_id}")],
        [_back(chat_id)],
    ])


def antidup_menu(chat_id: int, current_hours: int, enabled: bool) -> InlineKeyboardMarkup:
    toggle_label = "✅ Activado · pulsa para desactivar" if enabled else "❌ Desactivado · pulsa para activar"
    btns = [_btn(f"{v}h{_check(v == current_hours)}", f"ads:{chat_id}:{v}") for v in ANTIDUP_OPTIONS]
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn(toggle_label, f"aden:{chat_id}")],
        *_rows(btns, per_row=4),
        [_btn("✏️ Valor personalizado (1-168h)", f"adc:{chat_id}")],
        [_btn("🎯 Ajustar sensibilidad", f"ph:{chat_id}")],
        [_back(chat_id)],
    ])


def phash_menu(chat_id: int, current: int) -> InlineKeyboardMarkup:
    rows = [[_btn(f"{label} ({v}){_check(v == current)}", f"phs:{chat_id}:{v}")] for v, label in PHASH_OPTIONS]
    rows.append([_btn("🔙 Volver", f"ad:{chat_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# === ALIANZAS ===

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


# === ESTADÍSTICAS ===

def stats_menu(chat_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("🔄 Actualizar", f"st:{chat_id}")],
        [_back(chat_id)],
    ])


# === CASTIGOS ===

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
    setter = {"punq": "punqs", "puncd": "puncds", "punad": "punads"}[rule_key]
    rows = []
    for code, (emoji, label) in PUNISHMENT_TYPES.items():
        rows.append([_btn(
            f"{emoji} {label}{_check(code == current)}",
            f"{setter}:{chat_id}:{code}",
        )])
    notice_key = {"punq": "nq", "puncd": "ncd", "punad": "nad"}[rule_key]
    mute_key = {"punq": "mq", "puncd": "mcd", "punad": "mad"}[rule_key]
    if current == 2:
        rows.append([_btn("⏲️ Duración del aviso", f"{notice_key}:{chat_id}")])
    if current == 4:
        rows.append([_btn("⏲️ Duración del mute", f"{mute_key}:{chat_id}")])
    rows.append([_btn("🔙 Volver", f"pun:{chat_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def notice_duration_menu(chat_id: int, rule_key: str, current: int) -> InlineKeyboardMarkup:
    setter = {"nq": "nqs", "ncd": "ncds", "nad": "nads"}[rule_key]
    back_to = {"nq": "punq", "ncd": "puncd", "nad": "punad"}[rule_key]
    btns = []
    for v in NOTICE_DURATION_OPTIONS:
        label = "♾️ Permanente" if v == 0 else f"{v}s"
        btns.append(_btn(f"{label}{_check(v == current)}", f"{setter}:{chat_id}:{v}"))
    return InlineKeyboardMarkup(inline_keyboard=[
        *_rows(btns, per_row=3),
        [_btn("🔙 Volver", f"{back_to}:{chat_id}")],
    ])


def mute_duration_menu(chat_id: int, rule_key: str, current: int) -> InlineKeyboardMarkup:
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


# === WARNS ===

def warns_menu(cfg: dict) -> InlineKeyboardMarkup:
    chat_id = cfg["chat_id"]
    final_action = int(cfg["warn_final_action"])
    rows = [
        [_btn(f"⚠️ Límite · {cfg['warn_limit']} warns", f"wnlim:{chat_id}:0")],
        [_btn(f"📅 Expiración · {cfg['warn_expiration_days']} días", f"wnexp:{chat_id}:0")],
        [_btn(f"🚨 Acción final · {PUNISHMENT_TYPES[final_action][1]}", f"wnfin:{chat_id}:0")],
    ]
    if final_action == 4:
        from utils.helpers import format_duration
        rows.append([_btn(
            f"⏲️ Duración mute final · {format_duration(int(cfg['warn_final_mute_seconds']))}",
            f"wnfmute:{chat_id}:0",
        )])
    rows.append([_back(chat_id)])
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


def warn_final_mute_menu(chat_id: int, current: int) -> InlineKeyboardMarkup:
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


# === AVANZADAS ===

def advanced_menu(cfg: dict) -> InlineKeyboardMarkup:
    chat_id = cfg["chat_id"]
    autoclean_days = int(cfg["autoclean_days"])
    autoclean_label = "Nunca" if autoclean_days == 0 else f"{autoclean_days} días"
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn(
            f"🔒 Solo admins en menú: {'✅' if cfg['admin_only_menu'] else '❌'}",
            f"advt:{chat_id}:admin_only_menu",
        )],
        [_btn(
            f"🤫 Modo silencio total: {'✅' if cfg['silence_mode'] else '❌'}",
            f"advt:{chat_id}:silence_mode",
        )],
        [_btn(
            f"🧹 Borrar mensajes de servicio: {'✅' if cfg['delete_service_messages'] else '❌'}",
            f"advt:{chat_id}:delete_service_messages",
        )],
        [_btn(f"🗂️ Auto-limpieza: {autoclean_label}", f"advac:{chat_id}")],
        [_btn("🔄 Resetear cola actual", f"rstq:{chat_id}")],
        [_btn("⚠️ Restaurar valores por defecto", f"reset:{chat_id}")],
        [_back(chat_id)],
    ])


def autoclean_menu(chat_id: int, current: int) -> InlineKeyboardMarkup:
    btns = []
    for v in AUTOCLEAN_OPTIONS:
        label = "Nunca" if v == 0 else f"{v}d"
        btns.append(_btn(f"{label}{_check(v == current)}", f"advacs:{chat_id}:{v}"))
    return InlineKeyboardMarkup(inline_keyboard=[
        *_rows(btns, per_row=4),
        [_btn("🔙 Volver", f"adv:{chat_id}")],
    ])


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


# === FILTROS DE TIPOS DE CONTENIDO (estilo GroupHelp) ===

FILTERS_PER_PAGE = 8


def filter_main_menu(cfg: dict, page: int = 0) -> InlineKeyboardMarkup:
    """Menú principal de filtros con paginación."""
    chat_id = cfg["chat_id"]
    total_pages = (len(FILTER_TYPES) + FILTERS_PER_PAGE - 1) // FILTERS_PER_PAGE
    start = page * FILTERS_PER_PAGE
    end = start + FILTERS_PER_PAGE
    items = FILTER_TYPES[start:end]

    rows = []
    for emoji, label, field in items:
        current = int(cfg.get(field, 0))
        action_emoji, action_label = FILTER_ACTIONS[current]
        rows.append([_btn(
            f"{emoji} {label} · {action_emoji} {action_label}",
            f"filtt:{chat_id}:{field}",
        )])

    # Navegación paginada
    nav = []
    if page > 0:
        nav.append(_btn("⬅️ Anterior", f"filt:{chat_id}:{page - 1}"))
    if page < total_pages - 1:
        nav.append(_btn("Siguiente ➡️", f"filt:{chat_id}:{page + 1}"))
    if nav:
        rows.append(nav)

    rows.append([_back(chat_id)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def filter_action_menu(chat_id: int, field: str, current: int, page: int = 0) -> InlineKeyboardMarkup:
    """Submenú de un filtro: elegir acción."""
    rows = []
    for action, (emoji, label) in FILTER_ACTIONS.items():
        rows.append([_btn(
            f"{emoji} {label}{_check(action == current)}",
            f"filts:{chat_id}:{field}:{action}",
        )])
    rows.append([_btn("🔙 Volver a filtros", f"filt:{chat_id}:{page}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# === TIPOS SUJETOS A LAS 3 REGLAS ===

def countable_menu(cfg: dict) -> InlineKeyboardMarkup:
    """
    Menú donde el admin activa/desactiva qué tipos cuentan como publicación.

    Cada tipo es un toggle. Si está ON, ese tipo pasa por las 3 reglas
    (cola/cooldown/antidup). Si está OFF, el bot lo ignora completamente.
    """
    from config import COUNTABLE_TYPES
    chat_id = cfg["chat_id"]
    rows = []
    for emoji, label, field, supports_antidup in COUNTABLE_TYPES:
        active = bool(int(cfg.get(field, 0)))
        state_icon = "✅" if active else "⬜"
        antidup_mark = "" if supports_antidup else " *"
        rows.append([_btn(
            f"{state_icon} {emoji} {label}{antidup_mark}",
            f"cntt:{chat_id}:{field}",
        )])
    rows.append([_back(chat_id)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# === Ayuda dentro del menú ===

def help_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_close()],
    ])
