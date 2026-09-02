#!/usr/bin/env python3
"""
D.I.O. — Divisor Integrado Operativo
Punto de entrada: ventana fullscreen sin bordes con grid de paneles Chromium
aislados por sesión, usando PyQt6 + QtWebEngine.
"""

import argparse
import base64
import json
import logging
import math
import os
import platform
import signal
import stat
import subprocess
import sys
import urllib.parse
from logging.handlers import RotatingFileHandler
from pathlib import Path

import config

# ── Detección de flags tempranos ANTES de crear QApplication ─────────────
# Todos los flags que modifican variables de entorno de Chromium deben
# setearse aquí, antes de importar nada de Qt.

# --low-memory: desactiva GPU para reducir consumo de RAM/VRAM
_LOW_MEMORY = "--low-memory" in sys.argv
if _LOW_MEMORY:
    _chromium_flags = os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "")
    _chromium_flags += " --disable-gpu"
    os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = _chromium_flags.strip()
    os.environ["QT_QUICK_BACKEND"] = "software"

# --no-dark-mode: el modo oscuro está ACTIVO por defecto; este flag lo apaga
_DARK_MODE = "--no-dark-mode" not in sys.argv
if _DARK_MODE:
    _chromium_flags = os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "")
    _chromium_flags += (
        " --force-dark-mode"
        " --enable-features=WebContentsForceDark"
        " --blink-settings=preferredColorScheme=1"
    )
    os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = _chromium_flags.strip()

# Anti-detección: impide que Google detecte QWebEngine como webview embebido.
# Sin esto, navigator.webdriver = true y Google bloquea OAuth.
_chromium_flags = os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "")
_chromium_flags += " --disable-blink-features=AutomationControlled"

# Estabilidad de Conexiones en Streaming (Claude / ChatGPT / Gemini SSE y WebSockets):
# Impide que Chromium congele temporizadores de JS o suspenda sockets cuando un panel
# no tiene el foco activo o mientras se ejecutan múltiples paneles simultáneamente.
_chromium_flags += (
    " --disable-background-timer-throttling"
    " --disable-backgrounding-occluded-windows"
    " --disable-renderer-backgrounding"
    " --disable-features=CalculateNativeWinOcclusion,IntensiveWakeUpThrottling"
)
os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = _chromium_flags.strip()

# --no-adblock: el adblock está ACTIVO por defecto; este flag lo apaga
_ADBLOCK_ENABLED = "--no-adblock" not in sys.argv

# --ask-download-location: pide ubicación manual en vez de guardar automático
_ASK_DOWNLOAD = "--ask-download-location" in sys.argv

# ── Detección de Wayland ANTES de crear QApplication ─────────────────────
if os.environ.get("XDG_SESSION_TYPE") == "wayland":
    os.environ.setdefault("QT_QPA_PLATFORM", "wayland;xcb")

from PyQt6.QtCore import QByteArray, QSize, QTimer, QUrl, Qt
from PyQt6.QtGui import QColor, QDesktopServices, QIcon, QKeySequence, QShortcut
from PyQt6.QtNetwork import QNetworkCookie
from PyQt6.QtWebEngineCore import (
    QWebEngineDownloadRequest,
    QWebEnginePage,
    QWebEngineProfile,
    QWebEngineScript,
    QWebEngineSettings,
    QWebEngineUrlRequestInterceptor,
)
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QSplitter,
    QSplitterHandle,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

# ── Logger global del módulo ─────────────────────────────────────────────
logger = logging.getLogger("dio")


def setup_logging() -> None:
    """Configura el logging con rotación de archivo y salida a consola."""
    config.DIO_DIR.mkdir(parents=True, exist_ok=True)

    handler = RotatingFileHandler(
        config.LOG_FILE,
        maxBytes=config.LOG_MAX_BYTES,
        backupCount=config.LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    )

    console = logging.StreamHandler()
    console.setFormatter(
        logging.Formatter("[D.I.O.] %(message)s")
    )

    logger.setLevel(logging.DEBUG)
    logger.addHandler(handler)
    logger.addHandler(console)


def _secure_directory(path: Path) -> None:
    """En Linux/macOS ajusta permisos de carpeta a 700 (solo el usuario)."""
    if platform.system() in ("Linux", "Darwin"):
        try:
            path.chmod(stat.S_IRWXU)
        except OSError as exc:
            logger.warning("No se pudo ajustar permisos de %s: %s", path, exc)


# ── CSS de modo oscuro (respaldo para sitios que ignoran Chromium flags) ──
_DARK_MODE_CSS = """
:root {
    color-scheme: dark !important;
}
"""


def _make_dark_mode_script() -> QWebEngineScript:
    """Inyecta scripts y CSS para forzar modo oscuro en Claude, ChatGPT y sitios web."""
    script = QWebEngineScript()
    script.setName("dio_dark_mode_force")
    script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
    script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
    script.setRunsOnSubFrames(True)
    script.setSourceCode("""
(function() {
    function applyDarkMode() {
        if (!document.documentElement) return;
        try {
            document.documentElement.classList.remove('light');
            document.documentElement.classList.add('dark');
            document.documentElement.setAttribute('data-theme', 'dark');
            document.documentElement.style.colorScheme = 'dark';
            if (document.body) {
                document.body.classList.remove('light');
                document.body.classList.add('dark');
                document.body.setAttribute('data-theme', 'dark');
                document.body.style.colorScheme = 'dark';
            }
            if (window.localStorage) {
                localStorage.setItem('theme', 'dark');
                localStorage.setItem('claude_theme', 'dark');
                localStorage.setItem('color-scheme', 'dark');
            }
        } catch(e) {}
    }

    applyDarkMode();
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', applyDarkMode);
    }

    function injectCSS() {
        if (document.getElementById('dio-dark-mode-style')) return;
        var style = document.createElement('style');
        style.id = 'dio-dark-mode-style';
        style.textContent = `
            html, body, [data-theme="light"] {
                color-scheme: dark !important;
                background-color: #18181b !important;
                color: #f4f4f5 !important;
            }
            :root, html.dark, [data-theme="dark"], body {
                --bg-primary: #18181b !important;
                --bg-secondary: #27272a !important;
                --bg-tertiary: #3f3f46 !important;
                --bg-100: #09090b !important;
                --bg-200: #18181b !important;
                --bg-300: #27272a !important;
                --bg-400: #3f3f46 !important;
                --bg-500: #52525b !important;
                --text-primary: #f4f4f5 !important;
                --text-secondary: #a1a1aa !important;
                --text-tertiary: #71717a !important;
                --border-primary: #27272a !important;
                --border-secondary: #3f3f46 !important;
            }
            /* Claude específicos */
            .bg-bg-000, .bg-bg-100, .bg-bg-200, .bg-bg-300, main, nav, aside {
                background-color: #18181b !important;
                color: #f4f4f5 !important;
            }
        `;
        (document.head || document.documentElement).appendChild(style);
    }

    if (document.head || document.documentElement) {
        injectCSS();
    } else {
        document.addEventListener('DOMContentLoaded', injectCSS);
    }
})();
""")
    return script


def _make_anti_detection_script() -> QWebEngineScript:
    """
    Inyecta JavaScript al momento de CREACIÓN del documento (antes de que
    cualquier script de Google pueda leer las propiedades) para ocultar las
    señales que delatan a QWebEngine como webview embebido:

    1. navigator.webdriver → false (Google lo usa como señal primaria)
    2. window.chrome.runtime → objeto simulado (Chrome real lo tiene)
    3. navigator.plugins → array con plugins falsos (Chrome real tiene >0)
    4. navigator.languages → ['es-CO', 'es', 'en'] (evita array vacío)
    """
    script = QWebEngineScript()
    script.setName("dio_anti_detection")
    # DocumentCreation = se ejecuta ANTES que cualquier <script> de la página
    script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
    script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
    script.setRunsOnSubFrames(True)
    script.setSourceCode("""
(function() {
    // 1. navigator.webdriver = false
    Object.defineProperty(navigator, 'webdriver', {
        get: function() { return false; },
        configurable: true
    });

    // 2. window.chrome con runtime simulado
    if (!window.chrome) {
        window.chrome = {};
    }
    if (!window.chrome.runtime) {
        window.chrome.runtime = {
            connect: function() { return {}; },
            sendMessage: function() {},
            onMessage: { addListener: function() {} },
            id: undefined
        };
    }

    // 3. navigator.plugins con al menos un plugin (Chrome real tiene varios)
    try {
        Object.defineProperty(navigator, 'plugins', {
            get: function() {
                return [{
                    name: 'Chrome PDF Plugin',
                    description: 'Portable Document Format',
                    filename: 'internal-pdf-viewer',
                    length: 1
                }];
            },
            configurable: true
        });
    } catch(e) {}

    // 4. navigator.languages (evita array vacío que delata webviews)
    try {
        Object.defineProperty(navigator, 'languages', {
            get: function() { return ['es-CO', 'es', 'en-US', 'en']; },
            configurable: true
        });
    } catch(e) {}
})();
""")
    return script


