"""
Tests para Formato de Preset Compartible (Roadmap 4.2 / Paso 7).
Verifica:
- Exportacion de presets a archivo .dio.tar.gz con manifest y adapters
- Importacion en entorno limpio y extraccion de adapters
- Preservacion y respaldo de config.toml con overwrite=False y overwrite=True
- Proteccion estricta contra Path Traversal / ZipSlip
- Subcomandos de export-preset e import-preset en CLI
"""

import json
import tarfile
from pathlib import Path
from unittest.mock import patch

import pytest

from dio.core import config
from dio.presets.package import (
    MANIFEST_FILENAME,
    PACKAGE_EXTENSION,
    PresetPackageError,
    export_preset,
    import_preset,
)


@pytest.fixture
def sample_preset_env(tmp_path):
    source_dir = tmp_path / "source_dio"
    source_dir.mkdir(parents=True)
    adapters_dir = source_dir / "adapters"
    adapters_dir.mkdir(parents=True)

    # Crear config.toml
    config_file = source_dir / "config.toml"
    config_file.write_text(
        '[general]\ndefault_rows = 2\ndefault_cols = 3\n\n[shortcuts]\nworkspace_prefix = "Ctrl+Alt"\n',
        encoding="utf-8",
    )

    # Crear adapter personalizado
    custom_adapter = {
        "name": "custom_agent",
        "match_patterns": ["agent.local"],
        "selectors": {
            "working": ".is-busy",
            "blocked": ".needs-auth",
            "done": ".finished",
        },
        "debounce_ms": 500,
    }
    (adapters_dir / "custom_agent.json").write_text(
        json.dumps(custom_adapter, indent=2),
        encoding="utf-8",
    )

    target_dir = tmp_path / "target_dio"
    target_dir.mkdir(parents=True)

    return {
        "source_dir": source_dir,
        "target_dir": target_dir,
        "output_pkg": tmp_path / "exported_preset.dio.tar.gz",
    }


def test_export_preset_creates_valid_tarball(sample_preset_env):
    out_pkg = export_preset(
        output_path=sample_preset_env["output_pkg"],
        name="mi_preset_ia",
        description="Preset para investigacion de IA",
        source_dio_dir=sample_preset_env["source_dir"],
        include_adapters=True,
    )

    assert out_pkg.exists()
    assert tarfile.is_tarfile(out_pkg)

    with tarfile.open(out_pkg, "r:gz") as tar:
        names = tar.getnames()
        assert MANIFEST_FILENAME in names
        assert "config.toml" in names
        assert "adapters/custom_agent.json" in names

        # Validar manifest
        manifest_f = tar.extractfile(MANIFEST_FILENAME)
        manifest_data = json.loads(manifest_f.read().decode("utf-8"))
        assert manifest_data["name"] == "mi_preset_ia"
        assert manifest_data["description"] == "Preset para investigacion de IA"
        assert manifest_data["schema_version"] == "1.0"
        assert "custom_agent.json" in manifest_data["adapters"]


def test_import_preset_clean_environment(sample_preset_env):
    out_pkg = export_preset(
        output_path=sample_preset_env["output_pkg"],
        name="preset_limpio",
        source_dio_dir=sample_preset_env["source_dir"],
    )

    target_dir = sample_preset_env["target_dir"]
    result = import_preset(out_pkg, target_dio_dir=target_dir)

    assert result["success"] is True
    assert result["config_status"] == "created"
    assert (target_dir / "config.toml").exists()
    assert (target_dir / "adapters" / "custom_agent.json").exists()
    assert "custom_agent.json" in result["imported_adapters"]

    # Verificar que el contenido de config.toml se importo correctamente
    content = (target_dir / "config.toml").read_text(encoding="utf-8")
    assert "default_rows = 2" in content


def test_import_preset_preserves_existing_config_unless_overwrite(sample_preset_env):
    out_pkg = export_preset(
        output_path=sample_preset_env["output_pkg"],
        source_dio_dir=sample_preset_env["source_dir"],
    )

    target_dir = sample_preset_env["target_dir"]
    existing_config = target_dir / "config.toml"
    existing_config.write_text("[general]\ndefault_rows = 4\n", encoding="utf-8")

    # Importar sin overwrite: debe omitir config.toml
    res_skip = import_preset(out_pkg, target_dio_dir=target_dir, overwrite=False)
    assert res_skip["config_status"] == "skipped_existing"
    assert "default_rows = 4" in existing_config.read_text(encoding="utf-8")

    # Importar con overwrite: debe respaldar config.toml.bak y sobrescribir
    res_overwrite = import_preset(out_pkg, target_dio_dir=target_dir, overwrite=True)
    assert res_overwrite["config_status"] == "overwritten"
    assert (target_dir / "config.toml.bak").exists()
    assert "default_rows = 4" in (target_dir / "config.toml.bak").read_text(encoding="utf-8")
    assert "default_rows = 2" in (target_dir / "config.toml").read_text(encoding="utf-8")


def test_path_traversal_zipslip_rejected(tmp_path):
    malicious_pkg = tmp_path / "malicious.dio.tar.gz"

    with tarfile.open(malicious_pkg, "w:gz") as tar:
        # Miembro manifest legitimo
        manifest = tmp_path / MANIFEST_FILENAME
        manifest.write_text(json.dumps({"name": "evil", "schema_version": "1.0"}), encoding="utf-8")
        tar.add(manifest, arcname=MANIFEST_FILENAME)

        # Miembro malicioso intentando escribir fuera del directorio
        evil_file = tmp_path / "evil.txt"
        evil_file.write_text("pwned", encoding="utf-8")
        tar.add(evil_file, arcname="../outside.txt")

    target_dir = tmp_path / "safe_target"
    target_dir.mkdir()

    with pytest.raises(PresetPackageError, match="Ruta no segura"):
        import_preset(malicious_pkg, target_dio_dir=target_dir)


def test_cli_export_and_import_commands(sample_preset_env, monkeypatch, capsys):
    from dio.cli import main

    out_file = str(sample_preset_env["source_dir"] / "test_cli.dio.tar.gz")

    with patch("dio.core.config.DIO_DIR", sample_preset_env["source_dir"]):
        # Test export
        monkeypatch.setattr(
            "sys.argv",
            ["dio-cli", "export-preset", "--output", out_file, "--name", "cli_test"],
        )
        main()
        captured = capsys.readouterr()
        assert "[OK] Preset exportado exitosamente" in captured.out
        assert Path(out_file).exists()

        # Test import
        target_dir = sample_preset_env["target_dir"]
        with patch("dio.core.config.DIO_DIR", target_dir):
            monkeypatch.setattr(
                "sys.argv",
                ["dio-cli", "import-preset", out_file, "--overwrite"],
            )
            main()
            captured_import = capsys.readouterr()
            assert "[OK] Preset 'cli_test' importado exitosamente" in captured_import.out
            assert (target_dir / "config.toml").exists()
