# -*- coding: utf-8 -*-
"""
states.py
Estados FSM (los "pasos" de los flujos guiados con el usuario).
"""
from aiogram.fsm.state import State, StatesGroup


class AddChannel(StatesGroup):
    """Añadir canal pegando @usuario, enlace o ID."""
    esperando_identificador = State()


class BulkImport(StatesGroup):
    """Importar muchos canales de golpe."""
    esperando_lista = State()


class RepostSet(StatesGroup):
    """Configurar uno de los 3 canales de repost (España/Latam/Findom)."""
    esperando_canal = State()


class RepostBtn(StatesGroup):
    """Editar el texto de uno de los 2 botones del repost."""
    esperando_texto = State()


class RepostOwner(StatesGroup):
    """Asignar a mano la @ de la propietaria real de un canal."""
    esperando = State()


class NewPromo(StatesGroup):
    """Crear una promo (mensaje maestro)."""
    esperando_nombre = State()
    esperando_mensaje = State()


class EditPromo(StatesGroup):
    """Editar una promo: cambiar nombre o el mensaje maestro."""
    esperando_nombre = State()
    esperando_mensaje = State()


class CustomValue(StatesGroup):
    """Pedir un número personalizado en el flujo de ENVÍO."""
    esperando_valor = State()


class CampNum(StatesGroup):
    """Pedir un número personalizado en el asistente de CAMPAÑAS."""
    esperando = State()


class NewCampaign(StatesGroup):
    """Asistente para crear una campaña automática."""
    nombre = State()
    region = State()
    categoria = State()
    promos = State()
    rotacion = State()
    dias = State()
    hora = State()
    lote = State()
    intervalo = State()
    borrado = State()


class EditCampaign(StatesGroup):
    """Editar una campaña ya creada, campo a campo."""
    valor = State()       # texto o número
    promos = State()      # selección múltiple de promos
    dias = State()        # selección múltiple de días
    region = State()
    categoria = State()
    duracion = State()


class ScheduleOne(StatesGroup):
    """Programar un envío único en fecha/hora concreta."""
    esperando_fecha = State()


class MoveChannel(StatesGroup):
    """Mover un canal a otro bloque."""
    esperando_bloque = State()


class SearchChannel(StatesGroup):
    """Buscar un canal por nombre."""
    esperando_texto = State()


class RestoreBackup(StatesGroup):
    """Esperando el archivo .db para restaurar."""
    esperando_archivo = State()


class ChannelTopics(StatesGroup):
    """Esperando los enlaces de hilo para un canal/grupo."""
    esperando = State()


class AllianceTopics(StatesGroup):
    """Esperando los enlaces de hilo para una alianza."""
    esperando = State()


class NewAlliance(StatesGroup):
    """Asistente para crear una alianza."""
    nombre = State()
    grupo = State()
    promo = State()
    zona = State()
    dias = State()
    horas = State()
    borrado = State()


class AllyNum(StatesGroup):
    """Número personalizado dentro del asistente de ALIANZAS."""
    esperando = State()


class EditAlliance(StatesGroup):
    """Editar una alianza ya creada."""
    valor = State()       # nombre / horas
    promo = State()
    dias = State()
    zona = State()
    duracion = State()
