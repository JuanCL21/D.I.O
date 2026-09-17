"""
D.I.O. — Tests automatizados para la Máquina de Estados Finita (FSM) de Panel (Paso 2).
Valida estados, transiciones válidas, guards/invariantes de exclusión mutua
y la Decisión 4 (RECOVERING -> ACTIVE con reseteo de crash_count).
"""

import pytest

from dio.core.state import (
    InvalidTransitionError,
    PanelEvent,
    PanelState,
    PanelStateMachine,
    TRANSITION_TABLE,
)


class TestPanelStateMachineTransitions:
    """Verifica todas las transiciones válidas del ciclo de vida."""

    def test_initial_state_to_active(self):
        """INITIALIZING -> ACTIVE vía INIT_FINISHED."""
        fsm = PanelStateMachine("panel_0", initial_state=PanelState.INITIALIZING)
        assert fsm.state == PanelState.INITIALIZING
        new_state = fsm.trigger(PanelEvent.INIT_FINISHED)
        assert new_state == PanelState.ACTIVE
        assert fsm.state == PanelState.ACTIVE

    def test_hibernation_and_restore_cycle(self):
        """ACTIVE -> HIBERNATING -> HIBERNATED -> RESTORING -> ACTIVE."""
        fsm = PanelStateMachine("panel_0", initial_state=PanelState.ACTIVE)

        # 1. ACTIVE -> HIBERNATING
        fsm.trigger(PanelEvent.DISCARD_REQUESTED)
        assert fsm.state == PanelState.HIBERNATING

        # 2. HIBERNATING -> HIBERNATED
        fsm.trigger(PanelEvent.DISCARD_COMPLETED)
        assert fsm.state == PanelState.HIBERNATED

        # 3. HIBERNATED -> RESTORING
        fsm.trigger(PanelEvent.RESTORE_REQUESTED)
        assert fsm.state == PanelState.RESTORING

        # 4. RESTORING -> ACTIVE
        fsm.trigger(PanelEvent.RESTORE_COMPLETED)
        assert fsm.state == PanelState.ACTIVE

    def test_crash_and_recovery_decision_4(self):
        """
        DECISIÓN 4:
        CRASHED -> RECOVERING -> ACTIVE vía LOAD_FINISHED_SUCCESS
        debe resetear crash_count estrictamente a 0.
        """
        fsm = PanelStateMachine("panel_0", initial_state=PanelState.ACTIVE)

        # Simular 2 crashes consecutivos
        fsm.trigger(PanelEvent.RENDER_CRASHED)
        assert fsm.state == PanelState.CRASHED
        assert fsm.crash_count == 1

        fsm.trigger(PanelEvent.RECOVERY_STARTED)
        assert fsm.state == PanelState.RECOVERING

        # Vuelve a crashear durante la recuperación
        fsm.trigger(PanelEvent.RENDER_CRASHED)
        assert fsm.state == PanelState.CRASHED
        assert fsm.crash_count == 2

        fsm.trigger(PanelEvent.RECOVERY_STARTED)
        assert fsm.state == PanelState.RECOVERING
        assert fsm.crash_count == 2

        # DECISIÓN 4: loadFinished(True) tras recreación exitosa
        fsm.trigger(PanelEvent.LOAD_FINISHED_SUCCESS)
        assert fsm.state == PanelState.ACTIVE
        assert fsm.crash_count == 0, "DECISIÓN 4 violada: crash_count debe ser 0 tras LOAD_FINISHED_SUCCESS"

    def test_recovery_exhaustion_to_failed(self):
        """CRASHED -> RECOVERING -> FAILED -> RECOVERING (manual reload)."""
        fsm = PanelStateMachine("panel_0", initial_state=PanelState.ACTIVE)
        fsm.trigger(PanelEvent.RENDER_CRASHED)
        fsm.trigger(PanelEvent.RECOVERY_STARTED)
        assert fsm.state == PanelState.RECOVERING

        fsm.trigger(PanelEvent.RECOVERY_FAILED)
        assert fsm.state == PanelState.FAILED

        # Recarga manual iniciada por el usuario
        fsm.trigger(PanelEvent.MANUAL_RELOAD)
        assert fsm.state == PanelState.RECOVERING

    def test_max_retries_threshold_exhaustion(self):
        """Verifica que el umbral por defecto (max_retries=3) permite exactamente 3 reintentos antes de FAILED."""
        fsm = PanelStateMachine("panel_0", initial_state=PanelState.ACTIVE, max_retries=3)
        assert fsm.max_retries == 3

        # Reintento 1
        fsm.trigger(PanelEvent.RENDER_CRASHED)
        assert fsm.crash_count == 1
        assert fsm.can_retry() is True
        fsm.trigger(PanelEvent.RECOVERY_STARTED)
        assert fsm.state == PanelState.RECOVERING

        # Reintento 2
        fsm.trigger(PanelEvent.RENDER_CRASHED)
        assert fsm.crash_count == 2
        assert fsm.can_retry() is True
        fsm.trigger(PanelEvent.RECOVERY_STARTED)
        assert fsm.state == PanelState.RECOVERING

        # Reintento 3
        fsm.trigger(PanelEvent.RENDER_CRASHED)
        assert fsm.crash_count == 3
        assert fsm.can_retry() is True
        fsm.trigger(PanelEvent.RECOVERY_STARTED)
        assert fsm.state == PanelState.RECOVERING

        # Caída 4: Agotados los 3 reintentos
        fsm.trigger(PanelEvent.RENDER_CRASHED)
        assert fsm.crash_count == 4
        assert fsm.can_retry() is False
        fsm.trigger(PanelEvent.RECOVERY_FAILED)
        assert fsm.state == PanelState.FAILED


