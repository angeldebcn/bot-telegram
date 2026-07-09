# -*- coding: utf-8 -*-
"""
config.py
Lee la configuración del bot desde las variables de entorno de Railway.
NUNCA se escribe el token aquí: se pone en Railway -> Variables.
"""
import os

# Token que te da @BotFather (obligatorio).
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

# Tu user_id de Telegram. Solo tú podrás manejar el bot.
# Si no lo sabes, arranca el bot y escríbele /id en privado.
OWNER_ID = int(os.getenv("OWNER_ID", "0") or "0")

# Zona horaria base (todo se calcula en hora de España por defecto).
DEFAULT_TZ = os.getenv("TZ", "Europe/Madrid").strip()

# Ruta de la base de datos. En Railway monta un Volume en /data.
DB_PATH = os.getenv("DB_PATH", "/data/bot.db").strip()

# Pausa (segundos) entre cada envío para no saturar la API de Telegram.
SEND_DELAY = float(os.getenv("SEND_DELAY", "0.4") or "0.4")

if not BOT_TOKEN:
    raise RuntimeError(
        "Falta BOT_TOKEN. Añádelo en Railway -> pestaña Variables."
    )
