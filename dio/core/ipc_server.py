"""
D.I.O. — Servidor IPC seguro sobre QLocalServer.

DECISIÓN 3 (Vinculante):
- Socket UNIX en ~/.dio/dio.sock con umask 0o077 (H-06).
- Autenticación de kernel: SO_PEERCRED verifica UID del peer == UID del proceso D.I.O.
- Token de sesión efímero para eval_js (generado en memoria, nunca en disco ni ps aux).
- Framing: uint32 Big Endian, 2000ms timeout, 64KB max payload.
- Paneles referenciados por panel_id estable.
"""

import os
import secrets
import socket
import struct
from typing import Any, Callable, Optional

from PyQt6.QtCore import QObject, QTimer, pyqtSignal
from PyQt6.QtNetwork import QLocalServer, QLocalSocket

import dio.core.config as config
from dio.core.ipc_protocol import (
    FRAME_TIMEOUT_MS,
    HEADER_SIZE,
    MAX_PAYLOAD,
    IpcCommand,
    frame_message,
    make_response,
    parse_frame,
)
from dio.core.logger import logger
from dio.core.security import ensure_umask


class DIOIpcServer(QObject):
    """
    Servidor IPC seguro para control externo de D.I.O.
    Escucha en un socket UNIX, autentica vía SO_PEERCRED, y despacha
    comandos al DIOWindow a través de señales Qt.
    """

    # ── Señales para despachar comandos a DIOWindow ──────────────────────
    navigate_requested = pyqtSignal(str, str)          # panel_id, url
    focus_requested = pyqtSignal(str)                   # panel_id
    close_panel_requested = pyqtSignal(str)             # panel_id
    split_requested = pyqtSignal(str, str)              # panel_id, url
    eval_js_requested = pyqtSignal(str, str)            # panel_id, code
    status_requested = pyqtSignal()

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)

        # Token efímero de sesión: solo en RAM, nunca en disco ni en args CLI
        self._session_token: str = secrets.token_hex(32)
        logger.info(
            "IPC: Token de sesión efímero generado (64 chars hex, solo en memoria)"
        )

        self._server = QLocalServer(self)
        self._server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        self._server.newConnection.connect(self._on_new_connection)

        self._clients: list[QLocalSocket] = []
        self._buffers: dict[int, bytes] = {}

        # Handler de comandos — será conectado por DIOWindow
        self._command_handler: Optional[Callable[[str, dict], dict]] = None

        # Referencia al DIOWindow para consultas directas
        self._window = None

    @property
    def session_token(self) -> str:
        """Token efímero (solo lectura). Nunca debe exponerse a logs ni disco."""
        return self._session_token

    def set_command_handler(self, handler: Callable[[str, dict], dict]) -> None:
        """Registra el handler de comandos (DIOWindow.handle_ipc_command)."""
        self._command_handler = handler

    def set_window(self, window: Any) -> None:
        """Almacena referencia al DIOWindow para consultas directas."""
        self._window = window

    def start(self, socket_path: Optional[str] = None) -> bool:
        """
        Inicia el servidor IPC en el socket UNIX especificado.
        Elimina el socket previo si existe (remanente de crash anterior).
        """
        ensure_umask()
        cfg = config.load_config_toml()
        path = socket_path or cfg.get("ipc", {}).get(
            "socket_path", str(config.DIO_DIR / "dio.sock")
        )

        # Limpiar socket huérfano de ejecución anterior
        if os.path.exists(path):
            try:
                os.unlink(path)
            except OSError as e:
                logger.warning("IPC: No se pudo eliminar socket previo %s: %s", path, e)

        if not self._server.listen(path):
            logger.error(
                "IPC: No se pudo iniciar QLocalServer en %s: %s",
                path, self._server.errorString(),
            )
            return False

        logger.info("IPC: Servidor escuchando en %s", path)
        return True

    def stop(self) -> None:
        """Detiene el servidor y cierra todas las conexiones activas."""
        for client in list(self._clients):
            try:
                client.disconnected.disconnect()
            except Exception:
                pass
            client.disconnectFromServer()
            client.deleteLater()
        self._clients.clear()
        self._buffers.clear()

        if self._server.isListening():
            self._server.close()
            logger.info("IPC: Servidor detenido")

    # ── Conexiones entrantes ─────────────────────────────────────────────

    def _on_new_connection(self) -> None:
        while self._server.hasPendingConnections():
            local_socket = self._server.nextPendingConnection()
            if local_socket is None:
                continue

            # Autenticación SO_PEERCRED
            if not self._authenticate_peer(local_socket):
                self._reject_connection(local_socket, "Autenticación SO_PEERCRED fallida: UID no coincide")
                continue

            client_id = id(local_socket)
            self._clients.append(local_socket)
            self._buffers[client_id] = b""

            local_socket.readyRead.connect(
                lambda s=local_socket: self._on_data_ready(s)
            )
            local_socket.disconnected.connect(
                lambda s=local_socket: self._on_client_disconnected(s)
            )

            logger.debug("IPC: Cliente conectado (autenticado)")

    def _authenticate_peer(self, local_socket: QLocalSocket) -> bool:
        """
        Verifica SO_PEERCRED: extrae el UID del proceso que conecta y lo compara
        con el UID del proceso D.I.O. actual. Rechaza si no coincide.
        """
        try:
            raw_descriptor = local_socket.socketDescriptor()
            if raw_descriptor is None:
                return False

            raw_fd = int(raw_descriptor)
            # Descriptor inválido (ej. -1 o valor unsigned equivalente)
            if raw_fd < 0 or raw_fd >= 0x7FFFFFFF_FFFFFFFF:
                logger.warning("IPC: socketDescriptor() retornó fd inválido: %s", raw_descriptor)
                return False

            # socket.fromfd duplica internamente el descriptor en C
            raw_sock = socket.fromfd(raw_fd, socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                # SO_PEERCRED: struct ucred { pid_t pid; uid_t uid; gid_t gid; }
                # En Linux: 3 x int32 = 12 bytes
                SO_PEERCRED = getattr(socket, "SO_PEERCRED", 17)
                cred_data = raw_sock.getsockopt(
                    socket.SOL_SOCKET, SO_PEERCRED, struct.calcsize("iii")
                )
                peer_pid, peer_uid, peer_gid = struct.unpack("iii", cred_data)
            finally:
                raw_sock.close()

            my_uid = os.getuid()
            if peer_uid != my_uid:
                logger.warning(
                    "IPC: Conexión rechazada — peer UID %d != proceso UID %d (pid=%d)",
                    peer_uid, my_uid, peer_pid,
                )
                return False

            logger.debug(
                "IPC: SO_PEERCRED verificado — peer pid=%d, uid=%d, gid=%d",
                peer_pid, peer_uid, peer_gid,
            )
            return True

        except (OSError, struct.error, ValueError, TypeError) as e:
            logger.error("IPC: Error al verificar SO_PEERCRED: %s", e)
            return False

    def _reject_connection(self, local_socket: QLocalSocket, reason: str) -> None:
        """Envía error y cierra la conexión inmediatamente."""
        try:
            error_resp = make_response("error", success=False, error=reason)
            local_socket.write(frame_message(error_resp))
            local_socket.flush()
        except Exception:
            pass
        local_socket.disconnectFromServer()
        local_socket.deleteLater()
        logger.warning("IPC: Conexión rechazada — %s", reason)

    # ── Lectura de datos ─────────────────────────────────────────────────

    def _on_data_ready(self, local_socket: QLocalSocket) -> None:
        client_id = id(local_socket)
        if client_id not in self._buffers:
            return

        raw_data = local_socket.readAll().data()
        self._buffers[client_id] += raw_data

        # Intentar parsear frames completos
        while True:
            try:
                message, remaining = parse_frame(self._buffers[client_id])
            except ValueError as e:
                logger.warning("IPC: Frame inválido desde cliente: %s", e)
                error_resp = make_response("error", success=False, error=str(e))
                self._send_response(local_socket, error_resp)
                self._buffers[client_id] = b""
                break

            if message is None:
                break

            self._buffers[client_id] = remaining
            self._handle_message(local_socket, message)

    def _on_client_disconnected(self, local_socket: QLocalSocket) -> None:
        client_id = id(local_socket)
        self._buffers.pop(client_id, None)
        if local_socket in self._clients:
            self._clients.remove(local_socket)
        local_socket.deleteLater()
        logger.debug("IPC: Cliente desconectado")

    # ── Despacho de comandos ─────────────────────────────────────────────

    def _handle_message(self, local_socket: QLocalSocket, message: dict) -> None:
        command = message.get("command", "")
        params = message.get("params", {})

        logger.debug("IPC: Comando recibido: %s, params: %s", command, list(params.keys()))

        # Comando especial: auth (entrega token tras SO_PEERCRED)
        if command == IpcCommand.AUTH.value:
            response = make_response(
                command,
                success=True,
                data={"session_token": self._session_token},
            )
            self._send_response(local_socket, response)
            return

        # Verificación de eval_js: requiere allow_eval_js + token válido
        if command == IpcCommand.EVAL_JS.value:
            cfg = config.load_config_toml()
            if not cfg.get("ipc", {}).get("allow_eval_js", False):
                response = make_response(
                    command,
                    success=False,
                    error="eval_js está deshabilitado en config.toml ([ipc] allow_eval_js = false). "
                          "ADVERTENCIA: Habilitarlo expone la sesión web a inyección de código arbitrario.",
                )
                self._send_response(local_socket, response)
                return

            token = params.get("token", "")
            if not secrets.compare_digest(token, self._session_token):
                response = make_response(
                    command,
                    success=False,
                    error="Token de sesión inválido para eval_js.",
                )
                self._send_response(local_socket, response)
                return

        # Despachar al handler de comandos registrado por DIOWindow
        if self._command_handler is not None:
            try:
                result = self._command_handler(command, params)
                response = make_response(command, success=True, data=result)
            except Exception as e:
                logger.error("IPC: Error ejecutando comando '%s': %s", command, e)
                response = make_response(command, success=False, error=str(e))
        else:
            response = make_response(
                command,
                success=False,
                error="Servidor IPC no conectado a DIOWindow.",
            )

        self._send_response(local_socket, response)

    def _send_response(self, local_socket: QLocalSocket, response: dict) -> None:
        try:
            data = frame_message(response)
            local_socket.write(data)
            local_socket.flush()
        except Exception as e:
            logger.error("IPC: Error al enviar respuesta: %s", e)
