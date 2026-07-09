# -*- coding: utf-8 -*-
"""
h_promos.py
Gestión de promos = "mensajes maestros".
Tú le envías el mensaje al bot UNA vez (foto + texto + emojis premium)
y se guarda. Toda difusión se hace copiando ese mensaje (copy_message),
por eso los emojis premium nunca se pierden.
"""
import logging

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery

import keyboards as kb
import database as db
from guard import IsOwner
from states import NewPromo, EditPromo

router = Router()
router.message.filter(IsOwner())
router.callback_query.filter(IsOwner())

log = logging.getLogger("mala-bot.promos")


@router.callback_query(F.data == "menu:promos")
@router.message(Command("promos"))
async def menu_promos(evento, state: FSMContext):
    await state.clear()
    promos = await db.get_promos()
    texto = (f"📢 <b>Promos</b>\n\nTienes <b>{len(promos)}</b> promos "
             f"guardadas.\nCada proma es un mensaje maestro que el bot "
             f"reenvía tal cual (emojis premium incluidos).")
    if isinstance(evento, Message):
        await evento.answer(texto, reply_markup=kb.menu_promos(promos))
    else:
        await evento.message.edit_text(texto,
                                       reply_markup=kb.menu_promos(promos))
        await evento.answer()


# ---------- Crear promo ----------
@router.callback_query(F.data == "promo:new")
async def cb_nueva(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(NewPromo.esperando_nombre)
    await callback.message.edit_text(
        "📢 <b>Nueva promo</b>\n\nPaso 1 de 2 — Escribe un <b>nombre</b> "
        "para identificarla (ej: «España 1-6» o «Findom»).\n\n"
        "/cancel para salir.")
@router.message(NewPromo.esperando_nombre)
async def recibir_nombre(message: Message, state: FSMContext):
    await state.update_data(nombre=(message.text or "Promo").strip()[:40])
    await state.set_state(NewPromo.esperando_mensaje)
    await message.answer(
        "Paso 2 de 2 — Ahora <b>envíame la publicación tal cual</b> la "
        "quieres difundir: foto, texto, emojis premium animados, botones... "
        "todo.\n\n⚠️ <b>No borres ese mensaje</b> de este chat: el bot lo "
        "necesita guardado para poder copiarlo.")


@router.message(NewPromo.esperando_mensaje)
async def recibir_mensaje(message: Message, state: FSMContext):
    datos = await state.get_data()
    await state.clear()
    # ¿De dónde viene el mensaje maestro?
    #  - Si el usuario REENVIÓ algo desde un canal -> forward_origin.
    #  - Si lo escribió aquí en el chat privado -> el origen es el chat.
    origen_chat = message.chat.id
    origen_msg = message.message_id
    desde_canal = False
    fo = getattr(message, "forward_origin", None)
    if fo is not None:
        # Mensaje reenviado: intentamos usar el canal de origen real.
        chat_orig = getattr(fo, "chat", None)
        mid_orig = getattr(fo, "message_id", None)
        if chat_orig is not None and mid_orig:
            origen_chat = chat_orig.id
            origen_msg = mid_orig
            desde_canal = True

    promo_id = await db.add_promo(
        datos.get("nombre", "Promo"), origen_chat, origen_msg)

    modo = await db.get_setting("modo_difusion", "copiar")
    aviso = ""
    if modo == "reenviar" and not desde_canal:
        aviso = ("\n\n⚠️ <b>Atención:</b> el modo difusión está en "
                 "<b>Reenviar</b>, pero esta promo la escribiste en el chat "
                 "privado. Para que el reenvío funcione y los emojis "
                 "premium se vean, debes <b>reenviar la promo desde un "
                 "canal tuyo</b>, no escribirla aquí. Bórrala y créala "
                 "reenviándola desde tu canal almacén.")
    elif modo == "reenviar" and desde_canal:
        aviso = ("\n\n✅ Perfecto: viene de un canal, el reenvío con emojis "
                 "premium funcionará.")

    await message.answer(
        f"✅ Promo <b>#{promo_id}</b> «{datos.get('nombre')}» guardada."
        f"{aviso}\n\nYa puedes usarla en «Enviar ahora» o en una campaña.",
        reply_markup=kb.menu_promos(await db.get_promos()))


# ---------- Ver / previsualizar / borrar ----------
@router.callback_query(F.data.startswith("promo:view:"))
async def cb_ver(callback: CallbackQuery):
    await callback.answer()
    promo_id = int(callback.data.split(":")[-1])
    p = await db.get_promo(promo_id)
    if not p:
        await callback.answer("No existe", show_alert=True)
        return
    await callback.message.edit_text(
        f"📢 <b>Promo #{p['id']}</b>\n"
        f"• Nombre: {p['name']}\n"
        f"• Creada: {p['created_at']}",
        reply_markup=kb.ficha_promo(promo_id))
@router.callback_query(F.data.startswith("promo:prev:"))
async def cb_previsualizar(callback: CallbackQuery):
    promo_id = int(callback.data.split(":")[-1])
    p = await db.get_promo(promo_id)
    if not p:
        await callback.answer("No existe", show_alert=True)
        return
    modo = await db.get_setting("modo_difusion", "copiar")
    try:
        if modo == "reenviar":
            # Igual que se difundirá: así ves de verdad cómo quedará.
            await callback.bot.forward_message(
                chat_id=callback.from_user.id,
                from_chat_id=p["src_chat_id"],
                message_id=p["src_message_id"])
            await callback.answer("👆 Así se verá (modo reenviar)")
        else:
            await callback.bot.copy_message(
                chat_id=callback.from_user.id,
                from_chat_id=p["src_chat_id"],
                message_id=p["src_message_id"])
            await callback.answer("👆 Así se verá (modo copiar)")
    except Exception as e:
        await callback.answer(
            f"No se pudo previsualizar: {e}", show_alert=True)
@router.callback_query(F.data.startswith("promo:del:"))
async def cb_borrar(callback: CallbackQuery):
    """Antes de borrar, avisa si alguna campaña o alianza usa esta promo."""
    await callback.answer()
    promo_id = int(callback.data.split(":")[-1])
    p = await db.get_promo(promo_id)
    nombre = p["name"] if p else promo_id
    uso = await db.promo_en_uso(promo_id)
    aviso = ""
    if uso["campaigns"] or uso["alliances"]:
        partes = []
        if uso["campaigns"]:
            partes.append("campañas: " + ", ".join(uso["campaigns"]))
        if uso["alliances"]:
            partes.append("alianzas: " + ", ".join(uso["alliances"]))
        aviso = ("\n\n⚠️ <b>OJO:</b> esta promo la usan estas "
                 + " · ".join(partes) + ".\nSi la borras, esas campañas o "
                 "alianzas fallarán cuando les toque. Cámbiales la promo "
                 "antes de borrar esta.")
    await callback.message.edit_text(
        f"🗑️ <b>¿Eliminar la promo «{nombre}»?</b>{aviso}",
        reply_markup=kb.confirmar_borrado(
            "delpromo", promo_id, f"promo:view:{promo_id}"))


@router.callback_query(F.data.startswith("delpromo:yes:"))
async def cb_borrar_ok(callback: CallbackQuery):
    await callback.answer("Promo eliminada")
    promo_id = int(callback.data.split(":")[-1])
    await db.delete_promo(promo_id)
    promos = await db.get_promos()
    await callback.message.edit_text(
        f"✅ Promo eliminada.\n\n📢 <b>Promos</b> ({len(promos)})",
        reply_markup=kb.menu_promos(promos))


# ---------- Editar el mensaje maestro de una promo ----------
@router.callback_query(F.data.startswith("promo:edit:"))
async def cb_editar(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    promo_id = int(callback.data.split(":")[-1])
    await state.set_state(EditPromo.esperando_mensaje)
    await state.update_data(promo_id=promo_id)
    await callback.message.edit_text(
        "✏️ <b>Editar promo</b>\n\n"
        "Envíame la <b>nueva publicación</b> tal cual: foto, texto, emojis "
        "premium, botones... todo.\n\n"
        "Sustituirá por completo al mensaje maestro anterior. La promo "
        "mantiene el mismo número, así que las campañas que la usan "
        "seguirán funcionando solas.\n\n/cancel para salir.")
@router.message(EditPromo.esperando_mensaje)
async def recibir_edicion(message: Message, state: FSMContext):
    datos = await state.get_data()
    await state.clear()
    promo_id = datos["promo_id"]
    # Detectar de dónde viene el mensaje (canal reenviado o chat privado),
    # igual que al crear una promo nueva.
    origen_chat = message.chat.id
    origen_msg = message.message_id
    desde_canal = False
    fo = getattr(message, "forward_origin", None)
    if fo is not None:
        chat_orig = getattr(fo, "chat", None)
        mid_orig = getattr(fo, "message_id", None)
        if chat_orig is not None and mid_orig:
            origen_chat = chat_orig.id
            origen_msg = mid_orig
            desde_canal = True

    await db.update_promo(promo_id, src_chat_id=origen_chat,
                          src_message_id=origen_msg)
    p = await db.get_promo(promo_id)

    modo = await db.get_setting("modo_difusion", "copiar")
    aviso = ""
    if modo == "reenviar" and not desde_canal:
        aviso = ("\n\n⚠️ <b>Atención:</b> el modo está en <b>Reenviar</b> "
                 "pero esto lo escribiste en el chat privado. Para que los "
                 "emojis premium se vean, edítala otra vez <b>reenviando "
                 "la promo desde tu canal almacén</b>.")
    elif modo == "reenviar" and desde_canal:
        aviso = ("\n\n✅ Viene de un canal: el reenvío con emojis premium "
                 "funcionará.")

    await message.answer(
        f"✅ Promo <b>#{promo_id}</b> «{p['name']}» actualizada.\n"
        f"El nuevo contenido ya está guardado.{aviso}",
        reply_markup=kb.ficha_promo(promo_id))


# ---------- Cambiar solo el nombre de una promo ----------
@router.callback_query(F.data.startswith("promo:rename:"))
async def cb_renombrar(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    promo_id = int(callback.data.split(":")[-1])
    await state.set_state(EditPromo.esperando_nombre)
    await state.update_data(promo_id=promo_id)
    await callback.message.edit_text(
        "🏷️ Escribe el <b>nuevo nombre</b> para esta promo:\n\n"
        "/cancel para salir.")
@router.message(EditPromo.esperando_nombre)
async def recibir_nuevo_nombre(message: Message, state: FSMContext):
    datos = await state.get_data()
    await state.clear()
    promo_id = datos["promo_id"]
    await db.update_promo(promo_id, name=(message.text or "Promo").strip()[:40])
    await message.answer(
        f"✅ Nombre cambiado.",
        reply_markup=kb.ficha_promo(promo_id))
