"""
D.I.O. — Widgets personalizados: Splitters sin bordes, Overlays de carga,
indicadores de muteo y notificaciones toast.
"""

from PyQt6.QtCore import QSize, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QPixmap
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import QFrame, QLabel, QPushButton, QSplitter, QSplitterHandle, QVBoxLayout


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


class HibernationOverlay(QFrame):
    """
    Overlay que se muestra sobre un panel hibernado.
    Presenta la captura visual estática (snapshot) atenuada y un badge
    interactivo para despertar el panel al hacer clic.
    """
    wake_requested = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("HibernationOverlay")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        self._snapshot_label = QLabel(self)
        self._snapshot_label.setScaledContents(True)

        self._backdrop = QFrame(self)
        self._backdrop.setStyleSheet("background: rgba(15, 15, 23, 0.85);")

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        card = QFrame(self)
        card.setStyleSheet("""
            QFrame {
                background: #181825;
                border: 1.5px solid #45475a;
                border-radius: 12px;
                padding: 18px 24px;
            }
            QLabel {
                color: #cdd6f4;
                font-family: system-ui, sans-serif;
            }
        """)
        card_layout = QVBoxLayout(card)
        card_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.setSpacing(6)

        title = QLabel("🌙 <b style='font-size: 15px; color: #89b4fa;'>Panel en Hibernación</b>")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(title)

        desc = QLabel("<span style='font-size: 12px; color: #a6adc8;'>Memoria RAM liberada por inactividad.</span>")
        desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(desc)

        action = QLabel("<b style='font-size: 12px; color: #a6e3a1;'>⚡ Haz clic para reanudar la sesión</b>")
        action.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(action)

        layout.addWidget(card)
        self.hide()

    def set_snapshot(self, pixmap: QPixmap) -> None:
        """Aplica la captura de pantalla estática al overlay."""
        self._snapshot_label.setPixmap(pixmap)
        self.reposition()

    def mousePressEvent(self, event) -> None:
        self.wake_requested.emit()
        super().mousePressEvent(event)

    def reposition(self) -> None:
        parent = self.parent()
        if parent is not None:
            self.setGeometry(0, 0, parent.width(), parent.height())
            self._snapshot_label.setGeometry(0, 0, parent.width(), parent.height())
            self._backdrop.setGeometry(0, 0, parent.width(), parent.height())


class CrashOverlay(QFrame):
    """
    Overlay visual de resiliencia ante crashes de renderer (Crash Recovery).
    Informa del estado de recuperación y provee recarga manual si se agotan reintentos.
    """
    manual_reload_requested = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("CrashOverlay")
        self.setStyleSheet("background: rgba(17, 17, 27, 0.95);")

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._card = QFrame(self)
        self._card.setStyleSheet("""
            QFrame {
                background: #1e1e2e;
                border: 1.5px solid #f38ba8;
                border-radius: 12px;
                padding: 20px;
            }
            QLabel {
                color: #cdd6f4;
                font-family: system-ui, sans-serif;
            }
            QPushButton {
                background-color: #f38ba8;
                color: #11111b;
                font-weight: bold;
                font-size: 13px;
                padding: 8px 16px;
                border-radius: 6px;
                border: none;
            }
            QPushButton:hover {
                background-color: #eba0ac;
            }
        """)
        card_layout = QVBoxLayout(self._card)
        card_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.setSpacing(10)

        self._icon_label = QLabel("⚠️ <b style='font-size: 16px; color: #f38ba8;'>Renderer Interrumpido</b>")
        self._icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(self._icon_label)

        self._status_label = QLabel("Recuperando automáticamente sesión...")
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(self._status_label)

        self._reload_btn = QPushButton("🔄 Recargar Panel")
        self._reload_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._reload_btn.clicked.connect(self.manual_reload_requested.emit)
        self._reload_btn.hide()
        card_layout.addWidget(self._reload_btn)

        layout.addWidget(self._card)
        self.hide()

    def show_recovering(self, attempt: int, max_retries: int, delay_s: float) -> None:
        """Muestra estado de reintento automático con backoff."""
        self._icon_label.setText("⚠️ <b style='font-size: 15px; color: #fab387;'>Recuperando Renderer</b>")
        self._status_label.setText(
            f"El proceso web falló inesperadamente.<br>"
            f"Reintentando conexión ({attempt}/{max_retries}) en {delay_s:.1f}s…"
        )
        self._reload_btn.hide()
        self.reposition()
        self.show()
        self.raise_()

    def show_failed(self) -> None:
        """Muestra estado de fallo definitivo con botón de recarga manual."""
        self._icon_label.setText("❌ <b style='font-size: 15px; color: #f38ba8;'>Recuperación Fallida</b>")
        self._status_label.setText(
            "Se agotaron todos los reintentos automáticos.<br>"
            "Puedes intentar recargar el panel manualmente."
        )
        self._reload_btn.show()
        self.reposition()
        self.show()
        self.raise_()

    def reposition(self) -> None:
        parent = self.parent()
        if parent is not None:
            self.setGeometry(0, 0, parent.width(), parent.height())
