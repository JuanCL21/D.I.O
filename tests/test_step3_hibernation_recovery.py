"""
D.I.O. — Tests automatizados para el Paso 3:
Hibernación de memoria (Tab Discarding), Crash Recovery y ProfileManager (Decisión 2).
"""

import os
import shutil
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from PyQt6.QtCore import QUrl
from PyQt6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
from PyQt6.QtWidgets import QApplication

from dio.browser.profile_manager import ProfileManager
from dio.browser.page import DIOPage
from dio.core.state import PanelEvent, PanelState
import dio.core.config as config
import dio


@pytest.fixture
def temp_dio_env(tmp_path):
    """Directorio temporal para aislamiento de pruebas de perfil y persistencia."""
    dio_dir = tmp_path / ".dio"
    profiles_dir = dio_dir / "profiles"
    profiles_dir.mkdir(parents=True)
    session_file = dio_dir / "session.json"
    config_toml = dio_dir / "config.toml"
    log_file = dio_dir / "dio.log"
    return {
        "dio_dir": dio_dir,
        "profiles_dir": profiles_dir,
        "session_file": session_file,
        "config_toml": config_toml,
        "log_file": log_file,
    }


class TestProfileManagerDecision2:
    """Verifica el cumplimiento estricto de la Decisión 2 y preservación de perfiles en disco."""

    def test_profile_creation_and_disk_persistence(self, temp_dio_env):
        """Verifica que el perfil persiste en disco y no se destruye al cerrar."""
        with patch.object(config, "PROFILES_DIR", temp_dio_env["profiles_dir"]), \
             patch.object(config, "DIO_DIR", temp_dio_env["dio_dir"]):

            pm = ProfileManager(max_in_memory=2)
            prof1 = pm.get_or_create_profile("panel_0", is_pinned=False)
            assert prof1 is not None

            # Verificar existencia física del directorio en disco
            disk_path = temp_dio_env["profiles_dir"] / "panel_0"
            assert disk_path.exists()
            assert disk_path.is_dir()

            # Liberar referencia en memoria (simula cierre/hibernación de panel)
            pm.release_profile_reference("panel_0")

            # DECISIÓN 2: El directorio en disco DEBE permanecer intacto
            assert disk_path.exists(), "DECISIÓN 2 violada: el directorio del perfil en disco fue eliminado al liberar referencia"

    def test_lru_eviction_excludes_pinned_profiles(self, temp_dio_env):
        """Verifica que el desalojo LRU de memoria RAM respeta y excluye los perfiles pinned."""
        with patch.object(config, "PROFILES_DIR", temp_dio_env["profiles_dir"]), \
             patch.object(config, "DIO_DIR", temp_dio_env["dio_dir"]):

            pm = ProfileManager(max_in_memory=2)

            # 1. Crear panel_0 como PINNED
            prof0 = pm.get_or_create_profile("panel_0", is_pinned=True)
            pm.release_profile_reference("panel_0")  # ref_count = 0, pero pinned = True

            # 2. Crear panel_1 como NO PINNED
            prof1 = pm.get_or_create_profile("panel_1", is_pinned=False)
            pm.release_profile_reference("panel_1")  # ref_count = 0, no pinned

            # 3. Crear panel_2: debe forzar desalojo de panel_1 (no de panel_0 porque está pinned)
            prof2 = pm.get_or_create_profile("panel_2", is_pinned=False)

            assert "panel_0" in pm._pool, "Perfil PINNED fue desalojado erróneamente del pool"
            assert "panel_1" not in pm._pool, "Perfil no pinned debió ser desalojado por LRU"
            assert "panel_2" in pm._pool

            # Verificar que los datos en disco de TODOS los perfiles siguen intactos
            assert (temp_dio_env["profiles_dir"] / "panel_0").exists()
            assert (temp_dio_env["profiles_dir"] / "panel_1").exists()
            assert (temp_dio_env["profiles_dir"] / "panel_2").exists()

    def test_delete_profile_from_disk_explicit(self, temp_dio_env):
        """Verifica que el borrado definitivo en disco requiere confirmación explícita."""
        with patch.object(config, "PROFILES_DIR", temp_dio_env["profiles_dir"]):
            pm = ProfileManager()
            pm.get_or_create_profile("panel_x")
            disk_path = temp_dio_env["profiles_dir"] / "panel_x"
            assert disk_path.exists()

            # Sin confirmación explícita debe fallar
            with pytest.raises(ValueError):
                pm.delete_profile_from_disk("panel_x", confirmed=False)

            # Con confirmación explícita borra
            res = pm.delete_profile_from_disk("panel_x", confirmed=True)
            assert res is True
            assert not disk_path.exists()


