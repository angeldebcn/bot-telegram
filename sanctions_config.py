"""
=====================================================================
PANEL DE CONFIGURACIÓN DEL SISTEMA DE SANCIONES (solo owner)
=====================================================================

Comando: /config  (solo el owner, en privado con el bot)

Dos secciones:

1. ROLES DE GRUPOS
   Para cada grupo donde está el bot, el owner marca con botones:
   - 🎯 Grupo de verificadas (donde se usa /reporte)
   - 👮 Grupo de staff (donde llegan reportes + botones + listas)
   - 📋 Aplican las 3 reglas (cola/cooldown/antidup) aquí
   - 🛡️ Se ejecutan mutes/bans aquí

2. STAFF
   El owner ve la lista blanca de staff y puede añadir/quitar personas.
   Para añadir: se reenvía un mensaje de la persona, o se usa /addstaff.

Todo con botones. El owner navega: /config -> elige sección -> elige grupo
-> activa/desactiva flags.
"""
import logging
from typing import Optional

from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from config import OWNER_USER_ID
import roles_db
from stats import cache_user, list_bot_chats

logger = logging.getLogger(__name__)
router = Router(name="sanctions_config")


# ===========================================================================
# HELPERS
# ===========================================================================
def _is_owner(user_id: Optional[int]) -> bool:
    return OWNER_USER_ID is not None and user_id == OWNER_USER_ID


def _is_private(message: Message) -> bool:
    return message.chat.type == ChatType.PRIVATE


def _check(active: bool) -> str:
    return "✅" if active else "⬜"


def _short_title(title: Optional[str], chat_id: int) -> str:
    if title:
        return title[:30]
    return f"Grupo {chat_id}"


# ===========================================================================
# MENÚ PRINCIPAL DE /config
# ===========================================================================
def _main_config_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏷️ Roles de grupos", callback_data="cfg:groups")],
        [InlineKeyboardButton(text="👮 Gestionar staff", callback_data="cfg:staff")],
        [InlineKeyboardButton(text="❌ Cerrar", callback_data="cfg:close")],
    ])


@router.message(Command("config", "configurar", "ajustes"))
async def cmd_config(message: Message, bot: Bot) -> None:
    if not message.from_user or not _is_owner(message.from_user.id):
        # Silencio total: si no es el owner, ni respondemos (es un panel privado)
        return
    if not _is_private(message):
        await message.reply(
            "🔐 Este panel es privado. Escríbeme <b>por privado</b> /config."
        )
        return

    text = (
        "⚙️ <b>PANEL DE CONFIGURACIÓN</b>\n\n"
        "Desde aquí configuras el sistema de sanciones de la comunidad.\n\n"
        "🏷️ <b>Roles de grupos</b>: marca qué grupo es el de verificadas, "
        "cuál el de staff, y dónde aplican las reglas y sanciones.\n\n"
        "👮 <b>Gestionar staff</b>: quién puede usar los comandos de sanción."
    )
    await message.answer(text, reply_markup=_main_config_menu())


@router.callback_query(F.data == "cfg:close")
async def cb_config_close(cb: CallbackQuery, bot: Bot) -> None:
    if not _is_owner(cb.from_user.id):
        await cb.answer()
        return
    try:
        await cb.message.delete()
    except TelegramBadRequest:
        pass
    await cb.answer("Cerrado")


@router.callback_query(F.data == "cfg:main")
async def cb_config_main(cb: CallbackQuery, bot: Bot) -> None:
    if not _is_owner(cb.from_user.id):
        await cb.answer()
        return
    text = (
        "⚙️ <b>PANEL DE CONFIGURACIÓN</b>\n\n"
        "🏷️ <b>Roles de grupos</b>: marca qué grupo es el de verificadas, "
        "cuál el de staff, y dónde aplican las reglas y sanciones.\n\n"
        "👮 <b>Gestionar staff</b>: quién puede usar los comandos de sanción."
    )
    try:
        await cb.message.edit_text(text, reply_markup=_main_config_menu())
    except TelegramBadRequest:
        pass
    await cb.answer()


