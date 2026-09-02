"""
D.I.O. — Tests automatizados del grid, perfiles y persistencia de sesión.
Usa "about:blank" como URL para no depender de red real.
"""

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

# Asegurar que el directorio raíz del proyecto está en el path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PyQt6.QtWidgets import QApplication

# Fixture de QApplication — una sola instancia para todos los tests
_app = None


@pytest.fixture(scope="session", autouse=True)
def qapp():
    """Crea una única QApplication para toda la sesión de tests."""
    global _app
    if _app is None:
        _app = QApplication.instance() or QApplication(sys.argv)
    return _app


@pytest.fixture
def temp_dio_dir(tmp_path):
    """Provee un directorio temporal para ~/.dio/ durante los tests."""
    dio_dir = tmp_path / ".dio"
    profiles_dir = dio_dir / "profiles"
    profiles_dir.mkdir(parents=True)
    session_file = dio_dir / "session.json"
    config_file = dio_dir / "config.json"
    log_file = dio_dir / "dio.log"
    return {
        "dio_dir": dio_dir,
        "profiles_dir": profiles_dir,
        "session_file": session_file,
        "config_file": config_file,
        "log_file": log_file,
    }


def _make_window(rows, cols, urls, temp_dio_dir_fixture):
    """Helper: crea un DIOWindow con rutas redirigidas al directorio temporal."""
    import config
    import dio

    # Patchear las rutas de config para usar el directorio temporal
    with patch.object(config, "PROFILES_DIR", temp_dio_dir_fixture["profiles_dir"]), \
         patch.object(config, "SESSION_FILE", temp_dio_dir_fixture["session_file"]), \
         patch.object(config, "DIO_DIR", temp_dio_dir_fixture["dio_dir"]), \
         patch.object(config, "LOG_FILE", temp_dio_dir_fixture["log_file"]):
        window = dio.DIOWindow(rows, cols, urls, "test_preset", 0)
    return window


# ── Test 1: número de paneles coincide con el grid ───────────────────────

class TestPanelCount:
    """Verifica que se crean el número correcto de paneles por grid."""

    def test_panel_count_2x2(self, qapp, temp_dio_dir):
        """Grid 2x2 debe crear 4 paneles."""
        urls = ["about:blank"] * 4
        window = _make_window(2, 2, urls, temp_dio_dir)
        assert len(window._panels) == 4
        window.close()

    def test_panel_count_2x3(self, qapp, temp_dio_dir):
        """Grid 2x3 debe crear 6 paneles."""
        urls = ["about:blank"] * 6
        window = _make_window(2, 3, urls, temp_dio_dir)
        assert len(window._panels) == 6
        window.close()

    def test_panel_count_partial(self, qapp, temp_dio_dir):
        """Si se pasan menos URLs que celdas del grid, se crean solo las URLs dadas."""
        urls = ["about:blank"] * 3
        window = _make_window(2, 2, urls, temp_dio_dir)
        assert len(window._panels) == 3
        window.close()


# ── Test 2: cada panel tiene un profile path único ───────────────────────

class TestUniqueProfiles:
    """Verifica que ningún panel comparte carpeta de perfil con otro."""

    def test_unique_profile_paths_4(self, qapp, temp_dio_dir):
        """4 paneles deben tener 4 storage paths distintos."""
        urls = ["about:blank"] * 4
        window = _make_window(2, 2, urls, temp_dio_dir)

        storage_paths = set()
        for profile in window._profiles:
            path = profile.persistentStoragePath()
            assert path not in storage_paths, (
                f"Storage path duplicado: {path}"
            )
            storage_paths.add(path)

        assert len(storage_paths) == 4
        window.close()

    def test_unique_profile_paths_6(self, qapp, temp_dio_dir):
        """6 paneles deben tener 6 storage paths distintos."""
        urls = ["about:blank"] * 6
        window = _make_window(2, 3, urls, temp_dio_dir)

        storage_paths = set()
        for profile in window._profiles:
            path = profile.persistentStoragePath()
            assert path not in storage_paths, (
                f"Storage path duplicado: {path}"
            )
            storage_paths.add(path)

        assert len(storage_paths) == 6
        window.close()


# ── Test 3: guardar y cargar session.json ─────────────────────────────────

class TestSessionPersistence:
    """Verifica que guardar y cargar session.json reproduce el mismo estado."""

    def test_session_roundtrip(self, qapp, temp_dio_dir):
        """Guardar sesión y verificar que el JSON contiene las URLs correctas."""
        import config

        urls = [
            "about:blank",
            "https://example.com",
            "https://test.org",
            "about:blank",
        ]

        with patch.object(config, "PROFILES_DIR", temp_dio_dir["profiles_dir"]), \
             patch.object(config, "SESSION_FILE", temp_dio_dir["session_file"]), \
             patch.object(config, "DIO_DIR", temp_dio_dir["dio_dir"]), \
             patch.object(config, "LOG_FILE", temp_dio_dir["log_file"]):

            import dio
            window = dio.DIOWindow(2, 2, urls, "test_preset", 0)

            # Guardar sesión
            window._save_session()

            # Verificar que session.json existe
            assert temp_dio_dir["session_file"].exists()

            # Leer y verificar contenido
            data = json.loads(
                temp_dio_dir["session_file"].read_text(encoding="utf-8")
            )

            assert data["preset"] == "test_preset"
            assert data["grid"] == "2x2"
            assert len(data["urls"]) == 4
            assert "splitter_states" in data
            assert "root" in data["splitter_states"]

            window.close()

    def test_session_url_count_matches(self, qapp, temp_dio_dir):
        """El número de URLs en session.json debe coincidir con los paneles."""
        import config

        urls = ["about:blank"] * 6

        with patch.object(config, "PROFILES_DIR", temp_dio_dir["profiles_dir"]), \
             patch.object(config, "SESSION_FILE", temp_dio_dir["session_file"]), \
             patch.object(config, "DIO_DIR", temp_dio_dir["dio_dir"]), \
             patch.object(config, "LOG_FILE", temp_dio_dir["log_file"]):

            import dio
            window = dio.DIOWindow(2, 3, urls, "ia_grid", 0)
            window._save_session()

            data = json.loads(
                temp_dio_dir["session_file"].read_text(encoding="utf-8")
            )
            assert len(data["urls"]) == len(window._panels) == 6

            window.close()
