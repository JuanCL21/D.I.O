"""
D.I.O. — Notificador nativo del sistema operativo (Paso 5).
Dispara notificaciones nativas del SO mediante procesos desacoplados
(subprocess.Popen con notify-send) para no bloquear en ningun caso el hilo de la UI.
"""

import shutil
import subprocess
from typing import Optional

from dio.core.logger import logger


def send_system_notification(
    title: str,
    message: str,
    urgency: str = "normal",
    app_name: str = "D.I.O.",
    timeout_ms: int = 5000,
) -> bool:
    """
    Emite una notificacion de escritorio utilizando notify-send.
    Se ejecuta de forma asincrona en un subproceso desacoplado para no bloquear Qt.
    """
    notify_bin = shutil.which("notify-send")
    if not notify_bin:
        logger.debug("notify-send no disponible en el sistema; notificacion omitida")
        return False

    cmd = [
        notify_bin,
        "-a", app_name,
        "-u", urgency,
        "-t", str(timeout_ms),
        title,
        message,
    ]

    try:
        subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
        logger.debug("Notificacion enviada: [%s] %s - %s", urgency, title, message)
        return True
    except OSError as e:
        logger.warning("Error al disparar notify-send: %s", e)
        return False
