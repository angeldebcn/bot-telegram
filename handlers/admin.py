"""
Panel /admin del owner. Solo accesible para OWNER_USER_ID.

Comandos:
- /admin           → panel principal
- /admin help      → lista de subcomandos
- /admin list      → lista todas las licencias
- /admin activate <chat_id> <días>  → activar X días
- /admin lifetime <chat_id>         → activación permanente
- /admin deactivate <chat_id>       → desactivar (vuelve a pending)
- /admin ban <chat_id>              → vetar
- /admin info <chat_id>             → detalles
- /admin leave <chat_id>            → bot sale del grupo
"""
import logging
from datetime import datetime
from typing import Optional

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import Message

from config import LICENSE_EXTEND_OPTIONS, SUBSCRIPTION_PRICE_EUR
from database import licenses as licenses_db
from database.stats import list_bot_chats
from keyboards.admin_builders import admin_main_menu, license_actions_menu
from utils.license_helpers import format_license_status, is_owner

logger = logging.getLogger(__name__)
router = Router(name="admin")


def _owner_only(message: Message) -> bool:
    if not message.from_user or not is_owner(message.from_user.id):
        return False
    return True


async def _build_dashboard_text() -> str:
    """Construye el texto del panel principal con stats."""
    counts = await licenses_db.count_by_status()
    active = counts.get("active", 0)
    owner = counts.get("owner", 0)
    pending = counts.get("pending", 0)
    expired = counts.get("expired", 0)
    banned = counts.get("banned", 0)
    income = active * SUBSCRIPTION_PRICE_EUR
    return (
        "👑 <b>PANEL DE OWNER</b>\n\n"
        "📊 <b>Resumen:</b>\n"
        f"  ✅ Activos: <b>{active}</b>\n"
        f"  👑 Tuyos (propietario): <b>{owner}</b>\n"
        f"  ⏳ Pendientes: <b>{pending}</b>\n"
        f"  ❌ Expirados: <b>{expired}</b>\n"
        f"  🚫 Vetados: <b>{banned}</b>\n\n"
        f"💎 <b>Ingresos brutos est.</b>: {income:.2f} €/mes "
        f"(× {SUBSCRIPTION_PRICE_EUR:.2f} € de suscripción)\n\n"
        "Usa los botones para gestionar grupos."
    )


@router.message(Command("admin"))
async def cmd_admin(message: Message, bot: Bot) -> None:
    if not _owner_only(message):
        # Silencioso para no exponer la existencia del comando
        return
    text = _command_args = (message.text or "").split(maxsplit=2)
    args = (message.text or "").split()[1:] if message.text else []

    # Sin argumentos → dashboard con botones
    if not args:
        text = await _build_dashboard_text()
        await message.answer(text, reply_markup=admin_main_menu())
        return

    sub = args[0].lower()

    if sub in ("help", "ayuda", "?"):
        await message.answer(
            "👑 <b>SUBCOMANDOS DE ADMIN</b>\n\n"
            "<code>/admin</code> — Panel con botones\n"
            "<code>/admin list</code> — Lista grupos\n"
            "<code>/admin list pending</code> — Solo pendientes\n"
            "<code>/admin list active</code> — Solo activos\n"
            "<code>/admin activate &lt;chat_id&gt; &lt;días&gt;</code>\n"
            "<code>/admin lifetime &lt;chat_id&gt;</code>\n"
            "<code>/admin deactivate &lt;chat_id&gt;</code>\n"
            "<code>/admin ban &lt;chat_id&gt;</code>\n"
            "<code>/admin info &lt;chat_id&gt;</code>\n"
            "<code>/admin leave &lt;chat_id&gt;</code>\n\n"
            "💡 Lo más cómodo: usa /admin sin args y navega con botones."
        )
        return

    if sub == "list":
        filt = args[1] if len(args) > 1 else None
        await _send_license_list(message, filt)
        return

    if sub == "info" and len(args) >= 2:
        chat_id = _parse_chat_id(args[1])
        if chat_id is None:
            await message.answer("❌ Chat ID inválido.")
            return
        await _send_license_info(message, chat_id)
        return

    if sub == "activate" and len(args) >= 3:
        chat_id = _parse_chat_id(args[1])
        try:
            days = int(args[2])
        except ValueError:
            await message.answer("❌ Días inválidos.")
            return
        if chat_id is None or days <= 0:
            await message.answer("❌ Parámetros inválidos.")
            return
        exp = await licenses_db.extend(chat_id, days, activated_by=message.from_user.id)
        await message.answer(
            f"✅ Activado <code>{chat_id}</code> hasta <b>{exp.strftime('%d/%m/%Y')}</b>."
        )
        await _notify_chat_activated(bot, chat_id)
        return

    if sub == "lifetime" and len(args) >= 2:
        chat_id = _parse_chat_id(args[1])
        if chat_id is None:
            await message.answer("❌ Chat ID inválido.")
            return
        await licenses_db.set_lifetime(chat_id, activated_by=message.from_user.id)
        await message.answer(f"♾️ Activado de por vida <code>{chat_id}</code>.")
        await _notify_chat_activated(bot, chat_id, lifetime=True)
        return

    if sub == "deactivate" and len(args) >= 2:
        chat_id = _parse_chat_id(args[1])
        if chat_id is None:
            await message.answer("❌ Chat ID inválido.")
            return
        await licenses_db.set_status(chat_id, "pending")
        await message.answer(f"⏳ Desactivado <code>{chat_id}</code>.")
        return

    if sub == "ban" and len(args) >= 2:
        chat_id = _parse_chat_id(args[1])
        if chat_id is None:
            await message.answer("❌ Chat ID inválido.")
            return
        await licenses_db.set_status(chat_id, "banned")
        await message.answer(f"🚫 Vetado <code>{chat_id}</code>.")
        return

    if sub == "leave" and len(args) >= 2:
        chat_id = _parse_chat_id(args[1])
        if chat_id is None:
            await message.answer("❌ Chat ID inválido.")
            return
        try:
            await bot.leave_chat(chat_id)
            await message.answer(f"🚪 Bot salido de <code>{chat_id}</code>.")
        except Exception as e:
            await message.answer(f"❌ Error: {e}")
        return

    await message.answer("❌ Subcomando desconocido. Usa <code>/admin help</code>.")


