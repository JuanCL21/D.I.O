"""
D.I.O. — Gestor de Perfiles de Navegación (ProfileManager).

DECISIÓN 2 (Vinculante):
- Cerrar o hibernar un panel NUNCA destruye el perfil persistente en disco ni su sesión.
- Implementa pool/caché en memoria de QWebEngineProfile con política de desalojo LRU.
- Los perfiles marcados como "pinned" quedan EXCLUIDOS de la expulsión LRU.
- El borrado definitivo del perfil en disco es una acción separada, explícita y confirmada,
  nunca un efecto colateral de cerrar o hibernar.
- Preserva el fix H-01: desacople limpio y ordenado en memoria sin tocar el almacenamiento persistente.
"""

import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QObject
from PyQt6.QtWebEngineCore import QWebEngineProfile

import dio.core.config as config
from dio.core.logger import logger
from dio.core.security import secure_directory
from dio.browser.scripts import make_anti_detection_script, make_dark_mode_script


@dataclass
class ProfileEntry:
    """Entrada de perfil en el pool LRU en memoria."""
    panel_id: str
    profile: QWebEngineProfile
    is_pinned: bool
    last_accessed: float
    ref_count: int = 1


class ProfileManager(QObject):
    """
    Administrador centralizado de QWebEngineProfiles con caché en memoria LRU.
    Garantiza aislamiento estricto por panel y persistencia perpetua en disco.
    """

    def __init__(self, max_in_memory: int = 16, parent=None) -> None:
        super().__init__(parent)
        self.max_in_memory = max_in_memory
        self._pool: dict[str, ProfileEntry] = {}

    def get_or_create_profile(
        self,
        panel_id: str,
        is_pinned: bool = False,
        adblock_interceptor=None,
        dark_mode: bool = True,
    ) -> QWebEngineProfile:
        """
        Obtiene un perfil existente del pool o crea uno nuevo configurando sus rutas
        en ~/.dio/profiles/{panel_id}/. Si el pool excede la capacidad, ejecuta desalojo LRU
        excluyendo siempre perfiles 'pinned'.
        """
        now = time.time()

        # 1. Si ya está en caché en memoria, actualizar LRU y retornar
        if panel_id in self._pool:
            entry = self._pool[panel_id]
            entry.last_accessed = now
            entry.ref_count += 1
            if is_pinned:
                entry.is_pinned = True
            logger.debug("ProfileManager: Reutilizando perfil en memoria [%s] (ref_count=%d)", panel_id, entry.ref_count)
            return entry.profile

        # 2. Desalojo LRU si alcanzamos el límite en memoria
        if len(self._pool) >= self.max_in_memory:
            self._evict_lru()

        # 3. Crear nuevo QWebEngineProfile persistente en disco
        profile_path = config.PROFILES_DIR / panel_id
        profile_path.mkdir(parents=True, exist_ok=True)
        secure_directory(profile_path)

        profile = QWebEngineProfile(panel_id, self)
        profile.setPersistentStoragePath(str(profile_path))
        profile.setCachePath(str(profile_path / "cache"))
        profile.setHttpUserAgent(config.USER_AGENT)

        if adblock_interceptor is not None:
            profile.setUrlRequestInterceptor(adblock_interceptor)

        settings = config.load_settings()
        dl_dir = settings.get("downloads_dir", str(Path.home() / "Downloads" / "DIO"))
        profile.setDownloadPath(str(Path(dl_dir).expanduser()))

        if dark_mode:
            profile.scripts().insert(make_dark_mode_script())

        # Anti-detección para evitar bloqueo de Google OAuth y automatización
        profile.scripts().insert(make_anti_detection_script())

        entry = ProfileEntry(
            panel_id=panel_id,
            profile=profile,
            is_pinned=is_pinned,
            last_accessed=now,
            ref_count=1,
        )
        self._pool[panel_id] = entry
        logger.info("ProfileManager: Perfil cargado en memoria [%s] (pinned=%s, total=%d)", panel_id, is_pinned, len(self._pool))
        return profile

    def release_profile_reference(self, panel_id: str) -> None:
        """
        Decrementa la referencia activa de un perfil (ej. al cerrar o hibernar un panel).
        DECISIÓN 2: NO borra los datos de disco. El perfil permanece en caché LRU hasta
        que sea necesario desalojarlo de memoria.
        """
        if panel_id not in self._pool:
            return

        entry = self._pool[panel_id]
        entry.ref_count = max(0, entry.ref_count - 1)
        entry.last_accessed = time.time()
        logger.debug("ProfileManager: Referencia liberada para [%s] (ref_count=%d)", panel_id, entry.ref_count)

    def set_pinned(self, panel_id: str, pinned: bool) -> None:
        """Marca o desmarca un perfil como 'pinned' para protegerlo de la expulsión LRU."""
        if panel_id in self._pool:
            self._pool[panel_id].is_pinned = pinned
            logger.info("ProfileManager: Perfil [%s] pinned=%s", panel_id, pinned)

    def is_pinned(self, panel_id: str) -> bool:
        if panel_id in self._pool:
            return self._pool[panel_id].is_pinned
        return False

    def _evict_lru(self) -> Optional[str]:
        """
        Expulsa de la memoria RAM el perfil menos recientemente usado (LRU)
        cuyo ref_count sea 0 y que NO esté marcado como 'pinned'.
        Los datos en disco (~/.dio/profiles/{panel_id}) permanecen 100% intactos.
        """
        candidates = [
            (pid, entry)
            for pid, entry in self._pool.items()
            if entry.ref_count == 0 and not entry.is_pinned
        ]

        if not candidates:
            logger.warning("ProfileManager: No hay candidatos desocupados para desalojo LRU (todos activos o pinned)")
            return None

        # Ordenar por el acceso más antiguo
        candidates.sort(key=lambda item: item[1].last_accessed)
        evict_id, evict_entry = candidates[0]

        logger.info("ProfileManager: Desalojando perfil de memoria RAM [%s] (datos en disco intactos)", evict_id)
        evict_entry.profile.deleteLater()
        del self._pool[evict_id]
        return evict_id

    def delete_profile_from_disk(self, panel_id: str, confirmed: bool = False) -> bool:
        """
        DECISIÓN 2: Acción separada y explícita de UI con confirmación.
        Nunca se ejecuta como efecto colateral de cerrar o hibernar un panel.
        """
        if not confirmed:
            raise ValueError("El borrado definitivo de un perfil en disco requiere confirmación explícita (confirmed=True)")

        # 1. Desalojar de memoria si está activo
        if panel_id in self._pool:
            entry = self._pool.pop(panel_id)
            entry.profile.deleteLater()

        # 2. Eliminar directorio de datos en disco
        target_path = config.PROFILES_DIR / panel_id
        if target_path.exists():
            for attempt in range(5):
                try:
                    shutil.rmtree(target_path)
                    logger.info("ProfileManager: Perfil [%s] eliminado permanentemente de disco tras confirmación", panel_id)
                    return True
                except OSError as exc:
                    if attempt < 4:
                        time.sleep(0.05)
                        continue
                    logger.error("ProfileManager: Error al eliminar perfil [%s] de disco: %s", panel_id, exc)
                    return False

        return False
