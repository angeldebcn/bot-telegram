"""
=====================================================================
PANELES DE CONSULTA (solo staff + owner)
=====================================================================

Tres comandos:

  /lista       -> lista de todas las personas sancionadas, agrupadas en
                  Warn leve / Warn grave / Ban, con paginación ◀️ ▶️.
                  Cada ficha: perfil (@ clicable), nombre (clicable), ID,
                  razón corta profesional, puntos y tiempo de expiración.

  /buscar @/id -> la ficha de una persona concreta (razón + expiración +
                  puntos + cuánto falta para el ban).

  /pendientes  -> reportes que nadie ha resuelto todavía, con el perfil de
                  quien reportó y un enlace para saltar al mensaje original.

La lista puede ser muy larga, así que se pagina: se trocea en páginas y se
navega con botones. El estado de la página va en el callback_data.
"""
import logging
from typing import Optional

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from config import OWNER_USER_ID
import sanctions_db
import roles_db
from sanctions_text import format_points_status, format_time_left

logger = logging.getLogger(__name__)
router = Router(name="sanctions_panels")

# Cuántas fichas por página
FICHAS_POR_PAGINA = 8


# ===========================================================================
# HELPERS
# ===========================================================================
async def _is_staff_or_owner(user_id: int) -> bool:
    if OWNER_USER_ID is not None and user_id == OWNER_USER_ID:
        return True
    return await roles_db.is_staff(user_id)


def _split_args(message: Message) -> Optional[str]:
    if not message.text:
        return None
    parts = message.text.split(maxsplit=1)
    return parts[1] if len(parts) > 1 else None


def _mention(user_id: int, username: Optional[str], full_name: Optional[str]) -> str:
    if full_name:
        name = full_name
    elif username:
        name = f"@{username}"
    else:
        name = f"id {user_id}"
    name = name.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return f'<a href="tg://user?id={user_id}">{name}</a>'


def _ficha_line(ficha: dict, categoria: str) -> str:
    """Una línea/bloque de la lista para una persona."""
    uid = ficha["user_id"]
    username = ficha.get("username")
    full_name = ficha.get("full_name")

    # Perfil clicable (@ si tiene) + nombre clicable
    partes = []
    if username:
        partes.append(f'<a href="tg://user?id={uid}">@{username}</a>')
    if full_name:
        safe_name = full_name.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        partes.append(f'<a href="tg://user?id={uid}">{safe_name}</a>')
    perfil = " | ".join(partes) if partes else "(sin nombre)"

    linea = f"• {perfil}\n  🆔 <code>{uid}</code>\n  📋 {ficha['reason_short']}"

    if categoria != "ban":
        tleft = format_time_left(ficha.get("expires_at"))
        if tleft and tleft != "expirado":
            linea += f"\n  ⏳ Expira en {tleft}"
        # cuántos puntos / cuánto falta
        pts = ficha.get("points", 0)
        faltan = max(0, sanctions_db.POINTS_BAN_THRESHOLD - pts)
        if faltan == 1:
            linea += f"\n  ⚠️ {pts}/3 puntos · falta 1 para el baneo"
        else:
            linea += f"\n  ⚠️ {pts}/3 puntos · faltan {faltan} para el baneo"
    return linea


def _build_list_pages(data: dict) -> list[str]:
    """
    Construye las páginas de texto de la lista completa.
    Devuelve una lista de strings (cada uno es una página).
    """
    # Construir todos los bloques en orden: ban, grave, leve
    secciones = [
        ("ban", "🚫 <b>BANEADOS</b>"),
        ("grave", "⛔ <b>WARN GRAVE</b>"),
        ("leve", "⚠️ <b>WARN LEVE</b>"),
    ]

    # Aplanar en una lista de "items", insertando cabeceras de sección
    items: list[str] = []
    for key, titulo in secciones:
        fichas = data.get(key, [])
        if not fichas:
            continue
        items.append(f"__SECTION__{titulo} ({len(fichas)})")
        for f in fichas:
            items.append(_ficha_line(f, key))

    if not items:
        return ["📋 <b>LISTA DE PERSONAS REPORTADAS</b>\n\nNo hay nadie sancionado ahora mismo. 🎉"]

    # Paginar: agrupamos fichas (no cabeceras) hasta FICHAS_POR_PAGINA
    pages: list[str] = []
    current: list[str] = []
    ficha_count = 0

    for item in items:
        is_header = item.startswith("__SECTION__")
        if is_header:
            current.append(item.replace("__SECTION__", ""))
        else:
            if ficha_count >= FICHAS_POR_PAGINA:
                pages.append("\n\n".join(current))
                current = []
                ficha_count = 0
            current.append(item)
            ficha_count += 1

    if current:
        pages.append("\n\n".join(current))

    # Añadir cabecera general a cada página
    total = len(pages)
    final_pages = []
    for i, p in enumerate(pages, 1):
        header = f"📋 <b>PERSONAS REPORTADAS EN MALA STUDIOS</b>  ·  Página {i}/{total}\n"
        final_pages.append(header + "\n" + p)
    return final_pages