# ── Estilo Global de Diálogos Modernos y Alto Contraste ───────────────────
GLOBAL_DIALOG_STYLE = """
QDialog, QMessageBox {
    background-color: #181825;
    color: #cdd6f4;
    font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
}
QMessageBox QLabel {
    color: #ffffff;
    font-size: 13px;
}
QMessageBox QPushButton, QDialogButtonBox QPushButton {
    background-color: #313244;
    color: #ffffff;
    font-size: 13px;
    padding: 7px 18px;
    border-radius: 6px;
    border: 1px solid #45475a;
}
QMessageBox QPushButton:hover, QDialogButtonBox QPushButton:hover {
    background-color: #45475a;
    border-color: #89b4fa;
    color: #89b4fa;
}
QMessageBox QPushButton:default {
    background-color: #89b4fa;
    color: #11111b;
    font-weight: bold;
    border: none;
}
QMessageBox QPushButton:default:hover {
    background-color: #b4befe;
}
QSplitter {
    spacing: 0px;
    margin: 0px;
    padding: 0px;
    border: none;
    background: transparent;
}
QSplitter::handle {
    background: transparent;
    border: none;
    margin: 0px;
    padding: 0px;
    width: 0px;
    height: 0px;
}
QSplitter::handle:horizontal {
    width: 0px;
    height: 0px;
    border: none;
    background: transparent;
}
QSplitter::handle:vertical {
    height: 0px;
    width: 0px;
    border: none;
    background: transparent;
}
"""


# ── QSplitters 100% Sin Bordes ni Líneas Divisorias (0px Real) ────────────

class SeamlessSplitterHandle(QSplitterHandle):
    """Handle invisible con tamaño 0 exacto para eliminar cualquier línea o margen."""

    def __init__(self, orientation: Qt.Orientation, parent: QSplitter) -> None:
        super().__init__(orientation, parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setMaximumSize(0, 0)
        self.resize(0, 0)

    def paintEvent(self, event) -> None:
        # No pintar absolutamente nada (garantiza 0px visual y elimina líneas)
        pass

    def sizeHint(self) -> QSize:
        return QSize(0, 0)


class SeamlessSplitter(QSplitter):
    """QSplitter sin bordes, sin margen y con handles invisibles de 0px."""

    def __init__(self, orientation: Qt.Orientation, parent=None) -> None:
        super().__init__(orientation, parent)
        self.setHandleWidth(0)
        self.setChildrenCollapsible(False)
        self.setStyleSheet("""
            QSplitter {
                spacing: 0px;
                margin: 0px;
                padding: 0px;
                border: none;
                background: transparent;
            }
            QSplitter::handle {
                background: transparent;
                border: none;
                width: 0px;
                height: 0px;
                max-width: 0px;
                max-height: 0px;
                margin: 0px;
                padding: 0px;
            }
        """)

    def createHandle(self) -> QSplitterHandle:
        return SeamlessSplitterHandle(self.orientation(), self)


# ── Resolución Inteligente de Búsqueda o URL ──────────────────────────────

def resolve_query_or_url(text: str) -> str:
    """
    Convierte el texto ingresado en una URL válida o en una búsqueda de Google:
    - Si ya tiene protocolo (http://, https://, etc.), se usa directamente.
    - Si contiene espacios o es un término general, busca en Google.
    - Si parece dominio (ej. youtube.com, wiki.org/wiki/...), antepone https://.
    - Si es localhost o IP, antepone http://.
    """
    text = text.strip()
    if not text:
        return ""

    if text.startswith(("http://", "https://", "file://", "about:")):
        return text

    # Si contiene espacios, es una búsqueda en Google
    if " " in text:
        return f"https://www.google.com/search?q={urllib.parse.quote_plus(text)}"

    # Localhost o IPs directas
    if text.startswith("localhost") or text.startswith("127.0.0.1") or (":" in text and text.split(":")[0].replace(".", "").isdigit()):
        return f"http://{text}"

    # Dominios conocidos con TLDs comunes o estructura dominio.tld
    parts = text.split("/")[0].split(":")
    domain_part = parts[0]
    if "." in domain_part and not domain_part.endswith("."):
        tld = domain_part.split(".")[-1]
        if len(tld) >= 2 and tld.isalpha():
            return f"https://{text}"

    # Término suelto sin espacios ni punto (ej: 'python', 'antigravity') -> buscar en Google
    return f"https://www.google.com/search?q={urllib.parse.quote_plus(text)}"


# ── Ventana Modal de Búsqueda / Omnibox Inteligente ───────────────────────

class OmniSearchDialog(QDialog):
    """
    Mini ventana de búsqueda y navegación estilo Spotlight / Google.
    Permite ingresar términos de búsqueda o URLs, y ofrece accesos rápidos a servicios comunes.
    """

    def __init__(self, parent=None, title: str = "Navegar o Buscar", initial_text: str = "") -> None:
        super().__init__(parent)
        self.setWindowTitle(f"D.I.O. — {title}")
        self.setFixedWidth(640)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.result_url: str = ""

        # Layout exterior
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(8, 8, 8, 8)

        card = QFrame(self)
        card.setObjectName("OmniCard")
        card.setStyleSheet("""
            #OmniCard {
                background-color: #1e1e2e;
                border: 1.5px solid #45475a;
                border-radius: 14px;
            }
            QLabel {
                color: #cdd6f4;
                font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
            }
            QLineEdit {
                background-color: #181825;
                color: #ffffff;
                font-size: 15px;
                font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
                padding: 10px 14px;
                border: 1.5px solid #313244;
                border-radius: 8px;
                selection-background-color: #89b4fa;
                selection-color: #11111b;
            }
            QLineEdit:focus {
                border: 1.5px solid #89b4fa;
                background-color: #11111b;
            }
            QPushButton.chip-btn {
                background-color: #313244;
                color: #cdd6f4;
                border: 1px solid #45475a;
                border-radius: 6px;
                padding: 6px 12px;
                font-size: 12px;
                font-weight: 500;
            }
            QPushButton.chip-btn:hover {
                background-color: #45475a;
                color: #ffffff;
                border-color: #89b4fa;
            }
            QPushButton.action-btn {
                background-color: #89b4fa;
                color: #11111b;
                font-weight: bold;
                font-size: 13px;
                padding: 8px 20px;
                border-radius: 6px;
                border: none;
            }
            QPushButton.action-btn:hover {
                background-color: #b4befe;
            }
            QPushButton.cancel-btn {
                background-color: transparent;
                color: #a6adc8;
                font-size: 13px;
                padding: 8px 14px;
                border-radius: 6px;
                border: 1px solid #313244;
            }
            QPushButton.cancel-btn:hover {
                background-color: #313244;
                color: #ffffff;
            }
        """)

        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(22, 20, 22, 20)
        card_layout.setSpacing(14)

        # Encabezado
        header_layout = QHBoxLayout()
        icon_title = QLabel(f"🌐 <b style='font-size:16px; color:#ffffff;'>{title}</b>")
        header_layout.addWidget(icon_title)
        header_layout.addStretch()

        esc_hint = QLabel("<span style='color:#6c7086; font-size:12px;'>[Esc para cerrar]</span>")
        header_layout.addWidget(esc_hint)
        card_layout.addLayout(header_layout)

        # Subtítulo explicativo
        subtitle = QLabel("Escribe una búsqueda en Google o cualquier dirección web (ej: <i>youtube.com</i>):")
        subtitle.setStyleSheet("color: #a6adc8; font-size: 12px;")
        card_layout.addWidget(subtitle)

        # Input omnibox
        self.input_edit = QLineEdit(initial_text)
        self.input_edit.setPlaceholderText("Buscar en Google o escribir URL...")
        self.input_edit.returnPressed.connect(self._on_accept)
        card_layout.addWidget(self.input_edit)

        # Fila de accesos directos (Chips)
        chips_title = QLabel("<b style='color:#89b4fa; font-size:11px;'>ACCESOS DIRECTOS:</b>")
        card_layout.addWidget(chips_title)

        chips_layout = QHBoxLayout()
        chips_layout.setSpacing(6)

        quick_links = [
            ("🔍 Google", "https://www.google.com"),
            ("🤖 ChatGPT", "https://chatgpt.com"),
            ("⚡ Gemini", "https://gemini.google.com"),
            ("🟣 Claude", "https://claude.ai"),
            ("💬 WhatsApp", "https://web.whatsapp.com"),
            ("✉️ Gmail", "https://mail.google.com"),
            ("📺 YouTube", "https://youtube.com"),
        ]

        for label, url in quick_links:
            btn = QPushButton(label)
            btn.setProperty("class", "chip-btn")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda checked=False, u=url: self._quick_navigate(u))
            chips_layout.addWidget(btn)

        chips_layout.addStretch()
        card_layout.addLayout(chips_layout)

        card_layout.addSpacing(4)

        # Footer con botones de acción
        footer_layout = QHBoxLayout()
        hint = QLabel("💡 <i>Presiona Enter para navegar o buscar</i>")
        hint.setStyleSheet("color: #6c7086; font-size: 11px;")
        footer_layout.addWidget(hint)
        footer_layout.addStretch()

        cancel_btn = QPushButton("Cancelar")
        cancel_btn.setProperty("class", "cancel-btn")
        cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_btn.clicked.connect(self.reject)
        footer_layout.addWidget(cancel_btn)

        go_btn = QPushButton("🚀 Ir / Buscar")
        go_btn.setProperty("class", "action-btn")
        go_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        go_btn.clicked.connect(self._on_accept)
        footer_layout.addWidget(go_btn)

        card_layout.addLayout(footer_layout)
        main_layout.addWidget(card)

        # Foco automático al campo de texto
        QTimer.singleShot(50, self.input_edit.setFocus)
        if initial_text:
            self.input_edit.selectAll()

    def _quick_navigate(self, url: str) -> None:
        self.result_url = url
        self.accept()

    def _on_accept(self) -> None:
        raw = self.input_edit.text().strip()
        if raw:
            self.result_url = resolve_query_or_url(raw)
            self.accept()
        else:
            self.reject()