class TestHibernationAndPinning:
    """Verifica la hibernación (Tab Discarding) y la excepción de paneles fijados (Pinned)."""

    def test_hibernate_and_wake_panel(self, temp_dio_env):
        """Verifica el ciclo ACTIVE -> HIBERNATED -> RESTORING -> ACTIVE en un panel real."""
        with patch.object(config, "PROFILES_DIR", temp_dio_env["profiles_dir"]), \
             patch.object(config, "SESSION_FILE", temp_dio_env["session_file"]), \
             patch.object(config, "CONFIG_TOML", temp_dio_env["config_toml"]), \
             patch.object(config, "DIO_DIR", temp_dio_env["dio_dir"]), \
             patch.object(config, "LOG_FILE", temp_dio_env["log_file"]):

            urls = ["about:blank", "about:blank"]
            window = dio.DIOWindow(1, 2, urls, "test", 0)

            # Simular que los paneles completaron su carga inicial (INITIALIZING -> ACTIVE)
            for i in range(len(window._panels)):
                window._on_load_finished(window._overlays[i], i, ok=True)

            # 1. Ambos paneles inicializan en ACTIVE
            assert window._fsms[0].state == PanelState.ACTIVE
            assert window._fsms[1].state == PanelState.ACTIVE

            # 2. Hibernar panel 1
            success = window.hibernate_panel(1)
            assert success is True
            assert window._fsms[1].state == PanelState.HIBERNATED
            assert not isinstance(window._panels[1].page(), DIOPage), "La DIOPage debió ser destruida para liberar el proceso"

            # 3. Despertar panel 1
            wake_success = window.wake_panel(1)
            assert wake_success is True
            assert window._fsms[1].state == PanelState.RESTORING
            assert isinstance(window._panels[1].page(), DIOPage), "La DIOPage debió recrearse"

            # Simular que loadFinished se completa
            window._on_load_finished(window._overlays[1], 1, ok=True)
            assert window._fsms[1].state == PanelState.ACTIVE

            window.close()

    def test_pinned_panel_never_hibernates(self, temp_dio_env):
        """
        REQUISITO OBLIGATORIO:
        Un panel marcado como Pinned / Do Not Sleep NUNCA debe hibernar.
        """
        with patch.object(config, "PROFILES_DIR", temp_dio_env["profiles_dir"]), \
             patch.object(config, "SESSION_FILE", temp_dio_env["session_file"]), \
             patch.object(config, "CONFIG_TOML", temp_dio_env["config_toml"]), \
             patch.object(config, "DIO_DIR", temp_dio_env["dio_dir"]), \
             patch.object(config, "LOG_FILE", temp_dio_env["log_file"]):

            urls = ["about:blank", "about:blank"]
            window = dio.DIOWindow(1, 2, urls, "test", 0)
            for i in range(len(window._panels)):
                window._on_load_finished(window._overlays[i], i, ok=True)

            # Marcar panel 0 como PINNED
            window._pinned_flags[0] = True
            window._profile_manager.set_pinned("panel_0", True)

            # Intentar hibernar panel 0
            hib_res = window.hibernate_panel(0)
            assert hib_res is False, "Panel marcado como PINNED no debe permitir hibernación"
            assert window._fsms[0].state == PanelState.ACTIVE, "FSM debe permanecer en ACTIVE"
            assert window._panels[0].page() is not None

            window.close()


class TestCrashRecoveryAndBackoff:
    """Verifica la recuperación ante caídas de renderer con FSM y backoff."""

    def test_crash_triggers_recovery_and_decision_4(self, temp_dio_env):
        """
        Verifica que renderProcessTerminated activa el flujo de Crash Recovery
        y que tras carga exitosa crash_count se resetea a 0 (Decisión 4).
        """
        with patch.object(config, "PROFILES_DIR", temp_dio_env["profiles_dir"]), \
             patch.object(config, "SESSION_FILE", temp_dio_env["session_file"]), \
             patch.object(config, "CONFIG_TOML", temp_dio_env["config_toml"]), \
             patch.object(config, "DIO_DIR", temp_dio_env["dio_dir"]), \
             patch.object(config, "LOG_FILE", temp_dio_env["log_file"]):

            urls = ["about:blank"]
            window = dio.DIOWindow(1, 1, urls, "test", 0)
            window._on_load_finished(window._overlays[0], 0, ok=True)
            assert window._fsms[0].state == PanelState.ACTIVE

            # Simular caída de renderer
            window._on_render_crash(
                window._panels[0],
                0,
                QWebEnginePage.RenderProcessTerminationStatus.CrashedTerminationStatus,
                139,
            )

            # Debe transicionar a RECOVERING
            assert window._fsms[0].state == PanelState.RECOVERING
            assert window._fsms[0].crash_count == 1

            # Simular éxito de recuperación tras recreación
            window._on_load_finished(window._overlays[0], 0, ok=True)

            # DECISIÓN 4: Retorna a ACTIVE con crash_count = 0
            assert window._fsms[0].state == PanelState.ACTIVE
            assert window._fsms[0].crash_count == 0

            window.close()

    def test_h01_fix_remains_active_with_fsm(self, temp_dio_env):
        """
        VERIFICACIÓN CRUZADA H-01:
        Cerrar paneles no destruye los perfiles en disco ni produce use-after-free.
        """
        with patch.object(config, "PROFILES_DIR", temp_dio_env["profiles_dir"]), \
             patch.object(config, "SESSION_FILE", temp_dio_env["session_file"]), \
             patch.object(config, "CONFIG_TOML", temp_dio_env["config_toml"]), \
             patch.object(config, "DIO_DIR", temp_dio_env["dio_dir"]), \
             patch.object(config, "LOG_FILE", temp_dio_env["log_file"]):

            urls = ["about:blank", "about:blank", "about:blank"]
            window = dio.DIOWindow(1, 3, urls, "test", 0)
            assert len(window._panels) == 3

            # Teardown de panel 0
            window.teardown_panel(0)
            assert len(window._panels) == 2

            # Los perfiles en disco deben existir todos
            assert (temp_dio_env["profiles_dir"] / "panel_0").exists()
            assert (temp_dio_env["profiles_dir"] / "panel_1").exists()
            assert (temp_dio_env["profiles_dir"] / "panel_2").exists()

            window.close()
