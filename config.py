"""
D.I.O. — Divisor Integrado Operativo
Módulo de configuración: presets de URLs, rutas de perfiles y ajustes globales.
Los presets pueden migrar a ~/.dio/config.json para edición externa sin tocar código.
"""

import json
from pathlib import Path


# ---------------------------------------------------------------------------
# Directorio base de D.I.O. (toda la persistencia va aquí)
# ---------------------------------------------------------------------------
DIO_DIR: Path = Path.home() / ".dio"

# ---------------------------------------------------------------------------
# Directorio de perfiles persistentes (sesiones aisladas por panel)
# ---------------------------------------------------------------------------
PROFILES_DIR: Path = DIO_DIR / "profiles"

# ---------------------------------------------------------------------------
# Archivo de sesión (layout, URLs, estado de splitters)
# ---------------------------------------------------------------------------
SESSION_FILE: Path = DIO_DIR / "session.json"

# ---------------------------------------------------------------------------
# Archivo de configuración externa editable por el usuario
# ---------------------------------------------------------------------------
CONFIG_FILE: Path = DIO_DIR / "config.json"

# ---------------------------------------------------------------------------
# Archivo de log con rotación
# ---------------------------------------------------------------------------
LOG_FILE: Path = DIO_DIR / "dio.log"
LOG_MAX_BYTES: int = 5 * 1024 * 1024  # 5 MB
LOG_BACKUP_COUNT: int = 3

# ---------------------------------------------------------------------------
# Grid por defecto cuando no se pasa --grid
# ---------------------------------------------------------------------------
DEFAULT_GRID: str = "2x2"

# ---------------------------------------------------------------------------
# Preset activo por defecto cuando no se pasa --preset
# ---------------------------------------------------------------------------
DEFAULT_PRESET: str = "ia_grid"

# ---------------------------------------------------------------------------
# Espaciado en píxeles entre los paneles (handle width de los QSplitters).
# 0 = sin separación visible; subir a 2-4 para ver la línea divisoria.
# ---------------------------------------------------------------------------
PANEL_SPACING: int = 0

# ---------------------------------------------------------------------------
# User-Agent de Chrome de escritorio actual y realista.
# Necesario para que sitios como WhatsApp Web no degraden la experiencia.
# ---------------------------------------------------------------------------
USER_AGENT: str = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36"
)

# ---------------------------------------------------------------------------
# Permisos del navegador
# ---------------------------------------------------------------------------
# Auto-otorgar notificaciones de escritorio (necesario para WhatsApp Web).
AUTO_GRANT_NOTIFICATIONS: bool = True

# Auto-otorgar cámara y micrófono. Desactivado por defecto; activar si se
# necesitan videollamadas dentro de los paneles.
AUTO_GRANT_MEDIA: bool = False

# ---------------------------------------------------------------------------
# Presets de URLs por defecto (embebidos en el código).
# Se usan como semilla para generar ~/.dio/config.json la primera vez.
# Una vez generado ese JSON, el usuario puede editarlo libremente.
# ---------------------------------------------------------------------------
PRESETS: dict[str, list[str]] = {
    # 6 URLs — pensado para grid 2x3 con agentes de IA
    "ia_grid": [
        "https://gemini.google.com",
        "https://chatgpt.com",
        "https://claude.ai",
        "https://www.perplexity.ai",
        "https://copilot.microsoft.com",
        "https://grok.com",
    ],

    # 8 URLs — Gmail multi-cuenta (cada /u/N/ es una cuenta distinta)
    "correos_8": [
        "https://mail.google.com/mail/u/0/",
        "https://mail.google.com/mail/u/1/",
        "https://mail.google.com/mail/u/2/",
        "https://mail.google.com/mail/u/3/",
        "https://mail.google.com/mail/u/4/",
        "https://mail.google.com/mail/u/5/",
        "https://mail.google.com/mail/u/6/",
        "https://mail.google.com/mail/u/7/",
    ],

    # 4 URLs — WhatsApp Web (sesiones aisladas por perfil, cada una con su QR)
    "whatsapp_4": [
        "https://web.whatsapp.com",
        "https://web.whatsapp.com",
        "https://web.whatsapp.com",
        "https://web.whatsapp.com",
    ],
}


# ---------------------------------------------------------------------------
# Dominios de confianza para auto-conceder micrófono y cámara.
# Cualquier dominio fuera de esta lista mostrará un diálogo de confirmación.
# ---------------------------------------------------------------------------
TRUSTED_MEDIA_DOMAINS: list[str] = [
    "web.whatsapp.com",
    "gemini.google.com",
    "chatgpt.com",
    "claude.ai",
    "www.perplexity.ai",
    "perplexity.ai",
    "copilot.microsoft.com",
    "grok.com",
    "mail.google.com",
    "meet.google.com",
    "outlook.live.com",
    "teams.microsoft.com",
    "discord.com",
    "zoom.us",
]

