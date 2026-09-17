"""
Tests para el subsistema de AI Cockpit de D.I.O. (Paso 5):
- Carga y validacion de schema de adapters declarativos JSON
- Prioridad de carga: ~/.dio/adapters/ sobrescribe defaults
- Prueba de ruptura de selector en JSON sin tocar Python
- Generacion de scripts para ApplicationWorld
- Captura de senales en DIOPage
- Disparo no bloqueante de notificaciones nativas
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PyQt6.QtCore import QCoreApplication
from PyQt6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineScript
from PyQt6.QtWidgets import QApplication

from dio.agents.loader import (
    AgentAdapter,
    find_adapter_for_url,
    load_adapter_from_file,
    load_all_adapters,
    validate_adapter_dict,
)
from dio.browser.agent_observer import (
    AGENT_STATE_PREFIX,
    build_observer_script_source,
    make_agent_observer_script,
)
from dio.browser.page import DIOPage
from dio.core.notifier import send_system_notification
from dio.core.state import AgentState


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(["dio_test"])
    yield app


# ── Tests de Schema y Carga de Adapters ───────────────────────────────────────

def test_default_adapters_exist_and_valid():
    adapters = load_all_adapters()
    names = {a.name for a in adapters}
    assert "chatgpt" in names
    assert "claude" in names
    assert "gemini" in names

    for adapter in adapters:
        assert len(adapter.match_patterns) > 0
        assert adapter.working_selector
        assert adapter.blocked_selector
        assert adapter.done_selector
        assert adapter.debounce_ms >= 100


def test_validate_adapter_dict_malformed():
    # Sin 'name'
    assert validate_adapter_dict({"match_patterns": ["test.com"], "selectors": {}}, "test.json") is None

    # Sin 'match_patterns'
    assert validate_adapter_dict({"name": "test", "selectors": {}}, "test.json") is None

    # 'selectors' incompleto (falta 'done')
    bad_selectors = {
        "name": "test",
        "match_patterns": ["test.com"],
        "selectors": {
            "working": "button.stop",
            "blocked": "button.confirm",
        },
    }
    assert validate_adapter_dict(bad_selectors, "test.json") is None


def test_user_adapter_overrides_default(tmp_path, monkeypatch):
    # Simular directorio de usuario en tmp_path
    monkeypatch.setattr("dio.agents.loader.USER_ADAPTERS_DIR", tmp_path)

    custom_claude = {
        "name": "claude",
        "match_patterns": ["claude.ai", "custom-claude.internal"],
        "selectors": {
            "working": "button.custom-stop",
            "blocked": "button.custom-confirm",
            "done": "button.custom-send",
        },
        "debounce_ms": 1200,
    }
    custom_file = tmp_path / "claude.json"
    custom_file.write_text(json.dumps(custom_claude), encoding="utf-8")

    adapters = load_all_adapters()
    claude = next((a for a in adapters if a.name == "claude"), None)
    assert claude is not None
    assert claude.working_selector == "button.custom-stop"
    assert claude.debounce_ms == 1200
    assert "custom-claude.internal" in claude.match_patterns


def test_url_matching():
    chatgpt = find_adapter_for_url("https://chatgpt.com/c/123-abc")
    assert chatgpt is not None
    assert chatgpt.name == "chatgpt"

    claude = find_adapter_for_url("https://claude.ai/chat/xyz")
    assert claude is not None
    assert claude.name == "claude"

    gemini = find_adapter_for_url("https://gemini.google.com/app/456")
    assert gemini is not None
    assert gemini.name == "gemini"

    unsupported = find_adapter_for_url("https://wikipedia.org")
    assert unsupported is None


# ── Prueba de Ruptura y Correccion en JSON (Decision 1) ──────────────────────

def test_breaking_and_fixing_selector_changes_script_without_touching_python(tmp_path):
    adapter_file = tmp_path / "custom_agent.json"

    # 1. Version valida inicial
    v1_data = {
        "name": "custom_agent",
        "match_patterns": ["custom.ai"],
        "selectors": {
            "working": "button.working-v1",
            "blocked": "button.blocked-v1",
            "done": "button.done-v1",
        },
    }
    adapter_file.write_text(json.dumps(v1_data), encoding="utf-8")
    adapter_v1 = load_adapter_from_file(adapter_file)
    assert adapter_v1 is not None
    js_code_v1 = build_observer_script_source(adapter_v1)
    assert "button.working-v1" in js_code_v1

    # 2. Romper deliberadamente el selector en el archivo JSON
    v2_data = dict(v1_data)
    v2_data["selectors"] = {
        "working": "div.broken-selector-after-dom-update",
        "blocked": "button.blocked-v1",
        "done": "button.done-v1",
    }
    adapter_file.write_text(json.dumps(v2_data), encoding="utf-8")
    adapter_v2 = load_adapter_from_file(adapter_file)
    assert adapter_v2 is not None
    js_code_v2 = build_observer_script_source(adapter_v2)
    assert "button.working-v1" not in js_code_v2
    assert "div.broken-selector-after-dom-update" in js_code_v2

    # 3. Corregir el selector en el archivo JSON
    v3_data = dict(v1_data)
    v3_data["selectors"]["working"] = "button.fixed-stop-button"
    adapter_file.write_text(json.dumps(v3_data), encoding="utf-8")
    adapter_v3 = load_adapter_from_file(adapter_file)
    assert adapter_v3 is not None
    js_code_v3 = build_observer_script_source(adapter_v3)
    assert "button.fixed-stop-button" in js_code_v3


# ── Tests de ApplicationWorld y Captura de Senal ─────────────────────────────

def test_observer_script_configured_in_application_world():
    adapters = load_all_adapters()
    claude = next(a for a in adapters if a.name == "claude")
    script = make_agent_observer_script(claude)

    assert script.name() == "dio_agent_observer_claude"
    assert script.worldId() == QWebEngineScript.ScriptWorldId.ApplicationWorld
    assert script.injectionPoint() == QWebEngineScript.InjectionPoint.DocumentReady
    assert script.runsOnSubFrames() is False
    assert "WORKING_SEL" in script.sourceCode()


def test_dio_page_console_message_emits_agent_state(qapp):
    profile = QWebEngineProfile("test_agent_profile", None)
    page = DIOPage(profile, None)

    received_states = []
    page.agent_state_changed.connect(received_states.append)

    # Simular mensaje proveniente del observer inyectado
    test_msg = f"{AGENT_STATE_PREFIX}working"
    page.javaScriptConsoleMessage(
        QWebEnginePage.JavaScriptConsoleMessageLevel.InfoMessageLevel,
        test_msg,
        1,
        "observer.js",
    )

    assert len(received_states) == 1
    assert received_states[0] == "working"

    # Simular transicion a done
    done_msg = f"{AGENT_STATE_PREFIX}done"
    page.javaScriptConsoleMessage(
        QWebEnginePage.JavaScriptConsoleMessageLevel.InfoMessageLevel,
        done_msg,
        1,
        "observer.js",
    )

    assert len(received_states) == 2
    assert received_states[1] == "done"


# ── Tests de Notificaciones Nativas Desacopladas ─────────────────────────────

def test_send_system_notification_nonblocking():
    with patch("shutil.which", return_value="/usr/bin/notify-send"), \
         patch("subprocess.Popen") as mock_popen:
        success = send_system_notification(
            title="D.I.O. Test",
            message="Respuesta lista",
            urgency="normal",
        )
        assert success is True
        assert mock_popen.called
        args, kwargs = mock_popen.call_args
        cmd = args[0]
        assert cmd[0] == "/usr/bin/notify-send"
        assert "-a" in cmd and "D.I.O." in cmd
        assert "-u" in cmd and "normal" in cmd
        assert "D.I.O. Test" in cmd
        assert "Respuesta lista" in cmd
        assert kwargs.get("start_new_session") is True


def test_send_system_notification_missing_binary():
    with patch("shutil.which", return_value=None):
        success = send_system_notification("Titulo", "Cuerpo")
        assert success is False
