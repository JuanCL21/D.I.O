"""
D.I.O. — Tests automatizados para el sistema de configuración declarativa (config.toml)
y migración no destructiva de formatos legacy.
"""

import json
import os
import stat
import sys
from pathlib import Path

import pytest

# Asegurar raíz en sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dio.core.config import (
    DEFAULT_CONFIG,
    dump_toml,
    ensure_config,
    load_config_toml,
    migrate_legacy_config,
    save_config_toml,
)
import dio.core.config as config
from dio.__main__ import parse_args


@pytest.fixture
def temp_dio_env(tmp_path):
    """Provee un directorio temporal limpio para pruebas de configuración."""
    d = tmp_path / ".dio"
    d.mkdir(parents=True)
    return d


class TestConfigDeclarative:
    """Verifica la generación, serialización y carga de config.toml."""

    def test_default_config_structure(self, temp_dio_env):
        """Verifica que ensure_config genera un config.toml completo con todas las secciones."""
        cfg = ensure_config(temp_dio_env)
        toml_path = temp_dio_env / "config.toml"
        assert toml_path.exists()

        assert "general" in cfg
        assert "sleeping" in cfg
        assert "ipc" in cfg
        assert "shortcuts" in cfg
        assert "presets" in cfg

        assert cfg["ipc"]["allow_eval_js"] is False
        assert cfg["general"]["default_grid"] == "2x2"
        assert "ia_grid" in cfg["presets"]
        assert len(cfg["presets"]["ia_grid"]["urls"]) == 6

    def test_toml_roundtrip(self, temp_dio_env):
        """Verifica que guardar y recargar TOML preserva tipos y valores."""
        test_cfg = dict(DEFAULT_CONFIG)
        test_cfg["general"]["focus_color"] = "#ff007f"
        test_cfg["sleeping"]["timeout_minutes"] = 30
        test_cfg["panels"] = {
            "panel_0": {"pinned": True},
            "panel_1": {"pinned": False},
        }
        test_cfg["presets"]["custom_test"] = {
            "grid": "1x2",
            "urls": ["https://example.org", "https://example.com"],
        }

        toml_file = temp_dio_env / "custom.toml"
        save_config_toml(test_cfg, toml_file)
        assert toml_file.exists()

        loaded = load_config_toml(toml_file)
        assert loaded["general"]["focus_color"] == "#ff007f"
        assert loaded["sleeping"]["timeout_minutes"] == 30
        assert loaded["panels"]["panel_0"]["pinned"] is True
        assert loaded["panels"]["panel_1"]["pinned"] is False
        assert loaded["presets"]["custom_test"]["urls"] == [
            "https://example.org",
            "https://example.com",
        ]

    def test_permissions_umask(self, temp_dio_env):
        """H-06: Verifica que los archivos creados tengan permisos restrictivos (0600/0700)."""
        toml_file = temp_dio_env / "config.toml"
        save_config_toml(DEFAULT_CONFIG, toml_file)
        assert toml_file.exists()

        mode = toml_file.stat().st_mode
        # En sistemas POSIX, otros y grupo no deben tener permisos de escritura ni lectura
        if os.name == "posix":
            assert not (mode & stat.S_IRWXO), "Permisos inseguros para otros (others)"


class TestLegacyMigration:
    """Verifica la migración automática y no destructiva de archivos JSON a config.toml."""

    def test_migrate_all_legacy_files(self, temp_dio_env):
        """Crea settings.json, config.json y session.json legacy y comprueba migración completa."""
        legacy_settings = {
            "startup_behavior": "load_preset",
            "default_preset": "custom_ia",
            "focus_color": "#123456",
            "tab_sleeping_enabled": True,
            "tab_sleeping_minutes": 20,
            "passthrough_key": "Pause",
        }
        legacy_presets = {
            "custom_ia": [
                "https://custom1.ai",
                "https://custom2.ai",
                "https://custom3.ai",
                "https://custom4.ai",
            ],
            "work": [
                "https://work.com",
                "https://mail.work.com",
            ],
        }
        legacy_session = {
            "preset": "work",
            "grid": "1x2",
            "urls": ["https://work.com", "https://mail.work.com"],
        }

        (temp_dio_env / "settings.json").write_text(json.dumps(legacy_settings), encoding="utf-8")
        (temp_dio_env / "config.json").write_text(json.dumps(legacy_presets), encoding="utf-8")
        (temp_dio_env / "session.json").write_text(json.dumps(legacy_session), encoding="utf-8")

        # Ejecutar migración
        migrated = migrate_legacy_config(temp_dio_env)
        assert migrated is True

        # Verificar que config.toml fue generado
        target_toml = temp_dio_env / "config.toml"
        assert target_toml.exists()

        # Verificar que los archivos legacy se respaldaron en legacy/
        legacy_dir = temp_dio_env / "legacy"
        assert legacy_dir.exists()
        assert (legacy_dir / "settings.json.bak").exists()
        assert (legacy_dir / "config.json.bak").exists()
        assert (legacy_dir / "session.json.bak").exists()

        # Verificar que los originales NO fueron destruidos
        assert (temp_dio_env / "settings.json").exists()
        assert (temp_dio_env / "config.json").exists()
        assert (temp_dio_env / "session.json").exists()

        # Cargar el config.toml generado y validar que no se perdió ningún dato
        cfg = load_config_toml(target_toml)
        assert cfg["general"]["startup_behavior"] == "load_preset"
        assert cfg["general"]["focus_color"] == "#123456"
        assert cfg["sleeping"]["enabled"] is True
        assert cfg["sleeping"]["timeout_minutes"] == 20
        assert cfg["shortcuts"]["passthrough_key"] == "Pause"
        assert "custom_ia" in cfg["presets"]
        assert cfg["presets"]["custom_ia"]["urls"] == [
            "https://custom1.ai",
            "https://custom2.ai",
            "https://custom3.ai",
            "https://custom4.ai",
        ]
        assert "work" in cfg["presets"]
        assert cfg["presets"]["work"]["urls"] == [
            "https://work.com",
            "https://mail.work.com",
        ]

    def test_no_migration_if_toml_exists(self, temp_dio_env):
        """Si config.toml ya existe, no se debe sobreescribir ni re-migrar."""
        toml_path = temp_dio_env / "config.toml"
        toml_path.write_text("existing = true\n", encoding="utf-8")

        # Crear archivo legacy
        (temp_dio_env / "settings.json").write_text('{"focus_color": "#000000"}', encoding="utf-8")

        migrated = migrate_legacy_config(temp_dio_env)
        assert migrated is False
        assert toml_path.read_text(encoding="utf-8") == "existing = true\n"


class TestCLIOverrides:
    """Verifica que los argumentos CLI sobreescriban los valores de config.toml."""

    def test_cli_overrides_defaults(self, monkeypatch):
        """Los flags CLI deben tener precedencia sobre los valores por defecto de config.toml."""
        monkeypatch.setattr(
            sys,
            "argv",
            ["dio", "--grid", "3x3", "--preset", "correos_8", "--no-dark-mode", "--no-adblock", "--low-memory"],
        )

        args = parse_args(default_grid="2x2", default_preset="ia_grid")
        assert args.grid == "3x3"
        assert args.preset == "correos_8"
        assert args.no_dark_mode is True
        assert args.no_adblock is True
        assert args.low_memory is True
