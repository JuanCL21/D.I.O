"""
D.I.O. — Ventana de Panel Desacoplado (DetachedPanelWindow).
Permite desacoplar un panel web existente a una ventana independiente flotante
preservando exactamente el mismo QWebEngineView, su QWebEngineProfile, cookies,
sesion activa y ciclo de vida en la FSM.
"""

from typing import Callable, Optional
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QIcon, QKeySequence, QShortcut
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from dio.core.logger import logger


class DetachedPanelWindow(QMainWindow):
    """
    Ventana secundaria que aloja un panel desacoplado del grid principal.
    Permite moverlo libremente a otro monitor sin recrear sesion ni perfil.
    """

    reattach_requested = pyqtSignal(QWebEngineView)
    closed_without_reattach = pyqtSignal(QWebEngineView)

    def __init__(
        self,
        view: QWebEngineView,
        panel_id: str,
        reattach_callback: Optional[Callable[[QWebEngineView], None]] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._view = view
        self._panel_id = panel_id
        self._reattach_callback = reattach_callback
        self._is_reattached = False

        self.setWindowTitle(f"D.I.O. — {panel_id.upper()} (Desacoplado)")
        self.resize(800, 600)
        self.setStyleSheet("background: #09090b; color: #f4f4f5;")

        # Contenedor central
        container = QWidget(self)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Barra superior minimalista
        top_bar = QWidget(container)
        top_bar.setFixedHeight(28)
        top_bar.setStyleSheet("background: #18181b; border-bottom: 1px solid #27272a;")
        bar_layout = QHBoxLayout(top_bar)
        bar_layout.setContentsMargins(8, 0, 8, 0)
        bar_layout.setSpacing(6)

        title_lbl = QLabel(f"[POP-OUT] {panel_id.upper()}", top_bar)
        title_lbl.setStyleSheet("font-weight: bold; font-size: 11px; color: #a1a1aa;")
        bar_layout.addWidget(title_lbl)

        bar_layout.addStretch()

        reattach_btn = QPushButton("Re-acoplar (Ctrl+Shift+D)", top_bar)
        reattach_btn.setFixedHeight(22)
        reattach_btn.setStyleSheet(
            "QPushButton { background: #27272a; color: #e4e4e7; border: 1px solid #3f3f46; "
            "border-radius: 3px; font-size: 11px; padding: 2px 8px; }"
            "QPushButton:hover { background: #3f3f46; color: #ffffff; }"
        )
        reattach_btn.clicked.connect(self.reattach)
        bar_layout.addWidget(reattach_btn)

        layout.addWidget(top_bar)

        # Reparentar la vista existente
        self._view.setParent(container)
        layout.addWidget(self._view)
        self.setCentralWidget(container)

        # Atajo local para re-acoplar
        self._shortcut_reattach = QShortcut(QKeySequence("Ctrl+Shift+D"), self)
        self._shortcut_reattach.activated.connect(self.reattach)

        logger.info("Panel %s desacoplado en ventana flotante independiente", panel_id)

    @property
    def view(self) -> QWebEngineView:
        return self._view

    @property
    def panel_id(self) -> str:
        return self._panel_id

    def reattach(self) -> None:
        """Re-acopla el panel de vuelta a la ventana principal de D.I.O."""
        if self._is_reattached:
            return
        self._is_reattached = True

        # Desvincular vista de esta ventana
        self._view.setParent(None)

        if self._reattach_callback:
            self._reattach_callback(self._view)
        self.reattach_requested.emit(self._view)

        logger.info("Panel %s re-acoplado a la ventana principal", self._panel_id)
        self.close()

    def closeEvent(self, event) -> None:
        """Si la ventana se cierra con Alt+F4 o boton 'X', re-acoplar para no perder el panel."""
        if not self._is_reattached:
            self._is_reattached = True
            self._view.setParent(None)
            if self._reattach_callback:
                self._reattach_callback(self._view)
            self.reattach_requested.emit(self._view)
            logger.info("Cierre de ventana desacoplada: panel %s re-acoplado automaticamente", self._panel_id)
        super().closeEvent(event)