def _parse_chat_id(s: str) -> Optional[int]:
    try:
        return int(s)
    except ValueError:
        return None


async def _notify_chat_activated(
    bot: Bot, chat_id: int, lifetime: bool = False,
) -> None:
    """Avisa al grupo de que su suscripción está activa."""
    from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
    lic = await licenses_db.get_license(chat_id)
    if not lic:
        return
    text = "✅ <b>¡Bot activado en este grupo!</b>\n\n"
    if lifetime:
        text += "♾️ Tienes acceso <b>permanente</b>.\n\n"
    elif lic.get("expires_at"):
        text += f"📅 Suscripción válida hasta: <code>{lic['expires_at'][:10]}</code>\n\n"
    text += "Usa /menu para empezar a configurar las reglas."
    try:
        await bot.send_message(chat_id, text)
    except (TelegramBadRequest, TelegramForbiddenError):
        pass


async def _send_license_list(message: Message, status_filter: Optional[str] = None) -> None:
    if status_filter and status_filter not in licenses_db.VALID_STATUSES:
        await message.answer(
            f"❌ Filtro inválido. Usa uno de: {', '.join(licenses_db.VALID_STATUSES)}"
        )
        return
    items = await licenses_db.list_licenses(status_filter)
    if not items:
        await message.answer("📭 No hay licencias para mostrar.")
        return
    lines = ["📋 <b>Licencias</b>", ""]
    for lic in items[:50]:
        title = (lic.get("chat_title") or f"Chat {lic['chat_id']}")[:40]
        status_text = format_license_status(lic)
        lines.append(f"• <b>{title}</b>")
        lines.append(f"   <code>{lic['chat_id']}</code> · {status_text}")
        lines.append("")
    if len(items) > 50:
        lines.append(f"<i>... y {len(items) - 50} más</i>")
    await message.answer("\n".join(lines))


async def _send_license_info(message: Message, chat_id: int) -> None:
    lic = await licenses_db.get_license(chat_id)
    if not lic:
        await message.answer(f"📭 No hay licencia para <code>{chat_id}</code>.")
        return
    title = lic.get("chat_title") or f"Chat {chat_id}"
    text = (
        f"📍 <b>{title}</b>\n"
        f"🆔 <code>{chat_id}</code>\n\n"
        f"{format_license_status(lic)}\n\n"
    )
    if lic.get("added_by_username"):
        text += f"👤 Añadido por: @{lic['added_by_username']} (<code>{lic.get('added_by_user_id')}</code>)\n"
    elif lic.get("added_by_user_id"):
        text += f"👤 Añadido por: <code>{lic['added_by_user_id']}</code>\n"
    if lic.get("activated_at"):
        text += f"📅 Activado: <code>{lic['activated_at'][:16]}</code>\n"
    if lic.get("expires_at"):
        text += f"⏰ Expira: <code>{lic['expires_at'][:16]}</code>\n"
    await message.answer(text, reply_markup=license_actions_menu(chat_id))
