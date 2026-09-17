"""
D.I.O. Core Package
"""

from dio.core.config import (
    DIO_DIR,
    PROFILES_DIR,
    CONFIG_TOML,
    SESSION_FILE,
    LEGACY_DIR,
    LOG_FILE,
    DEFAULT_CONFIG,
    load_config_toml,
    save_config_toml,
    ensure_config,
    migrate_legacy_config,
)
from dio.core.logger import logger, setup_logging
from dio.core.security import ensure_umask, secure_directory
from dio.core.state import (
    InvalidTransitionError,
    PanelEvent,
    PanelState,
    PanelStateMachine,
    TRANSITION_TABLE,
    TransitionRule,
)
from dio.core.ipc_protocol import (
    FRAME_TIMEOUT_MS,
    HEADER_SIZE,
    MAX_PAYLOAD,
    IpcCommand,
    frame_message,
    make_request,
    make_response,
    parse_frame,
)
from dio.core.ipc_server import DIOIpcServer

__all__ = [
    "DIO_DIR",
    "PROFILES_DIR",
    "CONFIG_TOML",
    "SESSION_FILE",
    "LEGACY_DIR",
    "LOG_FILE",
    "DEFAULT_CONFIG",
    "load_config_toml",
    "save_config_toml",
    "ensure_config",
    "migrate_legacy_config",
    "logger",
    "setup_logging",
    "ensure_umask",
    "secure_directory",
    "PanelState",
    "PanelEvent",
    "PanelStateMachine",
    "TRANSITION_TABLE",
    "TransitionRule",
    "InvalidTransitionError",
    "FRAME_TIMEOUT_MS",
    "HEADER_SIZE",
    "MAX_PAYLOAD",
    "IpcCommand",
    "frame_message",
    "make_request",
    "make_response",
    "parse_frame",
    "DIOIpcServer",
]

