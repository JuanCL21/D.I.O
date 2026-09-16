"""
D.I.O. — Máquina de Estados Finita (FSM) de Ciclo de Vida de Paneles
Define estados formales, eventos, tabla de transiciones auditables e invariantes
estrictos para garantizar que la hibernación y el crash-recovery jamás se solapen.

DECISIÓN 4 (Vinculante):
La tabla de transiciones incluye explícitamente la fila:
RECOVERING -> ACTIVE (evento: loadFinished(True) tras recreación exitosa, efecto: crash_count = 0).
"""

from dataclasses import dataclass
from enum import Enum, auto
from typing import Callable, Optional

from dio.core.logger import logger


class PanelState(Enum):
    """Estados exhaustivos y formales del ciclo de vida de un panel."""
    INITIALIZING = auto()  # Panel recién creado, cargando primera URL
    ACTIVE = auto()        # Renderer vivo, página visible e interactiva
    HIBERNATING = auto()   # Proceso de captura de snapshot y desacople de página en curso
    HIBERNATED = auto()    # Página destruida, proceso Chromium liberado, snapshot estático visible
    RESTORING = auto()     # Página recreándose con mismo perfil tras click/foco del usuario
    CRASHED = auto()       # renderProcessTerminated detectado en la página
    RECOVERING = auto()    # Recreando página y reintentando carga con backoff exponencial
    FAILED = auto()        # Reintentos de recuperación agotados; esperando acción manual


class PanelEvent(Enum):
    """Eventos que disparan transiciones en el ciclo de vida de un panel."""
    INIT_FINISHED = auto()          # Primera carga completada exitosamente
    DISCARD_REQUESTED = auto()      # Timeout de inactividad alcanzado (no pinned, no audio)
    DISCARD_COMPLETED = auto()      # Snapshot guardado y QWebEnginePage destruido
    RESTORE_REQUESTED = auto()      # Click o foco en panel hibernado
    RESTORE_COMPLETED = auto()      # Página recreada y cargada tras hibernación
    RENDER_CRASHED = auto()         # renderProcessTerminated recibido del kernel/Chromium
    RECOVERY_STARTED = auto()       # Inicio de recreación automática tras crash
    LOAD_FINISHED_SUCCESS = auto()  # loadFinished(True) tras recreación exitosa (Decisión 4)
    RECOVERY_FAILED = auto()        # Agotados reintentos de recuperación
    MANUAL_RELOAD = auto()          # Click en botón de recarga manual tras fallo definitivo


class InvalidTransitionError(Exception):
    """Excepción lanzada cuando se intenta una transición prohibida por la FSM."""
    def __init__(self, current_state: PanelState, event: PanelEvent, reason: str = "") -> None:
        msg = f"Transición prohibida: no se puede procesar evento {event.name} desde estado {current_state.name}."
        if reason:
            msg += f" Motivo: {reason}"
        super().__init__(msg)
        self.current_state = current_state
        self.event = event
        self.reason = reason


@dataclass(frozen=True)
class TransitionRule:
    """Regla individual auditable de transición en la FSM."""
    source: PanelState
    event: PanelEvent
    target: PanelState
    description: str
    guard: Optional[str] = None
    effect: Optional[str] = None


# ── TABLA DE TRANSICIONES AUDITABLE (Fuente única de verdad) ─────────────────
TRANSITION_TABLE: tuple[TransitionRule, ...] = (
    # 1. Inicialización
    TransitionRule(
        source=PanelState.INITIALIZING,
        event=PanelEvent.INIT_FINISHED,
        target=PanelState.ACTIVE,
        description="Panel inicializa y completa su primera carga.",
        effect="panel marcado como activo",
    ),
    # 2. Hibernación (Tab Discarding)
    TransitionRule(
        source=PanelState.ACTIVE,
        event=PanelEvent.DISCARD_REQUESTED,
        target=PanelState.HIBERNATING,
        description="Panel supera timeout en background sin audio ni pinned.",
        guard="not pinned and background and not has_audio",
        effect="inicia captura de snapshot visual",
    ),
    TransitionRule(
        source=PanelState.HIBERNATING,
        event=PanelEvent.DISCARD_COMPLETED,
        target=PanelState.HIBERNATED,
        description="Snapshot guardado; QWebEnginePage desacoplada y liberada.",
        effect="proceso Chromium hijo destruido, memoria liberada",
    ),
    # 3. Restauración desde Hibernación
    TransitionRule(
        source=PanelState.HIBERNATED,
        event=PanelEvent.RESTORE_REQUESTED,
        target=PanelState.RESTORING,
        description="Usuario hace click o enfoca el panel hibernado.",
        effect="recrea QWebEnginePage con el mismo perfil persistente",
    ),
    TransitionRule(
        source=PanelState.RESTORING,
        event=PanelEvent.RESTORE_COMPLETED,
        target=PanelState.ACTIVE,
        description="Página restaurada finaliza carga de URL y remueve overlay.",
        effect="panel vuelve a ser completamente interactivo",
    ),
    # 4. Crash y Detección de Caída
    TransitionRule(
        source=PanelState.ACTIVE,
        event=PanelEvent.RENDER_CRASHED,
        target=PanelState.CRASHED,
        description="renderProcessTerminated detectado mientras el panel estaba activo.",
        effect="incrementa crash_count en 1",
    ),
    TransitionRule(
        source=PanelState.RESTORING,
        event=PanelEvent.RENDER_CRASHED,
        target=PanelState.CRASHED,
        description="renderProcessTerminated detectado durante la restauración.",
        effect="incrementa crash_count en 1",
    ),
    TransitionRule(
        source=PanelState.RECOVERING,
        event=PanelEvent.RENDER_CRASHED,
        target=PanelState.CRASHED,
        description="renderProcessTerminated detectado durante el reintento de recuperación.",
        effect="incrementa crash_count en 1",
    ),
    # 5. Recuperación ante Crash
    TransitionRule(
        source=PanelState.CRASHED,
        event=PanelEvent.RECOVERY_STARTED,
        target=PanelState.RECOVERING,
        description="Inicia reintento de recreación con backoff exponencial.",
        guard="crash_count < max_retries",
        effect="programa reintento con backoff",
    ),
    # DECISIÓN 4: Fila explícita RECOVERING -> ACTIVE
    TransitionRule(
        source=PanelState.RECOVERING,
        event=PanelEvent.LOAD_FINISHED_SUCCESS,
        target=PanelState.ACTIVE,
        description="loadFinished(True) tras recreación exitosa del renderer.",
        effect="crash_count se resetea a 0",
    ),
    TransitionRule(
        source=PanelState.RECOVERING,
        event=PanelEvent.RECOVERY_FAILED,
        target=PanelState.FAILED,
        description="Se agotaron todos los reintentos de recuperación automática.",
        guard="crash_count >= max_retries",
        effect="muestra pantalla de error con botón de recarga manual",
    ),
    TransitionRule(
        source=PanelState.FAILED,
        event=PanelEvent.MANUAL_RELOAD,
        target=PanelState.RECOVERING,
        description="Usuario hace click en botón de recarga manual.",
        effect="reinicia intento de carga",
    ),
)

