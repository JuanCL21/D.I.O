"""
D.I.O. — Logging centralizado con rotación de archivos.
"""

import logging
from logging.handlers import RotatingFileHandler

from dio.core.config import DIO_DIR, LOG_BACKUP_COUNT, LOG_FILE, LOG_MAX_BYTES
from dio.core.security import ensure_umask, secure_directory

logger = logging.getLogger("dio")


def setup_logging() -> None:
    """Configura el logging con rotación de archivo y salida a consola."""
    ensure_umask()
    DIO_DIR.mkdir(parents=True, exist_ok=True)
    secure_directory(DIO_DIR)

    # Evitar duplicar handlers si se llama más de una vez
    if logger.handlers:
        return

    handler = RotatingFileHandler(
        LOG_FILE,
        maxBytes=LOG_MAX_BYTES,
        backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    )

    console = logging.StreamHandler()
    console.setFormatter(
        logging.Formatter("[D.I.O.] %(message)s")
    )

    logger.setLevel(logging.DEBUG)
    logger.addHandler(handler)
    logger.addHandler(console)
