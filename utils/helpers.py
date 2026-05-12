"""Helpers varios."""
from datetime import datetime, timedelta
from typing import Optional


def format_duration(seconds: int) -> str:
    """Convierte segundos a un string humano."""
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        m = seconds // 60
        return f"{m} min"
    if seconds < 86400:
        h = seconds / 3600
        return f"{h:.0f}h" if h == int(h) else f"{h:.1f}h"
    d = seconds / 86400
    return f"{d:.0f}d" if d == int(d) else f"{d:.1f}d"


def format_minutes(minutes: int) -> str:
    """Convierte minutos a un string humano."""
    if minutes < 60:
        return f"{minutes} min"
    if minutes < 1440:
        h = minutes / 60
        return f"{h:.0f}h" if h == int(h) else f"{h:.1f}h"
    d = minutes / 1440
    return f"{d:.0f}d" if d == int(d) else f"{d:.1f}d"


def time_until(target: datetime) -> str:
    """Devuelve un string tipo '5 min', '1h 20 min' hasta `target`."""
    delta = target - datetime.utcnow()
    secs = int(delta.total_seconds())
    if secs <= 0:
        return "ya"
    if secs < 60:
        return f"{secs}s"
    if secs < 3600:
        return f"{secs // 60} min"
    h = secs // 3600
    m = (secs % 3600) // 60
    return f"{h}h {m} min" if m else f"{h}h"


def safe_username(username: Optional[str], user_id: int, full_name: Optional[str] = None) -> str:
    """Devuelve algo legible para mostrar a la usuaria."""
    if username:
        return f"@{username}"
    if full_name:
        return full_name
    return f"id:{user_id}"


def truncate(text: str, max_len: int = 50) -> str:
    """Trunca un string para que quepa en botones."""
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"
