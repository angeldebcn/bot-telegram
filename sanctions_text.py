"""
=====================================================================
FORMATEO DE TEXTO DEL SISTEMA DE SANCIONES
=====================================================================

Aquí vive toda la lógica de "cómo se ve" una sanción:
- Acortar/limpiar la razón para la lista (versión corta y profesional).
- Formatear el tiempo que falta para expirar (solo días/meses).
- Construir la línea de "puntos y cuánto falta para el ban".

La razón corta NO es un resumen con IA: es una limpieza determinista
(quita tacos, recorta, capitaliza) para que la lista se vea profesional
sin depender de servicios externos ni añadir coste.
"""
from datetime import datetime
from typing import Optional

from sanctions_db import (
    KIND_BAN,
    KIND_GRAVE,
    KIND_LEVE,
    POINTS_BAN_THRESHOLD,
)

# Palabrotas comunes a suavizar en la versión corta (lista básica).
# La razón COMPLETA (cruda) se guarda intacta; esto es solo para la lista.
_PROFANITY = {
    "puta", "puto", "putas", "putos", "mierda", "gilipollas", "cabron",
    "cabrón", "cabrones", "coño", "joder", "zorra", "zorras", "perra",
    "perras", "maricon", "maricón", "polla", "pollas", "verga", "pendejo",
    "pendeja", "imbecil", "imbécil", "estupido", "estúpido", "idiota",
    "subnormal", "retrasado", "hijo de puta", "hdp", "malparido",
}

_MAX_SHORT_LEN = 70


def clean_reason_short(reason: Optional[str]) -> str:
    """
    Convierte una razón cruda en una versión corta y profesional para la lista.

    Pasos:
    1. Si está vacía -> "Sin motivo especificado".
    2. Colapsa espacios y saltos de línea.
    3. Suaviza palabrotas evidentes (las sustituye por [...]).
    4. Recorta a ~70 caracteres sin cortar palabras a la mitad.
    5. Capitaliza la primera letra.
    """
    if not reason or not reason.strip():
        return "Sin motivo especificado"

    text = " ".join(reason.split())

    # Suavizar palabrotas (comparando palabra a palabra, sin distinguir may/min)
    words = text.split(" ")
    cleaned_words = []
    for w in words:
        # separar signos de puntuación pegados
        core = w.strip(".,!?¡¿;:\"'()").lower()
        if core in _PROFANITY:
            cleaned_words.append("[...]")
        else:
            cleaned_words.append(w)
    text = " ".join(cleaned_words)

    # Recortar sin partir palabras
    if len(text) > _MAX_SHORT_LEN:
        cut = text[:_MAX_SHORT_LEN].rsplit(" ", 1)[0]
        text = cut.rstrip(".,;:") + "…"

    # Capitalizar primera letra
    if text:
        text = text[0].upper() + text[1:]
    return text


def format_time_left(expires_at: Optional[datetime], now: Optional[datetime] = None) -> str:
    """
    Formatea el tiempo restante hasta la caducidad, SOLO en días y meses.
    Ejemplos: "2 meses", "18 días", "menos de 1 día".
    Devuelve "" si no hay fecha (ban permanente).
    """
    if expires_at is None:
        return ""
    now = now or datetime.utcnow()
    if expires_at <= now:
        return "expirado"

    delta = expires_at - now
    total_days = delta.days

    if total_days <= 0:
        return "menos de 1 día"
    if total_days < 30:
        return f"{total_days} día{'s' if total_days != 1 else ''}"
    # Meses (aprox 30 días)
    months = total_days // 30
    rem_days = total_days % 30
    if rem_days == 0:
        return f"{months} mes{'es' if months != 1 else ''}"
    return f"{months} mes{'es' if months != 1 else ''} y {rem_days} día{'s' if rem_days != 1 else ''}"


def format_points_status(points: int, banned: bool) -> str:
    """
    Línea que explica los puntos y cuánto falta para el ban.
    Ejemplos:
      - Baneado: "🚫 Baneado permanentemente"
      - 1 punto: "⚠️ Puntos: 1/3 · le faltan 2 para el baneo"
      - 2 puntos: "⚠️ Puntos: 2/3 · le falta 1 para el baneo"
    """
    if banned:
        return "🚫 Baneado permanentemente"
    faltan = max(0, POINTS_BAN_THRESHOLD - points)
    if faltan == 1:
        return f"⚠️ Puntos: {points}/{POINTS_BAN_THRESHOLD} · le falta 1 para el baneo"
    return f"⚠️ Puntos: {points}/{POINTS_BAN_THRESHOLD} · le faltan {faltan} para el baneo"


def kind_label(kind: str) -> str:
    """Nombre bonito de un tipo de sanción."""
    return {
        KIND_LEVE: "⚠️ Warn leve",
        KIND_GRAVE: "⛔ Warn grave",
        KIND_BAN: "🚫 Ban",
    }.get(kind, kind)
