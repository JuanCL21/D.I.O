#!/usr/bin/env python3
"""
D.I.O. CLI — Cliente de línea de comandos para control IPC de D.I.O.

Uso:
    python -m dio.cli status
    python -m dio.cli navigate --panel panel_0 --url https://chatgpt.com
    python -m dio.cli focus --panel panel_1
    python -m dio.cli split --url https://claude.ai
    python -m dio.cli close-panel --panel panel_2
    python -m dio.cli auth
    python -m dio.cli eval-js --panel panel_0 --code "document.title"

DECISIÓN 3: Framing uint32 Big Endian, 2000ms timeout, 64KB max, SO_PEERCRED auth.
El token de sesión para eval_js NUNCA se pasa como argumento CLI (visible en ps aux).
Se obtiene del servidor vía el comando 'auth' tras autenticación SO_PEERCRED, y se
almacena sólo en variable de entorno DIO_SESSION_TOKEN de la sesión de shell actual.
"""

import argparse
import json
import os
import socket
import struct
import sys
import time
from pathlib import Path
from typing import Any, Optional

# Protocolo (duplicar constantes para que cli.py funcione standalone sin Qt)
HEADER_SIZE = 4
MAX_PAYLOAD = 65536
FRAME_TIMEOUT_S = 2.0  # 2000ms como timeout de socket


def _default_socket_path() -> str:
    """Ruta al socket IPC de D.I.O., coherente con config.toml."""
    dio_dir = Path.home() / ".dio"
    return str(dio_dir / "dio.sock")


def _frame_message(data: dict[str, Any]) -> bytes:
    """Serializa un dict a JSON + framing uint32 BE."""
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(payload) > MAX_PAYLOAD:
        print(f"Error: Payload de {len(payload)} bytes excede el máximo de {MAX_PAYLOAD}.", file=sys.stderr)
        sys.exit(1)
    header = struct.pack(">I", len(payload))
    return header + payload


def _recv_frame(sock: socket.socket) -> dict[str, Any]:
    """Lee exactamente un frame del socket con timeout."""
    # Leer header (4 bytes)
    header = b""
    while len(header) < HEADER_SIZE:
        chunk = sock.recv(HEADER_SIZE - len(header))
        if not chunk:
            print("Error: Conexión cerrada por el servidor.", file=sys.stderr)
            sys.exit(1)
        header += chunk

    (payload_len,) = struct.unpack(">I", header)
    if payload_len > MAX_PAYLOAD:
        print(f"Error: Respuesta de {payload_len} bytes excede MAX_PAYLOAD.", file=sys.stderr)
        sys.exit(1)

    # Leer payload
    payload = b""
    while len(payload) < payload_len:
        chunk = sock.recv(payload_len - len(payload))
        if not chunk:
            print("Error: Conexión cerrada mientras se leía el payload.", file=sys.stderr)
            sys.exit(1)
        payload += chunk

    return json.loads(payload.decode("utf-8"))


def _connect(socket_path: str) -> socket.socket:
    """Conecta al socket UNIX de D.I.O."""
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(FRAME_TIMEOUT_S)
    try:
        sock.connect(socket_path)
    except FileNotFoundError:
        print(f"Error: Socket no encontrado en '{socket_path}'. ¿Está D.I.O. ejecutándose?", file=sys.stderr)
        sys.exit(1)
    except ConnectionRefusedError:
        print(f"Error: Conexión rechazada en '{socket_path}'. ¿Está D.I.O. ejecutándose?", file=sys.stderr)
        sys.exit(1)
    except PermissionError:
        print(f"Error: Permiso denegado al conectar a '{socket_path}'.", file=sys.stderr)
        sys.exit(1)
    return sock


def _send_command(socket_path: str, command: str, **params: Any) -> dict[str, Any]:
    """Envía un comando IPC y retorna la respuesta."""
    msg: dict[str, Any] = {"command": command}
    clean_params = {k: v for k, v in params.items() if v is not None}
    if clean_params:
        msg["params"] = clean_params

    sock = _connect(socket_path)
    try:
        t_start = time.monotonic()
        sock.sendall(_frame_message(msg))
        response = _recv_frame(sock)
        t_elapsed = (time.monotonic() - t_start) * 1000
        response["_latency_ms"] = round(t_elapsed, 2)
        return response
    except socket.timeout:
        print(f"Error: Timeout ({FRAME_TIMEOUT_S}s) esperando respuesta del servidor.", file=sys.stderr)
        sys.exit(1)
    finally:
        sock.close()


def cmd_status(args: argparse.Namespace) -> None:
    """Muestra el estado de todos los paneles."""
    resp = _send_command(args.socket, "status")
    if resp.get("success"):
        data = resp.get("data", {})
        print(json.dumps(data, indent=2, ensure_ascii=False))
    else:
        print(f"Error: {resp.get('error', 'desconocido')}", file=sys.stderr)
        sys.exit(1)


def cmd_navigate(args: argparse.Namespace) -> None:
    """Navega un panel a una URL."""
    resp = _send_command(args.socket, "navigate", panel_id=args.panel, url=args.url)
    if resp.get("success"):
        data = resp.get("data", {})
        print(f"[OK] Panel {data.get('panel_id')} -> {data.get('url')}")
    else:
        print(f"Error: {resp.get('error', 'desconocido')}", file=sys.stderr)
        sys.exit(1)