# ── Diálogo Grabador de Teclas para Remapeo ──────────────────────────────

class KeySequenceRecorderDialog(QDialog):
    """Diálogo modal compacto para capturar una nueva combinación de teclas."""

    def __init__(self, action_name: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Remapear Atajo")
        self.setFixedSize(380, 160)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.recorded_sequence: str | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)

        card = QFrame(self)
        card.setStyleSheet("""
            QFrame {
                background-color: #1e1e2e;
                border: 2px solid #89b4fa;
                border-radius: 12px;
            }
            QLabel {
                color: #cdd6f4;
                font-family: 'Segoe UI', system-ui, sans-serif;
            }
        """)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(18, 16, 18, 16)
        card_layout.setSpacing(10)

        title = QLabel(f"⌨️ <b style='color:#ffffff; font-size:14px;'>Presiona el nuevo atajo</b>")
        desc = QLabel(f"Para la acción: <span style='color:#89b4fa;'>{action_name}</span>")
        desc.setWordWrap(True)
        desc.setStyleSheet("font-size: 12px; color: #a6adc8;")

        hint = QLabel("<span style='color:#6c7086; font-size:11px;'>Presiona cualquier tecla o combinación. [Esc] para cancelar.</span>")

        card_layout.addWidget(title)
        card_layout.addWidget(desc)
        card_layout.addWidget(hint)
        layout.addWidget(card)

    def keyPressEvent(self, event) -> None:
        key = event.key()
        if key in (Qt.Key.Key_Control, Qt.Key.Key_Shift, Qt.Key.Key_Alt, Qt.Key.Key_Meta):
            return  # Esperar a que presione la tecla combinada

        if key == Qt.Key.Key_Escape:
            self.reject()
            return

        modifiers = event.modifiers()
        seq = QKeySequence(modifiers | Qt.Key(key))
        seq_str = seq.toString()
        if seq_str:
            self.recorded_sequence = seq_str
            self.accept()
        else:
            super().keyPressEvent(event)


# ── Overlay Modal de Configuración y Manual (F1) ──────────────────────────