# ---------------------------------------------------------------------------
# Carpeta base donde se guardan las descargas de D.I.O.
# Se crea automáticamente si no existe.
# ---------------------------------------------------------------------------
DOWNLOADS_DIR: Path = DIO_DIR / "downloads"

# ---------------------------------------------------------------------------
# Comportamiento al hacer clic en un enlace con target="_blank".
# "same_panel"     → navega en el mismo panel que originó el clic (default).
# "system_browser" → delega al navegador del sistema operativo.
# ---------------------------------------------------------------------------
EXTERNAL_LINK_BEHAVIOR: str = "same_panel"

# ---------------------------------------------------------------------------
# Modo oscuro forzado vía flags de Chromium + CSS de respaldo.
# Se puede desactivar con --no-dark-mode en la línea de comandos.
# ---------------------------------------------------------------------------
DARK_MODE_ENABLED: bool = True

# ---------------------------------------------------------------------------
# Bloqueador de anuncios y trackers nativo.
# Se puede desactivar con --no-adblock si algún sitio se rompe.
# ---------------------------------------------------------------------------
ADBLOCK_ENABLED: bool = True
ADBLOCK_HOSTS_FILE: Path = DIO_DIR / "adblock_hosts.txt"


def load_presets() -> dict[str, list[str]]:
    """
    Carga los presets desde ~/.dio/config.json si existe.
    Si no existe, lo genera con los PRESETS por defecto y retorna esos mismos.
    Esto permite al usuario editar el JSON a mano sin tocar código Python.
    """
    DIO_DIR.mkdir(parents=True, exist_ok=True)

    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data:
                return data
        except (json.JSONDecodeError, OSError):
            pass  # Si el JSON está corrupto, usar los defaults y recrear

    # Generar el archivo por primera vez (o recrear si estaba corrupto)
    try:
        CONFIG_FILE.write_text(
            json.dumps(PRESETS, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError:
        pass  # Si no se puede escribir, usar los embebidos sin error fatal

    return dict(PRESETS)


SETTINGS_FILE: Path = DIO_DIR / "settings.json"

DEFAULT_SETTINGS: dict = {
    "startup_behavior": "restore_last",  # "restore_last" o "load_preset"
    "default_preset": "ia_grid",
    "hardware_acceleration": True,
    "tab_sleeping_enabled": False,
    "tab_sleeping_minutes": 15,
    "downloads_dir": str(Path.home() / "Downloads" / "DIO"),
    "ask_download_location": False,
    "gaps": 0,
    "focus_color": "#89b4fa",
    "overlay_opacity": 75,
    "passthrough_key": "ScrollLock",
    "invocation_key": "F1",
    "devtools_enabled": False,
    "disabled_shortcuts": [],
    "custom_keybindings": {},
    "custom_user_agents": {},
    "custom_css_rules": {},
}


def load_settings() -> dict:
    """Carga la configuración persistente del usuario desde ~/.dio/settings.json."""
    DIO_DIR.mkdir(parents=True, exist_ok=True)
    if SETTINGS_FILE.exists():
        try:
            data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                merged = dict(DEFAULT_SETTINGS)
                merged.update(data)
                return merged
        except (json.JSONDecodeError, OSError):
            pass

    try:
        SETTINGS_FILE.write_text(
            json.dumps(DEFAULT_SETTINGS, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError:
        pass

    return dict(DEFAULT_SETTINGS)


def save_settings(settings_dict: dict) -> None:
    """Guarda la configuración del usuario en ~/.dio/settings.json."""
    DIO_DIR.mkdir(parents=True, exist_ok=True)
    try:
        SETTINGS_FILE.write_text(
            json.dumps(settings_dict, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError:
        pass


def ensure_adblock_hosts() -> None:
    """
    Copia el archivo de hosts de adblock por defecto a ~/.dio/ si no existe.
    El usuario puede editar ~/.dio/adblock_hosts.txt para personalizar la lista.
    """
    if ADBLOCK_HOSTS_FILE.exists():
        return

    # Ruta del archivo embebido junto al código fuente
    import os as _os
    src = Path(_os.path.dirname(_os.path.abspath(__file__))) / "config" / "adblock_hosts.txt"
    if src.exists():
        try:
            DIO_DIR.mkdir(parents=True, exist_ok=True)
            ADBLOCK_HOSTS_FILE.write_text(
                src.read_text(encoding="utf-8"), encoding="utf-8"
            )
        except OSError:
            pass

