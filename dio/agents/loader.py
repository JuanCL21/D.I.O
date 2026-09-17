"""
D.I.O. — Subsistema de Agentes de IA: Loader de Adapters Declarativos.

DECISION 1 (Vinculante):
Los adapters de IA son datos declarativos en archivos JSON (~/.dio/adapters/*.json
o dio/agents/defaults/*.json), NUNCA modulos Python con selectores hardcodeados.
Este modulo unicamente parsea JSON, valida el schema y resuelve el adapter para una URL.
"""

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import dio.core.config as config
from dio.core.logger import logger
from dio.core.security import ensure_umask, secure_directory


# Directorio por defecto de adapters empaquetados
DEFAULTS_DIR = Path(__file__).resolve().parent / "defaults"
USER_ADAPTERS_DIR = config.DIO_DIR / "adapters"


@dataclass
class AgentAdapter:
    """Representacion tipada de un adapter declarativo de IA."""
    name: str
    match_patterns: list[str]
    working_selector: str
    blocked_selector: str
    done_selector: str
    input_selector: Optional[str] = None
    send_button_selector: Optional[str] = None
    debounce_ms: int = 800
    source_path: Optional[str] = None
    raw_json: dict[str, Any] = field(default_factory=dict)

    def matches_url(self, url: str) -> bool:
        """Comprueba si la URL actual coincide con alguno de los patrones del adapter."""
        if not url:
            return False
        url_lower = url.lower()
        for pattern in self.match_patterns:
            pattern_lower = pattern.lower()
            if pattern_lower in url_lower:
                return True
            try:
                if re.search(pattern, url, re.IGNORECASE):
                    return True
            except re.error:
                pass
        return False


def validate_adapter_dict(data: dict[str, Any], filepath: str) -> Optional[AgentAdapter]:
    """
    Valida la estructura del JSON del adapter contra el schema requerido.
    Retorna instancia de AgentAdapter si es valido, o None si no cumple el schema.
    """
    if not isinstance(data, dict):
        logger.warning("Adapter %s rechazado: la raiz debe ser un objeto JSON", filepath)
        return None

    name = data.get("name")
    if not name or not isinstance(name, str):
        logger.warning("Adapter %s rechazado: campo 'name' requerido y debe ser string", filepath)
        return None

    patterns = data.get("match_patterns")
    if not patterns or not isinstance(patterns, list) or not all(isinstance(p, str) for p in patterns):
        logger.warning("Adapter %s rechazado: 'match_patterns' debe ser una lista de strings no vacia", filepath)
        return None

    selectors = data.get("selectors")
    if not selectors or not isinstance(selectors, dict):
        logger.warning("Adapter %s rechazado: se requiere objeto 'selectors'", filepath)
        return None

    working = selectors.get("working")
    blocked = selectors.get("blocked")
    done = selectors.get("done")

    if not working or not isinstance(working, str):
        logger.warning("Adapter %s rechazado: selector 'working' requerido (string)", filepath)
        return None

    if not blocked or not isinstance(blocked, str):
        logger.warning("Adapter %s rechazado: selector 'blocked' requerido (string)", filepath)
        return None

    if not done or not isinstance(done, str):
        logger.warning("Adapter %s rechazado: selector 'done' requerido (string)", filepath)
        return None

    inp = selectors.get("input")
    send_btn = selectors.get("send_button")
    debounce = data.get("debounce_ms", 800)
    if not isinstance(debounce, int) or debounce < 100:
        debounce = 800

    return AgentAdapter(
        name=name,
        match_patterns=patterns,
        working_selector=working,
        blocked_selector=blocked,
        done_selector=done,
        input_selector=inp if isinstance(inp, str) else None,
        send_button_selector=send_btn if isinstance(send_btn, str) else None,
        debounce_ms=debounce,
        source_path=filepath,
        raw_json=data,
    )


def load_adapter_from_file(filepath: Path) -> Optional[AgentAdapter]:
    """Lee y valida un archivo JSON de adapter."""
    try:
        content = filepath.read_text(encoding="utf-8")
        data = json.loads(content)
        return validate_adapter_dict(data, str(filepath))
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Error leyendo adapter %s: %s", filepath, e)
        return None


def ensure_adapters_directory() -> Path:
    """Garantiza la existencia del directorio ~/.dio/adapters con permisos restrictivos."""
    ensure_umask()
    if not USER_ADAPTERS_DIR.exists():
        USER_ADAPTERS_DIR.mkdir(parents=True, exist_ok=True)
        secure_directory(USER_ADAPTERS_DIR)
        logger.info("Directorio de adapters creado en %s", USER_ADAPTERS_DIR)
    return USER_ADAPTERS_DIR


def load_all_adapters() -> list[AgentAdapter]:
    """
    Carga todos los adapters disponibles respetando la jerarquia:
    1. Primero los defaults incluidos en el paquete (dio/agents/defaults/*.json).
    2. Los adapters de usuario en ~/.dio/adapters/*.json sobrescriben a los defaults si tienen el mismo 'name'.
    Retorna la lista ordenada de adapters validos.
    """
    adapters_by_name: dict[str, AgentAdapter] = {}

    # 1. Cargar defaults empaquetados
    if DEFAULTS_DIR.exists():
        for file in sorted(DEFAULTS_DIR.glob("*.json")):
            adapter = load_adapter_from_file(file)
            if adapter:
                adapters_by_name[adapter.name] = adapter
                logger.debug("Adapter default cargado: %s (%s)", adapter.name, file.name)

    # 2. Cargar adapters de usuario (~/.dio/adapters/)
    user_dir = ensure_adapters_directory()
    if user_dir.exists():
        for file in sorted(user_dir.glob("*.json")):
            adapter = load_adapter_from_file(file)
            if adapter:
                if adapter.name in adapters_by_name:
                    logger.info("Adapter de usuario '%s' sobrescribe al default (%s)", adapter.name, file)
                else:
                    logger.info("Adapter de usuario '%s' cargado (%s)", adapter.name, file)
                adapters_by_name[adapter.name] = adapter

    return list(adapters_by_name.values())


def find_adapter_for_url(url: str, adapters: Optional[list[AgentAdapter]] = None) -> Optional[AgentAdapter]:
    """Encuentra el primer adapter que coincida con la URL proporcionada."""
    if not url or url in ("about:blank", "about:blank/"):
        return None
    adapter_list = adapters if adapters is not None else load_all_adapters()
    for adapter in adapter_list:
        if adapter.matches_url(url):
            return adapter
    return None
