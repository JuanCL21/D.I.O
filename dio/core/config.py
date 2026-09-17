"""
D.I.O. — Divisor Integrado Operativo
Módulo de configuración declarativa centralizada (~/.dio/config.toml).
Gestiona presets, propiedades de paneles (pinned), atajos, flags de inicio
y migración automática no destructiva desde formatos legacy (JSON).
"""

import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:
    try:
        import tomli as tomllib  # type: ignore
    except ImportError:
        import tomllib  # type: ignore

from dio.core.security import ensure_umask, secure_directory

# ---------------------------------------------------------------------------
# Directorio base de D.I.O. (toda la persistencia reside aquí)
# ---------------------------------------------------------------------------
DIO_DIR: Path = Path.home() / ".dio"

# Directorio de perfiles persistentes (sesiones aisladas por panel)
PROFILES_DIR: Path = DIO_DIR / "profiles"

# Archivo de configuración declarativa unificada (Paso 1)
CONFIG_TOML: Path = DIO_DIR / "config.toml"

# Archivo de estado de sesión (layout actual, geometrías, URLs vivas)
SESSION_FILE: Path = DIO_DIR / "session.json"

# Directorio para respaldar formatos legacy migrados
LEGACY_DIR: Path = DIO_DIR / "legacy"

# Archivos de configuración legacy (compatibilidad retroactiva)
CONFIG_FILE: Path = DIO_DIR / "config.json"
SETTINGS_FILE: Path = DIO_DIR / "settings.json"

# Archivo de log con rotación
LOG_FILE: Path = DIO_DIR / "dio.log"
LOG_MAX_BYTES: int = 5 * 1024 * 1024  # 5 MB
LOG_BACKUP_COUNT: int = 3

# Socket de control IPC (Paso 4)
SOCKET_FILE: Path = DIO_DIR / "dio.sock"

# Defaults globales
DEFAULT_GRID: str = "2x2"
DEFAULT_PRESET: str = "ia_grid"
PANEL_SPACING: int = 0

USER_AGENT: str = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36"
)

AUTO_GRANT_NOTIFICATIONS: bool = True
AUTO_GRANT_MEDIA: bool = False

PRESETS: dict[str, list[str]] = {
    "ia_grid": [
        "https://gemini.google.com",
        "https://chatgpt.com",
        "https://claude.ai",
        "https://www.perplexity.ai",
        "https://copilot.microsoft.com",
        "https://grok.com",
    ],
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
    "whatsapp_4": [
        "https://web.whatsapp.com",
        "https://web.whatsapp.com",
        "https://web.whatsapp.com",
        "https://web.whatsapp.com",
    ],
}

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

DOWNLOADS_DIR: Path = DIO_DIR / "downloads"
EXTERNAL_LINK_BEHAVIOR: str = "same_panel"
DARK_MODE_ENABLED: bool = True
ADBLOCK_ENABLED: bool = True
ADBLOCK_HOSTS_FILE: Path = DIO_DIR / "adblock_hosts.txt"

