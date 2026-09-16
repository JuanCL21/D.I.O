"""
D.I.O. — Widgets personalizados: Splitters sin bordes, Overlays de carga,
indicadores de muteo y notificaciones toast.
"""

from PyQt6.QtCore import QSize, QTimer, Qt
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import QLabel, QSplitter, QSplitterHandle


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