class TestPanelStateMachineInvariants:
    """Verifica que las transiciones prohibidas por diseño sean rechazadas categóricamente."""

    def test_prohibit_hibernating_while_recovering(self):
        """
        INVARIANTE CRÍTICO:
        Un panel en RECOVERING jamás puede ser hibernado simultáneamente.
        """
        fsm = PanelStateMachine("panel_0", initial_state=PanelState.ACTIVE)
        fsm.trigger(PanelEvent.RENDER_CRASHED)
        fsm.trigger(PanelEvent.RECOVERY_STARTED)
        assert fsm.state == PanelState.RECOVERING

        with pytest.raises(InvalidTransitionError) as exc_info:
            fsm.trigger(PanelEvent.DISCARD_REQUESTED)
        assert "no se puede procesar evento DISCARD_REQUESTED desde estado RECOVERING" in str(exc_info.value)

    def test_prohibit_crash_on_hibernated_panel(self):
        """
        INVARIANTE FÍSICO:
        Un panel HIBERNATED no tiene proceso Chromium vivo; no puede emitir un crash.
        """
        fsm = PanelStateMachine("panel_0", initial_state=PanelState.ACTIVE)
        fsm.trigger(PanelEvent.DISCARD_REQUESTED)
        fsm.trigger(PanelEvent.DISCARD_COMPLETED)
        assert fsm.state == PanelState.HIBERNATED

        with pytest.raises(InvalidTransitionError) as exc_info:
            fsm.trigger(PanelEvent.RENDER_CRASHED)
        assert "no se puede procesar evento RENDER_CRASHED desde estado HIBERNATED" in str(exc_info.value)

    def test_prohibit_crash_while_hibernating(self):
        """Durante el desmontaje de página (HIBERNATING), no se procesan crashes espurios."""
        fsm = PanelStateMachine("panel_0", initial_state=PanelState.ACTIVE)
        fsm.trigger(PanelEvent.DISCARD_REQUESTED)
        assert fsm.state == PanelState.HIBERNATING

        with pytest.raises(InvalidTransitionError):
            fsm.trigger(PanelEvent.RENDER_CRASHED)

    def test_prohibit_discard_on_failed_panel(self):
        """Un panel FAILED no puede descartarse por timeout de sleeping."""
        fsm = PanelStateMachine("panel_0", initial_state=PanelState.ACTIVE)
        fsm.trigger(PanelEvent.RENDER_CRASHED)
        fsm.trigger(PanelEvent.RECOVERY_STARTED)
        fsm.trigger(PanelEvent.RECOVERY_FAILED)
        assert fsm.state == PanelState.FAILED

        with pytest.raises(InvalidTransitionError):
            fsm.trigger(PanelEvent.DISCARD_REQUESTED)


class TestTransitionTableCompleteness:
    """Verifica que la tabla de transiciones sea la fuente auditable completa."""

    def test_decision_4_row_exists_in_table(self):
        """Confirma que la fila RECOVERING -> ACTIVE está explícitamente en TRANSITION_TABLE."""
        matching = [
            rule for rule in TRANSITION_TABLE
            if rule.source == PanelState.RECOVERING
            and rule.target == PanelState.ACTIVE
            and rule.event == PanelEvent.LOAD_FINISHED_SUCCESS
        ]
        assert len(matching) == 1, "Fila de Decisión 4 no encontrada en TRANSITION_TABLE"
        rule = matching[0]
        assert "crash_count se resetea a 0" in (rule.effect or "")