def _list_keyboard(page: int, total: int) -> Optional[InlineKeyboardMarkup]:
    """Botones ◀️ ▶️ para navegar la lista. None si solo hay 1 página."""
    if total <= 1:
        return None
    botones = []
    if page > 0:
        botones.append(InlineKeyboardButton(text="◀️ Anterior", callback_data=f"lst:{page-1}"))
    botones.append(InlineKeyboardButton(text=f"{page+1}/{total}", callback_data="lst:noop"))
    if page < total - 1:
        botones.append(InlineKeyboardButton(text="Siguiente ▶️", callback_data=f"lst:{page+1}"))
    return InlineKeyboardMarkup(inline_keyboard=[botones])


# Cache de páginas por chat (para no recalcular en cada clic).
# Se regenera cada vez que se abre /lista.
_pages_cache: dict[int, list[str]] = {}


# ===========================================================================
# /lista
# ===========================================================================
@router.message(Command("lista", "listado", "reportados"))
async def cmd_lista(message: Message, bot: Bot) -> None:
    if not message.from_user or not await _is_staff_or_owner(message.from_user.id):
        await message.reply("❌ Solo el staff puede ver la lista.")
        return

    data = await sanctions_db.get_all_active_sanctioned()
    pages = _build_list_pages(data)
    _pages_cache[message.chat.id] = pages

    kb = _list_keyboard(0, len(pages))
    await message.reply(pages[0], reply_markup=kb, disable_web_page_preview=True)


@router.callback_query(F.data.startswith("lst:"))
async def cb_list_nav(cb: CallbackQuery, bot: Bot) -> None:
    if not cb.from_user or not await _is_staff_or_owner(cb.from_user.id):
        await cb.answer("❌ Solo el staff.", show_alert=True)
        return

    action = cb.data.split(":")[1]
    if action == "noop":
        await cb.answer()
        return

    try:
        page = int(action)
    except ValueError:
        await cb.answer()
        return

    # Recuperar páginas del cache o regenerar
    pages = _pages_cache.get(cb.message.chat.id)
    if not pages:
        data = await sanctions_db.get_all_active_sanctioned()
        pages = _build_list_pages(data)
        _pages_cache[cb.message.chat.id] = pages

    if page < 0 or page >= len(pages):
        await cb.answer()
        return

    kb = _list_keyboard(page, len(pages))
    try:
        await cb.message.edit_text(
            pages[page], reply_markup=kb, disable_web_page_preview=True,
        )
    except TelegramBadRequest:
        pass
    await cb.answer()


