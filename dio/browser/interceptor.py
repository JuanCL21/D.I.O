"""
D.I.O. — Interceptor de peticiones de red para bloqueo de anuncios y rastreadores.
"""

from PyQt6.QtWebEngineCore import QWebEngineUrlRequestInterceptor

import dio.core.config as config
from dio.core.logger import logger


class AdBlockInterceptor(QWebEngineUrlRequestInterceptor):
    """
    Intercepta peticiones de red y bloquea los dominios de publicidad/tracking
    definidos en ~/.dio/adblock_hosts.txt. Lookup O(1) mediante set.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._blocked_hosts: set[str] = set()
        self._load_hosts()

    def _load_hosts(self) -> None:
        """Carga la lista de hosts bloqueados desde disco."""
        hosts_file = config.ADBLOCK_HOSTS_FILE
        if not hosts_file.exists():
            config.ensure_adblock_hosts()

        if not hosts_file.exists():
            logger.warning("adblock_hosts.txt no encontrado; adblock inactivo")
            return

        try:
            count = 0
            for line in hosts_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    self._blocked_hosts.add(line.lower())
                    count += 1
            logger.info("AdBlock: %d dominios cargados desde %s", count, hosts_file)
        except OSError as exc:
            logger.warning("No se pudo leer adblock_hosts.txt: %s", exc)

    def interceptRequest(self, info) -> None:
        """Bloquea peticiones cuyo host coincide con la lista de dominios."""
        host = info.requestUrl().host().lower()
        if host.startswith("www."):
            host = host[4:]

        # Nunca bloquear peticiones internas ni canales de streaming de los servicios principales
        if any(
            trusted in host
            for trusted in (
                "anthropic.com",
                "claude.ai",
                "openai.com",
                "chatgpt.com",
                "google.com",
                "gstatic.com",
                "perplexity.ai",
                "grok.com",
                "whatsapp.com",
                "whatsapp.net",
            )
        ):
            return

        for blocked in self._blocked_hosts:
            if host == blocked or host.endswith("." + blocked):
                info.block(True)
                return