# ===========================================================================
# SECCIÓN: ROLES DE GRUPOS
# ===========================================================================
async def _groups_menu() -> InlineKeyboardMarkup:
    """Lista de grupos donde está el bot, para elegir cuál configurar."""
    chats = await list_bot_chats()
    rows = []
    for chat in chats:
        cid = chat["chat_id"]
        title = _short_title(chat.get("chat_title"), cid)
        chat_type = chat.get("chat_type", "supergroup")
        # Mostrar iconos de rol actual junto al nombre
        roles = await roles_db.get_group_roles(cid)
        marcas = ""
        if chat_type == "channel":
            marcas += "📢"
        if roles.get("is_verified_group"):
            marcas += "🎯"
        if roles.get("is_staff_group"):
            marcas += "👮"
        if roles.get("applies_sanctions") and chat_type == "channel":
            marcas += "🛡️"
        label = f"{title} {marcas}".strip()
        rows.append([InlineKeyboardButton(text=label, callback_data=f"cfg:grp:{cid}")])
    rows.append([InlineKeyboardButton(text="🔙 Volver", callback_data="cfg:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(F.data == "cfg:groups")
async def cb_config_groups(cb: CallbackQuery, bot: Bot) -> None:
    if not _is_owner(cb.from_user.id):
        await cb.answer()
        return
    chats = await list_bot_chats()
    if not chats:
        text = (
            "🏷️ <b>ROLES DE GRUPOS</b>\n\n"
            "Todavía no tengo registrado ningún grupo. Añádeme a tus grupos "
            "y escribe algo en ellos; en cuanto te vea, aparecerán aquí."
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Volver", callback_data="cfg:main")],
        ])
    else:
        text = (
            "🏷️ <b>ROLES DE GRUPOS</b>\n\n"
            "Elige un grupo para configurar su rol.\n\n"
            "🎯 = grupo de verificadas · 👮 = grupo de staff"
        )
        kb = await _groups_menu()
    try:
        await cb.message.edit_text(text, reply_markup=kb)
    except TelegramBadRequest:
        pass
    await cb.answer()


async def _group_detail_menu(chat_id: int) -> tuple[str, InlineKeyboardMarkup]:
    """Panel de un grupo o canal concreto con sus flags."""
    roles = await roles_db.get_group_roles(chat_id)
    chats = await list_bot_chats()
    title = None
    chat_type = "supergroup"
    for c in chats:
        if c["chat_id"] == chat_id:
            title = c.get("chat_title")
            chat_type = c.get("chat_type", "supergroup")
            break
    title = _short_title(title, chat_id)

    applies_sanctions = bool(roles.get("applies_sanctions"))

    # === CANALES: panel simplificado (solo "se ejecutan sanciones") ===
    if chat_type == "channel":
        text = (
            f"📢 <b>{title}</b>  (canal)\n"
            f"🆔 <code>{chat_id}</code>\n\n"
            "En un canal solo tiene sentido una opción:\n\n"
            f"{_check(applies_sanctions)} <b>Se ejecutan sanciones</b>\n"
            "   Si está activo, cuando alguien sea baneado de la comunidad "
            "también será expulsado de este canal.\n\n"
            "<i>Nota: para que el bot pueda expulsar de un canal, debe ser "
            "administrador del canal con permiso para gestionar usuarios.</i>"
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text=f"{_check(applies_sanctions)} Se ejecutan sanciones",
                callback_data=f"cfg:flag:{chat_id}:applies_sanctions",
            )],
            [InlineKeyboardButton(text="🔙 Volver a la lista", callback_data="cfg:groups")],
        ])
        return text, kb

    # === GRUPOS: panel completo con los 4 flags ===
    is_verified = bool(roles.get("is_verified_group"))
    is_staff = bool(roles.get("is_staff_group"))
    applies_rules = bool(roles.get("applies_rules"))

    text = (
        f"🏷️ <b>{title}</b>\n"
        f"🆔 <code>{chat_id}</code>\n\n"
        "Pulsa para activar o desactivar cada rol:\n\n"
        f"{_check(is_verified)} <b>Grupo de verificadas</b>\n"
        "   Donde las chicas usan /reporte\n\n"
        f"{_check(is_staff)} <b>Grupo de staff</b>\n"
        "   Donde llegan los reportes con botones\n\n"
        f"{_check(applies_rules)} <b>Aplican las 3 reglas</b>\n"
        "   Cola / cooldown / anti-duplicado\n\n"
        f"{_check(applies_sanctions)} <b>Se ejecutan sanciones</b>\n"
        "   Aquí se aplican mutes y bans"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"{_check(is_verified)} Grupo de verificadas",
            callback_data=f"cfg:flag:{chat_id}:is_verified_group",
        )],
        [InlineKeyboardButton(
            text=f"{_check(is_staff)} Grupo de staff",
            callback_data=f"cfg:flag:{chat_id}:is_staff_group",
        )],
        [InlineKeyboardButton(
            text=f"{_check(applies_rules)} Aplican las 3 reglas",
            callback_data=f"cfg:flag:{chat_id}:applies_rules",
        )],
        [InlineKeyboardButton(
            text=f"{_check(applies_sanctions)} Se ejecutan sanciones",
            callback_data=f"cfg:flag:{chat_id}:applies_sanctions",
        )],
        [InlineKeyboardButton(text="🔙 Volver a grupos", callback_data="cfg:groups")],
    ])
    return text, kb


