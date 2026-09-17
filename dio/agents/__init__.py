"""
D.I.O. — Paquete de Agentes e Integracion IA (AI Cockpit).
"""

from dio.agents.loader import (
    AgentAdapter,
    USER_ADAPTERS_DIR,
    DEFAULTS_DIR,
    load_all_adapters,
    load_adapter_from_file,
    find_adapter_for_url,
    ensure_adapters_directory,
    validate_adapter_dict,
)

__all__ = [
    "AgentAdapter",
    "USER_ADAPTERS_DIR",
    "DEFAULTS_DIR",
    "load_all_adapters",
    "load_adapter_from_file",
    "find_adapter_for_url",
    "ensure_adapters_directory",
    "validate_adapter_dict",
]
