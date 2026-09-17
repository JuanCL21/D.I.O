"""
D.I.O. — Inyeccion de MutationObserver Generico para AI Cockpit (Paso 5).

DECISION DE ARQUITECTURA (Vinculante):
El observer se inyecta en QWebEngineScript.ScriptWorldId.ApplicationWorld (mundo aislado).
Esto aisla la logica de inspeccion y las variables de monitoreo respecto a los scripts
de terceros que corren en la pagina (MainWorld), impidiendo manipulacion o colisiones.
"""

import json
from PyQt6.QtWebEngineCore import QWebEngineScript

from dio.agents.loader import AgentAdapter

AGENT_STATE_PREFIX = "__DIO_AGENT_STATE__:"


def build_observer_script_source(adapter: AgentAdapter) -> str:
    """
    Genera el codigo JavaScript del MutationObserver parametrizado exclusivamente
    por los selectores del adapter JSON. Cero logica de servicio hardcodeada.
    """
    working_sel = json.dumps(adapter.working_selector)
    blocked_sel = json.dumps(adapter.blocked_selector)
    done_sel = json.dumps(adapter.done_selector)
    debounce_ms = adapter.debounce_ms
    prefix = json.dumps(AGENT_STATE_PREFIX)

    return f"""
(function() {{
    if (window.__dio_agent_observer_installed) return;
    window.__dio_agent_observer_installed = true;

    var WORKING_SEL = {working_sel};
    var BLOCKED_SEL = {blocked_sel};
    var DONE_SEL = {done_sel};
    var DEBOUNCE_MS = {debounce_ms};
    var PREFIX = {prefix};

    var currentState = "idle";
    var debounceTimer = null;
    var wasWorking = false;

    function evaluateState() {{
        var isWorking = false;
        var isBlocked = false;
        var isDone = false;

        try {{
            if (WORKING_SEL && document.querySelector(WORKING_SEL)) {{
                isWorking = true;
            }}
        }} catch(e) {{}}

        try {{
            if (BLOCKED_SEL && document.querySelector(BLOCKED_SEL)) {{
                isBlocked = true;
            }}
        }} catch(e) {{}}

        try {{
            if (DONE_SEL && document.querySelector(DONE_SEL)) {{
                isDone = true;
            }}
        }} catch(e) {{}}

        var newState = "idle";
        if (isWorking) {{
            newState = "working";
            wasWorking = true;
        }} else if (isBlocked) {{
            newState = "blocked";
        }} else if (isDone && wasWorking) {{
            newState = "done";
        }} else if (wasWorking && !isWorking) {{
            newState = "done";
        }} else {{
            newState = "idle";
        }}

        if (newState !== currentState) {{
            currentState = newState;
            console.log(PREFIX + currentState);
        }}
    }}

    function scheduleEvaluation() {{
        if (debounceTimer) {{
            clearTimeout(debounceTimer);
        }}
        debounceTimer = setTimeout(evaluateState, DEBOUNCE_MS);
    }}

    // Observar mutaciones en el arbol del DOM
    var observer = new MutationObserver(function(mutations) {{
        scheduleEvaluation();
    }});

    function startObserving() {{
        if (!document.body) {{
            setTimeout(startObserving, 50);
            return;
        }}
        observer.observe(document.body, {{
            childList: true,
            subtree: true,
            attributes: true,
            attributeFilter: ['disabled', 'aria-disabled', 'class', 'data-testid']
        }});
        // Evaluacion inicial
        evaluateState();
    }}

    if (document.readyState === 'loading') {{
        document.addEventListener('DOMContentLoaded', startObserving);
    }} else {{
        startObserving();
    }}
}})();
"""


def make_agent_observer_script(adapter: AgentAdapter) -> QWebEngineScript:
    """
    Construye un QWebEngineScript configurado para ejecutarse en ApplicationWorld.
    """
    script = QWebEngineScript()
    script.setName(f"dio_agent_observer_{adapter.name}")
    script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentReady)
    # Mundo aislado: protege la logica contra scripts maliciosos o interferencias de terceros
    script.setWorldId(QWebEngineScript.ScriptWorldId.ApplicationWorld)
    script.setRunsOnSubFrames(False)
    script.setSourceCode(build_observer_script_source(adapter))
    return script