DEFAULT_SETTINGS: dict[str, Any] = {
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

GLOBAL_DIALOG_STYLE: str = """
QDialog, QMessageBox {
    background-color: #181825;
    color: #cdd6f4;
    font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
}
QMessageBox QLabel {
    color: #ffffff;
    font-size: 13px;
}
QMessageBox QPushButton, QDialogButtonBox QPushButton {
    background-color: #313244;
    color: #ffffff;
    font-size: 13px;
    padding: 7px 18px;
    border-radius: 6px;
    border: 1px solid #45475a;
}
QMessageBox QPushButton:hover, QDialogButtonBox QPushButton:hover {
    background-color: #45475a;
    border-color: #89b4fa;
    color: #89b4fa;
}
QMessageBox QPushButton:default {
    background-color: #89b4fa;
    color: #11111b;
    font-weight: bold;
    border: none;
}
QMessageBox QPushButton:default:hover {
    background-color: #b4befe;
}
QSplitter {
    spacing: 0px;
    margin: 0px;
    padding: 0px;
    border: none;
    background: transparent;
}
QSplitter::handle {
    background: transparent;
    border: none;
    margin: 0px;
    padding: 0px;
    width: 0px;
    height: 0px;
}
"""

DEFAULT_CONFIG: dict[str, Any] = {
    "general": {
        "startup_behavior": "restore_last",
        "default_grid": "2x2",
        "default_preset": "ia_grid",
        "hardware_acceleration": True,
        "dark_mode": True,
        "adblock": True,
        "downloads_dir": str(Path.home() / "Downloads" / "DIO"),
        "ask_download_location": False,
        "gaps": 0,
        "focus_color": "#89b4fa",
        "overlay_opacity": 75,
    },
    "sleeping": {
        "enabled": False,
        "timeout_minutes": 15,
    },
    "recovery": {
        "max_retries": 3,
        "backoff_base_s": 1.0,
        "backoff_max_s": 16.0,
    },
    "ipc": {
        "allow_eval_js": False,
        "socket_path": str(DIO_DIR / "dio.sock"),
    },
    "shortcuts": {
        "passthrough_key": "ScrollLock",
        "invocation_key": "F1",
        "disabled_shortcuts": [],
        "custom_keybindings": {},
    },
    "panels": {
        # Configuración por panel, por ejemplo:
        # "panel_0": {"pinned": False}
    },
    "presets": {
        "ia_grid": {
            "grid": "2x3",
            "urls": [
                "https://gemini.google.com",
                "https://chatgpt.com",
                "https://claude.ai",
                "https://www.perplexity.ai",
                "https://copilot.microsoft.com",
                "https://grok.com",
            ],
        },
        "correos_8": {
            "grid": "2x4",
            "urls": [
                "https://mail.google.com/mail/u/0/",
                "https://mail.google.com/mail/u/1/",
                "https://mail.google.com/mail/u/2/",
                "https://mail.google.com/mail/u/3/",
                "https://mail.google.com/mail/u/4/",
                "https://mail.google.com/mail/u/5/",
                "https://mail.google.com/mail/u/6/",
                "https://mail.google.com/mail/u/7/",
            ],
        },
        "whatsapp_4": {
            "grid": "2x2",
            "urls": [
                "https://web.whatsapp.com",
                "https://web.whatsapp.com",
                "https://web.whatsapp.com",
                "https://web.whatsapp.com",
            ],
        },
    },
}


# ── Serializador TOML nativo (sin dependencias externas) ─────────────────────

def _format_toml_value(val: Any) -> str:
    if isinstance(val, bool):
        return "true" if val else "false"
    if isinstance(val, (int, float)):
        return str(val)
    if isinstance(val, str):
        escaped = val.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
        return f'"{escaped}"'
    if isinstance(val, list):
        items = [_format_toml_value(item) for item in val]
        if any("\n" in item or len(items) > 3 for item in items):
            inner = ",\n    ".join(items)
            return f"[\n    {inner},\n]"
        return f"[{', '.join(items)}]"
    if isinstance(val, dict):
        pairs = [f"{k} = {_format_toml_value(v)}" for k, v in val.items()]
        return f"{{ {', '.join(pairs)} }}"
    return f'"{str(val)}"'


def dump_toml(data: dict[str, Any]) -> str:
    """
    Serializa un diccionario en formato TOML estructurado y legible.
    Separa secciones principales y subtablas (ej. [presets.<nombre>]).
    """
    lines: list[str] = [
        "# ===========================================================================",
        "# D.I.O. — Divisor Integrado Operativo | Configuración Declarativa",
        "# Generado automáticamente. Puede editarse manualmente.",
        "# ===========================================================================",
        "",
    ]

    # 1. Claves escalares de nivel superior (si existieran)
    top_scalars = {k: v for k, v in data.items() if not isinstance(v, dict)}
    for k, v in top_scalars.items():
        lines.append(f"{k} = {_format_toml_value(v)}")
    if top_scalars:
        lines.append("")

    # 2. Secciones estándar (primer nivel de dicts)
    for section, content in data.items():
        if not isinstance(content, dict):
            continue

        # Verificar si es una sección con sub-tablas (como presets o panels)
        sub_tables = {k: v for k, v in content.items() if isinstance(v, dict)}
        scalars = {k: v for k, v in content.items() if not isinstance(v, dict)}

        lines.append(f"[{section}]")
        for k, v in scalars.items():
            lines.append(f"{k} = {_format_toml_value(v)}")
        lines.append("")

        for sub_name, sub_content in sub_tables.items():
            lines.append(f"[{section}.{sub_name}]")
            for sk, sv in sub_content.items():
                lines.append(f"{sk} = {_format_toml_value(sv)}")
            lines.append("")

    return "\n".join(lines).strip() + "\n"


# ── Carga y guardado de config.toml ─────────────────────────────────────────

def load_config_toml(path: Path | None = None) -> dict[str, Any]:
    """
    Carga y valida config.toml. Si faltan claves, se complementan con DEFAULT_CONFIG.
    """
    target = path or CONFIG_TOML
    if not target.exists():
        return dict(DEFAULT_CONFIG)

    try:
        with open(target, "rb") as f:
            user_data = tomllib.load(f)
    except Exception:
        return dict(DEFAULT_CONFIG)

    # Mezcla profunda con DEFAULT_CONFIG
    merged: dict[str, Any] = {}
    for sec, sec_vals in DEFAULT_CONFIG.items():
        if isinstance(sec_vals, dict):
            user_sec = user_data.get(sec, {})
            if isinstance(user_sec, dict):
                merged[sec] = dict(sec_vals)
                merged[sec].update(user_sec)
            else:
                merged[sec] = dict(sec_vals)
        else:
            merged[sec] = user_data.get(sec, sec_vals)

    # Preservar secciones o presets custom creados por el usuario
    for k, v in user_data.items():
        if k not in merged:
            merged[k] = v
        elif isinstance(v, dict) and isinstance(merged[k], dict):
            for sub_k, sub_v in v.items():
                if sub_k not in merged[k]:
                    merged[k][sub_k] = sub_v

    return merged


def save_config_toml(config_dict: dict[str, Any], path: Path | None = None) -> None:
    """
    Guarda la configuración en formato TOML asegurando permisos 0700/0600 (H-06).
    """
    target = path or CONFIG_TOML
    ensure_umask()
    target.parent.mkdir(parents=True, exist_ok=True)
    secure_directory(target.parent)

    toml_text = dump_toml(config_dict)
    target.write_text(toml_text, encoding="utf-8")


# ── Migración no destructiva de formatos legacy ─────────────────────────────

def migrate_legacy_config(dio_dir: Path | None = None) -> bool:
    """
    Detecta si existe configuración previa (session.json, config.json, settings.json)
    y si aún no existe config.toml, genera el config.toml equivalente sin perder datos
    y respaldando los originales en ~/.dio/legacy/.
    Retorna True si realizó migración, False en caso contrario.
    """
    base_dir = dio_dir or DIO_DIR
    target_toml = base_dir / "config.toml"
    if target_toml.exists():
        return False

    legacy_config = base_dir / "config.json"
    legacy_settings = base_dir / "settings.json"
    legacy_session = base_dir / "session.json"

    has_legacy = legacy_config.exists() or legacy_settings.exists() or legacy_session.exists()
    if not has_legacy:
        return False

    ensure_umask()
    legacy_backup_dir = base_dir / "legacy"
    legacy_backup_dir.mkdir(parents=True, exist_ok=True)
    secure_directory(legacy_backup_dir)

    # Iniciar con defaults
    new_cfg: dict[str, Any] = json.loads(json.dumps(DEFAULT_CONFIG))

    # 1. Migrar settings.json
    if legacy_settings.exists():
        try:
            s_data = json.loads(legacy_settings.read_text(encoding="utf-8"))
            if isinstance(s_data, dict):
                for k, v in s_data.items():
                    if k in new_cfg["general"]:
                        new_cfg["general"][k] = v
                    elif k in ("passthrough_key", "invocation_key", "disabled_shortcuts", "custom_keybindings"):
                        new_cfg["shortcuts"][k] = v
                    elif k == "tab_sleeping_enabled":
                        new_cfg["sleeping"]["enabled"] = bool(v)
                    elif k == "tab_sleeping_minutes":
                        new_cfg["sleeping"]["timeout_minutes"] = int(v)
            shutil.copy2(legacy_settings, legacy_backup_dir / "settings.json.bak")
        except Exception:
            pass

    # 2. Migrar config.json (presets de URLs)
    if legacy_config.exists():
        try:
            c_data = json.loads(legacy_config.read_text(encoding="utf-8"))
            if isinstance(c_data, dict):
                for preset_name, urls in c_data.items():
                    if isinstance(urls, list):
                        # Inferir grid según cantidad
                        cnt = len(urls)
                        grid_str = "2x2"
                        if cnt == 6:
                            grid_str = "2x3"
                        elif cnt == 8:
                            grid_str = "2x4"
                        elif cnt == 9:
                            grid_str = "3x3"
                        new_cfg["presets"][preset_name] = {
                            "grid": grid_str,
                            "urls": urls,
                        }
            shutil.copy2(legacy_config, legacy_backup_dir / "config.json.bak")
        except Exception:
            pass

    # 3. Migrar session.json (layout y urls de última sesión)
    if legacy_session.exists():
        try:
            sess_data = json.loads(legacy_session.read_text(encoding="utf-8"))
            if isinstance(sess_data, dict):
                if "preset" in sess_data and sess_data["preset"]:
                    new_cfg["general"]["default_preset"] = sess_data["preset"]
                if "grid" in sess_data and sess_data["grid"]:
                    new_cfg["general"]["default_grid"] = sess_data["grid"]
                # Preservar un preset especial "_last_session" si tiene URLs
                if "urls" in sess_data and isinstance(sess_data["urls"], list) and sess_data["urls"]:
                    new_cfg["presets"]["_last_session"] = {
                        "grid": sess_data.get("grid", "2x2"),
                        "urls": sess_data["urls"],
                    }
            shutil.copy2(legacy_session, legacy_backup_dir / "session.json.bak")
        except Exception:
            pass

    save_config_toml(new_cfg, target_toml)
    return True


def ensure_config(dio_dir: Path | None = None) -> dict[str, Any]:
    """
    Punto de entrada para inicializar la configuración:
    1. Asegura umask 0o077 y directorios base.
    2. Ejecuta migración legacy si corresponde.
    3. Si aún no existe config.toml, crea el default.
    4. Carga y retorna la configuración declarativa.
    """
    base_dir = dio_dir or DIO_DIR
    ensure_umask()
    base_dir.mkdir(parents=True, exist_ok=True)
    secure_directory(base_dir)

    target_toml = base_dir / "config.toml"
    if not target_toml.exists():
        migrated = migrate_legacy_config(base_dir)
        if not migrated:
            save_config_toml(DEFAULT_CONFIG, target_toml)

    return load_config_toml(target_toml)


# ── Compatibilidad con código previo ─────────────────────────────────────────

def load_presets() -> dict[str, list[str]]:
    """
    Función de compatibilidad: lee presets desde config.toml.
    Retorna un diccionario de {nombre_preset: [urls]}.
    """
    cfg = ensure_config()
    presets_section = cfg.get("presets", {})
    res: dict[str, list[str]] = {}
    for name, p_data in presets_section.items():
        if isinstance(p_data, dict) and "urls" in p_data:
            res[name] = p_data["urls"]
        elif isinstance(p_data, list):
            res[name] = p_data
    return res or dict(PRESETS)


def load_settings() -> dict[str, Any]:
    """
    Función de compatibilidad: combina [general], [sleeping] y [shortcuts] de config.toml.
    """
    cfg = ensure_config()
    res = dict(DEFAULT_SETTINGS)
    if "general" in cfg:
        res.update(cfg["general"])
    if "sleeping" in cfg:
        res["tab_sleeping_enabled"] = cfg["sleeping"].get("enabled", False)
        res["tab_sleeping_minutes"] = cfg["sleeping"].get("timeout_minutes", 15)
    if "shortcuts" in cfg:
        res.update(cfg["shortcuts"])
    return res


def save_settings(settings_dict: dict[str, Any]) -> None:
    """
    Función de compatibilidad: guarda campos en config.toml.
    """
    cfg = ensure_config()
    for k, v in settings_dict.items():
        if k in cfg.get("general", {}):
            cfg["general"][k] = v
        elif k == "tab_sleeping_enabled":
            cfg.setdefault("sleeping", {})["enabled"] = bool(v)
        elif k == "tab_sleeping_minutes":
            cfg.setdefault("sleeping", {})["timeout_minutes"] = int(v)
        elif k in cfg.get("shortcuts", {}):
            cfg["shortcuts"][k] = v
    save_config_toml(cfg)


def ensure_adblock_hosts() -> None:
    """
    Copia el archivo de hosts de adblock por defecto a ~/.dio/ si no existe.
    """
    if ADBLOCK_HOSTS_FILE.exists():
        return

    src = Path(__file__).resolve().parent.parent.parent / "config" / "adblock_hosts.txt"
    if src.exists():
        try:
            DIO_DIR.mkdir(parents=True, exist_ok=True)
            ADBLOCK_HOSTS_FILE.write_text(
                src.read_text(encoding="utf-8"), encoding="utf-8"
            )
        except OSError:
            pass
