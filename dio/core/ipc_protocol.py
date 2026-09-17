"""
D.I.O. — Protocolo IPC binario con framing uint32 Big Endian.

DECISIÓN 3 (Vinculante):
- Paneles direccionados por panel_id estable (no índice posicional).
- Framing: 4 bytes uint32 Big Endian (longitud del payload JSON), seguido del payload UTF-8.
- Timeout de lectura: 2000ms.
- Payload máximo: 64KB (65536 bytes).
- Autenticación: SO_PEERCRED + allow_eval_js=false por defecto.
"""

import json
import struct
from enum import Enum
from typing import Any, Optional


# ── Constantes de protocolo ──────────────────────────────────────────────────

HEADER_SIZE: int = 4                # uint32 Big Endian
MAX_PAYLOAD: int = 65536            # 64 KB
FRAME_TIMEOUT_MS: int = 2000        # 2 segundos
PROTOCOL_VERSION: str = "1.0"


# ── Comandos IPC ─────────────────────────────────────────────────────────────

class IpcCommand(str, Enum):
    """Comandos soportados por el servidor IPC de D.I.O."""
    NAVIGATE = "navigate"
    SPLIT = "split"
    FOCUS = "focus"
    CLOSE_PANEL = "close_panel"
    EVAL_JS = "eval_js"
    STATUS = "status"
    AUTH = "auth"


# ── Framing ──────────────────────────────────────────────────────────────────

def frame_message(data: dict[str, Any]) -> bytes:
    """
    Serializa un diccionario a JSON UTF-8 y lo prefija con un header
    de 4 bytes uint32 Big Endian que indica la longitud del payload.

    Raises:
        ValueError: Si el payload serializado supera MAX_PAYLOAD.
    """
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(payload) > MAX_PAYLOAD:
        raise ValueError(
            f"Payload de {len(payload)} bytes excede el máximo permitido de {MAX_PAYLOAD} bytes"
        )
    header = struct.pack(">I", len(payload))
    return header + payload


def parse_frame(buffer: bytes) -> tuple[Optional[dict[str, Any]], bytes]:
    """
    Intenta extraer un frame completo del buffer.

    Returns:
        (mensaje_parseado, buffer_restante) si hay un frame completo.
        (None, buffer_original) si el buffer es insuficiente.

    Raises:
        ValueError: Si el payload declarado excede MAX_PAYLOAD.
        json.JSONDecodeError: Si el payload no es JSON válido.
    """
    if len(buffer) < HEADER_SIZE:
        return None, buffer

    (payload_len,) = struct.unpack(">I", buffer[:HEADER_SIZE])

    if payload_len > MAX_PAYLOAD:
        raise ValueError(
            f"Frame declarado de {payload_len} bytes excede MAX_PAYLOAD ({MAX_PAYLOAD})"
        )

    total_len = HEADER_SIZE + payload_len
    if len(buffer) < total_len:
        return None, buffer

    payload_bytes = buffer[HEADER_SIZE:total_len]
    remaining = buffer[total_len:]

    message = json.loads(payload_bytes.decode("utf-8"))
    return message, remaining


# ── Helpers de construcción de mensajes ──────────────────────────────────────

def make_request(command: str, **kwargs: Any) -> dict[str, Any]:
    """Construye un mensaje de solicitud IPC."""
    msg: dict[str, Any] = {"command": command}
    if kwargs:
        msg["params"] = {k: v for k, v in kwargs.items() if v is not None}
    return msg


def make_response(
    command: str,
    success: bool,
    data: Optional[dict[str, Any]] = None,
    error: Optional[str] = None,
) -> dict[str, Any]:
    """Construye un mensaje de respuesta IPC."""
    resp: dict[str, Any] = {
        "command": command,
        "success": success,
    }
    if data is not None:
        resp["data"] = data
    if error is not None:
        resp["error"] = error
    return resp