@router.callback_query(F.data.startswith("cfg:grp:"))
async def cb_config_group_detail(cb: CallbackQuery, bot: Bot) -> None:
    if not _is_owner(cb.from_user.id):
        await cb.answer()
        return
    chat_id = int(cb.data.split(":")[2])
    await roles_db.ensure_group(chat_id)
    text, kb = await _group_detail_menu(chat_id)
    try:
        await cb.message.edit_text(text, reply_markup=kb)
    except TelegramBadRequest:
        pass
    await cb.answer()


# Roles que son "únicos" (solo un grupo puede tenerlos): staff.
# El de verificadas puede haber varios. Aquí staff lo tratamos como único.
@router.callback_query(F.data.startswith("cfg:flag:"))
async def cb_config_toggle_flag(cb: CallbackQuery, bot: Bot) -> None:
    if not _is_owner(cb.from_user.id):
        await cb.answer()
        return
    parts = cb.data.split(":")
    chat_id = int(parts[2])
    flag = parts[3]

    roles = await roles_db.get_group_roles(chat_id)
    current = bool(roles.get(flag, 0))
    new_value = 0 if current else 1

    # El grupo de staff es único: si activamos staff aquí, quitarlo de otros
    if flag == "is_staff_group" and new_value == 1:
        # Quitar el flag de staff de cualquier otro grupo
        all_roles = await roles_db.list_all_group_roles()
        for r in all_roles:
            if r["chat_id"] != chat_id and r.get("is_staff_group"):
                await roles_db.set_group_flag(r["chat_id"], "is_staff_group", 0)

    await roles_db.set_group_flag(chat_id, flag, new_value)

    # Refrescar el panel del grupo
    text, kb = await _group_detail_menu(chat_id)
    try:
        await cb.message.edit_text(text, reply_markup=kb)
    except TelegramBadRequest:
        pass

    nombres = {
        "is_verified_group": "Grupo de verificadas",
        "is_staff_group": "Grupo de staff",
        "applies_rules": "Aplican las 3 reglas",
        "applies_sanctions": "Se ejecutan sanciones",
    }
    estado = "activado" if new_value else "desactivado"
    await cb.answer(f"{nombres.get(flag, flag)}: {estado}")


# ===========================================================================
# SECCIÓN: STAFF
# ===========================================================================
async def _staff_menu() -> tuple[str, InlineKeyboardMarkup]:
    staff = await roles_db.list_staff()
    if not staff:
        text = (
            "👮 <b>GESTIONAR STAFF</b>\n\n"
            "No hay nadie en el staff todavía (además de ti, que siempre "
            "tienes permiso).\n\n"
            "Para añadir a alguien:\n"
            "• Reenvíame un mensaje suyo, o\n"
            "• Escribe <code>/addstaff @usuario</code> o <code>/addstaff ID</code>."
        )
    else:
        lineas = ["👮 <b>GESTIONAR STAFF</b>\n"]
        lineas.append(f"Personas con permiso ({len(staff)}):\n")
        for s in staff:
            uid = s["user_id"]
            uname = s.get("username")
            fname = s.get("full_name")
            if uname:
                nombre = f"@{uname}"
            elif fname:
                nombre = fname
            else:
                nombre = f"ID {uid}"
            lineas.append(f"• {nombre} — <code>{uid}</code>")
        lineas.append(
            "\nPara añadir: reenvíame un mensaje suyo o "
            "<code>/addstaff @usuario</code>.\n"
            "Para quitar: pulsa un botón de abajo."
        )
        text = "\n".join(lineas)

    rows = []
    for s in staff:
        uid = s["user_id"]
        uname = s.get("username")
        nombre = f"@{uname}" if uname else (s.get("full_name") or f"ID {uid}")
        rows.append([InlineKeyboardButton(
            text=f"🗑️ Quitar {nombre}", callback_data=f"cfg:delstaff:{uid}",
        )])
    rows.append([InlineKeyboardButton(text="🔙 Volver", callback_data="cfg:main")])
    return text, InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(F.data == "cfg:staff")
