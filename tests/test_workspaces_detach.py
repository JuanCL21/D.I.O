"""
Tests para Workspaces Virtuales y Panel Detach de D.I.O. (Paso 6):
- Inicializacion de QStackedWidget con max_workspaces (9 workspaces)
- Alternancia de workspaces (switch_workspace)
- Preservacion de FSM y perfiles en workspaces fuera de vista
- Desacoplar panel (detach_focused_panel) a DetachedPanelWindow
- Preservacion de QWebEngineProfile, cookies e historial tras detach
- Re-acoplar panel (reattach) sin perdida de estado ni huecos en el grid
- Reporte de workspace y detach en IPC status
"""

import time
from unittest.mock import MagicMock, patch

import pytest
from PyQt6.QtCore import QUrl
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import QApplication, QStackedWidget

from dio.core.state import PanelEvent, PanelState
from dio.ui.detached import DetachedPanelWindow
from dio.ui.window import DIOWindow


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(["dio_test_step6"])
    yield app


@pytest.fixture
def sample_window(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr("dio.core.config.DIO_DIR", tmp_path)
    monkeypatch.setattr("dio.core.config.PROFILES_DIR", tmp_path / "profiles")
    (tmp_path / "profiles").mkdir(parents=True, exist_ok=True)

    urls = ["https://example.com", "https://example.org", "https://example.net"]
    win = DIOWindow(rows=1, cols=3, urls=urls, preset_name="test_step6", monitor=0)
    yield win
    try:
        win.close()
    except Exception:
        pass


# ── Tests de Workspaces Virtuales ─────────────────────────────────────────────

def test_workspaces_initialization(sample_window):
    assert isinstance(sample_window.centralWidget(), QStackedWidget)
    assert sample_window._max_workspaces == 9
    assert sample_window._current_workspace_idx == 0
    assert sample_window._stacked_workspaces.currentIndex() == 0

    # Los 3 paneles iniciales deben pertenecer al workspace 0
    assert len(sample_window._panels) == 3
    assert all(ws == 0 for ws in sample_window._panel_workspaces)


def test_switch_workspace_navigation(sample_window):
    sample_window.switch_workspace(1)
    assert sample_window._current_workspace_idx == 1
    assert sample_window._stacked_workspaces.currentIndex() == 1

    sample_window.switch_workspace(4)
    assert sample_window._current_workspace_idx == 4
    assert sample_window._stacked_workspaces.currentIndex() == 4

    # Volver al workspace 0
    sample_window.switch_workspace(0)
    assert sample_window._current_workspace_idx == 0
    assert sample_window._stacked_workspaces.currentIndex() == 0


def test_fsm_preservation_across_workspaces(sample_window):
    # Transicionar a ACTIVE para permitir hibernar
    sample_window._fsms[0].trigger(PanelEvent.INIT_FINISHED)
    # Hibernar panel 0 en workspace 0
    sample_window.hibernate_panel(0)
    assert sample_window._fsms[0].state == PanelState.HIBERNATED

    # Cambiar a otro workspace
    sample_window.switch_workspace(2)
    assert sample_window._current_workspace_idx == 2

    # El panel 0 en el workspace 0 debe continuar en HIBERNATED sin alteraciones
    assert sample_window._fsms[0].state == PanelState.HIBERNATED

    # Regresar al workspace 0 y despertar
    sample_window.switch_workspace(0)
    sample_window.wake_panel(0)
    assert sample_window._fsms[0].state in (PanelState.RESTORING, PanelState.ACTIVE)


# ── Tests de Detach y Re-attach de Paneles ─────────────────────────────────────

def test_detach_focused_panel_preserves_profile_and_session(sample_window):
    view_to_detach = sample_window._panels[1]
    original_profile = view_to_detach.page().profile()
    original_page = view_to_detach.page()
    original_url = view_to_detach.url().toString()

    # Desacoplar vista explicitamente
    sample_window.detach_panel(view_to_detach)

    assert view_to_detach in sample_window._detached_views
    assert len(sample_window._detached_windows) == 1

    detached_win = sample_window._detached_windows[0]
    assert detached_win.view == view_to_detach

    # Verificar que el perfil, la pagina y la URL no fueron recreados
    assert view_to_detach.page() == original_page
    assert view_to_detach.page().profile() == original_profile
    assert view_to_detach.url().toString() == original_url

    # FSM sigue activa y rastreando el panel
    assert sample_window._fsms[1].panel_id == "panel_1"


def test_reattach_panel_restores_layout_cleanly(sample_window):
    view = sample_window._panels[1]
    sample_window.detach_panel(view)
    assert len(sample_window._detached_windows) == 1
    detached_win = sample_window._detached_windows[0]

    # Re-acoplar mediante metodo del pop-out
    detached_win.reattach()

    assert view not in sample_window._detached_views
    assert view.parent() is not None

    # Verificar que el grid restante no tiene huecos
    root = sample_window._root_splitter
    assert root is not None
    assert root.count() > 0


# ── Tests de IPC Status con Workspaces y Detach ───────────────────────────────

def test_ipc_status_includes_workspace_and_detach_metadata(sample_window):
    status = sample_window._ipc_status()

    assert "current_workspace" in status
    assert status["current_workspace"] == sample_window._current_workspace_idx + 1
    assert "max_workspaces" in status
    assert status["max_workspaces"] == 9

    for panel_info in status["panels"]:
        assert "workspace" in panel_info
        assert "detached" in panel_info
        assert isinstance(panel_info["detached"], bool)
        assert isinstance(panel_info["workspace"], int)
