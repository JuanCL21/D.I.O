#!/usr/bin/env python3
"""
D.I.O. — Divisor Integrado Operativo
Lanzador de compatibilidad hacia atrás para scripts existentes y accesos directos.
Redirige la ejecución a la arquitectura modular del paquete `dio`.
"""

import sys
from pathlib import Path

# Asegurar que el directorio raíz del proyecto está en sys.path
_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from dio.core.security import ensure_umask

# H-06: Umask restrictivo desde el arranque
ensure_umask()

# Re-exportar símbolos públicos para compatibilidad hacia atrás
from dio.core.config import *  # noqa: F401, F403
from dio.core.logger import logger, setup_logging
from dio.browser.interceptor import AdBlockInterceptor
from dio.browser.page import DIOPage
from dio.browser.scripts import (
    make_anti_detection_script,
    make_dark_mode_script,
    _make_anti_detection_script,
    _make_dark_mode_script,
)
from dio.ui.widgets import (
    LoadingOverlay,
    MutedIndicator,
    SeamlessSplitter,
    SeamlessSplitterHandle,
    ToastNotification,
)
from dio.ui.dialogs import (
    GridChooserDialog,
    KeySequenceRecorderDialog,
    OmniSearchDialog,
    SettingsOverlayDialog,
    resolve_query_or_url,
)
from dio.ui.window import DIOWindow
from dio.__main__ import main, parse_args, parse_grid, try_restore_session

if __name__ == "__main__":
    main()
