"""
D.I.O. — Divisor Integrado Operativo
"""

from dio.core.config import (
    DIO_DIR,
    PROFILES_DIR,
    CONFIG_TOML,
    SESSION_FILE,
    load_config_toml,
    save_config_toml,
    ensure_config,
)
from dio.core.logger import logger, setup_logging
from dio.ui.window import DIOWindow

__version__ = "1.0.0"

__all__ = [
    "DIOWindow",
    "DIO_DIR",
    "PROFILES_DIR",
    "CONFIG_TOML",
    "SESSION_FILE",
    "load_config_toml",
    "save_config_toml",
    "ensure_config",
    "logger",
    "setup_logging",
]
