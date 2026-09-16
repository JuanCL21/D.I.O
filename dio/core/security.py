"""
D.I.O. — Módulo de Seguridad y Permisos
H-06: Blindaje contra TOCTOU mediante umask 0o077 y utilidades de aseguramiento de directorios.
"""

import os
import platform
import stat
from pathlib import Path


def ensure_umask() -> None:
    """
    H-06: Establece umask restrictivo (0o077) antes de que se cree cualquier archivo
    o directorio bajo ~/.dio/ (logs, perfiles, session.json, config.toml, sockets).
    Garantiza permisos 0700 para directorios y 0600 para archivos desde su creación.
    """
    if hasattr(os, "umask"):
        os.umask(0o077)


def secure_directory(path: Path) -> None:
    """
    En Linux y macOS fuerza permisos 0700 (solo lectura/escritura/ejecución para el propietario).
    """
    if platform.system() in ("Linux", "Darwin"):
        try:
            path.chmod(stat.S_IRWXU)
        except OSError:
            pass


_secure_directory = secure_directory