class SettingsOverlayDialog(QDialog):
    """
    Overlay Modal completo de configuración y atajos de teclado para D.I.O.
    Inspirado en diseño Kiska / Figma moderno con sidebar y páginas modulares.
    """

    def __init__(self, shortcuts: dict[str, str], dio_window, parent=None) -> None:
        super().__init__(parent or dio_window)
        self._dio_window = dio_window
        self._shortcuts = shortcuts
        self._settings = config.load_settings()
        self._presets = config.load_presets()

        self.setWindowTitle("D.I.O. — Configuración y Manual")
        self.resize(960, 680)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

        # Atajos de cierre dentro del diálogo
        QShortcut(QKeySequence("F1"), self, self.accept)
        QShortcut(QKeySequence("Escape"), self, self.reject)

        self._setup_ui()

    def _setup_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(16, 16, 16, 16)

        # Tarjeta contenedora central con backdrop styling
        opacity = self._settings.get("overlay_opacity", 75) / 100.0
        bg_alpha = int(opacity * 255)

        card = QFrame(self)
        card.setObjectName("MainSettingsCard")
        card.setStyleSheet(f"""
            #MainSettingsCard {{
                background-color: #181825;
                border: 1.5px solid #313244;
                border-radius: 16px;
            }}
            QLabel {{
                color: #cdd6f4;
                font-family: 'Segoe UI', system-ui, sans-serif;
            }}
            QListWidget {{
                background-color: #11111b;
                border: none;
                border-top-left-radius: 16px;
                border-bottom-left-radius: 16px;
                padding: 12px 6px;
                color: #a6adc8;
                font-size: 13px;
            }}
            QListWidget::item {{
                padding: 12px 14px;
                border-radius: 8px;
                margin-bottom: 4px;
                font-weight: 500;
            }}
            QListWidget::item:selected {{
                background-color: #313244;
                color: #89b4fa;
                font-weight: bold;
            }}
            QListWidget::item:hover:!selected {{
                background-color: #1e1e2e;
                color: #ffffff;
            }}
            QStackedWidget {{
                background-color: #181825;
                border: none;
                border-top-right-radius: 16px;
                border-bottom-right-radius: 16px;
            }}
            QLineEdit, QComboBox, QSpinBox, QPlainTextEdit {{
                background-color: #1e1e2e;
                color: #ffffff;
                border: 1px solid #313244;
                border-radius: 6px;
                padding: 7px 10px;
                font-size: 13px;
                selection-background-color: #89b4fa;
                selection-color: #11111b;
            }}
            QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QPlainTextEdit:focus {{
                border-color: #89b4fa;
            }}
            QCheckBox, QRadioButton {{
                color: #cdd6f4;
                font-size: 13px;
                spacing: 8px;
            }}
            QCheckBox::indicator, QRadioButton::indicator {{
                width: 18px;
                height: 18px;
                border-radius: 4px;
                border: 1px solid #45475a;
                background-color: #1e1e2e;
            }}
            QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
                background-color: #a6e3a1;
                border-color: #a6e3a1;
            }}
            QRadioButton::indicator {{
                border-radius: 9px;
            }}
            QPushButton.primary-save-btn {{
                background-color: #a6e3a1;
                color: #11111b;
                font-weight: bold;
                font-size: 13px;
                padding: 9px 24px;
                border-radius: 8px;
                border: none;
            }}
            QPushButton.primary-save-btn:hover {{
                background-color: #94e2d5;
            }}
            QPushButton.secondary-btn {{
                background-color: #313244;
                color: #cdd6f4;
                font-size: 13px;
                padding: 9px 18px;
                border-radius: 8px;
                border: 1px solid #45475a;
            }}
            QPushButton.secondary-btn:hover {{
                background-color: #45475a;
                color: #ffffff;
            }}
            QTableWidget {{
                background-color: #1e1e2e;
                color: #cdd6f4;
                border: 1px solid #313244;
                border-radius: 8px;
                gridline-color: #262736;
            }}
            QHeaderView::section {{
                background-color: #11111b;
                color: #89b4fa;
                font-weight: bold;
                border: none;
                padding: 6px;
                font-size: 12px;
            }}
        """)

        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(0, 0, 0, 0)
        card_layout.setSpacing(0)

        # Body con Sidebar izquierda y Stack central
        body_layout = QHBoxLayout()
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)

        # ── Sidebar ──
        sidebar = QFrame()
        sidebar.setFixedWidth(230)
        sidebar.setStyleSheet("background-color: #11111b; border-right: 1px solid #313244;")
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(14, 18, 14, 18)
        sidebar_layout.setSpacing(14)

        # Logo / Título
        app_brand = QLabel("⚡ <b style='font-size:17px; color:#ffffff;'>D.I.O.</b> <span style='font-size:12px; color:#89b4fa;'>Control</span>")
        sidebar_layout.addWidget(app_brand)

        # Lista de secciones
        self.nav_list = QListWidget()
        items = [
            ("⚙️  1. Motor y Sistema", "Ajustes de inicio, GPU y descargas"),
            ("⌨️  2. Atajos de Teclado", "Remapeo y activación de teclas"),
            ("🎨  3. Apariencia y Grid", "Márgenes, foco y opacidad"),
            ("🚀  4. Opciones Avanzadas", "Sandboxing, User-Agent y Presets"),
            ("📖  5. Manual de Comandos", "Guía interactiva de atajos"),
        ]
        for title, tooltip in items:
            it = QListWidgetItem(title)
            it.setToolTip(tooltip)
            self.nav_list.addItem(it)

        sidebar_layout.addWidget(self.nav_list)

        # Hint en la parte inferior del sidebar
        f1_hint = QLabel("<span style='color:#6c7086; font-size:11px;'>Tip: Pulsa <b>F1</b> o <b>Esc</b> para cerrar en cualquier momento.</span>")
        f1_hint.setWordWrap(True)
        sidebar_layout.addWidget(f1_hint)

        body_layout.addWidget(sidebar)

        # ── Content Stack ──
        self.stack = QStackedWidget()
        self._build_tab_core()
        self._build_tab_keybindings()
        self._build_tab_appearance()
        self._build_tab_advanced()
        self._build_tab_manual()

        body_layout.addWidget(self.stack, stretch=1)
        card_layout.addLayout(body_layout, stretch=1)

        # ── Footer Global con botones de Acción ──
        footer = QFrame()
        footer.setStyleSheet("background-color: #11111b; border-top: 1px solid #313244; padding: 8px 16px;")
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(16, 10, 16, 10)

        version_lbl = QLabel("<span style='color:#6c7086; font-size:12px;'>D.I.O. v2.1 • Divisor Integrado Operativo</span>")
        footer_layout.addWidget(version_lbl)
        footer_layout.addStretch()

        cancel_btn = QPushButton("Cerrar [F1 / Esc]")
        cancel_btn.setProperty("class", "secondary-btn")
        cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_btn.clicked.connect(self.reject)
        footer_layout.addWidget(cancel_btn)

        save_btn = QPushButton("✓ Guardar y Aplicar Cambios")
        save_btn.setProperty("class", "primary-save-btn")
        save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        save_btn.clicked.connect(self._save_and_apply)
        footer_layout.addWidget(save_btn)

        card_layout.addWidget(footer)
        main_layout.addWidget(card)

        # Conectar navegación
        self.nav_list.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.nav_list.setCurrentRow(0)

    # ── PÁGINA 1: Motor y Sistema (Core) ───────────────────────────────────

    def _build_tab_core(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(18)

        header = QLabel("⚙️ <b style='font-size:18px; color:#ffffff;'>Ajustes del Motor y Comportamiento (Core)</b>")
        desc = QLabel("Configura el arranque, aceleración de hardware, rendimiento y descargas.")
        desc.setStyleSheet("color: #a6adc8; font-size: 13px;")
        layout.addWidget(header)
        layout.addWidget(desc)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        scroll_content = QWidget()
        form = QVBoxLayout(scroll_content)
        form.setSpacing(16)

        # 1. Comportamiento de inicio
        sec1 = QLabel("<b>1. Comportamiento de Inicio:</b>")
        form.addWidget(sec1)
        self.rb_restore = QRadioButton("Restaurar automáticamente la última sesión activa (mismas URLs, tamaños y estado)")
        self.rb_preset = QRadioButton("Cargar siempre el preset predeterminado al iniciar")
        if self._settings.get("startup_behavior") == "load_preset":
            self.rb_preset.setChecked(True)
        else:
            self.rb_restore.setChecked(True)
        form.addWidget(self.rb_restore)
        form.addWidget(self.rb_preset)

        # 2. Aceleración por Hardware (GPU)
        sec2 = QLabel("<b>2. Aceleración Gráfica (GPU):</b>")
        form.addWidget(sec2)
        self.chk_gpu = QCheckBox("Habilitar aceleración por hardware GPU (desmarcar si experimentas parpadeo o en PCs de bajos recursos)")
        self.chk_gpu.setChecked(self._settings.get("hardware_acceleration", True))
        form.addWidget(self.chk_gpu)

        # 3. Gestión de Memoria (Tab Sleeping)
        sec3 = QLabel("<b>3. Gestión de Memoria (Tab Sleeping):</b>")
        form.addWidget(sec3)
        sleep_row = QHBoxLayout()
        self.chk_sleeping = QCheckBox("Suspender automáticamente paneles inactivos tras:")
        self.chk_sleeping.setChecked(self._settings.get("tab_sleeping_enabled", False))
        self.combo_sleep_min = QComboBox()
        self.combo_sleep_min.addItems(["5 minutos", "10 minutos", "15 minutos", "30 minutos", "60 minutos"])
        cur_min = self._settings.get("tab_sleeping_minutes", 15)
        for i, val in enumerate([5, 10, 15, 30, 60]):
            if val == cur_min:
                self.combo_sleep_min.setCurrentIndex(i)
        sleep_row.addWidget(self.chk_sleeping)
        sleep_row.addWidget(self.combo_sleep_min)
        sleep_row.addStretch()
        form.addLayout(sleep_row)

        # 4. Carpeta de Descargas
        sec4 = QLabel("<b>4. Directorio Global de Descargas:</b>")
        form.addWidget(sec4)
        dl_row = QHBoxLayout()
        self.edit_downloads = QLineEdit(self._settings.get("downloads_dir", str(Path.home() / "Downloads" / "DIO")))
        browse_btn = QPushButton("📁 Examinar...")
        browse_btn.setProperty("class", "secondary-btn")
        browse_btn.clicked.connect(self._browse_downloads_dir)
        dl_row.addWidget(self.edit_downloads, stretch=1)
        dl_row.addWidget(browse_btn)
        form.addLayout(dl_row)

        self.chk_ask_download = QCheckBox("Preguntar siempre la ubicación de guardado antes de descargar cada archivo")
        self.chk_ask_download.setChecked(self._settings.get("ask_download_location", False))
        form.addWidget(self.chk_ask_download)

        form.addStretch()
        scroll.setWidget(scroll_content)
        layout.addWidget(scroll)
        self.stack.addWidget(page)

    def _browse_downloads_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Seleccionar carpeta de descargas de D.I.O.", self.edit_downloads.text())
        if path:
            self.edit_downloads.setText(path)

    # ── PÁGINA 2: Personalización de Atajos (Keybindings) ───────────────────

    def _build_tab_keybindings(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(14)

        header = QLabel("⌨️ <b style='font-size:18px; color:#ffffff;'>Personalización de Atajos (Keybindings)</b>")
        desc = QLabel("Activa, desactiva o remapea cualquier atajo de teclado de D.I.O.")
        desc.setStyleSheet("color: #a6adc8; font-size: 13px;")
        layout.addWidget(header)
        layout.addWidget(desc)

        # Buscador en tiempo real
        self.search_shortcuts = QLineEdit()
        self.search_shortcuts.setPlaceholderText("🔍 Filtrar comandos o teclas...")
        self.search_shortcuts.textChanged.connect(self._filter_shortcuts_table)
        layout.addWidget(self.search_shortcuts)

        # Tabla de atajos
        self.tbl_shortcuts = QTableWidget()
        self.tbl_shortcuts.setColumnCount(4)
        self.tbl_shortcuts.setHorizontalHeaderLabels(["Acción / Descripción", "Atajo Actual", "Remapear", "Activo"])
        self.tbl_shortcuts.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tbl_shortcuts.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.tbl_shortcuts.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.tbl_shortcuts.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.tbl_shortcuts.verticalHeader().setVisible(False)

        self._shortcut_rows_data: list[tuple[str, str, QPushButton, QCheckBox]] = []
        disabled_list = self._settings.get("disabled_shortcuts", [])

        self.tbl_shortcuts.setRowCount(len(self._shortcuts))
        for row, (key, desc_text) in enumerate(self._shortcuts.items()):
            # Col 0: Descripción
            item_desc = QTableWidgetItem(desc_text)
            item_desc.setFlags(item_desc.flags() ^ Qt.ItemFlag.ItemIsEditable)
            self.tbl_shortcuts.setItem(row, 0, item_desc)

            # Col 1: Tecla
            item_key = QTableWidgetItem(key)
            item_key.setFlags(item_key.flags() ^ Qt.ItemFlag.ItemIsEditable)
            item_key.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.tbl_shortcuts.setItem(row, 1, item_key)

            # Col 2: Botón remapear
            remap_btn = QPushButton("Cambiar")
            remap_btn.setProperty("class", "secondary-btn")
            remap_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            remap_btn.clicked.connect(lambda checked=False, r=row, d=desc_text: self._remap_key_row(r, d))
            self.tbl_shortcuts.setCellWidget(row, 2, remap_btn)

            # Col 3: Checkbox activo
            chk_active = QCheckBox()
            chk_active.setChecked(key not in disabled_list)
            chk_container = QWidget()
            chk_layout = QHBoxLayout(chk_container)
            chk_layout.setContentsMargins(8, 0, 8, 0)
            chk_layout.addWidget(chk_active)
            self.tbl_shortcuts.setCellWidget(row, 3, chk_container)

            self._shortcut_rows_data.append((key, desc_text, remap_btn, chk_active))

        layout.addWidget(self.tbl_shortcuts)

        # Atajo maestro passthrough
        pt_row = QHBoxLayout()
        pt_lbl = QLabel("Atajo Maestro de <b>Passthrough</b> (suspende D.I.O. para escribir crudo en la web):")
        self.combo_passthrough = QComboBox()
        self.combo_passthrough.addItems(["ScrollLock", "F12", "Pause", "Ctrl+Alt+P"])
        self.combo_passthrough.setCurrentText(self._settings.get("passthrough_key", "ScrollLock"))
        pt_row.addWidget(pt_lbl)
        pt_row.addWidget(self.combo_passthrough)
        pt_row.addStretch()
        layout.addLayout(pt_row)

        self.stack.addWidget(page)

    def _filter_shortcuts_table(self, query: str) -> None:
        query = query.lower().strip()
        for row in range(self.tbl_shortcuts.rowCount()):
            desc_item = self.tbl_shortcuts.item(row, 0)
            key_item = self.tbl_shortcuts.item(row, 1)
            text = f"{desc_item.text().lower()} {key_item.text().lower()}" if desc_item and key_item else ""
            self.tbl_shortcuts.setRowHidden(row, query not in text)

    def _remap_key_row(self, row: int, action_name: str) -> None:
        dialog = KeySequenceRecorderDialog(action_name, self)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.recorded_sequence:
            new_key = dialog.recorded_sequence
            item_key = self.tbl_shortcuts.item(row, 1)
            if item_key:
                item_key.setText(new_key)
            ToastNotification(f"Atajo remapeado a: {new_key}", self, color="#2563eb")

    # ── PÁGINA 3: Apariencia y Cuadrícula (Layout) ─────────────────────────

    def _build_tab_appearance(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(20)

        header = QLabel("🎨 <b style='font-size:18px; color:#ffffff;'>Apariencia y Cuadrícula (Layout)</b>")
        desc = QLabel("Personaliza los márgenes entre paneles, el color del foco y la opacidad del overlay.")
        desc.setStyleSheet("color: #a6adc8; font-size: 13px;")
        layout.addWidget(header)
        layout.addWidget(desc)

        # 1. Gaps / Márgenes entre paneles
        gaps_title = QLabel("<b>Separación entre Paneles (Gaps / Bordes):</b>")
        layout.addWidget(gaps_title)
        gaps_row = QHBoxLayout()
        self.slider_gaps = QSlider(Qt.Orientation.Horizontal)
        self.slider_gaps.setRange(0, 16)
        self.slider_gaps.setValue(self._settings.get("gaps", 0))
        self.lbl_gaps_val = QLabel(f"{self.slider_gaps.value()} px (borde a borde)")
        self.slider_gaps.valueChanged.connect(lambda v: self.lbl_gaps_val.setText(f"{v} px {'(borde a borde limpio)' if v == 0 else ''}"))
        gaps_row.addWidget(self.slider_gaps, stretch=1)
        gaps_row.addWidget(self.lbl_gaps_val)
        layout.addLayout(gaps_row)

        # 2. Color de foco
        focus_title = QLabel("<b>Color del Borde del Panel Activo (Focus Outline):</b>")
        layout.addWidget(focus_title)
        focus_row = QHBoxLayout()
        self.edit_focus_color = QLineEdit(self._settings.get("focus_color", "#89b4fa"))
        self.btn_color_picker = QPushButton("🎨 Seleccionar Color...")
        self.btn_color_picker.setProperty("class", "secondary-btn")
        self.btn_color_picker.clicked.connect(self._pick_focus_color)
        self.preview_color = QFrame()
        self.preview_color.setFixedSize(32, 32)
        self.preview_color.setStyleSheet(f"background-color: {self.edit_focus_color.text()}; border-radius: 6px; border: 1px solid #45475a;")
        self.edit_focus_color.textChanged.connect(lambda t: self.preview_color.setStyleSheet(f"background-color: {t}; border-radius: 6px; border: 1px solid #45475a;"))

        focus_row.addWidget(self.edit_focus_color, stretch=1)
        focus_row.addWidget(self.preview_color)
        focus_row.addWidget(self.btn_color_picker)
        layout.addLayout(focus_row)

        # 3. Opacidad del Overlay
        opacity_title = QLabel("<b>Opacidad del Fondo Translúcido del Overlay (Dimming):</b>")
        layout.addWidget(opacity_title)
        opacity_row = QHBoxLayout()
        self.slider_opacity = QSlider(Qt.Orientation.Horizontal)
        self.slider_opacity.setRange(30, 95)
        self.slider_opacity.setValue(self._settings.get("overlay_opacity", 75))
        self.lbl_opacity_val = QLabel(f"{self.slider_opacity.value()} %")
        self.slider_opacity.valueChanged.connect(lambda v: self.lbl_opacity_val.setText(f"{v} %"))
        opacity_row.addWidget(self.slider_opacity, stretch=1)
        opacity_row.addWidget(self.lbl_opacity_val)
        layout.addLayout(opacity_row)

        layout.addStretch()
        self.stack.addWidget(page)

    def _pick_focus_color(self) -> None:
        color = QColorDialog.getColor(QColor(self.edit_focus_color.text()), self, "Seleccionar Color de Foco")
        if color.isValid():
            self.edit_focus_color.setText(color.name())

    # ── PÁGINA 4: Opciones Operativas y Avanzadas ───────────────────────────

    def _build_tab_advanced(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(16)

        header = QLabel("🚀 <b style='font-size:18px; color:#ffffff;'>Opciones Operativas y Avanzadas</b>")
        desc = QLabel("Sandboxing, User-Agent spoofing, gestor de workspaces y reglas CSS/JS.")
        desc.setStyleSheet("color: #a6adc8; font-size: 13px;")
        layout.addWidget(header)
        layout.addWidget(desc)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        scroll_content = QWidget()
        form = QVBoxLayout(scroll_content)
        form.setSpacing(16)

        # 1. Sandboxing y limpieza por panel
        sec1 = QLabel("<b>1. Aislamiento de Sesiones (Sandboxing):</b>")
        form.addWidget(sec1)
        sand_row = QHBoxLayout()
        self.combo_profiles = QComboBox()
        for idx in range(max(len(self._dio_window._panels), 6)):
            self.combo_profiles.addItem(f"Panel {idx} (Perfil aislado: ~/.dio/profiles/panel_{idx})")
        btn_clean_profile = QPushButton("🗑️ Limpiar Datos/Cookies de este Panel")
        btn_clean_profile.setProperty("class", "secondary-btn")
        btn_clean_profile.clicked.connect(self._clean_selected_panel_profile)
        sand_row.addWidget(self.combo_profiles, stretch=1)
        sand_row.addWidget(btn_clean_profile)
        form.addLayout(sand_row)

        # 2. Spoofing de User-Agent
        sec2 = QLabel("<b>2. Spoofing de User-Agent (Engaño de Navegador):</b>")
        form.addWidget(sec2)
        ua_row = QHBoxLayout()
        self.combo_ua = QComboBox()
        self.combo_ua.addItems([
            "Desktop Chrome 137 (Recomendado)",
            "Mobile iPhone Safari (Carga versión compacta / móvil)",
            "Desktop Firefox Linux",
            "Personalizado...",
        ])
        ua_row.addWidget(self.combo_ua, stretch=1)
        form.addLayout(ua_row)

        # 3. Gestor de Presets / Workspaces
        sec3 = QLabel("<b>3. Gestor de Presets y Workspaces:</b>")
        form.addWidget(sec3)
        ws_row = QHBoxLayout()
        btn_save_ws = QPushButton("💾 Guardar Cuadrícula Actual como Nuevo Preset...")
        btn_save_ws.setProperty("class", "secondary-btn")
        btn_save_ws.clicked.connect(self._save_current_as_preset)
        ws_row.addWidget(btn_save_ws)
        ws_row.addStretch()
        form.addLayout(ws_row)

        # 4. Inyección de Código (Reglas de sitio)
        sec4 = QLabel("<b>4. Inyección de CSS / Estilos Personalizados:</b>")
        form.addWidget(sec4)
        self.txt_custom_css = QPlainTextEdit()
        self.txt_custom_css.setPlaceholderText("/* Escribe reglas CSS personalizadas aquí. Ej: * { scrollbar-width: none; } */")
        self.txt_custom_css.setFixedHeight(90)
        self.txt_custom_css.setPlainText(self._settings.get("custom_css", ""))
        form.addWidget(self.txt_custom_css)

        # 5. Modo Depuración / DevTools
        sec5 = QLabel("<b>5. Modo de Depuración y Desarrollo:</b>")
        form.addWidget(sec5)
        self.chk_devtools = QCheckBox("Habilitar menú contextual de clic derecho e inspección de elementos / DevTools")
        self.chk_devtools.setChecked(self._settings.get("devtools_enabled", False))
        form.addWidget(self.chk_devtools)

        form.addStretch()
        scroll.setWidget(scroll_content)
        layout.addWidget(scroll)
        self.stack.addWidget(page)

    def _clean_selected_panel_profile(self) -> None:
        idx = self.combo_profiles.currentIndex()
        profile_path = config.PROFILES_DIR / f"panel_{idx}"
        reply = QMessageBox.question(
            self,
            "Confirmar Limpieza",
            f"¿Deseas borrar las cookies y almacenamiento de sesión del Panel {idx}?\n({profile_path})",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            import shutil
            if profile_path.exists():
                try:
                    shutil.rmtree(profile_path)
                    ToastNotification(f"✓ Datos del Panel {idx} eliminados", self, color="#059669")
                except Exception as exc:
                    QMessageBox.warning(self, "Error", f"No se pudo eliminar: {exc}")

    def _save_current_as_preset(self) -> None:
        name, ok = QInputDialog.getText(self, "Nuevo Preset", "Ingresa el nombre para este preset de trabajo:")
        if ok and name.strip():
            preset_key = name.strip().lower().replace(" ", "_")
            current_urls = [p.url().toString() for p in self._dio_window._panels if p.url().isValid()]
            presets = config.load_presets()
            presets[preset_key] = current_urls
            try:
                config.CONFIG_FILE.write_text(json.dumps(presets, indent=2, ensure_ascii=False), encoding="utf-8")
                ToastNotification(f"✓ Preset '{preset_key}' guardado con {len(current_urls)} URLs", self, color="#059669")
            except Exception as exc:
                QMessageBox.warning(self, "Error", f"No se pudo guardar el preset: {exc}")

    # ── PÁGINA 5: Manual de Comandos ───────────────────────────────────────

    def _build_tab_manual(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(14)

        header = QLabel("📖 <b style='font-size:18px; color:#ffffff;'>Manual de Comandos y Atajos</b>")
        desc = QLabel("Referencia rápida de todos los comandos de D.I.O. listos para usar.")
        desc.setStyleSheet("color: #a6adc8; font-size: 13px;")
        layout.addWidget(header)
        layout.addWidget(desc)

        content_browser = QTextBrowser()
        content_browser.setOpenExternalLinks(False)

        html_rows = []
        for key, desc_text in self._shortcuts.items():
            key_pill = (
                f"<span style='background-color:#313244; color:#89b4fa; font-weight:bold; "
                f"font-family:monospace; font-size:13px; padding:4px 8px; border-radius:5px; "
                f"border:1px solid #45475a; white-space:nowrap;'>{key}</span>"
            )
            desc_val = f"<span style='color:#f0f6fc; font-size:13px;'>{desc_text}</span>"
            html_rows.append(f"""
                <tr style='border-bottom: 1px solid #2d2e3e;'>
                    <td style='padding: 9px 12px; width: 160px; vertical-align: middle;'>{key_pill}</td>
                    <td style='padding: 9px 12px; vertical-align: middle;'>{desc_val}</td>
                </tr>
            """)

        full_html = f"""
        <html>
        <head>
            <style>
                body {{ font-family: 'Segoe UI', sans-serif; background-color: #1e1e2e; color: #cdd6f4; margin: 0; padding: 0; }}
                table {{ width: 100%; border-collapse: collapse; }}
                th {{ text-align: left; color: #89b4fa; font-size: 12px; text-transform: uppercase; border-bottom: 2px solid #45475a; padding: 8px 12px; }}
            </style>
        </head>
        <body>
            <table>
                <thead>
                    <tr><th>Atajo de Teclado</th><th>Acción</th></tr>
                </thead>
                <tbody>
                    {''.join(html_rows)}
                </tbody>
            </table>
        </body>
        </html>
        """
        content_browser.setHtml(full_html)
        layout.addWidget(content_browser)
        self.stack.addWidget(page)

    # ── Guardar y Aplicar ──────────────────────────────────────────────────

    def _save_and_apply(self) -> None:
        """Guarda todos los cambios en settings.json y los aplica a la ventana principal."""
        # Core
        self._settings["startup_behavior"] = "load_preset" if self.rb_preset.isChecked() else "restore_last"
        self._settings["hardware_acceleration"] = self.chk_gpu.isChecked()
        self._settings["tab_sleeping_enabled"] = self.chk_sleeping.isChecked()
        sleep_vals = [5, 10, 15, 30, 60]
        self._settings["tab_sleeping_minutes"] = sleep_vals[self.combo_sleep_min.currentIndex()]
        self._settings["downloads_dir"] = self.edit_downloads.text().strip()
        self._settings["ask_download_location"] = self.chk_ask_download.isChecked()

        # Layout
        self._settings["gaps"] = self.slider_gaps.value()
        self._settings["focus_color"] = self.edit_focus_color.text().strip()
        self._settings["overlay_opacity"] = self.slider_opacity.value()

        # Keybindings
        disabled_keys = []
        for key, desc_text, _, chk in self._shortcut_rows_data:
            if not chk.isChecked():
                disabled_keys.append(key)
        self._settings["disabled_shortcuts"] = disabled_keys
        self._settings["passthrough_key"] = self.combo_passthrough.currentText()

        # Advanced
        self._settings["custom_css"] = self.txt_custom_css.toPlainText()
        self._settings["devtools_enabled"] = self.chk_devtools.isChecked()

        config.save_settings(self._settings)

        # Aplicar dinámicamente a la ventana principal
        if hasattr(self._dio_window, "apply_settings"):
            self._dio_window.apply_settings(self._settings)

        ToastNotification("✓ Configuración guardada y aplicada", self._dio_window, color="#059669")
        self.accept()


# ── Diálogo Modal de Selección Rápida de Grid ─────────────────────────────

class GridChooserDialog(QDialog):
    """Diálogo rápido para reorganizar la cuadrícula en 3 columnas x 2 filas, 2x2, etc."""

    def __init__(self, current_rows: int, current_cols: int, total_panels: int, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("D.I.O. — Reorganizar Cuadrícula")
        self.setFixedWidth(460)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.selected_grid: tuple[int, int] | None = None

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(8, 8, 8, 8)

        card = QFrame(self)
        card.setObjectName("GridCard")
        card.setStyleSheet("""
            #GridCard {
                background-color: #1e1e2e;
                border: 1.5px solid #45475a;
                border-radius: 14px;
            }
            QLabel {
                color: #cdd6f4;
                font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
            }
            QPushButton.grid-btn {
                background-color: #313244;
                color: #ffffff;
                border: 1px solid #45475a;
                border-radius: 8px;
                padding: 10px 14px;
                font-size: 13px;
                font-weight: bold;
                text-align: left;
            }
            QPushButton.grid-btn:hover {
                background-color: #45475a;
                border-color: #89b4fa;
                color: #89b4fa;
            }
            QPushButton.cancel-btn {
                background-color: transparent;
                color: #a6adc8;
                font-size: 13px;
                padding: 8px 14px;
                border-radius: 6px;
                border: 1px solid #313244;
            }
            QPushButton.cancel-btn:hover {
                background-color: #313244;
                color: #ffffff;
            }
        """)

        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(20, 18, 20, 18)
        card_layout.setSpacing(10)

        # Header
        header_layout = QHBoxLayout()
        icon_title = QLabel("📐 <b style='font-size:16px; color:#ffffff;'>Reorganizar Cuadrícula</b>")
        header_layout.addWidget(icon_title)
        header_layout.addStretch()
        esc_hint = QLabel("<span style='color:#6c7086; font-size:12px;'>[Esc para cerrar]</span>")
        header_layout.addWidget(esc_hint)
        card_layout.addLayout(header_layout)

        subtitle = QLabel(f"Tienes <b>{total_panels}</b> paneles abiertos. Selecciona la disposición:")
        subtitle.setStyleSheet("color: #a6adc8; font-size: 12px;")
        card_layout.addWidget(subtitle)

        # Presets rápidos
        presets = [
            ("⚡ 3 Columnas × 2 Filas (2x3)", 2, 3, "Ideal para 6 paneles de IA"),
            ("⚡ 2 Columnas × 3 Filas (3x2)", 3, 2, "Columnas verticales más anchas"),
            ("⚡ 2 Columnas × 2 Filas (2x2)", 2, 2, "Cuadrícula simétrica clásica"),
            ("⚡ 3 Columnas × 1 Fila (1x3)", 1, 3, "Panorama horizontal de 3 columnas"),
            ("⚡ 1 Columna × 3 Filas (3x1)", 3, 1, "Pila vertical completa"),
        ]

        for title, r, c, desc in presets:
            btn = QPushButton(f"{title} — {desc}")
            btn.setProperty("class", "grid-btn")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda checked=False, rows=r, cols=c: self._choose(rows, cols))
            card_layout.addWidget(btn)

        # Botón cancelar
        footer_layout = QHBoxLayout()
        footer_layout.addStretch()
        cancel_btn = QPushButton("Cancelar")
        cancel_btn.setProperty("class", "cancel-btn")
        cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_btn.clicked.connect(self.reject)
        footer_layout.addWidget(cancel_btn)
        card_layout.addLayout(footer_layout)

        main_layout.addWidget(card)

    def _choose(self, rows: int, cols: int) -> None:
        self.selected_grid = (rows, cols)
        self.accept()


# ── AdBlock Interceptor ───────────────────────────────────────────────────

class AdBlockInterceptor(QWebEngineUrlRequestInterceptor):
    """
    Intercepta peticiones de red y bloquea los dominios de publicidad/tracking
    definidos en ~/.dio/adblock_hosts.txt. Lookup O(1) mediante set.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._blocked_hosts: set[str] = set()
        self._load_hosts()

    def _load_hosts(self) -> None:
        """Carga la lista de hosts bloqueados desde disco."""
        hosts_file = config.ADBLOCK_HOSTS_FILE
        if not hosts_file.exists():
            config.ensure_adblock_hosts()

        if not hosts_file.exists():
            logger.warning("adblock_hosts.txt no encontrado; adblock inactivo")
            return

        try:
            count = 0
            for line in hosts_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    self._blocked_hosts.add(line.lower())
                    count += 1
            logger.info("AdBlock: %d dominios cargados desde %s", count, hosts_file)
        except OSError as exc:
            logger.warning("No se pudo leer adblock_hosts.txt: %s", exc)

    def interceptRequest(self, info) -> None:
        """Bloquea peticiones cuyo host coincide con la lista de dominios."""
        host = info.requestUrl().host().lower()
        if host.startswith("www."):
            host = host[4:]

        # Nunca bloquear peticiones internas ni canales de streaming de los servicios principales
        if any(
            trusted in host
            for trusted in (
                "anthropic.com",
                "claude.ai",
                "openai.com",
                "chatgpt.com",
                "google.com",
                "gstatic.com",
                "perplexity.ai",
                "grok.com",
                "whatsapp.com",
                "whatsapp.net",
            )
        ):
            return

        for blocked in self._blocked_hosts:
            if host == blocked or host.endswith("." + blocked):
                info.block(True)
                return


# ── Overlay de carga ─────────────────────────────────────────────────────

class LoadingOverlay(QLabel):
    """Overlay translúcido que muestra el progreso de carga sobre un panel."""

    def __init__(self, parent: QWebEngineView) -> None:
        super().__init__(parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet(
            "background: rgba(0, 0, 0, 180);"
            "color: #00ff88;"
            "font-size: 16px;"
            "font-family: monospace;"
            "font-weight: bold;"
            "border: none;"
        )
        self.setText("Cargando…")
        self.hide()

    def update_progress(self, percent: int) -> None:
        """Actualiza el texto del overlay con el porcentaje."""
        self.setText(f"Cargando… {percent}%")

    def reposition(self) -> None:
        """Reposiciona el overlay al tamaño del widget padre."""
        parent = self.parent()
        if parent is not None:
            self.setGeometry(0, 0, parent.width(), parent.height())


# ── Indicador de silencio ─────────────────────────────────────────────────

class MutedIndicator(QLabel):
    """Pequeño indicador rojo en la esquina superior derecha cuando el panel está silenciado."""

    def __init__(self, parent: QWebEngineView) -> None:
        super().__init__(parent)
        self.setText("🔇")
        self.setStyleSheet(
            "background: rgba(200, 0, 0, 200);"
            "color: white;"
            "font-size: 18px;"
            "padding: 2px 6px;"
            "border-radius: 4px;"
            "border: none;"
        )
        self.adjustSize()
        self.hide()

    def reposition(self) -> None:
        """Posiciona el indicador en la esquina superior derecha del panel."""
        parent = self.parent()
        if parent is not None:
            margin = 4
            self.move(parent.width() - self.width() - margin, margin)


# ── Toast de notificación ─────────────────────────────────────────────────

class ToastNotification(QLabel):
    """Notificación flotante breve que se autodestruye tras 3 segundos."""

    def __init__(self, message: str, parent, color: str = "#00aa44") -> None:
        super().__init__(message, parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet(
            f"background: {color};"
            "color: white;"
            "font-size: 13px;"
            "font-family: monospace;"
            "padding: 8px 16px;"
            "border-radius: 6px;"
            "border: none;"
        )
        self.adjustSize()
        self._reposition()
        self.show()
        self.raise_()
        QTimer.singleShot(3000, self.deleteLater)

    def _reposition(self) -> None:
        """Posiciona el toast en la esquina inferior derecha de la ventana padre."""
        parent = self.parent()
        if parent is not None:
            margin = 16
            self.move(
                parent.width() - self.width() - margin,
                parent.height() - self.height() - margin,
            )


# ── Página personalizada con soporte de popups / OAuth ────────────────────

class DIOPage(QWebEnginePage):
    """
    Subclase de QWebEnginePage que gestiona createWindow para:
    - Popups OAuth / diálogos de login: navega en el panel principal para
      evitar el bloqueo de Google a webviews embebidos.
    - target="_blank": navega en el mismo panel o delega al sistema.

    IMPORTANTE: Las ventanas popup se almacenan en _active_popups para evitar
    que el garbage collector de Python destruya los objetos C++ antes de que
    Qt termine de usarlos (RuntimeError: wrapped C/C++ object deleted).
    """

    def __init__(self, profile: QWebEngineProfile, parent_view: QWebEngineView) -> None:
        super().__init__(profile, parent_view)
        self._parent_view = parent_view
        self._active_popups: list[dict] = []

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

        Google bloquea OAuth en popups de webviews embebidos (QWebEngine) y
        el flujo GIS/gis_transform es POST-based, así que no se puede
        redirigir al navegador del sistema. La solución: cuando detectamos
        que el popup navega a accounts.google.com, redirigimos la URL al
        panel padre (navegación full-page), que Google sí permite.
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

        # Almacenar referencias persistentes para que el GC no destruya los
        # objetos C++ subyacentes mientras Qt los sigue usando.
        popup_record = {
            "dialog": dialog,
            "view": popup_view,
            "page": popup_page,
        }
        self._active_popups.append(popup_record)

        # Al cerrar el diálogo, liberar la referencia de forma segura
        def _on_popup_closed():
            try:
                self._active_popups.remove(popup_record)
            except ValueError:
                pass

        dialog.finished.connect(_on_popup_closed)
        popup_page.windowCloseRequested.connect(dialog.close)

        # Google bloquea OAuth en popups de webviews embebidos. Cuando el
        # popup intente navegar a accounts.google.com, lo interceptamos y
        # cargamos la URL directamente en el panel padre (full-page redirect).
        # Google permite OAuth como navegación de página completa.
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


# ── Ventana principal ────────────────────────────────────────────────────

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
        for i, panel in enumerate(self._panels):
            logger.info(
                "Cierre — Panel %d: URL=%s, tamaño=%dx%d",
                i, panel.url().toString(), panel.width(), panel.height(),
            )
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

    def _remove_panel(self) -> None:
        view = self._get_focused_view()
        if view is None or len(self._panels) <= 1:
            return
        idx = self._panels.index(view) if view in self._panels else -1
        if idx < 0:
            return
        url = view.url().toString()
        self._panels.pop(idx)
        if idx < len(self._overlays):
            self._overlays.pop(idx)
        if idx < len(self._mute_indicators):
            self._mute_indicators.pop(idx)
        view.setParent(None)
        view.page().deleteLater()
        view.deleteLater()
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

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="D.I.O.",
        description="Divisor Integrado Operativo — Grid de navegadores aislados",
    )
    parser.add_argument(
        "--grid",
        type=str,
        default=config.DEFAULT_GRID,
        help=f"Disposición del grid (ej: 2x2, 2x3). Default: {config.DEFAULT_GRID}",
    )
    parser.add_argument(
        "--preset",
        type=str,
        default=config.DEFAULT_PRESET,
        help=f"Preset de URLs a cargar (definidos en ~/.dio/config.json). Default: {config.DEFAULT_PRESET}",
    )
    parser.add_argument(
        "--low-memory",
        action="store_true",
        default=False,
        help="Desactiva aceleración GPU de Chromium para reducir consumo de RAM y VRAM.",
    )
    parser.add_argument(
        "--monitor",
        type=int,
        default=0,
        help="Índice del monitor donde abrir D.I.O. (0=primario). Default: 0",
    )
    parser.add_argument(
        "--no-dark-mode",
        action="store_true",
        default=False,
        help="Desactiva el modo oscuro forzado (activo por defecto).",
    )
    parser.add_argument(
        "--no-adblock",
        action="store_true",
        default=False,
        help="Desactiva el bloqueador de anuncios nativo (activo por defecto).",
    )
    parser.add_argument(
        "--ask-download-location",
        action="store_true",
        default=False,
        help="Pide ubicación de guardado para cada descarga mediante diálogo nativo.",
    )
    return parser.parse_args()


def parse_grid(grid_str: str) -> tuple[int, int]:
    try:
        parts = grid_str.lower().split("x")
        rows, cols = int(parts[0]), int(parts[1])
        if rows < 1 or cols < 1:
            raise ValueError
        return (rows, cols)
    except (ValueError, IndexError):
        logger.error("Formato de grid inválido '%s'. Usa RxC (ej: 2x3).", grid_str)
        sys.exit(1)


def try_restore_session(app: QApplication) -> dict | None:
    if not config.SESSION_FILE.exists():
        return None
    try:
        data = json.loads(config.SESSION_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("session.json corrupto o ilegible: %s", exc)
        return None
    if not isinstance(data, dict) or "urls" not in data:
        return None

    reply = QMessageBox.question(
        None,
        "D.I.O. — Restaurar sesión",
        (
            f"Se encontró una sesión guardada con {len(data['urls'])} paneles.\n"
            "¿Restaurar la última sesión de trabajo?"
        ),
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.Yes,
    )

    if reply == QMessageBox.StandardButton.Yes:
        logger.info("Usuario aceptó restaurar sesión")
        return data

    logger.info("Usuario rechazó restaurar sesión")
    return None


def main() -> None:
    """Punto de entrada principal."""
    setup_logging()
    logger.info("═" * 60)
    logger.info("D.I.O. iniciando…")

    if _LOW_MEMORY:
        logger.info("Modo bajo consumo (--low-memory) activado: GPU desactivada")
    if _DARK_MODE:
        logger.info("Modo oscuro forzado activado")
    if _ADBLOCK_ENABLED:
        logger.info("AdBlock nativo activado")

    config.ensure_adblock_hosts()

    args = parse_args()
    presets = config.load_presets()

    app = QApplication(sys.argv)
    app.setApplicationName("D.I.O.")
    app.setDesktopFileName("dio.desktop")
    icon_path = Path(__file__).resolve().parent / "assets" / "icon.png"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))
    app.setStyleSheet(GLOBAL_DIALOG_STYLE)

    session = try_restore_session(app)

    if session is not None:
        urls = session["urls"]
        grid_str = session.get("grid", args.grid)
        rows, cols = parse_grid(grid_str)
        preset_name = session.get("preset", args.preset)
        panel_counter = session.get("panel_counter", len(urls))

        window = DIOWindow(rows, cols, urls, preset_name, args.monitor)
        window._panel_counter = panel_counter

        splitter_states = session.get("splitter_states")
        if splitter_states:
            window._restore_splitter_states(splitter_states)

        logger.info("Sesión restaurada: %d paneles", len(urls))
        for i, url in enumerate(urls):
            logger.info("  Panel %d: %s", i, url)

    else:
        if args.preset not in presets:
            logger.error(
                "Preset '%s' no encontrado. Disponibles: %s",
                args.preset, ", ".join(presets.keys()),
            )
            sys.exit(1)

        rows, cols = parse_grid(args.grid)
        urls = presets[args.preset]
        grid_size = rows * cols
        panel_urls = urls[:grid_size]

        window = DIOWindow(rows, cols, panel_urls, args.preset, args.monitor)

    screens = app.screens()
    monitor_idx = min(args.monitor, len(screens) - 1)
    if monitor_idx >= 0 and screens:
        target_screen = screens[monitor_idx]
        geo = target_screen.geometry()
        window.setGeometry(geo)
        logger.info(
            "Monitor %d seleccionado: %s (%dx%d)",
            monitor_idx, target_screen.name(), geo.width(), geo.height(),
        )

    window.showFullScreen()

    app.aboutToQuit.connect(window._save_session)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, lambda *_: app.quit())

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
