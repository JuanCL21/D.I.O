"""
D.I.O. — Páginas personalizadas de QWebEngine con gestión de OAuth y ventanas emergentes.
"""

from PyQt6.QtCore import QTimer, QUrl, Qt, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import QDialog, QVBoxLayout

import dio.core.config as config
from dio.core.logger import logger
from dio.browser.agent_observer import AGENT_STATE_PREFIX


class DIOPage(QWebEnginePage):
    """
    Subclase de QWebEnginePage que gestiona createWindow para:
    - Popups OAuth / diálogos de login: navega en el panel principal para
      evitar el bloqueo de Google a webviews embebidos.
    - target="_blank": navega en el mismo panel o delega al sistema.
    - Captura de estados de agentes IA desde ApplicationWorld (Paso 5).

    IMPORTANTE: Las ventanas popup se almacenan en _active_popups para evitar
    que el garbage collector de Python destruya los objetos C++ antes de que
    Qt termine de usarlos (RuntimeError: wrapped C/C++ object deleted).
    """

    agent_state_changed = pyqtSignal(str)

    def __init__(self, profile: QWebEngineProfile, parent_view: QWebEngineView) -> None:
        super().__init__(profile, parent_view)
        self._parent_view = parent_view
        self._active_popups: list[dict] = []

    def javaScriptConsoleMessage(
        self,
        level: QWebEnginePage.JavaScriptConsoleMessageLevel,
        message: str,
        lineNumber: int,
        sourceID: str,
    ) -> None:
        if message and message.startswith(AGENT_STATE_PREFIX):
            state = message[len(AGENT_STATE_PREFIX):].strip().lower()
            logger.debug("AI Cockpit: estado recibido desde JS: %s", state)
            self.agent_state_changed.emit(state)
            return
        super().javaScriptConsoleMessage(level, message, lineNumber, sourceID)

    def createWindow(self, window_type: QWebEnginePage.WebWindowType) -> "QWebEnginePage | None":
        is_popup = window_type in (
            QWebEnginePage.WebWindowType.WebDialog,
            QWebEnginePage.WebWindowType.WebBrowserBackgroundTab,
        )

        if is_popup:
            return self._create_popup_window()

        if config.EXTERNAL_LINK_BEHAVIOR == "system_browser":
            return self._create_system_browser_redirect()

        return self

    def _create_popup_window(self) -> "QWebEnginePage":
        """
        Crea una ventana popup para flujos de autenticación.
        """
        dialog = QDialog()
        dialog.setWindowTitle("D.I.O. — Ventana emergente")
        dialog.resize(520, 640)
        dialog.setWindowFlags(dialog.windowFlags() | Qt.WindowType.Window)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(0, 0, 0, 0)

        popup_view = QWebEngineView(dialog)
        popup_page = QWebEnginePage(self.profile(), popup_view)
        popup_view.setPage(popup_page)

        layout.addWidget(popup_view)

        popup_record = {
            "dialog": dialog,
            "view": popup_view,
            "page": popup_page,
        }
        self._active_popups.append(popup_record)

        def _on_popup_closed():
            try:
                self._active_popups.remove(popup_record)
            except ValueError:
                pass

        dialog.finished.connect(_on_popup_closed)
        popup_page.windowCloseRequested.connect(dialog.close)

        parent_view = self._parent_view
        _oauth_redirected = {"done": False}

        def _intercept_google_oauth(url: QUrl):
            if _oauth_redirected["done"]:
                return
            host = url.host().lower()
            if "accounts.google.com" in host:
                _oauth_redirected["done"] = True
                logger.info(
                    "OAuth Google detectado → cargando en panel principal: %s",
                    url.toString()[:120],
                )
                parent_view.setUrl(url)
                QTimer.singleShot(200, dialog.close)

        popup_page.urlChanged.connect(_intercept_google_oauth)

        dialog.show()
        logger.info("Popup creado con perfil compartido")
        return popup_page

    def _create_system_browser_redirect(self) -> "QWebEnginePage":
        temp_page = _SystemBrowserRedirectPage(self.profile(), self._parent_view)
        return temp_page


class _SystemBrowserRedirectPage(QWebEnginePage):
    """Página auxiliar que abre la URL navegada en el navegador del sistema."""

    def __init__(self, profile: QWebEngineProfile, parent) -> None:
        super().__init__(profile, parent)
        self.urlChanged.connect(self._redirect_to_system)

    def _redirect_to_system(self, url: QUrl) -> None:
        if url.isValid() and url.scheme() in ("http", "https"):
            logger.info("Enlace externo → navegador del sistema: %s", url.toString())
            QDesktopServices.openUrl(url)
            QTimer.singleShot(100, self.deleteLater)
