"""
D.I.O. — Diálogos modales de usuario: Omnibox, Grabador de atajos,
Overlay de configuración integral y Selector de cuadrículas.
"""

import json
import os
import urllib.parse
from pathlib import Path

from PyQt6.QtCore import QSize, Qt, QTimer, QUrl
from PyQt6.QtGui import QColor, QDesktopServices, QIcon, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
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
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

import dio.core.config as config
from dio.core.logger import logger
from dio.core.security import secure_directory

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


