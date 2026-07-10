"""Teclados del panel de admin (owner)."""
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from config import LICENSE_EXTEND_OPTIONS


def admin_main_menu() -> InlineKeyboardMarkup:
    """Menú principal del panel del owner."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Todos los grupos", callback_data="adml:all")],
        [InlineKeyboardButton(text="⏳ Pendientes", callback_data="adml:pending"),
         InlineKeyboardButton(text="✅ Activos", callback_data="adml:active")],
        [InlineKeyboardButton(text="❌ Expirados", callback_data="adml:expired"),
         InlineKeyboardButton(text="🚫 Vetados", callback_data="adml:banned")],
        [InlineKeyboardButton(text="📊 Refrescar resumen", callback_data="admdash")],
    ])


def license_actions_menu(chat_id: int) -> InlineKeyboardMarkup:
    """Acciones sobre una licencia concreta."""
    rows = []
    # Botones de extensión
    pair = []
    for days in LICENSE_EXTEND_OPTIONS:
        pair.append(InlineKeyboardButton(
            text=f"+{days}d", callback_data=f"licext:{chat_id}:{days}",
        ))
        if len(pair) == 4:
            rows.append(pair)
            pair = []
    if pair:
        rows.append(pair)
    rows.append([
        InlineKeyboardButton(text="♾️ De por vida", callback_data=f"liclife:{chat_id}"),
    ])
    rows.append([
        InlineKeyboardButton(text="⏳ Marcar pendiente", callback_data=f"licdeact:{chat_id}"),
        InlineKeyboardButton(text="🚫 Vetar", callback_data=f"licban:{chat_id}"),
    ])
    rows.append([
        InlineKeyboardButton(text="🚪 Sacar el bot", callback_data=f"licleave:{chat_id}"),
    ])
    rows.append([
        InlineKeyboardButton(text="🔙 Volver al panel", callback_data="admdash"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def license_list_menu(licenses_list: list[dict], status_filter: str | None = None) -> InlineKeyboardMarkup:
    """Lista de grupos clicables para abrir su detalle."""
    rows = []
    for lic in licenses_list[:40]:
        title = (lic.get("chat_title") or f"Chat {lic['chat_id']}")[:30]
        emoji = {
            "owner": "👑", "active": "✅", "pending": "⏳",
            "expired": "❌", "banned": "🚫",
        }.get(lic.get("status"), "❓")
        rows.append([InlineKeyboardButton(
            text=f"{emoji} {title}", callback_data=f"licinfo:{lic['chat_id']}",
        )])
    rows.append([InlineKeyboardButton(text="🔙 Volver al panel", callback_data="admdash")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
