"""
D.I.O. — Divisor Integrado Operativo
Punto de entrada principal para ejecución como paquete (`python3 -m dio`).
"""

import argparse
import json
import os
import signal
import sys
from pathlib import Path

# ── H-06: Blindaje contra TOCTOU ─────────────────────────────────────────
if hasattr(os, "umask"):
    os.umask(0o077)

# ── Detección de flags tempranos ANTES de importar PyQt6 ──────────────────
# Flags de aceleración, modo oscuro, streaming y Wayland para Chromium
_LOW_MEMORY = "--low-memory" in sys.argv
if _LOW_MEMORY:
    _chromium_flags = os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "")
    _chromium_flags += " --disable-gpu"
    os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = _chromium_flags.strip()
    os.environ["QT_QUICK_BACKEND"] = "software"

_DARK_MODE = "--no-dark-mode" not in sys.argv
if _DARK_MODE:
    _chromium_flags = os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "")
    _chromium_flags += (
        " --force-dark-mode"
        " --enable-features=WebContentsForceDark"
        " --blink-settings=preferredColorScheme=1"
    )
    os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = _chromium_flags.strip()

_chromium_flags = os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "")
_chromium_flags += " --disable-blink-features=AutomationControlled"
_chromium_flags += (
    " --disable-background-timer-throttling"
    " --disable-backgrounding-occluded-windows"
    " --disable-renderer-backgrounding"
    " --disable-features=CalculateNativeWinOcclusion,IntensiveWakeUpThrottling"
)
os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = _chromium_flags.strip()

if os.environ.get("XDG_SESSION_TYPE") == "wayland":
    os.environ.setdefault("QT_QPA_PLATFORM", "wayland;xcb")

# ── Importaciones de Qt y D.I.O. ──────────────────────────────────────────
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication, QMessageBox

import dio.core.config as config
from dio.core.logger import logger, setup_logging
from dio.core.security import ensure_umask
from dio.ui.window import DIOWindow


def parse_args(default_grid: str, default_preset: str) -> argparse.Namespace:
    """
    Parser CLI: los flags actúan como overrides puntuales sobre lo que
    defina config.toml.
    """
    parser = argparse.ArgumentParser(
        prog="D.I.O.",
        description="Divisor Integrado Operativo — Grid de navegadores aislados",
    )
    parser.add_argument(
        "--grid",
        type=str,
        default=default_grid,
        help=f"Disposición del grid (ej: 2x2, 2x3). Default: {default_grid}",
    )
    parser.add_argument(
        "--preset",
        type=str,
        default=default_preset,
        help=f"Preset de URLs a cargar. Default: {default_preset}",
    )
    parser.add_argument(
        "--low-memory",
        action="store_true",
        default=False,
        help="Desactiva aceleración GPU de Chromium para reducir consumo de RAM y VRAM.",
    )
    parser.add_argument(
        "--monitor",
        type=int,
        default=0,
        help="Índice del monitor donde abrir D.I.O. (0=primario). Default: 0",
    )
    parser.add_argument(
        "--no-dark-mode",
        action="store_true",
        default=False,
        help="Desactiva el modo oscuro forzado (activo por defecto).",
    )
    parser.add_argument(
        "--no-adblock",
        action="store_true",
        default=False,
        help="Desactiva el bloqueador de anuncios nativo (activo por defecto).",
    )
    parser.add_argument(
        "--ask-download-location",
        action="store_true",
        default=False,
        help="Pide ubicación de guardado para cada descarga mediante diálogo nativo.",
    )
    return parser.parse_args()


def parse_grid(grid_str: str) -> tuple[int, int]:
    try:
        parts = grid_str.lower().split("x")
        rows, cols = int(parts[0]), int(parts[1])
        if rows < 1 or cols < 1:
            raise ValueError
        return (rows, cols)
    except (ValueError, IndexError):
        logger.error("Formato de grid inválido '%s'. Usa RxC (ej: 2x3).", grid_str)
        sys.exit(1)


