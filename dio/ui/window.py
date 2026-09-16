"""
D.I.O. — Ventana Principal (DIOWindow): Gestión de cuadrícula tiling,
atajos globales, teardown determinista de perfiles (H-01/H-02) y persistencia.
"""

import base64
import json
import logging
import os
import platform
import stat
import sys
import urllib.parse
from pathlib import Path

from PyQt6 import sip
from PyQt6.QtCore import QByteArray, QSize, QTimer, QUrl, Qt
from PyQt6.QtGui import QColor, QDesktopServices, QIcon, QKeySequence, QShortcut
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
    QVBoxLayout,
    QWidget,
)

import dio.core.config as config
from dio.core.logger import logger
from dio.core.security import _secure_directory, secure_directory
from dio.browser.interceptor import AdBlockInterceptor
from dio.browser.page import DIOPage, _SystemBrowserRedirectPage
from dio.browser.scripts import (
    make_anti_detection_script,
    make_dark_mode_script,
    _make_anti_detection_script,
    _make_dark_mode_script,
)
from dio.ui.widgets import (
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

        # Estado interno
        self._rows = rows
        self._cols = cols
        self._preset_name = preset_name
        self._monitor = monitor
        self._panels: list[QWebEngineView] = []
        self._profiles: list[QWebEngineProfile] = []
        self._overlays: list[LoadingOverlay] = []
        self._mute_indicators: list[MutedIndicator] = []
        self._panel_counter = 0

        # Interceptor de adblock compartido
        self._adblock_interceptor: AdBlockInterceptor | None = None
        if _ADBLOCK_ENABLED:
            self._adblock_interceptor = AdBlockInterceptor(self)

        # Registro de atajos para el manual dinámico
        self.shortcuts_registry: dict[str, str] = {}

        # Construir los paneles iniciales y el grid
        for url in urls:
            view = self._create_panel(url)
            self._panels.append(view)

        self._root_splitter = self._build_grid()
        self.setCentralWidget(self._root_splitter)

        if self._panels:
            self._panels[0].setFocus()

        self._setup_shortcuts()

        logger.info(
            "Ventana creada: grid=%dx%d, preset=%s, paneles=%d, monitor=%d, "
            "dark_mode=%s, adblock=%s",
            rows, cols, preset_name, len(self._panels), monitor,
            _DARK_MODE, _ADBLOCK_ENABLED,
        )

    # ── Creación de paneles ───────────────────────────────────────────────

    def _create_panel(self, url: str) -> QWebEngineView:
        """Crea un panel web con perfil aislado y persistente en disco."""
        idx = self._panel_counter
        self._panel_counter += 1

        profile_path = config.PROFILES_DIR / f"panel_{idx}"
        profile_path.mkdir(parents=True, exist_ok=True)
        _secure_directory(profile_path)

        profile = QWebEngineProfile(f"panel_{idx}", self)
        profile.setPersistentStoragePath(str(profile_path))
        profile.setCachePath(str(profile_path / "cache"))
        profile.setHttpUserAgent(config.USER_AGENT)

        if self._adblock_interceptor is not None:
            profile.setUrlRequestInterceptor(self._adblock_interceptor)

        settings = config.load_settings()
        dl_dir = settings.get("downloads_dir", str(Path.home() / "Downloads" / "DIO"))
        profile.setDownloadPath(str(Path(dl_dir).expanduser()))

        profile.downloadRequested.connect(
            lambda dl, i=idx, pn=self._preset_name: self._on_download_requested(dl, i, pn)
        )

        if _DARK_MODE:
            profile.scripts().insert(_make_dark_mode_script())

        # Anti-detección: inyecta JS que oculta señales de webview embebido
        # para que Google OAuth y otros servicios permitan el login
        profile.scripts().insert(_make_anti_detection_script())

        self._profiles.append(profile)

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

        # Overlay de carga
        overlay = LoadingOverlay(view)
        self._overlays.append(overlay)

        view.loadStarted.connect(lambda ov=overlay: self._on_load_started(ov))
        view.loadProgress.connect(lambda progress, ov=overlay: self._on_load_progress(ov, progress))
        view.loadFinished.connect(lambda ok, ov=overlay, i=idx: self._on_load_finished(ov, i, ok))

        # Indicador de silencio
        muted_indicator = MutedIndicator(view)
        self._mute_indicators.append(muted_indicator)

        # Crash recovery
        view.renderProcessTerminated.connect(
            lambda status, code, v=view, i=idx: self._on_render_crash(
                v, i, status, code
            )
        )

        view.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        logger.info("Panel %d creado: %s", idx, url)
        return view

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

    @staticmethod
    def _on_load_finished(overlay: LoadingOverlay, panel_idx: int, ok: bool) -> None:
        overlay.hide()
        if not ok:
            logger.warning("Panel %d: carga falló o fue interrumpida", panel_idx)

    # ── Construcción del grid con QSplitters anidados ─────────────────────

    def _build_grid(self) -> QSplitter:
        total = len(self._panels)
        if total == 0:
            return QSplitter(Qt.Orientation.Vertical)

        # Usar las dimensiones configuradas si son válidas; de lo contrario, calcularlas
        if hasattr(self, "_rows") and hasattr(self, "_cols") and self._rows > 0 and self._cols > 0:
            rows = self._rows
            cols = self._cols
            # Si el total de paneles excede rows*cols, ajustar filas automáticamente
            if rows * cols < total:
                rows = math.ceil(total / cols)
                self._rows = rows
        else:
            rows, cols = self._compute_grid_dimensions(total)
            self._rows = rows
            self._cols = cols

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
                    row_splitter.addWidget(self._panels[panel_idx])
                    panel_idx += 1
            root.addWidget(row_splitter)
            row_splitters.append(row_splitter)

        # Nivelar y distribuir simétricamente los tamaños de todas las filas y columnas
        if root.count() > 0:
            root.setSizes([10000] * root.count())
        for r_split in row_splitters:
            if r_split.count() > 0:
                r_split.setSizes([10000] * r_split.count())

        return root

    @staticmethod
    def _compute_grid_dimensions(n: int) -> tuple[int, int]:
        if n <= 0:
            return (0, 0)
        cols = math.ceil(math.sqrt(n))
        rows = math.ceil(n / cols)
        return (rows, cols)

    def _rebuild_grid(self) -> None:
        for panel in self._panels:
            panel.setParent(None)

        old_splitter = self._root_splitter
        self._root_splitter = self._build_grid()
        self.setCentralWidget(self._root_splitter)
        old_splitter.deleteLater()

        if self._panels:
            self._panels[0].setFocus()

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
            msg = f"✓ Descarga completada: {name}"
            color = "#006622"
            logger.info("Descarga completada: '%s'", name)
        else:
            msg = f"✗ Descarga fallida: {name}"
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

        notice = QLabel("⚠ Solo se leerán cookies del dominio indicado. Nunca se registran valores en logs.")
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

        ToastNotification(f"✓ {count} cookies importadas desde {browser_combo.currentText()}", self)

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
            "Panel %d: proceso de render terminado (estado=%s, código=%d). "
            "Reintentando en 3 segundos…",
            panel_idx, status_str, exit_code,
        )
        QTimer.singleShot(3000, view.reload)

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

    # ── Atajos de teclado ─────────────────────────────────────────────────

    def _setup_shortcuts(self) -> None:
        def reg(key: str, description: str, callback) -> None:
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.activated.connect(callback)
            self.shortcuts_registry[key] = description

        # Cerrar la aplicación (Ctrl+Q; se eliminó Esc para evitar cierres accidentales al usar la web)
        reg("Ctrl+Q", "Cerrar la aplicación y guardar sesión", self.close)

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
        reg("Ctrl+M", "Silenciar / activar audio del panel activo (muestra 🔇)", self._toggle_mute)
        reg("Ctrl+Shift+A", "Silenciar TODOS los paneles simultáneamente", self._mute_all)

        # Reorganización y Nivelación de Cuadrícula
        reg("Ctrl+E", "Nivelar y equilibrar todos los paneles simétricamente al 100%", self._equalize_panels)
        reg("Ctrl+Shift+E", "Nivelar y equilibrar todos los paneles simétricamente al 100%", self._equalize_panels)
        reg("Ctrl+G", "Menú rápido para reorganizar cuadrícula (3 cols × 2 filas, 2x2, etc.)", self._change_grid_dialog)
        reg("Ctrl+Alt+3", "Reorganizar inmediatamente en 3 columnas × 2 filas (2x3)", lambda checked=False: self._set_grid_dimensions(2, 3))
        reg("Ctrl+Alt+6", "Reorganizar inmediatamente en 3 columnas × 2 filas (2x3)", lambda checked=False: self._set_grid_dimensions(2, 3))
        reg("Ctrl+Alt+2", "Reorganizar inmediatamente en 2 columnas × 2 filas (2x2)", lambda checked=False: self._set_grid_dimensions(2, 2))
        reg("Ctrl+Alt+1", "Reorganizar en 3 columnas horizontales (1x3)", lambda checked=False: self._set_grid_dimensions(1, 3))

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
        if focus_widget is None and self._panels:
            return self._panels[0]
        widget = focus_widget
        while widget is not None:
            if isinstance(widget, QWebEngineView):
                return widget
            widget = widget.parent()
        return self._panels[0] if self._panels else None

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
            self._rebuild_grid()
            logger.info("Panel agregado: %s (total=%d)", dialog.result_url, len(self._panels))

    def teardown_panel(self, idx: int) -> None:
        """
        H-01 / H-02: Destruye de forma determinista un panel y sus recursos asociados.
        Aplica el desacople estricto: panel.setPage(None) antes de destruir la página,
        destruye la página explícitamente y libera el perfil C++ en memoria
        (profile.deleteLater()), evitando fugas de procesos Chromium y desfasaje de índices.
        """
        if idx < 0 or idx >= len(self._panels):
            return

        view = self._panels.pop(idx)
        profile = self._profiles.pop(idx) if idx < len(self._profiles) else None

        if idx < len(self._overlays):
            overlay = self._overlays.pop(idx)
            overlay.setParent(None)
            overlay.deleteLater()

        if idx < len(self._mute_indicators):
            indicator = self._mute_indicators.pop(idx)
            indicator.setParent(None)
            indicator.deleteLater()

        # Desacoplar vista del layout
        view.setParent(None)

        # 1. Desacoplar explícitamente la página del QWebEngineView
        page = view.page()
        view.setPage(None)

        # 2. Destruir la página desacoplada antes de liberar el perfil
        if page is not None:
            page.setParent(None)
            try:
                sip.delete(page)
            except Exception:
                page.deleteLater()
        view.deleteLater()

        # 3. Liberar el perfil en memoria (QWebEngineProfile)
        #    deleteLater() descarga las estructuras C++ y termina el proceso
        #    de render de Chromium asociado; los datos en disco (~/.dio/profiles/panel_N/)
        #    permanecen intactos para futuras sesiones.
        if profile is not None:
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
            self._panels[idx].setFocus()

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
            f"📐 Cuadrícula equilibrada: {self._cols} columnas × {self._rows} filas",
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
            f"📐 Cuadrícula organizada: {cols} columnas × {rows} filas",
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
        ToastNotification("🚀 Nueva ventana de D.I.O. iniciada", self)
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


# ── Parsing de argumentos ────────────────────────────────────────────────