def cmd_focus(args: argparse.Namespace) -> None:
    """Da foco a un panel."""
    resp = _send_command(args.socket, "focus", panel_id=args.panel)
    if resp.get("success"):
        data = resp.get("data", {})
        print(f"[OK] Foco en {data.get('panel_id')}")
    else:
        print(f"Error: {resp.get('error', 'desconocido')}", file=sys.stderr)
        sys.exit(1)


def cmd_close_panel(args: argparse.Namespace) -> None:
    """Cierra un panel."""
    resp = _send_command(args.socket, "close_panel", panel_id=args.panel)
    if resp.get("success"):
        data = resp.get("data", {})
        print(f"[OK] Panel {data.get('panel_id')} cerrado")
    else:
        print(f"Error: {resp.get('error', 'desconocido')}", file=sys.stderr)
        sys.exit(1)


def cmd_split(args: argparse.Namespace) -> None:
    """Agrega un nuevo panel."""
    resp = _send_command(args.socket, "split", url=args.url)
    if resp.get("success"):
        data = resp.get("data", {})
        print(f"[OK] Nuevo panel {data.get('panel_id')} con URL {data.get('url')}")
    else:
        print(f"Error: {resp.get('error', 'desconocido')}", file=sys.stderr)
        sys.exit(1)


def cmd_auth(args: argparse.Namespace) -> None:
    """
    Obtiene el token de sesión efímero del servidor IPC (tras autenticación SO_PEERCRED).
    Imprime instrucciones para exportarlo como variable de entorno.
    NUNCA se pasa como argumento CLI (visible en `ps aux`).
    """
    resp = _send_command(args.socket, "auth")
    if resp.get("success"):
        token = resp.get("data", {}).get("session_token", "")
        # Imprimir la línea export para que el usuario la evalúe en su shell
        print(f"export DIO_SESSION_TOKEN={token}")
        print("# Ejecuta: eval $(dio-cli auth)", file=sys.stderr)
        print("# El token SOLO vive en la variable de entorno de esta sesión de shell.", file=sys.stderr)
    else:
        print(f"Error: {resp.get('error', 'desconocido')}", file=sys.stderr)
        sys.exit(1)


def cmd_eval_js(args: argparse.Namespace) -> None:
    """
    Ejecuta JavaScript en un panel. Requiere token de sesión vía $DIO_SESSION_TOKEN.
    El token NUNCA se pasa como argumento CLI para evitar exposición en `ps aux`.
    """
    token = os.environ.get("DIO_SESSION_TOKEN", "")
    if not token:
        print(
            "Error: Variable de entorno DIO_SESSION_TOKEN no definida.\n"
            "Obtén el token con: eval $(dio-cli auth)\n"
            "ADVERTENCIA: eval_js expone la sesión web a inyección de código arbitrario.",
            file=sys.stderr,
        )
        sys.exit(1)

    resp = _send_command(
        args.socket,
        "eval_js",
        panel_id=args.panel,
        code=args.code,
        token=token,
    )
    if resp.get("success"):
        data = resp.get("data", {})
        print(f"[OK] eval_js ejecutado en {data.get('panel_id')}")
    else:
        print(f"Error: {resp.get('error', 'desconocido')}", file=sys.stderr)
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="dio-cli",
        description="D.I.O. CLI — Control externo de paneles web vía IPC seguro",
    )
    parser.add_argument(
        "--socket", "-s",
        default=_default_socket_path(),
        help=f"Ruta al socket UNIX (default: {_default_socket_path()})",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # status
    sp_status = subparsers.add_parser("status", help="Estado de todos los paneles (JSON)")
    sp_status.set_defaults(func=cmd_status)

    # navigate
    sp_nav = subparsers.add_parser("navigate", help="Navegar un panel a una URL")
    sp_nav.add_argument("--panel", required=True, help="ID del panel (ej. panel_0)")
    sp_nav.add_argument("--url", required=True, help="URL destino")
    sp_nav.set_defaults(func=cmd_navigate)

    # focus
    sp_focus = subparsers.add_parser("focus", help="Dar foco a un panel")
    sp_focus.add_argument("--panel", required=True, help="ID del panel (ej. panel_0)")
    sp_focus.set_defaults(func=cmd_focus)

    # close-panel
    sp_close = subparsers.add_parser("close-panel", help="Cerrar un panel")
    sp_close.add_argument("--panel", required=True, help="ID del panel (ej. panel_0)")
    sp_close.set_defaults(func=cmd_close_panel)

    # split
    sp_split = subparsers.add_parser("split", help="Agregar un nuevo panel")
    sp_split.add_argument("--url", default="about:blank", help="URL del nuevo panel")
    sp_split.set_defaults(func=cmd_split)

    # auth
    sp_auth = subparsers.add_parser(
        "auth",
        help="Obtener token de sesión (eval $(dio-cli auth))",
    )
    sp_auth.set_defaults(func=cmd_auth)

    # eval-js
    sp_eval = subparsers.add_parser(
        "eval-js",
        help="Ejecutar JavaScript en un panel (requiere $DIO_SESSION_TOKEN)",
    )
    sp_eval.add_argument("--panel", required=True, help="ID del panel (ej. panel_0)")
    sp_eval.add_argument("--code", required=True, help="Código JavaScript a ejecutar")
    sp_eval.set_defaults(func=cmd_eval_js)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