async def cb_config_staff(cb: CallbackQuery, bot: Bot) -> None:
    if not _is_owner(cb.from_user.id):
        await cb.answer()
        return
    text, kb = await _staff_menu()
    try:
        await cb.message.edit_text(text, reply_markup=kb)
    except TelegramBadRequest:
        pass
    await cb.answer()


@router.callback_query(F.data.startswith("cfg:delstaff:"))
async def cb_config_del_staff(cb: CallbackQuery, bot: Bot) -> None:
    if not _is_owner(cb.from_user.id):
        await cb.answer()
        return
    uid = int(cb.data.split(":")[2])
    await roles_db.remove_staff(uid)
    text, kb = await _staff_menu()
    try:
        await cb.message.edit_text(text, reply_markup=kb)
    except TelegramBadRequest:
        pass
    await cb.answer("Quitado del staff")


# ===========================================================================
# /addstaff (owner) — por reenvío, @ o id
# ===========================================================================
@router.message(Command("addstaff", "añadirstaff", "agregarstaff"))
async def cmd_addstaff(message: Message, bot: Bot) -> None:
    if not message.from_user or not _is_owner(message.from_user.id):
        return

    uid = None
    username = None
    full_name = None

    # 1. Por reenvío de un mensaje suyo
    if message.forward_from:
        u = message.forward_from
        uid, username, full_name = u.id, u.username, u.full_name
    # 2. Por reply
    elif message.reply_to_message and message.reply_to_message.from_user:
        u = message.reply_to_message.from_user
        uid, username, full_name = u.id, u.username, u.full_name
    else:
        # 3. Por argumento @ o id
        parts = (message.text or "").split(maxsplit=1)
        if len(parts) < 2:
            await message.reply(
                "❌ Uso: reenvíame un mensaje de la persona, o "
                "<code>/addstaff @usuario</code> o <code>/addstaff ID</code>."
            )
            return
        token = parts[1].strip().split()[0]
        if token.startswith("@"):
            import sanctions_db
            found = await sanctions_db.resolve_username_global(token)
            if found:
                uid = found["user_id"]
                username = found.get("username")
                full_name = found.get("full_name")
            else:
                await message.reply(
                    f"❌ No encuentro a <b>{token}</b>. Reenvíame un mensaje suyo "
                    "o usa su ID numérico."
                )
                return
        elif token.lstrip("-").isdigit():
            uid = int(token)
        else:
            await message.reply("❌ No entendí. Usa @usuario o un ID numérico.")
            return

    if uid is None:
        await message.reply("❌ No pude identificar a la persona.")
        return

    if _is_owner(uid):
        await message.reply("ℹ️ Tú ya tienes todos los permisos como dueño.")
        return

    await roles_db.add_staff(uid, username, full_name, message.from_user.id)
    nombre = f"@{username}" if username else (full_name or f"ID {uid}")
    await message.reply(f"✅ {nombre} añadido al staff. Ya puede usar los comandos de sanción.")


@router.message(Command("delstaff", "quitarstaff"))
async def cmd_delstaff(message: Message, bot: Bot) -> None:
    if not message.from_user or not _is_owner(message.from_user.id):
        return

    uid = None
    if message.reply_to_message and message.reply_to_message.from_user:
        uid = message.reply_to_message.from_user.id
    else:
        parts = (message.text or "").split(maxsplit=1)
        if len(parts) < 2:
            await message.reply(
                "❌ Uso: responde a un mensaje suyo con /delstaff, o "
                "<code>/delstaff @usuario</code> o <code>/delstaff ID</code>."
            )
            return
        token = parts[1].strip().split()[0]
        if token.startswith("@"):
            import sanctions_db
            found = await sanctions_db.resolve_username_global(token)
            if found:
                uid = found["user_id"]
            else:
                await message.reply(f"❌ No encuentro a <b>{token}</b>.")
                return
        elif token.lstrip("-").isdigit():
            uid = int(token)
        else:
            await message.reply("❌ No entendí. Usa @usuario o un ID.")
            return

    removed = await roles_db.remove_staff(uid)
    if removed:
        await message.reply("✅ Quitado del staff.")
    else:
        await message.reply("ℹ️ Esa persona no estaba en el staff.")
