"""
D.I.O. — Ventana Principal (DIOWindow): Gestión de cuadrícula tiling,
atajos globales, teardown determinista de perfiles (H-01/H-02) y persistencia.
"""

import base64
import json
import logging
import math
import os
import platform
import stat
import sys
import time
import urllib.parse
from pathlib import Path

from PyQt6 import sip
from PyQt6.QtCore import QByteArray, QSize, QTimer, QUrl, Qt
from PyQt6.QtGui import QColor, QDesktopServices, QIcon, QKeySequence, QPixmap, QShortcut
from PyQt6.QtNetwork import QNetworkCookie
from PyQt6.QtWebEngineCore import (
    QWebEngineDownloadRequest,
    QWebEnginePage,
    QWebEngineProfile,
    QWebEngineScript,
    QWebEngineSettings,
)
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

import dio.core.config as config
from dio.core.logger import logger
from dio.core.security import _secure_directory, secure_directory
from dio.core.state import AgentState, PanelEvent, PanelState, PanelStateMachine
from dio.core.ipc_server import DIOIpcServer
from dio.core.ipc_protocol import IpcCommand
from dio.core.notifier import send_system_notification
from dio.agents.loader import find_adapter_for_url, load_all_adapters
from dio.browser.agent_observer import make_agent_observer_script
from dio.browser.interceptor import AdBlockInterceptor
from dio.browser.page import DIOPage, _SystemBrowserRedirectPage
from dio.browser.profile_manager import ProfileManager
from dio.browser.scripts import (
    make_anti_detection_script,
    make_dark_mode_script,
    _make_anti_detection_script,
    _make_dark_mode_script,
)
from dio.ui.widgets import (
    CrashOverlay,
    HibernationOverlay,
    LoadingOverlay,
    MutedIndicator,
    SeamlessSplitter,
    SeamlessSplitterHandle,
    ToastNotification,
)
from dio.ui.dialogs import (
    GridChooserDialog,
    KeySequenceRecorderDialog,
    OmniSearchDialog,
    SettingsOverlayDialog,
    resolve_query_or_url,
)
from dio.ui.detached import DetachedPanelWindow

def _get_cli_flags():
    cfg = config.ensure_config()
    gen = cfg.get("general", {})
    dark = False if "--no-dark-mode" in sys.argv else gen.get("dark_mode", True)
    adblock = False if "--no-adblock" in sys.argv else gen.get("adblock", True)
    ask_dl = True if "--ask-download-location" in sys.argv else gen.get("ask_download_location", False)
    low_mem = True if "--low-memory" in sys.argv else not gen.get("hardware_acceleration", True)
    return dark, adblock, ask_dl, low_mem

_DARK_MODE, _ADBLOCK_ENABLED, _ASK_DOWNLOAD, _LOW_MEMORY = _get_cli_flags()

