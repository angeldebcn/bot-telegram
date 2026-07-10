"""CRUD de la configuración por chat. Cada grupo tiene sus propios valores."""
import json
import logging
from typing import Any

from config import DEFAULTS
from db import get_db

logger = logging.getLogger(__name__)


# Todos los campos editables desde el menú
EDITABLE_FIELDS = list(DEFAULTS.keys())


async def get_config(chat_id: int) -> dict[str, Any]:
    """Devuelve la config del chat. Si no existe, crea una con defaults."""
    async with get_db() as db:
        cur = await db.execute(
            "SELECT * FROM chat_config WHERE chat_id = ?", (chat_id,)
        )
        row = await cur.fetchone()
        if row is None:
            # Crear fila con defaults
            await _create_default(db, chat_id)
            await db.commit()
            cur = await db.execute(
                "SELECT * FROM chat_config WHERE chat_id = ?", (chat_id,)
            )
            row = await cur.fetchone()
        return dict(row)


async def _create_default(db, chat_id: int) -> None:
    """Crea una fila de config con valores por defecto."""
    cols = ["chat_id"] + EDITABLE_FIELDS
    placeholders = ",".join("?" for _ in cols)
    values = [chat_id] + [DEFAULTS[k] for k in EDITABLE_FIELDS]
    await db.execute(
        f"INSERT INTO chat_config ({','.join(cols)}) VALUES ({placeholders})",
        values,
    )


async def update_config(chat_id: int, field: str, value: int) -> None:
    """Actualiza UN campo de la config. Valida que el campo sea editable."""
    if field not in EDITABLE_FIELDS:
        raise ValueError(f"Campo no editable: {field}")
    # Aseguramos que existe la fila
    await get_config(chat_id)
    async with get_db() as db:
        await db.execute(
            f"UPDATE chat_config SET {field} = ?, updated_at = CURRENT_TIMESTAMP "
            "WHERE chat_id = ?",
            (value, chat_id),
        )
        await db.commit()


async def update_chat_title(chat_id: int, title: str) -> None:
    """Actualiza el título del chat (se llama cuando recibimos mensajes)."""
    await get_config(chat_id)
    async with get_db() as db:
        await db.execute(
            "UPDATE chat_config SET chat_title = ? WHERE chat_id = ?",
            (title, chat_id),
        )
        await db.commit()


async def reset_to_defaults(chat_id: int) -> None:
    """Restaura todos los campos a sus valores por defecto."""
    async with get_db() as db:
        sets = ", ".join(f"{k} = ?" for k in EDITABLE_FIELDS)
        values = [DEFAULTS[k] for k in EDITABLE_FIELDS] + [chat_id]
        await db.execute(
            f"UPDATE chat_config SET {sets}, updated_at = CURRENT_TIMESTAMP "
            "WHERE chat_id = ?",
            values,
        )
        await db.commit()


async def export_config_json(chat_id: int) -> str:
    """Devuelve la config como JSON bonito."""
    cfg = await get_config(chat_id)
    # Quitamos campos meta
    cfg.pop("created_at", None)
    cfg.pop("updated_at", None)
    cfg.pop("chat_title", None)
    cfg.pop("chat_id", None)
    return json.dumps(cfg, indent=2, ensure_ascii=False)


async def import_config_json(chat_id: int, raw_json: str) -> tuple[bool, str]:
    """Importa config desde JSON. Devuelve (ok, mensaje)."""
    try:
        data = json.loads(raw_json)
    except json.JSONDecodeError as e:
        return False, f"❌ JSON inválido: {e}"
    if not isinstance(data, dict):
        return False, "❌ El JSON debe ser un objeto."
    # Aseguramos fila
    await get_config(chat_id)
    valid_count = 0
    async with get_db() as db:
        for field, value in data.items():
            if field not in EDITABLE_FIELDS:
                continue
            if not isinstance(value, int):
                continue
            await db.execute(
                f"UPDATE chat_config SET {field} = ? WHERE chat_id = ?",
                (value, chat_id),
            )
            valid_count += 1
        await db.execute(
            "UPDATE chat_config SET updated_at = CURRENT_TIMESTAMP WHERE chat_id = ?",
            (chat_id,),
        )
        await db.commit()
    return True, f"✅ Importados {valid_count} ajustes."