def try_restore_session(app: QApplication) -> dict | None:
    if not config.SESSION_FILE.exists():
        return None
    try:
        data = json.loads(config.SESSION_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("session.json corrupto o ilegible: %s", exc)
        return None
    if not isinstance(data, dict) or "urls" not in data:
        return None

    reply = QMessageBox.question(
        None,
        "D.I.O. — Restaurar sesión",
        (
            f"Se encontró una sesión guardada con {len(data['urls'])} paneles.\n"
            "¿Restaurar la última sesión de trabajo?"
        ),
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.Yes,
    )

    if reply == QMessageBox.StandardButton.Yes:
        logger.info("Usuario aceptó restaurar sesión")
        return data

    logger.info("Usuario rechazó restaurar sesión")
    return None


def main() -> None:
    """Punto de entrada principal de D.I.O."""
    ensure_umask()
    setup_logging()
    logger.info("═" * 60)
    logger.info("D.I.O. iniciando…")

    # Inicializar configuración declarativa (~/.dio/config.toml) y migración legacy
    cfg = config.ensure_config()
    gen_cfg = cfg.get("general", {})

    cfg_default_grid = gen_cfg.get("default_grid", config.DEFAULT_GRID)
    cfg_default_preset = gen_cfg.get("default_preset", config.DEFAULT_PRESET)

    args = parse_args(default_grid=cfg_default_grid, default_preset=cfg_default_preset)

    # Overrides efectivos
    effective_dark_mode = False if args.no_dark_mode else gen_cfg.get("dark_mode", True)
    effective_adblock = False if args.no_adblock else gen_cfg.get("adblock", True)
    effective_low_memory = True if args.low_memory else not gen_cfg.get("hardware_acceleration", True)

    if effective_low_memory:
        logger.info("Modo bajo consumo activado: GPU desactivada")
    if effective_dark_mode:
        logger.info("Modo oscuro forzado activado")
    if effective_adblock:
        logger.info("AdBlock nativo activado")

    config.ensure_adblock_hosts()

    presets = config.load_presets()

    app = QApplication(sys.argv)
    app.setApplicationName("D.I.O.")
    app.setDesktopFileName("dio.desktop")
    icon_path = Path(__file__).resolve().parent.parent / "assets" / "icon.png"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))
    app.setStyleSheet(config.GLOBAL_DIALOG_STYLE)

    # Comportamiento según startup_behavior ("restore_last" o "load_preset")
    startup_behavior = gen_cfg.get("startup_behavior", "restore_last")
    session = None
    if startup_behavior == "restore_last":
        session = try_restore_session(app)

    if session is not None:
        urls = session["urls"]
        grid_str = session.get("grid", args.grid)
        rows, cols = parse_grid(grid_str)
        preset_name = session.get("preset", args.preset)
        panel_counter = session.get("panel_counter", len(urls))

        window = DIOWindow(rows, cols, urls, preset_name, args.monitor)
        window._panel_counter = panel_counter

        splitter_states = session.get("splitter_states")
        if splitter_states:
            window._restore_splitter_states(splitter_states)

        logger.info("Sesión restaurada: %d paneles", len(urls))
        for i, url in enumerate(urls):
            logger.info("  Panel %d: %s", i, url)

    else:
        if args.preset not in presets:
            logger.error(
                "Preset '%s' no encontrado. Disponibles: %s",
                args.preset, ", ".join(presets.keys()),
            )
            sys.exit(1)

        rows, cols = parse_grid(args.grid)
        urls = presets[args.preset]
        grid_size = rows * cols
        panel_urls = urls[:grid_size]

        window = DIOWindow(rows, cols, panel_urls, args.preset, args.monitor)

    screens = app.screens()
    monitor_idx = min(args.monitor, len(screens) - 1)
    if monitor_idx >= 0 and screens:
        target_screen = screens[monitor_idx]
        geo = target_screen.geometry()
        window.setGeometry(geo)
        logger.info(
            "Monitor %d seleccionado: %s (%dx%d)",
            monitor_idx, target_screen.name(), geo.width(), geo.height(),
        )

    window.showFullScreen()

    app.aboutToQuit.connect(window._save_session)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, lambda *_: app.quit())

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