class DIOWindow(QMainWindow):
    """Ventana principal: grid de paneles web con sesiones aisladas."""

    def __init__(
        self,
        rows: int,
        cols: int,
        urls: list[str],
        preset_name: str,
        monitor: int,
    ) -> None:
        super().__init__()

        # Sin bordes, sin barra de título
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window
        )
        self.setStyleSheet("background: black;")
        self.setWindowTitle("D.I.O.")

        icon_path = Path(__file__).resolve().parent / "assets" / "icon.png"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        # ProfileManager (Decisión 2: pool LRU y preservación de perfiles en disco)
        self._profile_manager = ProfileManager(parent=self)

        # Estado interno
        self._rows = rows
        self._cols = cols
        self._preset_name = preset_name
        self._monitor = monitor
        self._panels: list[QWebEngineView] = []
        self._profiles: list[QWebEngineProfile] = []
        self._overlays: list[LoadingOverlay] = []
        self._mute_indicators: list[MutedIndicator] = []
        self._fsms: list[PanelStateMachine] = []
        self._hibernation_overlays: list[HibernationOverlay] = []
        self._crash_overlays: list[CrashOverlay] = []
        self._pinned_flags: list[bool] = []
        self._last_focused_times: list[float] = []
        self._last_known_urls: list[str] = []
        self._panel_counter = 0

        # AI Cockpit (Paso 5): adapters de agentes y estados por panel
        self._agent_adapters = load_all_adapters()
        self._agent_states: list[AgentState] = []

        # Interceptor de adblock compartido
        self._adblock_interceptor: AdBlockInterceptor | None = None
        if _ADBLOCK_ENABLED:
            self._adblock_interceptor = AdBlockInterceptor(self)

        # Registro de atajos para el manual dinámico
        self.shortcuts_registry: dict[str, str] = {}

        # Workspaces virtuales (Paso 6)
        cfg = config.load_config_toml()
        self._max_workspaces = cfg.get("shortcuts", {}).get("max_workspaces", 9)
        self._current_workspace_idx = 0
        self._stacked_workspaces = QStackedWidget(self)
        self._workspace_splitters: list[QSplitter | None] = [None] * self._max_workspaces
        self._workspace_widgets: list[QWidget] = []
        self._panel_workspaces: list[int] = []
        self._detached_views: set[QWebEngineView] = set()
        self._detached_windows: list[DetachedPanelWindow] = []

        # Construir los paneles iniciales y asignarlos al workspace 0
        for url in urls:
            view = self._create_panel(url)
            self._panels.append(view)
            self._panel_workspaces.append(0)

        # Inicializar páginas de workspaces en QStackedWidget
        for ws_i in range(self._max_workspaces):
            ws_widget = self._build_workspace_widget(ws_i)
            self._workspace_widgets.append(ws_widget)
            self._stacked_workspaces.addWidget(ws_widget)

        self.setCentralWidget(self._stacked_workspaces)
        self._stacked_workspaces.setCurrentIndex(0)

        if self._panels:
            self._panels[0].setFocus()

        self._setup_shortcuts()

        # Temporizador de comprobación de inactividad para hibernación
        self._sleeping_timer = QTimer(self)
        self._sleeping_timer.setInterval(15000)  # Cada 15 segundos
        self._sleeping_timer.timeout.connect(self._check_background_sleeping)
        self._sleeping_timer.start()

        # ── Servidor IPC (Paso 4) ────────────────────────────────────────
        self._ipc_server = DIOIpcServer(parent=self)
        self._ipc_server.set_command_handler(self.handle_ipc_command)
        self._ipc_server.set_window(self)
        if self._ipc_server.start():
            logger.info("IPC: Servidor arrancado con éxito")
        else:
            logger.warning("IPC: No se pudo arrancar el servidor")

        logger.info(
            "Ventana creada: grid=%dx%d, preset=%s, paneles=%d, monitor=%d, "
            "dark_mode=%s, adblock=%s",
            rows, cols, preset_name, len(self._panels), monitor,
            _DARK_MODE, _ADBLOCK_ENABLED,
        )

    # ── Creación de paneles ───────────────────────────────────────────────

    def _create_panel(self, url: str) -> QWebEngineView:
        """Crea un panel web con perfil aislado y persistente en disco (Decisión 2)."""
        idx = self._panel_counter
        self._panel_counter += 1
        panel_id = f"panel_{idx}"

        # 1. Leer estado pinned desde config.toml
        cfg = config.load_config_toml()
        is_pinned = cfg.get("panels", {}).get(panel_id, {}).get("pinned", False)

        # 2. Obtener o crear perfil vía ProfileManager (Decisión 2: caché LRU sin borrar disco)
        profile = self._profile_manager.get_or_create_profile(
            panel_id,
            is_pinned=is_pinned,
            adblock_interceptor=self._adblock_interceptor,
            dark_mode=_DARK_MODE,
        )
        self._profiles.append(profile)

        profile.downloadRequested.connect(
            lambda dl, i=idx, pn=self._preset_name: self._on_download_requested(dl, i, pn)
        )

        view = QWebEngineView()
        page = DIOPage(profile, view)
        page.featurePermissionRequested.connect(
            lambda origin, feature, p=page: self._handle_permission(
                p, origin, feature
            )
        )

        settings = page.settings()
        settings.setAttribute(
            QWebEngineSettings.WebAttribute.LocalStorageEnabled, True
        )
        settings.setAttribute(
            QWebEngineSettings.WebAttribute.JavascriptEnabled, True
        )
        settings.setAttribute(
            QWebEngineSettings.WebAttribute.JavascriptCanAccessClipboard, True
        )
        settings.setAttribute(
            QWebEngineSettings.WebAttribute.JavascriptCanPaste, True
        )

        view.setPage(page)
        view.setStyleSheet("background: black;")
        view.setUrl(QUrl(url))

        # Registrar metadatos de panel
        self._last_known_urls.append(url)
        self._last_focused_times.append(time.time())
        self._pinned_flags.append(is_pinned)

        view.urlChanged.connect(lambda qurl, i=idx: self._on_url_changed(i, qurl))

        # Overlay de carga
        overlay = LoadingOverlay(view)
        self._overlays.append(overlay)

        # Overlay de hibernación (Paso 3)
        hib_overlay = HibernationOverlay(view)
        hib_overlay.wake_requested.connect(lambda i=idx: self.wake_panel(i))
        self._hibernation_overlays.append(hib_overlay)

        # Overlay de crash recovery (Paso 3)
        crash_overlay = CrashOverlay(view)
        crash_overlay.manual_reload_requested.connect(lambda i=idx: self.manual_reload_panel(i))
        self._crash_overlays.append(crash_overlay)

        # Indicador de silencio
        muted_indicator = MutedIndicator(view)
        self._mute_indicators.append(muted_indicator)

        view.loadStarted.connect(lambda ov=overlay: self._on_load_started(ov))
        view.loadProgress.connect(lambda progress, ov=overlay: self._on_load_progress(ov, progress))
        view.loadFinished.connect(lambda ok, ov=overlay, i=idx: self._on_load_finished(ov, i, ok))

        # Crash recovery
        view.renderProcessTerminated.connect(
            lambda status, code, v=view, i=idx: self._on_render_crash(
                v, i, status, code
            )
        )

        # FSM de ciclo de vida del panel
        cfg = config.load_config_toml()
        max_retries = cfg.get("recovery", {}).get("max_retries", 3)
        fsm = PanelStateMachine(panel_id=panel_id, max_retries=max_retries)
        self._fsms.append(fsm)

        # AI Cockpit (Paso 5): verificar si URL coincide con adapter e inyectar en ApplicationWorld
        adapter = find_adapter_for_url(url, self._agent_adapters)
        if adapter:
            script = make_agent_observer_script(adapter)
            profile.scripts().insert(script)
            logger.info("Panel %d [%s]: Observer de IA '%s' inyectado en ApplicationWorld", idx, panel_id, adapter.name)

        page.agent_state_changed.connect(
            lambda state, i=idx: self._on_agent_state_changed(i, state)
        )
        self._agent_states.append(AgentState.IDLE)

        view.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        logger.info("Panel %d creado [%s]: %s (pinned=%s)", idx, panel_id, url, is_pinned)
        return view

    def _on_url_changed(self, panel_idx: int, qurl: QUrl) -> None:
        """Actualiza la última URL conocida para poder restaurarla tras hibernación o crash."""
        if panel_idx < len(self._last_known_urls) and qurl.isValid():
            url_str = qurl.toString()
            if url_str and url_str != "about:blank":
                self._last_known_urls[panel_idx] = url_str

                # AI Cockpit: verificar si nueva URL activa un adapter de IA
                if panel_idx < len(self._profiles):
                    adapter = find_adapter_for_url(url_str, self._agent_adapters)
                    if adapter:
                        profile = self._profiles[panel_idx]
                        for s in list(profile.scripts().toList()):
                            if s.name().startswith("dio_agent_observer_"):
                                profile.scripts().remove(s)
                        script = make_agent_observer_script(adapter)
                        profile.scripts().insert(script)
                        logger.info("Panel %d: Observer de IA actualizado a '%s'", panel_idx, adapter.name)

    # ── Callbacks de overlay de carga ─────────────────────────────────────

    @staticmethod
    def _on_load_started(overlay: LoadingOverlay) -> None:
        overlay.reposition()
        overlay.setText("Cargando…")
        overlay.show()
        overlay.raise_()

    @staticmethod
    def _on_load_progress(overlay: LoadingOverlay, progress: int) -> None:
        overlay.update_progress(progress)

    def _on_load_finished(self, overlay: LoadingOverlay, panel_idx: int, ok: bool) -> None:
        overlay.hide()
        if not ok:
            logger.warning("Panel %d: carga falló o fue interrumpida", panel_idx)
        if panel_idx < len(self._fsms):
            fsm = self._fsms[panel_idx]
            if fsm.state == PanelState.INITIALIZING:
                fsm.trigger(PanelEvent.INIT_FINISHED)
            elif fsm.state == PanelState.RESTORING and ok:
                fsm.trigger(PanelEvent.RESTORE_COMPLETED)
                if panel_idx < len(self._hibernation_overlays):
                    self._hibernation_overlays[panel_idx].hide()
            elif fsm.state == PanelState.RECOVERING and ok:
                # DECISIÓN 4: loadFinished(True) tras recreación exitosa resetea crash_count a 0
                fsm.trigger(PanelEvent.LOAD_FINISHED_SUCCESS)
                if panel_idx < len(self._crash_overlays):
                    self._crash_overlays[panel_idx].hide()

    # ── Construcción del grid con QSplitters anidados ─────────────────────

    # ── Construcción de Workspaces y Grid con QSplitters anidados ─────────

    @property
    def _root_splitter(self) -> QSplitter | None:
        if hasattr(self, "_workspace_splitters") and 0 <= self._current_workspace_idx < len(self._workspace_splitters):
            return self._workspace_splitters[self._current_workspace_idx]
        return None

    @_root_splitter.setter
    def _root_splitter(self, splitter: QSplitter | None) -> None:
        if hasattr(self, "_workspace_splitters") and 0 <= self._current_workspace_idx < len(self._workspace_splitters):
            self._workspace_splitters[self._current_workspace_idx] = splitter

    def _build_workspace_widget(self, ws_idx: int) -> QWidget:
        ws_panels = [
            p for i, p in enumerate(self._panels)
            if i < len(self._panel_workspaces)
            and self._panel_workspaces[i] == ws_idx
            and p not in self._detached_views
        ]
        total = len(ws_panels)
        if total == 0:
            self._workspace_splitters[ws_idx] = None
            empty = QWidget()
            empty.setStyleSheet("background: #09090b;")
            lay = QVBoxLayout(empty)
            lbl = QLabel(f"Workspace {ws_idx + 1} vacio\nUsa Ctrl+N para agregar un nuevo panel a este espacio.")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setStyleSheet("color: #71717a; font-size: 14px;")
            lay.addWidget(lbl)
            return empty

        # Usar las dimensiones configuradas si son válidas; de lo contrario, calcularlas
        if ws_idx == 0 and hasattr(self, "_rows") and hasattr(self, "_cols") and self._rows > 0 and self._cols > 0:
            rows = self._rows
            cols = self._cols
            if rows * cols < total:
                rows = math.ceil(total / cols)
                self._rows = rows
        else:
            rows, cols = self._compute_grid_dimensions(total)

        root = SeamlessSplitter(Qt.Orientation.Vertical)
        panel_idx = 0
        row_splitters = []
        for _ in range(rows):
            if panel_idx >= total:
                break
            row_splitter = SeamlessSplitter(Qt.Orientation.Horizontal)
            panels_in_row = min(cols, total - panel_idx)
            for _ in range(panels_in_row):
                if panel_idx < total:
                    row_splitter.addWidget(ws_panels[panel_idx])
                    panel_idx += 1
            root.addWidget(row_splitter)
            row_splitters.append(row_splitter)

        if root.count() > 0:
            root.setSizes([10000] * root.count())
        for r_split in row_splitters:
            if r_split.count() > 0:
                r_split.setSizes([10000] * r_split.count())

        self._workspace_splitters[ws_idx] = root
        return root

    def _build_grid(self) -> QSplitter:
        return self._build_workspace_widget(self._current_workspace_idx)

    @staticmethod
    def _compute_grid_dimensions(n: int) -> tuple[int, int]:
        if n <= 0:
            return (0, 0)
        cols = math.ceil(math.sqrt(n))
        rows = math.ceil(n / cols)
        return (rows, cols)

    def _rebuild_workspace(self, ws_idx: int) -> None:
        if ws_idx < 0 or ws_idx >= self._max_workspaces:
            return

        ws_panels = [
            p for i, p in enumerate(self._panels)
            if i < len(self._panel_workspaces)
            and self._panel_workspaces[i] == ws_idx
            and p not in self._detached_views
        ]
        for p in ws_panels:
            p.setParent(None)

        old_widget = self._workspace_widgets[ws_idx]
        new_widget = self._build_workspace_widget(ws_idx)
        self._workspace_widgets[ws_idx] = new_widget

        self._stacked_workspaces.removeWidget(old_widget)
        self._stacked_workspaces.insertWidget(ws_idx, new_widget)
        old_widget.deleteLater()
        self._stacked_workspaces.setCurrentIndex(self._current_workspace_idx)

        if ws_panels:
            ws_panels[0].setFocus()

    def _rebuild_grid(self) -> None:
        self._rebuild_workspace(self._current_workspace_idx)

    def switch_workspace(self, target_idx: int) -> None:
        """Cambia al workspace virtual especificado (0 a max_workspaces-1)."""
        if target_idx < 0 or target_idx >= self._max_workspaces:
            return
        if target_idx == self._current_workspace_idx:
            return

        self._current_workspace_idx = target_idx
        self._stacked_workspaces.setCurrentIndex(target_idx)
        ToastNotification(f"Workspace {target_idx + 1}", self)

        ws_panels = [
            p for i, p in enumerate(self._panels)
            if i < len(self._panel_workspaces)
            and self._panel_workspaces[i] == target_idx
            and p not in self._detached_views
        ]
        if ws_panels:
            ws_panels[0].setFocus()
        logger.info("Workspace cambiado a %d (paneles=%d)", target_idx + 1, len(ws_panels))

    def detach_panel(self, view: QWebEngineView | None = None) -> None:
        """Extrae el panel especificado (o el enfocado) envolviendolo en una ventana flotante independiente."""
        if view is None:
            view = self._get_focused_view()
        if view is None or view in self._detached_views or view not in self._panels:
            return

        idx = self._panels.index(view)
        panel_id = self._panel_index_to_id(idx)

        active_in_grid = [p for p in self._panels if p not in self._detached_views]
        if len(active_in_grid) <= 1:
            ToastNotification("No se puede desacoplar el unico panel activo", self)
            return

        self._detached_views.add(view)
        ws_idx = self._panel_workspaces[idx] if idx < len(self._panel_workspaces) else self._current_workspace_idx
        self._rebuild_workspace(ws_idx)

        detached_win = DetachedPanelWindow(
            view=view,
            panel_id=panel_id,
            reattach_callback=lambda v: self.reattach_panel(v),
            parent=None,
        )
        self._detached_windows.append(detached_win)
        detached_win.show()
        ToastNotification(f"Panel {panel_id} desacoplado", self)
        logger.info("Panel %s desacoplado a ventana flotante", panel_id)

    def detach_focused_panel(self) -> None:
        """Atajo Ctrl+Shift+D: desacopla el panel que tiene el foco activo."""
        self.detach_panel(None)

    def reattach_panel(self, view: QWebEngineView) -> None:
        """Re-acopla un panel desacoplado al workspace activo."""
        if view not in self._detached_views:
            return

        self._detached_views.remove(view)
        self._detached_windows = [w for w in self._detached_windows if w.view != view]

        if view in self._panels:
            idx = self._panels.index(view)
            if idx < len(self._panel_workspaces):
                self._panel_workspaces[idx] = self._current_workspace_idx
            panel_id = self._panel_index_to_id(idx)
        else:
            panel_id = "panel"

        self._rebuild_workspace(self._current_workspace_idx)
        view.setFocus()
        ToastNotification(f"Panel {panel_id} re-acoplado a Workspace {self._current_workspace_idx + 1}", self)
        logger.info("Panel %s re-acoplado a Workspace %d", panel_id, self._current_workspace_idx + 1)

    # ── Permisos del navegador (con dominios confiables) ──────────────────

    def _handle_permission(
        self,
        page: QWebEnginePage,
        origin: QUrl,
        feature: QWebEnginePage.Feature,
    ) -> None:
        host = origin.host().lower()
        if host.startswith("www."):
            host = host[4:]

        notification_features = {QWebEnginePage.Feature.Notifications}
        media_features = {
            QWebEnginePage.Feature.MediaAudioCapture,
            QWebEnginePage.Feature.MediaVideoCapture,
            QWebEnginePage.Feature.MediaAudioVideoCapture,
        }

        # Notificaciones automáticas
        if config.AUTO_GRANT_NOTIFICATIONS and feature in notification_features:
            page.setFeaturePermission(
                origin, feature, QWebEnginePage.PermissionPolicy.GrantedByUser
            )
            logger.info("Permiso concedido: Notifications → %s", host)
            return

        # Portapapeles (Copiar / Pegar automático)
        if feature == QWebEnginePage.Feature.ClipboardReadWrite:
            page.setFeaturePermission(
                origin, feature, QWebEnginePage.PermissionPolicy.GrantedByUser
            )
            logger.info("Permiso concedido: ClipboardReadWrite → %s", host)
            return

        # Micrófono / Cámara
        if feature in media_features:
            feature_name = {
                QWebEnginePage.Feature.MediaAudioCapture: "micrófono",
                QWebEnginePage.Feature.MediaVideoCapture: "cámara",
                QWebEnginePage.Feature.MediaAudioVideoCapture: "micrófono y cámara",
            }.get(feature, str(feature))

            is_trusted = any(
                host == trusted or host.endswith("." + trusted)
                for trusted in config.TRUSTED_MEDIA_DOMAINS
            )

            if is_trusted:
                page.setFeaturePermission(
                    origin, feature, QWebEnginePage.PermissionPolicy.GrantedByUser
                )
                logger.info(
                    "Permiso concedido automáticamente: %s → %s (dominio confiable)",
                    feature_name, host,
                )
                return

            reply = QMessageBox.question(
                self,
                "D.I.O. — Permiso de hardware",
                (
                    f"<b>{origin.host()}</b> solicita acceso a tu "
                    f"<b>{feature_name}</b>.<br><br>"
                    f"¿Permitir?"
                ),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )

            if reply == QMessageBox.StandardButton.Yes:
                page.setFeaturePermission(
                    origin, feature, QWebEnginePage.PermissionPolicy.GrantedByUser
                )
                logger.info("Permiso concedido por usuario: %s → %s", feature_name, host)
            else:
                page.setFeaturePermission(
                    origin, feature, QWebEnginePage.PermissionPolicy.DeniedByUser
                )
                logger.info("Permiso denegado por usuario: %s → %s", feature_name, host)
            return

        page.setFeaturePermission(
            origin, feature, QWebEnginePage.PermissionPolicy.DeniedByUser
        )

    # ── Gestión de descargas ──────────────────────────────────────────────

    def _on_download_requested(
        self,
        download: QWebEngineDownloadRequest,
        panel_idx: int,
        preset_name: str,
    ) -> None:
        suggested_name = download.suggestedFileName() or "descarga"
        settings = config.load_settings()
        custom_dl_dir = settings.get("downloads_dir", str(Path.home() / "Downloads" / "DIO"))
        ask_location = settings.get("ask_download_location", _ASK_DOWNLOAD)

        base_dir = Path(custom_dl_dir).expanduser() if custom_dl_dir else Path.home() / "Downloads" / "DIO"
        base_dir.mkdir(parents=True, exist_ok=True)

        if ask_location:
            default_save = str(base_dir / suggested_name)
            save_path, _ = QFileDialog.getSaveFileName(
                self,
                "D.I.O. — Guardar archivo",
                default_save,
            )
            if not save_path:
                download.cancel()
                logger.info("Descarga cancelada por usuario: %s (panel %d)", suggested_name, panel_idx)
                return
            dest = Path(save_path)
            download.setDownloadDirectory(str(dest.parent))
            download.setDownloadFileName(dest.name)
        else:
            dest_dir = base_dir / preset_name if preset_name else base_dir
            dest_dir.mkdir(parents=True, exist_ok=True)
            download.setDownloadDirectory(str(dest_dir))
            download.setDownloadFileName(suggested_name)

        download.accept()
        logger.info(
            "Descarga iniciada: '%s' desde panel %d → %s",
            suggested_name, panel_idx, download.downloadDirectory(),
        )

        download.isFinishedChanged.connect(
            lambda dl=download, name=suggested_name: self._on_download_finished(dl, name)
        )

    def _on_download_finished(
        self, download: QWebEngineDownloadRequest, name: str
    ) -> None:
        if download.state() == QWebEngineDownloadRequest.DownloadState.DownloadCompleted:
            msg = f"[OK] Descarga completada: {name}"
            color = "#006622"
            logger.info("Descarga completada: '%s'", name)
        else:
            msg = f"[ERROR] Descarga fallida: {name}"
            color = "#880000"
            logger.warning("Descarga fallida: '%s' (estado=%s)", name, download.state())

        ToastNotification(msg, self, color)

    # ── Control de audio ──────────────────────────────────────────────────

    def _toggle_mute(self) -> None:
        """Ctrl+M: silencia/activa el audio del panel con foco."""
        view = self._get_focused_view()
        if view is None:
            return

        page = view.page()
        new_muted = not page.isAudioMuted()
        page.setAudioMuted(new_muted)

        panel_idx = self._panels.index(view) if view in self._panels else -1
        if 0 <= panel_idx < len(self._mute_indicators):
            indicator = self._mute_indicators[panel_idx]
            indicator.reposition()
            if new_muted:
                indicator.show()
                indicator.raise_()
            else:
                indicator.hide()

        state = "silenciado" if new_muted else "con audio"
        logger.info("Panel %d: %s", panel_idx, state)

    def _mute_all(self) -> None:
        """Ctrl+Shift+A: silencia todos los paneles."""
        for idx, view in enumerate(self._panels):
            view.page().setAudioMuted(True)
            if idx < len(self._mute_indicators):
                indicator = self._mute_indicators[idx]
                indicator.reposition()
                indicator.show()
                indicator.raise_()
        logger.info("Todos los paneles silenciados (%d)", len(self._panels))

    # ── Importación de cookies ────────────────────────────────────────────

    def _import_cookies(self) -> None:
        """Ctrl+Shift+I: Importa cookies desde navegadores instalados en el sistema."""
        view = self._get_focused_view()
        if view is None:
            return

        panel_idx = self._panels.index(view) if view in self._panels else 0
        current_domain = view.url().host() or ""
        if current_domain.startswith("www."):
            current_domain = current_domain[4:]

        dialog = QDialog(self)
        dialog.setWindowTitle("D.I.O. — Importar cookies")
        dialog.resize(440, 180)
        layout = QFormLayout(dialog)

        browser_combo = QComboBox()
        browser_combo.addItems([
            "Chrome", "Chromium", "Firefox", "Edge", "Brave", "Opera", "Vivaldi",
        ])
        browser_combo.setStyleSheet("background-color: #1e1e2e; color: #ffffff; padding: 6px; border: 1px solid #45475a; border-radius: 4px;")
        layout.addRow("Navegador de origen:", browser_combo)

        domain_edit = QLineEdit(current_domain)
        domain_edit.setStyleSheet("background-color: #1e1e2e; color: #ffffff; padding: 6px; border: 1px solid #45475a; border-radius: 4px;")
        layout.addRow("Dominio a importar:", domain_edit)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addRow(buttons)

        notice = QLabel("[AVISO] Solo se leeran cookies del dominio indicado. Nunca se registran valores en logs.")
        notice.setStyleSheet("color: #a6adc8; font-size: 11px;")
        layout.addRow(notice)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        browser_name = browser_combo.currentText().lower()
        domain = domain_edit.text().strip()
        if not domain:
            QMessageBox.warning(self, "D.I.O.", "Debes especificar un dominio.")
            return

        try:
            import browser_cookie3

            browser_fn_map = {
                "chrome":   browser_cookie3.chrome,
                "chromium": browser_cookie3.chromium,
                "firefox":  browser_cookie3.firefox,
                "edge":     browser_cookie3.edge,
                "brave":    browser_cookie3.brave,
                "opera":    browser_cookie3.opera,
                "vivaldi":  browser_cookie3.vivaldi,
            }

            browser_fn = browser_fn_map.get(browser_name)
            if browser_fn is None:
                QMessageBox.warning(self, "D.I.O.", f"Navegador '{browser_name}' no soportado.")
                return

            cookiejar = browser_fn(domain_name=domain)

        except PermissionError:
            QMessageBox.critical(
                self, "D.I.O. — Error de acceso",
                f"No se puede acceder a las cookies de {browser_combo.currentText()}.\n\n"
                "Cierra el navegador completamente e inténtalo de nuevo.",
            )
            logger.warning("Importación bloqueada: %s tiene cookies bloqueadas", browser_combo.currentText())
            return
        except Exception as exc:
            QMessageBox.critical(self, "D.I.O. — Error", f"No se pudieron leer las cookies:\n{exc}")
            logger.error("Error importando cookies desde %s: %s", browser_combo.currentText(), exc)
            return

        profile = self._profiles[panel_idx] if panel_idx < len(self._profiles) else None
        if profile is None:
            return

        cookie_store = profile.cookieStore()
        count = 0
        for cookie in cookiejar:
            qt_cookie = QNetworkCookie()
            qt_cookie.setName(cookie.name.encode())
            qt_cookie.setValue(cookie.value.encode())
            qt_cookie.setDomain(cookie.domain)
            qt_cookie.setPath(cookie.path)
            qt_cookie.setSecure(bool(cookie.secure))
            if cookie.expires and cookie.expires > 0:
                from PyQt6.QtCore import QDateTime
                qt_cookie.setExpirationDate(
                    QDateTime.fromSecsSinceEpoch(int(cookie.expires))
                )
            cookie_store.setCookie(qt_cookie)
            count += 1

        view.reload()
        logger.info(
            "Cookies importadas: dominio=%s, navegador=%s, cantidad=%d, panel=%d",
            domain, browser_combo.currentText(), count, panel_idx,
        )

        ToastNotification(f"[OK] {count} cookies importadas desde {browser_combo.currentText()}", self)

    # ── Crash recovery ────────────────────────────────────────────────────

    def _on_render_crash(
        self,
        view: QWebEngineView,
        panel_idx: int,
        status: QWebEnginePage.RenderProcessTerminationStatus,
        exit_code: int,
    ) -> None:
        status_names = {
            QWebEnginePage.RenderProcessTerminationStatus.NormalTerminationStatus: "normal",
            QWebEnginePage.RenderProcessTerminationStatus.AbnormalTerminationStatus: "abnormal",
            QWebEnginePage.RenderProcessTerminationStatus.CrashedTerminationStatus: "crashed",
            QWebEnginePage.RenderProcessTerminationStatus.KilledTerminationStatus: "killed",
        }
        status_str = status_names.get(status, f"desconocido({status})")
        logger.warning(
            "Panel %d: proceso de render terminado (estado=%s, código=%d).",
            panel_idx, status_str, exit_code,
        )

        if panel_idx >= len(self._fsms):
            return

        fsm = self._fsms[panel_idx]
        if fsm.can_trigger(PanelEvent.RENDER_CRASHED):
            fsm.trigger(PanelEvent.RENDER_CRASHED)

        cfg = config.load_config_toml()
        rec_cfg = cfg.get("recovery", {})
        max_retries = rec_cfg.get("max_retries", fsm.max_retries)
        fsm.max_retries = max_retries
        base_s = rec_cfg.get("backoff_base_s", 1.0)
        max_s = rec_cfg.get("backoff_max_s", 16.0)

        if fsm.can_retry():
            if fsm.can_trigger(PanelEvent.RECOVERY_STARTED):
                fsm.trigger(PanelEvent.RECOVERY_STARTED)
            # Backoff exponencial: base_s * 2^(crash_count - 1), tope max_s
            # Para max_retries=3: intento 1 -> 1.0s, intento 2 -> 2.0s, intento 3 -> 4.0s
            delay = min(base_s * (2 ** (fsm.crash_count - 1)), max_s)
            logger.info(
                "Panel %d [%s]: Programando reintento de recuperación %d/%d en %.1fs",
                panel_idx, fsm.panel_id, fsm.crash_count, max_retries, delay,
            )
            if panel_idx < len(self._crash_overlays):
                self._crash_overlays[panel_idx].show_recovering(fsm.crash_count, max_retries, delay)
            QTimer.singleShot(int(delay * 1000), lambda i=panel_idx: self._attempt_crash_recovery(i))
        else:
            logger.warning(
                "Panel %d [%s]: Agotados %d reintentos automáticos. Transicionando a FAILED.",
                panel_idx, fsm.panel_id, max_retries,
            )
            if fsm.can_trigger(PanelEvent.RECOVERY_FAILED):
                fsm.trigger(PanelEvent.RECOVERY_FAILED)
            if panel_idx < len(self._crash_overlays):
                self._crash_overlays[panel_idx].show_failed()

    def _attempt_crash_recovery(self, idx: int) -> None:
        """Recrea de forma segura el panel tras un crash usando el mismo perfil (Decisión 2)."""
        if idx < 0 or idx >= len(self._panels):
            return

        fsm = self._fsms[idx]
        if fsm.state != PanelState.RECOVERING:
            return

        view = self._panels[idx]
        panel_id = f"panel_{idx}"
        is_pinned = self._pinned_flags[idx] if idx < len(self._pinned_flags) else False

        logger.info("Panel %d [%s]: Ejecutando reintento de recuperación (intento %d)", idx, panel_id, fsm.crash_count)

        # 1. Desacoplar página averiada
        old_page = view.page()
        view.setPage(None)
        if old_page is not None and not sip.isdeleted(old_page):
            try:
                old_page.setParent(None)
                sip.delete(old_page)
            except Exception:
                old_page.deleteLater()

        # 2. Recrear con el mismo perfil persistente en disco (Decisión 2)
        profile = self._profile_manager.get_or_create_profile(
            panel_id,
            is_pinned=is_pinned,
            adblock_interceptor=self._adblock_interceptor,
            dark_mode=_DARK_MODE,
        )
        if idx < len(self._profiles):
            self._profiles[idx] = profile

        page = DIOPage(profile, view)
        page.featurePermissionRequested.connect(
            lambda origin, feature, p=page: self._handle_permission(p, origin, feature)
        )
        view.setPage(page)

        # 3. Recargar última URL conocida
        target_url = self._last_known_urls[idx] if idx < len(self._last_known_urls) else "about:blank"
        view.setUrl(QUrl(target_url))

    def manual_reload_panel(self, idx: int) -> None:
        """Permite al usuario forzar la recarga manual tras agotarse los reintentos automáticos."""
        if idx < 0 or idx >= len(self._panels):
            return
        fsm = self._fsms[idx]
        if fsm.state == PanelState.FAILED:
            fsm.trigger(PanelEvent.MANUAL_RELOAD)
            self._attempt_crash_recovery(idx)

    # ── Hibernación de memoria (Tab Discarding) ───────────────────────────

    def hibernate_panel(self, idx: int) -> bool:
        """
        Transiciona un panel de ACTIVE -> HIBERNATING -> HIBERNATED.
        Captura snapshot visual, destruye la QWebEnginePage liberando el proceso Chromium hijo,
        muestra el snapshot con el overlay y conserva el perfil persistente en disco (Decisión 2).
        """
        if idx < 0 or idx >= len(self._panels):
            return False

        fsm = self._fsms[idx]
        if fsm.state != PanelState.ACTIVE:
            logger.warning("No se puede hibernar panel %d: estado actual es %s", idx, fsm.state.name)
            return False

        if idx < len(self._pinned_flags) and self._pinned_flags[idx]:
            logger.info("Panel %d está marcado como PINNED (Do Not Sleep); hibernación ignorada", idx)
            return False

        view = self._panels[idx]
        panel_id = f"panel_{idx}"

        try:
            fsm.trigger(PanelEvent.DISCARD_REQUESTED)

            # 1. Captura de snapshot visual con grab()
            pixmap = view.grab()

            # 2. Mostrar overlay estático de hibernación
            if idx < len(self._hibernation_overlays):
                hib_overlay = self._hibernation_overlays[idx]
                hib_overlay.set_snapshot(pixmap)
                hib_overlay.reposition()
                hib_overlay.show()
                hib_overlay.raise_()

            fsm.trigger(PanelEvent.DISCARD_COMPLETED)

            # 3. Desacople y destrucción de QWebEnginePage para liberar proceso de Chromium
            page = view.page()
            view.setPage(None)
            if page is not None and not sip.isdeleted(page):
                try:
                    page.setParent(None)
                    sip.delete(page)
                except Exception:
                    page.deleteLater()

            # 4. Decisión 2: Notificar a ProfileManager para liberar referencia en memoria (sin tocar disco)
            self._profile_manager.release_profile_reference(panel_id)

            logger.info("Panel %d [%s] hibernado exitosamente (memoria de renderer liberada)", idx, panel_id)
            return True
        except Exception as exc:
            logger.error("Error al hibernar panel %d: %s", idx, exc)
            return False

    def wake_panel(self, idx: int) -> bool:
        """
        Transiciona un panel de HIBERNATED -> RESTORING -> ACTIVE.
        Recrea QWebEnginePage con el MISMO perfil persistente en disco (Decisión 2)
        y recarga la última URL conocida.
        """
        if idx < 0 or idx >= len(self._panels):
            return False

        fsm = self._fsms[idx]
        if fsm.state != PanelState.HIBERNATED:
            return False

        view = self._panels[idx]
        panel_id = f"panel_{idx}"
        is_pinned = self._pinned_flags[idx] if idx < len(self._pinned_flags) else False

        try:
            fsm.trigger(PanelEvent.RESTORE_REQUESTED)

            # 1. Recrear perfil y página compartida (Decisión 2: datos en disco intactos)
            profile = self._profile_manager.get_or_create_profile(
                panel_id,
                is_pinned=is_pinned,
                adblock_interceptor=self._adblock_interceptor,
                dark_mode=_DARK_MODE,
            )
            if idx < len(self._profiles):
                self._profiles[idx] = profile

            page = DIOPage(profile, view)
            page.featurePermissionRequested.connect(
                lambda origin, feature, p=page: self._handle_permission(p, origin, feature)
            )

            settings = page.settings()
            settings.setAttribute(QWebEngineSettings.WebAttribute.LocalStorageEnabled, True)
            settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
            settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanAccessClipboard, True)
            settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanPaste, True)

            view.setPage(page)

            # 2. Restaurar última URL
            target_url = self._last_known_urls[idx] if idx < len(self._last_known_urls) else "about:blank"
            view.setUrl(QUrl(target_url))

            if idx < len(self._last_focused_times):
                self._last_focused_times[idx] = time.time()

            logger.info("Panel %d [%s] restaurando desde hibernación hacia %s", idx, panel_id, target_url)
            return True
        except Exception as exc:
            logger.error("Error al despertar panel %d: %s", idx, exc)
            return False

    def _check_background_sleeping(self) -> None:
        """Verifica periódicamente qué paneles en background superaron el timeout de inactividad."""
        cfg = config.load_config_toml()
        sleeping_cfg = cfg.get("sleeping", {})
        if not sleeping_cfg.get("enabled", False):
            return

        timeout_minutes = sleeping_cfg.get("timeout_minutes", 15)
        timeout_s = timeout_minutes * 60
        now = time.time()

        focused_view = self._get_focused_view()

        for i, view in enumerate(self._panels):
            if i >= len(self._fsms) or i >= len(self._pinned_flags):
                continue

            # 1. Perfil marcado como Pinned NUNCA hiberna
            if self._pinned_flags[i]:
                continue

            # 2. Panel debe estar ACTIVE
            if self._fsms[i].state != PanelState.ACTIVE:
                continue

            # 3. Panel no debe tener el foco
            if view == focused_view or view.hasFocus():
                if i < len(self._last_focused_times):
                    self._last_focused_times[i] = now
                continue

            # 4. Panel no debe tener audio activo
            page = view.page()
            if page is not None and hasattr(page, "recentlyAudible") and page.recentlyAudible():
                continue

            # 5. Superó el timeout en background
            last_focus = self._last_focused_times[i] if i < len(self._last_focused_times) else now
            if now - last_focus >= timeout_s:
                logger.info("Hibernando panel %d por inactividad (>%d min)", i, timeout_minutes)
                self.hibernate_panel(i)

    def toggle_pin_focused_panel(self) -> None:
        """Ctrl+P: Conmuta el estado 'Pinned / Do Not Sleep' para el panel con foco."""
        view = self._get_focused_view()
        if view is None or view not in self._panels:
            return

        idx = self._panels.index(view)
        new_pinned = not self._pinned_flags[idx]
        self._pinned_flags[idx] = new_pinned
        panel_id = f"panel_{idx}"

        self._profile_manager.set_pinned(panel_id, new_pinned)

        # Persistir en config.toml
        cfg = config.load_config_toml()
        cfg.setdefault("panels", {}).setdefault(panel_id, {})["pinned"] = new_pinned
        config.save_config_toml(cfg)

        status_str = "FIJADO [PIN] (Do Not Sleep)" if new_pinned else "DESFIJADO [SLEEP] (Hibernacion activa)"
        ToastNotification(f"Panel {idx} {status_str}", self)
        logger.info("Panel %d [%s]: %s", idx, panel_id, status_str)

    def _manual_hibernate_focused(self) -> None:
        """Ctrl+Shift+H: Hiberna manualmente el panel con foco (para pruebas o ahorro inmediato)."""
        view = self._get_focused_view()
        if view is None or view not in self._panels:
            return
        idx = self._panels.index(view)
        # Desenfocar para permitir hibernar
        self.setFocus()
        self.hibernate_panel(idx)

    # ── Persistencia de sesión ────────────────────────────────────────────

    def _save_session(self) -> None:
        """Guarda el layout de trabajo actual en ~/.dio/session.json."""
        if not self._panels:
            return
        try:
            config.DIO_DIR.mkdir(parents=True, exist_ok=True)

            urls = [view.url().toString() for view in self._panels]
            splitter_states = self._serialize_splitter_states()

            session = {
                "preset": self._preset_name,
                "grid": f"{self._rows}x{self._cols}",
                "panel_counter": self._panel_counter,
                "urls": urls,
                "splitter_states": splitter_states,
            }

            config.SESSION_FILE.write_text(
                json.dumps(session, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )

            logger.info("Sesión guardada: %d paneles", len(urls))
            for i, url in enumerate(urls):
                logger.info("  Panel %d: %s", i, url)

        except Exception as exc:
            logger.error("Error guardando sesión: %s", exc)

    def _serialize_splitter_states(self) -> dict:
        states = {}
        root = self._root_splitter
        states["root"] = base64.b64encode(bytes(root.saveState())).decode("ascii")
        for i in range(root.count()):
            child = root.widget(i)
            if isinstance(child, QSplitter):
                states[f"row_{i}"] = base64.b64encode(bytes(child.saveState())).decode("ascii")
        return states

    def _restore_splitter_states(self, states: dict) -> None:
        try:
            root = self._root_splitter
            if "root" in states:
                root.restoreState(QByteArray(base64.b64decode(states["root"])))
            for i in range(root.count()):
                key = f"row_{i}"
                if key in states:
                    child = root.widget(i)
                    if isinstance(child, QSplitter):
                        child.restoreState(QByteArray(base64.b64decode(states[key])))
            logger.info("Estados de splitters restaurados")
        except Exception as exc:
            logger.warning("Error restaurando splitters: %s", exc)

    def closeEvent(self, event) -> None:
        # Detener servidor IPC antes del cierre (Paso 4)
        if hasattr(self, '_ipc_server') and self._ipc_server is not None:
            self._ipc_server.stop()

        # H-02: Guardar sesión antes de desmontar paneles y desacoplar
        # explícitamente las páginas para evitar use-after-free y warnings
        # de "Release of profile requested but WebEnginePage still not deleted".
        self._save_session()
        for i, panel in enumerate(self._panels):
            logger.info(
                "Cierre — Panel %d: URL=%s, tamaño=%dx%d",
                i, panel.url().toString(), panel.width(), panel.height(),
            )
        while self._panels:
            self.teardown_panel(0)
        super().closeEvent(event)

    # ── Redimensionado ────────────────────────────────────────────────────

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        for overlay in self._overlays:
            if overlay.isVisible():
                overlay.reposition()
        for indicator in self._mute_indicators:
            if indicator.isVisible():
                indicator.reposition()
        for hib in self._hibernation_overlays:
            if hib.isVisible():
                hib.reposition()
        for crash in self._crash_overlays:
            if crash.isVisible():
                crash.reposition()

    # ── Atajos de teclado ─────────────────────────────────────────────────

    def _setup_shortcuts(self) -> None:
        def reg(key: str, description: str, callback) -> None:
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.activated.connect(callback)
            self.shortcuts_registry[key] = description

        # Cerrar la aplicación (Ctrl+Q; se eliminó Esc para evitar cierres accidentales al usar la web)
        reg("Ctrl+Q", "Cerrar la aplicación y guardar sesión", self.close)

        # Fijar panel (Pinned / Do Not Sleep) y forzar hibernación
        reg("Ctrl+P", "Fijar / Desfijar panel activo (Pinned: Do Not Sleep)", self.toggle_pin_focused_panel)
        reg("Ctrl+Shift+H", "Hibernar panel activo inmediatamente", self._manual_hibernate_focused)

        # Navegación y Búsqueda inteligente
        reg("Ctrl+L", "Ir a URL o Buscar en Google en el panel activo", self._goto_url)

        # Historial de navegación
        reg("Alt+Left", "Retroceder en el historial del panel activo", self._go_back)
        reg("Alt+Right", "Avanzar en el historial del panel activo", self._go_forward)

        # Recarga
        reg("Ctrl+R", "Recargar el panel activo", self._reload_focused)
        reg("Ctrl+Shift+R", "Recargar TODOS los paneles", self._reload_all)

        # Gestión de paneles y Ventanas
        reg("Ctrl+N", "Agregar un panel nuevo a la cuadrícula actual", self._add_panel)
        reg("Ctrl+Shift+N", "Abrir una nueva ventana independiente de D.I.O.", self._open_new_window)
        reg("Ctrl+W", "Quitar el panel activo y reorganizar grid", self._remove_panel)

        # Foco directo
        for n in range(1, 10):
            reg(
                f"Ctrl+{n}",
                f"Mover foco al panel {n}",
                lambda checked=False, idx=n - 1: self._focus_panel(idx),
            )

        # Pantalla completa
        reg("F11", "Alternar pantalla completa / ventana normal", self._toggle_fullscreen)

        # Control de audio
        reg("Ctrl+M", "Silenciar / activar audio del panel activo (muestra indicador MUTE)", self._toggle_mute)
        reg("Ctrl+Shift+A", "Silenciar TODOS los paneles simultáneamente", self._mute_all)

        # Reorganización y Nivelación de Cuadrícula
        reg("Ctrl+E", "Nivelar y equilibrar todos los paneles simétricamente al 100%", self._equalize_panels)
        reg("Ctrl+Shift+E", "Nivelar y equilibrar todos los paneles simétricamente al 100%", self._equalize_panels)
        reg("Ctrl+G", "Menú rápido para reorganizar cuadrícula (3 cols × 2 filas, 2x2, etc.)", self._change_grid_dialog)

        # Workspaces virtuales (Paso 6): Ctrl+Alt+1..9 configurable desde config.toml
        cfg = config.load_config_toml()
        ws_prefix = cfg.get("shortcuts", {}).get("workspace_prefix", "Ctrl+Alt")
        detach_key = cfg.get("shortcuts", {}).get("detach_panel", "Ctrl+Shift+D")

        for ws_idx in range(self._max_workspaces):
            ws_num = ws_idx + 1
            reg(
                f"{ws_prefix}+{ws_num}",
                f"Cambiar a Workspace {ws_num}",
                lambda checked=False, i=ws_idx: self.switch_workspace(i),
            )

        # Desacoplar panel (Paso 6)
        reg(detach_key, "Desacoplar panel activo a ventana flotante", self.detach_focused_panel)

        # Importar cookies
        reg(
            "Ctrl+Shift+I",
            "Importar cookies/sesión desde navegador del sistema",
            self._import_cookies,
        )

        # Panel de Configuración y Manual (F1)
        reg("F1", "Abrir el panel de configuración y atajos de D.I.O.", self._show_shortcuts_manual)
        reg(
            "Ctrl+Shift+M",
            "Mostrar el panel de configuración y manual",
            self._show_shortcuts_manual,
        )

    # ── Acciones de atajos ────────────────────────────────────────────────

    def _get_focused_view(self) -> QWebEngineView | None:
        focus_widget = QApplication.focusWidget()
        if focus_widget is None:
            ws_panels = [p for i, p in enumerate(self._panels) if i < len(self._panel_workspaces) and self._panel_workspaces[i] == self._current_workspace_idx and p not in self._detached_views]
            return ws_panels[0] if ws_panels else (self._panels[0] if self._panels else None)
        widget = focus_widget
        while widget is not None:
            if isinstance(widget, QWebEngineView):
                return widget
            widget = widget.parent()
        ws_panels = [p for i, p in enumerate(self._panels) if i < len(self._panel_workspaces) and self._panel_workspaces[i] == self._current_workspace_idx and p not in self._detached_views]
        return ws_panels[0] if ws_panels else (self._panels[0] if self._panels else None)

    def _goto_url(self) -> None:
        """Abre la ventana inteligente de búsqueda/URL para el panel activo."""
        view = self._get_focused_view()
        if view is None:
            return

        current_url = view.url().toString()
        if current_url in ("about:blank", "about:blank/"):
            current_url = ""

        dialog = OmniSearchDialog(self, title="Ir a URL o Buscar en Google", initial_text=current_url)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.result_url:
            view.setUrl(QUrl(dialog.result_url))
            panel_idx = self._panels.index(view) if view in self._panels else -1
            logger.info("Ctrl+L: panel %d → %s", panel_idx, dialog.result_url)

    def _go_back(self) -> None:
        view = self._get_focused_view()
        if view is not None:
            view.page().triggerAction(QWebEnginePage.WebAction.Back)

    def _go_forward(self) -> None:
        view = self._get_focused_view()
        if view is not None:
            view.page().triggerAction(QWebEnginePage.WebAction.Forward)

    def _reload_focused(self) -> None:
        view = self._get_focused_view()
        if view is not None:
            view.reload()

    def _reload_all(self) -> None:
        for panel in self._panels:
            panel.reload()

    def _add_panel(self) -> None:
        """Agrega un panel nuevo pidiendo la URL o término de búsqueda."""
        dialog = OmniSearchDialog(self, title="Nuevo Panel — Buscar o URL")
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.result_url:
            view = self._create_panel(dialog.result_url)
            self._panels.append(view)
            self._panel_workspaces.append(self._current_workspace_idx)
            self._rebuild_grid()
            logger.info("Panel agregado a Workspace %d: %s (total=%d)", self._current_workspace_idx + 1, dialog.result_url, len(self._panels))

    def teardown_panel(self, idx: int) -> None:
        """
        H-01 / H-02 & DECISIÓN 2: Destruye de forma determinista un panel y sus recursos asociados.
        Aplica el desacople estricto: panel.setPage(None) antes de destruir la página,
        destruye la página explícitamente y libera la referencia en memoria vía ProfileManager.
        Los datos y sesiones en disco (~/.dio/profiles/panel_N/) NUNCA se destruyen aquí.
        """
        if idx < 0 or idx >= len(self._panels):
            return

        view = self._panels.pop(idx)
        profile = self._profiles.pop(idx) if idx < len(self._profiles) else None
        panel_id = f"panel_{idx}"

        if idx < len(self._overlays):
            overlay = self._overlays.pop(idx)
            overlay.setParent(None)
            overlay.deleteLater()

        if idx < len(self._mute_indicators):
            indicator = self._mute_indicators.pop(idx)
            indicator.setParent(None)
            indicator.deleteLater()

        if idx < len(self._hibernation_overlays):
            hib_ov = self._hibernation_overlays.pop(idx)
            hib_ov.setParent(None)
            hib_ov.deleteLater()

        if idx < len(self._crash_overlays):
            crash_ov = self._crash_overlays.pop(idx)
            crash_ov.setParent(None)
            crash_ov.deleteLater()

        if idx < len(self._fsms):
            self._fsms.pop(idx)

        if idx < len(self._agent_states):
            self._agent_states.pop(idx)

        if idx < len(self._panel_workspaces):
            self._panel_workspaces.pop(idx)

        if idx < len(self._pinned_flags):
            self._pinned_flags.pop(idx)

        if idx < len(self._last_focused_times):
            self._last_focused_times.pop(idx)

        if idx < len(self._last_known_urls):
            self._last_known_urls.pop(idx)

        # Desacoplar vista del layout
        view.setParent(None)

        # 1. H-01: Desacoplar explícitamente la página del QWebEngineView
        page = view.page()
        view.setPage(None)

        # 2. Destruir la página desacoplada antes de liberar el perfil
        if page is not None and not sip.isdeleted(page):
            try:
                page.setParent(None)
                sip.delete(page)
            except Exception:
                page.deleteLater()
        view.deleteLater()

        # 3. DECISIÓN 2: Liberar la referencia en ProfileManager (LRU en memoria).
        #    Los datos en disco (~/.dio/profiles/panel_N/) permanecen 100% intactos.
        self._profile_manager.release_profile_reference(panel_id)
        if profile is not None and profile.parent() == self:
            profile.deleteLater()

    def _remove_panel(self) -> None:
        view = self._get_focused_view()
        if view is None or len(self._panels) <= 1:
            return
        idx = self._panels.index(view) if view in self._panels else -1
        if idx < 0:
            return
        url = view.url().toString()
        self.teardown_panel(idx)
        self._rebuild_grid()
        logger.info("Panel %d eliminado: %s (restantes=%d)", idx, url, len(self._panels))

    def _focus_panel(self, idx: int) -> None:
        if 0 <= idx < len(self._panels):
            if idx < len(self._fsms) and self._fsms[idx].state == PanelState.HIBERNATED:
                self.wake_panel(idx)
            self._panels[idx].setFocus()
            if idx < len(self._last_focused_times):
                self._last_focused_times[idx] = time.time()
            # AI Cockpit: limpieza automatica del indicador al hacer foco en el panel
            if idx < len(self._agent_states) and self._agent_states[idx] == AgentState.DONE:
                self._agent_states[idx] = AgentState.IDLE
                self._update_panel_border(idx, AgentState.IDLE)

    def _toggle_fullscreen(self) -> None:
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def _equalize_panels(self) -> None:
        """Nivela y reequilibra el tamaño de todos los paneles al 100% simétrico."""
        if not self._root_splitter:
            return
        self._rebuild_grid()
        ToastNotification(
            f"Cuadricula equilibrada: {self._cols} columnas x {self._rows} filas",
            self,
            color="#2563eb",
        )
        logger.info("Paneles ecualizados simétricamente: %dx%d", self._rows, self._cols)

    def _set_grid_dimensions(self, rows: int, cols: int) -> None:
        """Cambia la cuadrícula a dimensiones específicas y nivela los tamaños."""
        self._rows = rows
        self._cols = cols
        self._rebuild_grid()
        ToastNotification(
            f"Cuadricula organizada: {cols} columnas x {rows} filas",
            self,
            color="#059669",
        )
        logger.info("Grid cambiado a %dx%d (%d columnas, %d filas)", rows, cols, cols, rows)

    def _change_grid_dialog(self) -> None:
        """Abre el diálogo rápido para elegir disposición de columnas y filas."""
        dialog = GridChooserDialog(self._rows, self._cols, len(self._panels), self)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.selected_grid:
            r, c = dialog.selected_grid
            self._set_grid_dimensions(r, c)

    def _open_new_window(self) -> None:
        """Lanza una nueva ventana/instancia independiente de D.I.O."""
        cmd = [sys.executable, str(Path(__file__).resolve()), "--preset", self._preset_name]
        subprocess.Popen(cmd)
        ToastNotification("Nueva ventana de D.I.O. iniciada", self)
        logger.info("Nueva ventana de D.I.O. lanzada")

    def apply_settings(self, settings_dict: dict) -> None:
        """Aplica dinámicamente configuraciones en caliente."""
        gaps = settings_dict.get("gaps", 0)
        config.PANEL_SPACING = gaps
        if self._root_splitter:
            self._root_splitter.setHandleWidth(gaps)
        logger.info("Ajustes aplicados en caliente: gaps=%d", gaps)

    def _show_shortcuts_manual(self) -> None:
        """Muestra o cierra (toggle) el Overlay Modal de configuración y manual."""
        if hasattr(self, "_active_manual_dialog") and self._active_manual_dialog is not None:
            try:
                self._active_manual_dialog.accept()
            except Exception:
                pass
            self._active_manual_dialog = None
            return

        dialog = SettingsOverlayDialog(self.shortcuts_registry, self, self)
        self._active_manual_dialog = dialog
        dialog.exec()
        self._active_manual_dialog = None

    # ── IPC: Paso 4 — Handler de comandos ─────────────────────────────────

    def _panel_id_to_index(self, panel_id: str) -> int:
        """
        Convierte un panel_id estable (ej. 'panel_0') al índice actual en self._panels.
        Recorre las FSMs que almacenan el panel_id original.
        Retorna -1 si no se encuentra.
        """
        for idx, fsm in enumerate(self._fsms):
            if fsm.panel_id == panel_id:
                return idx
        return -1

    def _panel_index_to_id(self, idx: int) -> str:
        """Retorna el panel_id estable para un índice dado."""
        if 0 <= idx < len(self._fsms):
            return self._fsms[idx].panel_id
        return f"panel_{idx}"

    def handle_ipc_command(self, command: str, params: dict) -> dict:
        """
        Despacha un comando IPC recibido del DIOIpcServer.
        Retorna un dict con el resultado (será serializado como JSON).
        """
        try:
            cmd = IpcCommand(command)
        except ValueError:
            raise ValueError(f"Comando IPC desconocido: '{command}'")

        if cmd == IpcCommand.STATUS:
            return self._ipc_status()
        elif cmd == IpcCommand.NAVIGATE:
            return self._ipc_navigate(params)
        elif cmd == IpcCommand.FOCUS:
            return self._ipc_focus(params)
        elif cmd == IpcCommand.CLOSE_PANEL:
            return self._ipc_close_panel(params)
        elif cmd == IpcCommand.SPLIT:
            return self._ipc_split(params)
        elif cmd == IpcCommand.EVAL_JS:
            return self._ipc_eval_js(params)
        else:
            raise ValueError(f"Comando '{command}' no implementado")

    def _ipc_status(self) -> dict:
        """Retorna estado completo de todos los paneles para consumo externo."""
        panels_info = []
        for idx, view in enumerate(self._panels):
            panel_id = self._panel_index_to_id(idx)
            state = self._fsms[idx].state.name.lower() if idx < len(self._fsms) else "unknown"
            agent_st = self._agent_states[idx].value if idx < len(self._agent_states) else "idle"
            url = view.url().toString() if view else ""
            pinned = self._pinned_flags[idx] if idx < len(self._pinned_flags) else False
            ws_num = (self._panel_workspaces[idx] + 1) if idx < len(self._panel_workspaces) else 1
            is_detached = view in self._detached_views
            panels_info.append({
                "panel_id": panel_id,
                "index": idx,
                "workspace": ws_num,
                "detached": is_detached,
                "state": state,
                "agent_state": agent_st,
                "url": url,
                "pinned": pinned,
            })

        return {
            "current_workspace": self._current_workspace_idx + 1,
            "max_workspaces": self._max_workspaces,
            "panel_count": len(self._panels),
            "grid": f"{self._rows}x{self._cols}",
            "preset": self._preset_name,
            "panels": panels_info,
        }

    def _ipc_navigate(self, params: dict) -> dict:
        """Navega un panel a una URL. Requiere: panel_id, url."""
        panel_id = params.get("panel_id", "")
        url = params.get("url", "")
        if not panel_id or not url:
            raise ValueError("Faltan parámetros: 'panel_id' y 'url' son requeridos")

        idx = self._panel_id_to_index(panel_id)
        if idx < 0 or idx >= len(self._panels):
            raise ValueError(f"Panel '{panel_id}' no encontrado")

        # Si está hibernado, despertar primero
        if idx < len(self._fsms) and self._fsms[idx].state == PanelState.HIBERNATED:
            self.wake_panel(idx)

        self._panels[idx].setUrl(QUrl(url))
        logger.info("IPC: navigate %s → %s", panel_id, url)
        return {"panel_id": panel_id, "url": url}

    def _ipc_focus(self, params: dict) -> dict:
        """Da foco a un panel. Requiere: panel_id."""
        panel_id = params.get("panel_id", "")
        if not panel_id:
            raise ValueError("Falta parámetro: 'panel_id' es requerido")

        idx = self._panel_id_to_index(panel_id)
        if idx < 0 or idx >= len(self._panels):
            raise ValueError(f"Panel '{panel_id}' no encontrado")

        self._focus_panel(idx)
        logger.info("IPC: focus → %s (idx=%d)", panel_id, idx)
        return {"panel_id": panel_id, "focused": True}

    def _ipc_close_panel(self, params: dict) -> dict:
        """Cierra un panel. Requiere: panel_id."""
        panel_id = params.get("panel_id", "")
        if not panel_id:
            raise ValueError("Falta parámetro: 'panel_id' es requerido")

        idx = self._panel_id_to_index(panel_id)
        if idx < 0 or idx >= len(self._panels):
            raise ValueError(f"Panel '{panel_id}' no encontrado")

        if len(self._panels) <= 1:
            raise ValueError("No se puede cerrar el último panel")

        url = self._panels[idx].url().toString()
        self.teardown_panel(idx)
        self._rebuild_grid()
        logger.info("IPC: close_panel %s (url=%s)", panel_id, url)
        return {"panel_id": panel_id, "closed": True}

    def _ipc_split(self, params: dict) -> dict:
        """Agrega un nuevo panel con la URL dada. Requiere: url."""
        url = params.get("url", "about:blank")

        view = self._create_panel(url)
        self._panels.append(view)
        self._panel_workspaces.append(self._current_workspace_idx)
        self._rebuild_grid()

        new_idx = len(self._panels) - 1
        new_panel_id = self._panel_index_to_id(new_idx)
        logger.info("IPC: split → nuevo %s con url=%s", new_panel_id, url)
        return {"panel_id": new_panel_id, "url": url}

    def _ipc_eval_js(self, params: dict) -> dict:
        """Ejecuta JavaScript en un panel. Requiere: panel_id, code. Protegido por token."""
        panel_id = params.get("panel_id", "")
        code = params.get("code", "")
        if not panel_id or not code:
            raise ValueError("Faltan parámetros: 'panel_id' y 'code' son requeridos")

        idx = self._panel_id_to_index(panel_id)
        if idx < 0 or idx >= len(self._panels):
            raise ValueError(f"Panel '{panel_id}' no encontrado")

        page = self._panels[idx].page()
        if page is None:
            raise ValueError(f"Panel '{panel_id}' no tiene página activa")

        # Ejecución síncrona bloqueante con callback
        result = {"panel_id": panel_id, "executed": True}
        page.runJavaScript(code)
        logger.info("IPC: eval_js en %s (%d chars de JS)", panel_id, len(code))
        return result

    # ── AI Cockpit: Paso 5 — Handlers de Estado y Bordes ──────────────────

    def _on_agent_state_changed(self, panel_idx: int, state_str: str) -> None:
        """Maneja cambios de estado emitidos por el MutationObserver del agente de IA."""
        if panel_idx < 0 or panel_idx >= len(self._agent_states):
            return

        try:
            new_state = AgentState(state_str)
        except ValueError:
            new_state = AgentState.IDLE

        old_state = self._agent_states[panel_idx]
        if new_state == old_state:
            return

        self._agent_states[panel_idx] = new_state
        panel_id = self._panel_index_to_id(panel_idx)
        logger.info("AI Cockpit [%s]: estado agente %s -> %s", panel_id, old_state.value, new_state.value)

        # Actualizar indicador visual de borde
        self._update_panel_border(panel_idx, new_state)

        # Notificacion nativa del SO si no tiene foco o ventana inactiva
        if new_state in (AgentState.DONE, AgentState.BLOCKED):
            is_focused = (self._get_focused_view() == self._panels[panel_idx])
            is_active_window = self.isActiveWindow()
            if not is_focused or not is_active_window:
                title = f"D.I.O. — {panel_id.upper()}"
                if new_state == AgentState.DONE:
                    msg = "Respuesta completada"
                    urgency = "normal"
                else:
                    msg = "Requiere confirmacion (bloqueado)"
                    urgency = "critical"
                send_system_notification(title=title, message=msg, urgency=urgency)

    def _update_panel_border(self, panel_idx: int, state: AgentState) -> None:
        """Actualiza el borde de color del panel segun el estado del agente de IA."""
        if 0 <= panel_idx < len(self._panels):
            view = self._panels[panel_idx]
            if state == AgentState.WORKING:
                # Azul
                view.setStyleSheet("background: black; border: 2px solid #2563eb;")
            elif state == AgentState.BLOCKED:
                # Ambar
                view.setStyleSheet("background: black; border: 2px solid #f59e0b;")
            elif state == AgentState.DONE:
                # Cian
                view.setStyleSheet("background: black; border: 2px solid #06b6d4;")
            else:
                # Idle
                view.setStyleSheet("background: black; border: none;")


# ── Parsing de argumentos ────────────────────────────────────────────────

