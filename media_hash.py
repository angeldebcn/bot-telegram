"""Cálculo de pHash para fotos y primer frame de vídeos."""
import asyncio
import logging
import tempfile
from io import BytesIO
from pathlib import Path
from typing import Optional

import imagehash
from PIL import Image

logger = logging.getLogger(__name__)


def _phash_from_bytes(data: bytes) -> Optional[str]:
    """pHash hex de unos bytes de imagen. None si falla."""
    try:
        img = Image.open(BytesIO(data))
        img.load()
        return str(imagehash.phash(img))
    except Exception as e:
        logger.warning("Error calculando pHash: %s", e)
        return None


async def phash_image(data: bytes) -> Optional[str]:
    """Versión async del cálculo de pHash (la imagen procesa en thread aparte)."""
    return await asyncio.to_thread(_phash_from_bytes, data)


def _first_frame_phash_sync(video_path: str) -> Optional[str]:
    """Extrae el primer frame y calcula su pHash. Usa OpenCV."""
    try:
        import cv2
    except ImportError:
        logger.warning("OpenCV no disponible, no se puede hashear vídeo.")
        return None
    cap = None
    try:
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            return None
        ok, frame = cap.read()
        if not ok or frame is None:
            return None
        # BGR -> RGB
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        img = Image.fromarray(frame_rgb)
        return str(imagehash.phash(img))
    except Exception as e:
        logger.warning("Error procesando vídeo: %s", e)
        return None
    finally:
        if cap is not None:
            cap.release()


async def phash_video_first_frame(video_bytes: bytes) -> Optional[str]:
    """
    Guarda los bytes a un archivo temporal y extrae el pHash del primer frame.
    """
    def _work() -> Optional[str]:
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
            tmp.write(video_bytes)
            tmp_path = tmp.name
        try:
            return _first_frame_phash_sync(tmp_path)
        finally:
            try:
                Path(tmp_path).unlink(missing_ok=True)
            except OSError:
                pass
    return await asyncio.to_thread(_work)


def hamming_distance_hex(h1: str, h2: str) -> int:
    """Distancia de Hamming entre dos pHash hex (64 bits = 16 chars)."""
    try:
        return bin(int(h1, 16) ^ int(h2, 16)).count("1")
    except (ValueError, TypeError):
        return 999  # tratar como "muy diferente"
