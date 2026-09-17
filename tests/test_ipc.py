"""
Tests para el sistema IPC de D.I.O. (Paso 4):
- Framing binario uint32 Big Endian + JSON UTF-8
- Límite de payload (MAX_PAYLOAD = 64KB)
- Autenticación SO_PEERCRED y rechazo de UIDs no autorizados
- Token de sesión efímero para eval_js
- Despacho de comandos (status, navigate, focus, split, close_panel)
"""

import json
import os
import socket
import struct
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PyQt6.QtCore import QCoreApplication
from PyQt6.QtNetwork import QLocalSocket

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


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def qapp():
    app = QCoreApplication.instance()
    if app is None:
        app = QCoreApplication([])
    yield app


@pytest.fixture
def temp_socket_path():
    with tempfile.TemporaryDirectory() as tmpdir:
        sock_path = str(Path(tmpdir) / "test_dio.sock")
        yield sock_path


# ── Tests de Protocolo y Framing ─────────────────────────────────────────────

def test_frame_message_and_parse_frame_roundtrip():
    data = {"command": "status", "params": {"panel_id": "panel_0"}}
    framed = frame_message(data)

    # 4 bytes de header uint32 BE + payload
    assert len(framed) > HEADER_SIZE
    payload_len = struct.unpack(">I", framed[:HEADER_SIZE])[0]
    assert len(framed) == HEADER_SIZE + payload_len

    parsed, remaining = parse_frame(framed)
    assert parsed == data
    assert remaining == b""


def test_parse_frame_incomplete_buffer():
    data = {"command": "navigate", "params": {"panel_id": "panel_0", "url": "https://example.com"}}
    framed = frame_message(data)

    # Solo el header
    parsed, remaining = parse_frame(framed[:HEADER_SIZE])
    assert parsed is None
    assert remaining == framed[:HEADER_SIZE]

    # Header + parte del payload
    parsed, remaining = parse_frame(framed[:HEADER_SIZE + 5])
    assert parsed is None
    assert remaining == framed[:HEADER_SIZE + 5]

    # Buffer con bytes extra después del frame
    extra_bytes = b"extra_garbage"
    parsed, remaining = parse_frame(framed + extra_bytes)
    assert parsed == data
    assert remaining == extra_bytes


def test_frame_message_exceeds_max_payload():
    huge_data = {"data": "A" * (MAX_PAYLOAD + 10)}
    with pytest.raises(ValueError, match="excede el máximo permitido"):
        frame_message(huge_data)


def test_parse_frame_declares_exceeding_max_payload():
    # Header manipulado que declara > 64KB
    bad_header = struct.pack(">I", MAX_PAYLOAD + 1) + b"dummy"
    with pytest.raises(ValueError, match="excede MAX_PAYLOAD"):
        parse_frame(bad_header)


# ── Tests de Servidor IPC y Autenticación ─────────────────────────────────────

def test_server_ephemeral_token():
    server = DIOIpcServer()
    token = server.session_token
    assert len(token) == 64  # 32 bytes hex = 64 chars
    assert all(c in "0123456789abcdefABCDEF" for c in token)
    # Debe ser efímero y diferente en cada instancia
    server2 = DIOIpcServer()
    assert server.session_token != server2.session_token


def test_server_lifecycle_and_socket_cleanup(qapp, temp_socket_path):
    server = DIOIpcServer()
    assert server.start(temp_socket_path)
    assert os.path.exists(temp_socket_path)

    # Iniciar un segundo servidor en el mismo path debe limpiar el socket previo
    server2 = DIOIpcServer()
    assert server2.start(temp_socket_path)
    assert os.path.exists(temp_socket_path)

    server2.stop()
    server.stop()


def test_client_server_so_peercred_success(qapp, temp_socket_path):
    server = DIOIpcServer()
    server.start(temp_socket_path)

    # Registrar un handler simulado
    handler = MagicMock(return_value={"result": "ok"})
    server.set_command_handler(handler)

    # Cliente Python estándar vía socket UNIX
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.connect(temp_socket_path)

    # Enviar comando 'status'
    req = {"command": "status"}
    client.sendall(frame_message(req))

    # Esperar y procesar eventos Qt
    t0 = time.time()
    while not handler.called and time.time() - t0 < 2.0:
        qapp.processEvents()
        time.sleep(0.01)

    assert handler.called
    cmd, params = handler.call_args[0]
    assert cmd == "status"

    # Leer respuesta
    header = client.recv(HEADER_SIZE)
    (length,) = struct.unpack(">I", header)
    resp_bytes = client.recv(length)
    resp = json.loads(resp_bytes.decode("utf-8"))

    assert resp["success"] is True
    assert resp["data"] == {"result": "ok"}

    client.close()
    server.stop()


def test_client_server_so_peercred_rejection(qapp, temp_socket_path):
    server = DIOIpcServer()
    server.start(temp_socket_path)

    # Simular que el peer tiene UID diferente (ej. 9999 != os.getuid())
    with patch.object(server, "_authenticate_peer", return_value=False):
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.connect(temp_socket_path)

        # Procesar eventos Qt para procesar la nueva conexión
        for _ in range(10):
            qapp.processEvents()
            time.sleep(0.01)

        # Debe recibir frame de error de autenticación y cerrarse
        header = client.recv(HEADER_SIZE)
        assert len(header) == HEADER_SIZE
        (length,) = struct.unpack(">I", header)
        resp_bytes = client.recv(length)
        resp = json.loads(resp_bytes.decode("utf-8"))

        assert resp["success"] is False
        assert "SO_PEERCRED" in resp["error"]

        client.close()

    server.stop()