# Mapa indexado para consulta O(1)
_TRANSITION_MAP: dict[tuple[PanelState, PanelEvent], TransitionRule] = {
    (rule.source, rule.event): rule for rule in TRANSITION_TABLE
}


# ── INVARIANTES Y PROHIBICIONES EXPLÍCITAS ────────────────────────────────────
PROHIBITED_TRANSITIONS_RATIONALE: dict[tuple[PanelState, PanelEvent], str] = {
    (PanelState.RECOVERING, PanelEvent.DISCARD_REQUESTED): (
        "Garantía de exclusión mutua: un panel en proceso de recuperación de crash "
        "no puede ser hibernado simultáneamente."
    ),
    (PanelState.CRASHED, PanelEvent.DISCARD_REQUESTED): (
        "Un panel caído debe procesar su recuperación antes de cualquier gestión de energía."
    ),
    (PanelState.HIBERNATED, PanelEvent.RENDER_CRASHED): (
        "Invariante físico: un panel HIBERNATED tiene su QWebEnginePage y proceso Chromium "
        "destruidos; no tiene proceso vivo que pueda emitir un crash."
    ),
    (PanelState.HIBERNATING, PanelEvent.RENDER_CRASHED): (
        "Durante el proceso de hibernación la página está siendo intencionalmente desmontada."
    ),
    (PanelState.FAILED, PanelEvent.DISCARD_REQUESTED): (
        "Un panel en estado FAILED está a la espera de recarga manual y no debe descartarse."
    ),
}


class PanelStateMachine:
    """
    Máquina de estados finita asociada a cada panel.
    Mantiene el estado actual, el contador de caídas (`crash_count`)
    y audita rigurosamente todas las transiciones.
    """

    def __init__(
        self,
        panel_id: str,
        initial_state: PanelState = PanelState.INITIALIZING,
        on_state_changed: Optional[Callable[[PanelState, PanelState, PanelEvent], None]] = None,
    ) -> None:
        self.panel_id: str = panel_id
        self._state: PanelState = initial_state
        self.crash_count: int = 0
        self._on_state_changed: Optional[Callable[[PanelState, PanelState, PanelEvent], None]] = on_state_changed

    @property
    def state(self) -> PanelState:
        return self._state

    def can_trigger(self, event: PanelEvent) -> bool:
        """Verifica si un evento es válido desde el estado actual."""
        return (self._state, event) in _TRANSITION_MAP

    def trigger(self, event: PanelEvent) -> PanelState:
        """
        Ejecuta una transición de estado ante un evento.
        Lanza InvalidTransitionError si la transición está prohibida o no está en la tabla.
        """
        key = (self._state, event)
        if key not in _TRANSITION_MAP:
            reason = PROHIBITED_TRANSITIONS_RATIONALE.get(
                key, "Transición no definida en la tabla formal de la FSM."
            )
            logger.warning(
                "FSM [%s]: Transición inválida intentada %s -> %s (%s)",
                self.panel_id,
                self._state.name,
                event.name,
                reason,
            )
            raise InvalidTransitionError(self._state, event, reason)

        rule = _TRANSITION_MAP[key]
        old_state = self._state
        new_state = rule.target

        # ── Efectos de transición auditables ──────────────────────────────
        if event == PanelEvent.RENDER_CRASHED:
            self.crash_count += 1
            logger.info("FSM [%s]: Crash registrado (crash_count=%d)", self.panel_id, self.crash_count)

        elif rule.source == PanelState.RECOVERING and new_state == PanelState.ACTIVE and event == PanelEvent.LOAD_FINISHED_SUCCESS:
            # DECISIÓN 4: loadFinished(True) tras recreación exitosa resetea crash_count a 0
            self.crash_count = 0
            logger.info("FSM [%s]: DECISIÓN 4 aplicada: Recuperación exitosa. crash_count reseteado a 0", self.panel_id)

        self._state = new_state
        logger.debug(
            "FSM [%s]: %s -> %s vía %s (%s)",
            self.panel_id,
            old_state.name,
            new_state.name,
            event.name,
            rule.description,
        )

        if self._on_state_changed is not None:
            try:
                self._on_state_changed(old_state, new_state, event)
            except Exception as exc:
                logger.error("FSM [%s]: Error en callback on_state_changed: %s", self.panel_id, exc)

        return new_state
