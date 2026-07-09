# -*- coding: utf-8 -*-
"""
h_backup.py
Copia de seguridad de la base de datos.
  /backup  -> el bot te envía el archivo bot.db a tu chat.
  /restore -> le reenvías un bot.db y el bot lo restaura.
Además hace un backup automático una vez por semana.
"""
import os
import shutil
import logging
import datetime

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, FSInputFile

import keyboards as kb
import database as db
import config
import broadcaster
from broadcaster import scheduler
from guard import IsOwner
from states import RestoreBackup

router = Router()
router.message.filter(IsOwner())
router.callback_query.filter(IsOwner())

log = logging.getLogger("mala-bot.backup")


# ---------------------------------------------------------------------------
# CREAR Y ENVIAR UN BACKUP
# ---------------------------------------------------------------------------
async def _enviar_backup(bot, motivo: str = "manual") -> bool:
    """Copia bot.db a un archivo con fecha y se lo envía al dueño."""
    origen = db.db_file_path()
    if not os.path.exists(origen):
        try:
            await bot.send_message(
                config.OWNER_ID,
                "⚠️ No encontré la base de datos para hacer el backup.")
        except Exception:
            pass
        return False
    fecha = datetime.datetime.now().strftime("%Y%m%d_%H%M")
    copia = f"/tmp/backup_mala_{fecha}.db"
    try:
        # Forzamos que SQLite vuelque todo a disco antes de copiar.
        try:
            await db.conn().commit()
        except Exception:
            pass
        shutil.copyfile(origen, copia)
        documento = FSInputFile(copia, filename=f"backup_mala_{fecha}.db")
        etiqueta = ("🗓️ Backup automático semanal"
                    if motivo == "auto" else "💾 Backup de tu base de datos")
        await bot.send_document(
            config.OWNER_ID, documento,
            caption=(f"{etiqueta}\n\n"
                     f"Guarda este archivo. Si algún día se pierde la base "
                     f"de datos, usa /restore y reenvíame este mismo "
                     f"archivo para recuperarlo todo."))
        return True
    except Exception as e:
        log.warning(f"Fallo creando backup: {e}")
        try:
            await bot.send_message(
                config.OWNER_ID, f"⚠️ No se pudo crear el backup: {e}")
        except Exception:
            pass
        return False
    finally:
        try:
            if os.path.exists(copia):
                os.remove(copia)
        except Exception:
            pass


@router.callback_query(F.data == "set:backup")
@router.message(Command("backup"))
async def cmd_backup(evento):
    bot = evento.bot
    if isinstance(evento, CallbackQuery):
        await evento.answer("Creando backup...")
        await evento.message.edit_text(
            "💾 Creando la copia de seguridad...",
            reply_markup=kb.volver("menu:settings"))
    else:
        await evento.answer("💾 Creando la copia de seguridad...")
    ok = await _enviar_backup(bot, "manual")
    if not ok and isinstance(evento, Message):
        await evento.answer("No se pudo crear el backup. Revisa los logs.")


# ---------------------------------------------------------------------------
# RESTAURAR UN BACKUP
# ---------------------------------------------------------------------------
@router.callback_query(F.data == "set:restore")
@router.message(Command("restore"))
async def cmd_restore(evento, state: FSMContext):
    await state.set_state(RestoreBackup.esperando_archivo)
    texto = (
        "♻️ <b>Restaurar copia de seguridad</b>\n\n"
        "Reenvíame ahora el archivo <code>bot.db</code> de un backup "
        "anterior (el documento que te mandé con /backup).\n\n"
        "⚠️ <b>Atención:</b> esto reemplazará TODA la base de datos actual "
        "por la del archivo. Los canales o campañas que hayas añadido "
        "después de ese backup se perderán.\n\n"
        "/cancel para no hacer nada.")
    if isinstance(evento, CallbackQuery):
        await evento.answer()
        await evento.message.edit_text(texto)
    else:
        await evento.answer(texto)


@router.message(RestoreBackup.esperando_archivo, F.document)
async def recibir_backup(message: Message, state: FSMContext):
    await state.clear()
    doc = message.document
    nombre = (doc.file_name or "").lower()
    if not nombre.endswith(".db"):
        await message.answer(
            "❌ Eso no parece un archivo de base de datos (.db). "
            "Restauración cancelada.",
            reply_markup=kb.menu_principal())
        return
    aviso = await message.answer("♻️ Restaurando, espera...")
    destino = db.db_file_path()
    temporal = "/tmp/restore_entrante.db"
    try:
        # 1) Descargar el archivo que envió el usuario.
        await message.bot.download(doc, destination=temporal)
        # 2) Comprobar que es una base de datos válida del bot.
        import sqlite3
        prueba = sqlite3.connect(temporal)
        tablas = {r[0] for r in prueba.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        prueba.close()
        necesarias = {"channels", "promos", "campaigns", "alliances"}
        if not necesarias.issubset(tablas):
            await aviso.edit_text(
                "❌ El archivo no es una base de datos válida de este bot. "
                "No se ha cambiado nada.")
            return
        # 3) Cerrar la BD actual, sustituir el archivo y reabrir.
        await db.close_db()
        shutil.copyfile(temporal, destino)
        await db.init_db()
        # 4) Reprogramar campañas y alianzas con los datos restaurados.
        for j in list(scheduler.get_jobs()):
            try:
                scheduler.remove_job(j.id)
            except Exception:
                pass
        await broadcaster.restaurar(message.bot)
        # Contar lo recuperado.
        canales = await db.count_channels()
        camp = len(await db.get_campaigns())
        ally = len(await db.get_alliances())
        await aviso.edit_text(
            f"✅ <b>Base de datos restaurada</b>\n\n"
            f"• Canales: {canales}\n• Campañas: {camp}\n"
            f"• Alianzas: {ally}\n\n"
            f"Todo vuelve a estar en marcha.")
        await message.answer("Listo.", reply_markup=kb.menu_principal())
    except Exception as e:
        log.warning(f"Fallo restaurando: {e}")
        await aviso.edit_text(
            f"❌ No se pudo restaurar: {e}\n"
            f"La base de datos actual no se ha tocado.")
    finally:
        try:
            if os.path.exists(temporal):
                os.remove(temporal)
        except Exception:
            pass


@router.message(RestoreBackup.esperando_archivo)
async def restore_sin_archivo(message: Message):
    """Si en vez de un archivo manda texto."""
    await message.answer(
        "📎 Necesito que me <b>reenvíes el archivo</b> .db, no texto. "
        "Inténtalo de nuevo o escribe /cancel.")


# ---------------------------------------------------------------------------
# BACKUP AUTOMÁTICO SEMANAL
# ---------------------------------------------------------------------------
def programar_backup_automatico(bot) -> None:
    """Cada lunes a las 09:00 el bot se envía un backup solo."""
    scheduler.add_job(
        _enviar_backup, "cron", day_of_week="mon", hour=9, minute=0,
        args=[bot, "auto"], id="backup_auto", replace_existing=True)
    log.info("Backup automático semanal programado (lunes 09:00).")