def test_auth_command_delivers_token(qapp, temp_socket_path):
    server = DIOIpcServer()
    server.start(temp_socket_path)

    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.connect(temp_socket_path)

    req = {"command": "auth"}
    client.sendall(frame_message(req))

    for _ in range(10):
        qapp.processEvents()
        time.sleep(0.01)

    header = client.recv(HEADER_SIZE)
    (length,) = struct.unpack(">I", header)
    resp = json.loads(client.recv(length).decode("utf-8"))

    assert resp["success"] is True
    assert resp["data"]["session_token"] == server.session_token

    client.close()
    server.stop()


def test_eval_js_security_guard(qapp, temp_socket_path):
    server = DIOIpcServer()
    server.start(temp_socket_path)

    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.connect(temp_socket_path)

    # Caso 1: allow_eval_js = False en config (por defecto)
    req = {"command": "eval_js", "params": {"panel_id": "panel_0", "code": "alert(1)", "token": server.session_token}}
    client.sendall(frame_message(req))

    for _ in range(10):
        qapp.processEvents()
        time.sleep(0.01)

    header = client.recv(HEADER_SIZE)
    (length,) = struct.unpack(">I", header)
    resp = json.loads(client.recv(length).decode("utf-8"))

    assert resp["success"] is False
    assert "deshabilitado" in resp["error"]

    # Caso 2: allow_eval_js = True pero token incorrecto
    with patch("dio.core.config.load_config_toml", return_value={"ipc": {"allow_eval_js": True}}):
        bad_req = {"command": "eval_js", "params": {"panel_id": "panel_0", "code": "alert(1)", "token": "invalid_token"}}
        client.sendall(frame_message(bad_req))

        for _ in range(10):
            qapp.processEvents()
            time.sleep(0.01)

        header = client.recv(HEADER_SIZE)
        (length,) = struct.unpack(">I", header)
        resp2 = json.loads(client.recv(length).decode("utf-8"))

        assert resp2["success"] is False
        assert "Token de sesión inválido" in resp2["error"]

    client.close()
    server.stop()


# ── Tests de CLI y End-to-End ────────────────────────────────────────────────

def test_cli_dispatch_and_execution(qapp, temp_socket_path, capsys):
    from dio.cli import (
        cmd_auth,
        cmd_close_panel,
        cmd_focus,
        cmd_navigate,
        cmd_split,
        cmd_status,
    )
    import argparse

    server = DIOIpcServer()
    server.start(temp_socket_path)

    def mock_handler(command, params):
        if command == "status":
            return {
                "panel_count": 2,
                "grid": "1x2",
                "panels": [
                    {"panel_id": "panel_0", "state": "active", "url": "https://example.com"},
                    {"panel_id": "panel_1", "state": "hibernated", "url": "https://test.org"},
                ],
            }
        elif command == "navigate":
            return {"panel_id": params["panel_id"], "url": params["url"]}
        elif command == "focus":
            return {"panel_id": params["panel_id"], "focused": True}
        elif command == "split":
            return {"panel_id": "panel_2", "url": params["url"]}
        elif command == "close_panel":
            return {"panel_id": params["panel_id"], "closed": True}
        raise ValueError(f"Unknown: {command}")

    server.set_command_handler(mock_handler)

    import threading

    def run_in_thread(func, args):
        err = []
        def target():
            try:
                func(args)
            except Exception as e:
                err.append(e)
        t = threading.Thread(target=target)
        t.start()
        t0 = time.time()
        while t.is_alive() and time.time() - t0 < 3.0:
            qapp.processEvents()
            time.sleep(0.005)
        t.join(timeout=1.0)
        if err:
            raise err[0]

    # 1. status
    args_status = argparse.Namespace(socket=temp_socket_path)
    run_in_thread(cmd_status, args_status)
    out = capsys.readouterr().out
    assert "panel_0" in out
    assert "active" in out

    # 2. navigate
    args_nav = argparse.Namespace(socket=temp_socket_path, panel="panel_0", url="https://newurl.com")
    run_in_thread(cmd_navigate, args_nav)
    out = capsys.readouterr().out
    assert "panel_0" in out
    assert "https://newurl.com" in out

    # 3. focus
    args_focus = argparse.Namespace(socket=temp_socket_path, panel="panel_1")
    run_in_thread(cmd_focus, args_focus)
    out = capsys.readouterr().out
    assert "panel_1" in out

    # 4. split
    args_split = argparse.Namespace(socket=temp_socket_path, url="https://split.com")
    run_in_thread(cmd_split, args_split)
    out = capsys.readouterr().out
    assert "panel_2" in out

    # 5. close-panel
    args_close = argparse.Namespace(socket=temp_socket_path, panel="panel_1")
    run_in_thread(cmd_close_panel, args_close)
    out = capsys.readouterr().out
    assert "cerrado" in out

    # 6. auth
    args_auth = argparse.Namespace(socket=temp_socket_path)
    run_in_thread(cmd_auth, args_auth)
    out = capsys.readouterr().out
    assert "export DIO_SESSION_TOKEN=" in out

    server.stop()
