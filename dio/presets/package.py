"""
D.I.O. — Paquete de gestion de presets compartibles (Roadmap 4.2 / Paso 7).
Permite exportar e importar configuraciones completas (config.toml + adapters)
en un formato empaquetado seguro (.dio.tar.gz) para compartir con otros usuarios.
"""

import json
import os
import shutil
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import dio
from dio.core import config
from dio.core.logger import logger

MANIFEST_FILENAME = "preset_manifest.json"
PACKAGE_EXTENSION = ".dio.tar.gz"


class PresetPackageError(Exception):
    """Excepcion base para errores de empaquetado o importacion de presets."""
    pass


def export_preset(
    output_path: Path | str,
    name: str = "custom_preset",
    description: str = "",
    source_dio_dir: Optional[Path] = None,
    include_adapters: bool = True,
) -> Path:
    """
    Empaqueta config.toml y la carpeta de adapters de usuario en un archivo .dio.tar.gz.
    """
    base_dir = Path(source_dio_dir) if source_dio_dir else config.DIO_DIR
    out_file = Path(output_path)

    # Asegurar extension .dio.tar.gz o .tar.gz
    out_str = str(out_file)
    if not (out_str.endswith(".dio.tar.gz") or out_str.endswith(".tar.gz")):
        out_file = Path(f"{out_str}.dio.tar.gz")

    out_file.parent.mkdir(parents=True, exist_ok=True)

    config_path = base_dir / "config.toml"
    adapters_dir = base_dir / "adapters"

    # Recopilar adapters
    adapter_files: list[Path] = []
    if include_adapters and adapters_dir.exists() and adapters_dir.is_dir():
        adapter_files = sorted(list(adapters_dir.glob("*.json")))

    manifest: dict[str, Any] = {
        "schema_version": "1.0",
        "name": name,
        "description": description,
        "dio_version": dio.__version__,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "has_config": config_path.exists(),
        "adapters": [p.name for p in adapter_files],
    }

    with tempfile.TemporaryDirectory(prefix="dio_preset_export_") as tmp_dir:
        staging_dir = Path(tmp_dir)
        manifest_file = staging_dir / MANIFEST_FILENAME
        manifest_file.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

        with tarfile.open(out_file, "w:gz") as tar:
            # 1. Agregar manifest
            tar.add(manifest_file, arcname=MANIFEST_FILENAME)

            # 2. Agregar config.toml si existe
            if config_path.exists():
                tar.add(config_path, arcname="config.toml")
            else:
                # Si no existe, volcar configuracion por defecto
                default_toml = staging_dir / "config.toml"
                default_toml.write_text(config.save_config_toml(config.DEFAULT_CONFIG), encoding="utf-8")
                tar.add(default_toml, arcname="config.toml")

            # 3. Agregar adapters
            for af in adapter_files:
                tar.add(af, arcname=f"adapters/{af.name}")

    logger.info("Preset exportado exitosamente a '%s' (adapters=%d)", out_file, len(adapter_files))
    return out_file


def _validate_safe_path(base_dir: Path, target_path: Path) -> bool:
    """Evita ataques de Path Traversal asegurando que el destino este dentro del directorio base."""
    try:
        resolved_base = base_dir.resolve()
        resolved_target = target_path.resolve()
        return resolved_target.is_relative_to(resolved_base)
    except Exception:
        return False


def import_preset(
    archive_path: Path | str,
    target_dio_dir: Optional[Path] = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    """
    Importa un paquete de preset (.dio.tar.gz) en el directorio ~/.dio/.
    - Extrae adapters a ~/.dio/adapters/
    - Actualiza o respalda config.toml segun el parametro overwrite
    """
    archive = Path(archive_path)
    if not archive.exists():
        raise PresetPackageError(f"Archivo de preset no encontrado: {archive}")

    target_dir = Path(target_dio_dir) if target_dio_dir else config.DIO_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    adapters_dest_dir = target_dir / "adapters"
    adapters_dest_dir.mkdir(parents=True, exist_ok=True)

    if not tarfile.is_tarfile(archive):
        raise PresetPackageError(f"El archivo '{archive}' no es un tarball valido.")

    with tempfile.TemporaryDirectory(prefix="dio_preset_import_") as tmp_dir:
        extract_dir = Path(tmp_dir)

        try:
            with tarfile.open(archive, "r:gz") as tar:
                # Validar seguridad contra ZipSlip / Path Traversal
                for member in tar.getmembers():
                    dest_file = extract_dir / member.name
                    if not _validate_safe_path(extract_dir, dest_file):
                        raise PresetPackageError(f"Ruta no segura detectada en archivo de preset: {member.name}")
                if hasattr(tarfile, "data_filter"):
                    tar.extractall(extract_dir, filter="data")
                else:
                    tar.extractall(extract_dir)
        except tarfile.TarError as exc:
            raise PresetPackageError(f"Error al descomprimir preset: {exc}") from exc

        # 1. Leer y validar manifest
        manifest_path = extract_dir / MANIFEST_FILENAME
        if not manifest_path.exists():
            raise PresetPackageError("El paquete no contiene preset_manifest.json valido.")

        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise PresetPackageError(f"Error al parsear preset_manifest.json: {exc}") from exc

        # 2. Gestionar config.toml
        config_src = extract_dir / "config.toml"
        config_dest = target_dir / "config.toml"
        config_status = "unchanged"

        if config_src.exists():
            if not config_dest.exists():
                shutil.copy2(config_src, config_dest)
                config_status = "created"
            elif overwrite:
                bak_path = target_dir / "config.toml.bak"
                shutil.copy2(config_dest, bak_path)
                shutil.copy2(config_src, config_dest)
                config_status = "overwritten"
            else:
                config_status = "skipped_existing"

        # 3. Gestionar adapters
        imported_adapters: list[str] = []
        adapters_src_dir = extract_dir / "adapters"
        if adapters_src_dir.exists() and adapters_src_dir.is_dir():
            for af in adapters_src_dir.glob("*.json"):
                dest_adapter = adapters_dest_dir / af.name
                if dest_adapter.exists() and not overwrite:
                    continue
                shutil.copy2(af, dest_adapter)
                imported_adapters.append(af.name)

        logger.info(
            "Preset '%s' importado en '%s'. Config: %s, Adapters importados: %d",
            manifest.get("name", "unknown"),
            target_dir,
            config_status,
            len(imported_adapters),
        )

        return {
            "success": True,
            "manifest": manifest,
            "imported_adapters": imported_adapters,
            "config_status": config_status,
            "target_dir": str(target_dir),
        }