# ===========================================================================
# /buscar
# ===========================================================================
@router.message(Command("buscar", "buscarusuario", "info"))
async def cmd_buscar(message: Message, bot: Bot) -> None:
    if not message.from_user or not await _is_staff_or_owner(message.from_user.id):
        await message.reply("❌ Solo el staff puede buscar.")
        return

    args = _split_args(message)

    # Resolver el usuario: reply, @ o id
    uid = None
    username = None
    full_name = None

    if message.reply_to_message and message.reply_to_message.from_user:
        u = message.reply_to_message.from_user
        uid, username, full_name = u.id, u.username, u.full_name
    elif args:
        token = args.strip().split()[0]
        if token.startswith("@"):
            found = await sanctions_db.resolve_username_global(token)
            if found:
                uid = found["user_id"]
                username = found.get("username")
                full_name = found.get("full_name")
            else:
                await message.reply(
                    f"❌ No encuentro a <b>{token}</b>. Prueba con su ID numérico "
                    "o responde a un mensaje suyo."
                )
                return
        elif token.lstrip("-").isdigit():
            uid = int(token)
            info = await sanctions_db.get_sanctioned_user_info(uid)
            if info:
                username = info.get("username")
                full_name = info.get("full_name")
        else:
            await message.reply(
                "❌ Uso: <code>/buscar @usuario</code> o <code>/buscar 123456789</code>, "
                "o responde a un mensaje suyo con <code>/buscar</code>."
            )
            return
    else:
        await message.reply(
            "❌ Uso: <code>/buscar @usuario</code> o <code>/buscar 123456789</code>, "
            "o responde a un mensaje suyo con <code>/buscar</code>."
        )
        return

    # Obtener el estado
    status = await sanctions_db.get_user_status(uid)
    mention = _mention(uid, username, full_name)

    if not status["active"]:
        await message.reply(
            f"✅ {mention}\n🆔 <code>{uid}</code>\n\nNo tiene ninguna sanción activa.",
            disable_web_page_preview=True,
        )
        return

    # Construir ficha detallada
    lineas = [f"🔎 <b>Ficha de sanciones</b>\n"]
    lineas.append(f"👤 {mention}")
    lineas.append(f"🆔 <code>{uid}</code>\n")

    if status["banned"]:
        lineas.append("🚫 <b>BANEADO permanentemente</b> de la comunidad.")
        # Buscar la razón del ban
        for s in status["active"]:
            if s["kind"] == sanctions_db.KIND_BAN:
                lineas.append(f"📋 Motivo: {s.get('reason_short') or 'Sin motivo'}")
                break
    else:
        lineas.append(format_points_status(status["points"], False))
        lineas.append("")
        # Listar cada warn activo con su expiración
        for s in status["active"]:
            if s["kind"] == sanctions_db.KIND_LEVE:
                tipo = "⚠️ Warn leve"
            elif s["kind"] == sanctions_db.KIND_GRAVE:
                tipo = "⛔ Warn grave"
            elif s["kind"] == sanctions_db.KIND_MUTE:
                tipo = "🔇 Silencio"
            else:
                continue
            from sanctions_db import _parse_ts
            exp = _parse_ts(s.get("expires_at"))
            tleft = format_time_left(exp) if exp else ""
            razon = s.get("reason_short") or "Sin motivo"
            linea = f"{tipo} · {razon}"
            if tleft and tleft != "expirado":
                linea += f" · expira en {tleft}"
            lineas.append(linea)

    await message.reply("\n".join(lineas), disable_web_page_preview=True)


# ===========================================================================
# /pendientes
# ===========================================================================
@router.message(Command("pendientes", "pending", "sinresolver"))
async def cmd_pendientes(message: Message, bot: Bot) -> None:
    if not message.from_user or not await _is_staff_or_owner(message.from_user.id):
        await message.reply("❌ Solo el staff puede ver los pendientes.")
        return

    pending = await sanctions_db.get_pending_reports()
    if not pending:
        await message.reply("✅ No hay reportes pendientes. Todo al día. 🎉")
        return

    lineas = [f"⏳ <b>REPORTES SIN RESOLVER</b> ({len(pending)})\n"]
    for rep in pending:
        rid = rep["id"]
        reporter_m = _mention(
            rep["reporter_id"], rep.get("reporter_user"), rep.get("reporter_name"),
        )
        # A quién se reporta
        if rep.get("target_id"):
            target_m = _mention(
                rep["target_id"], rep.get("target_user"), rep.get("target_name"),
            )
        else:
            target_m = "(no identificado)"

        razon = rep.get("reason") or "sin motivo"
        if len(razon) > 60:
            razon = razon[:60] + "…"

        bloque = (
            f"🚨 <b>Reporte #{rid}</b>\n"
            f"   👤 Contra: {target_m}\n"
            f"   🗣️ Reporta: {reporter_m}\n"
            f"   📝 {razon}"
        )

        # Enlace para saltar al mensaje original (si tenemos los datos)
        staff_chat = rep.get("staff_chat")
        staff_msg = rep.get("staff_msg_id")
        if staff_chat and staff_msg:
            # Los enlaces t.me/c/ usan el chat_id sin el -100 inicial
            chat_num = str(staff_chat).replace("-100", "")
            bloque += f"\n   🔗 <a href=\"https://t.me/c/{chat_num}/{staff_msg}\">Ir al reporte</a>"

        lineas.append(bloque)

    texto = "\n\n".join(lineas)
    # Telegram limita a 4096 caracteres; si se pasa, recortar
    if len(texto) > 4000:
        texto = texto[:3900] + "\n\n<i>…y más. Resuelve algunos para ver el resto.</i>"

    await message.reply(texto, disable_web_page_preview=True)
