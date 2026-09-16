"""
D.I.O. — Inyección de scripts y estilos en QWebEngine.
Contiene la lógica de modo oscuro forzado y anti-detección de automatización.
"""

from PyQt6.QtWebEngineCore import QWebEngineScript


def make_dark_mode_script() -> QWebEngineScript:
    """Inyecta scripts y CSS para forzar modo oscuro en Claude, ChatGPT y sitios web."""
    script = QWebEngineScript()
    script.setName("dio_dark_mode_force")
    script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
    script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
    script.setRunsOnSubFrames(True)
    script.setSourceCode("""
(function() {
    function applyDarkMode() {
        if (!document.documentElement) return;
        try {
            document.documentElement.classList.remove('light');
            document.documentElement.classList.add('dark');
            document.documentElement.setAttribute('data-theme', 'dark');
            document.documentElement.style.colorScheme = 'dark';
            if (document.body) {
                document.body.classList.remove('light');
                document.body.classList.add('dark');
                document.body.setAttribute('data-theme', 'dark');
                document.body.style.colorScheme = 'dark';
            }
            if (window.localStorage) {
                localStorage.setItem('theme', 'dark');
                localStorage.setItem('claude_theme', 'dark');
                localStorage.setItem('color-scheme', 'dark');
            }
        } catch(e) {}
    }

    applyDarkMode();
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', applyDarkMode);
    }

    function injectCSS() {
        if (document.getElementById('dio-dark-mode-style')) return;
        var style = document.createElement('style');
        style.id = 'dio-dark-mode-style';
        style.textContent = `
            html, body, [data-theme="light"] {
                color-scheme: dark !important;
                background-color: #18181b !important;
                color: #f4f4f5 !important;
            }
            :root, html.dark, [data-theme="dark"], body {
                --bg-primary: #18181b !important;
                --bg-secondary: #27272a !important;
                --bg-tertiary: #3f3f46 !important;
                --bg-100: #09090b !important;
                --bg-200: #18181b !important;
                --bg-300: #27272a !important;
                --bg-400: #3f3f46 !important;
                --bg-500: #52525b !important;
                --text-primary: #f4f4f5 !important;
                --text-secondary: #a1a1aa !important;
                --text-tertiary: #71717a !important;
                --border-primary: #27272a !important;
                --border-secondary: #3f3f46 !important;
            }
            /* Claude específicos */
            .bg-bg-000, .bg-bg-100, .bg-bg-200, .bg-bg-300, main, nav, aside {
                background-color: #18181b !important;
                color: #f4f4f5 !important;
            }
        `;
        (document.head || document.documentElement).appendChild(style);
    }

    if (document.head || document.documentElement) {
        injectCSS();
    } else {
        document.addEventListener('DOMContentLoaded', injectCSS);
    }
})();
""")
    return script


def make_anti_detection_script() -> QWebEngineScript:
    """
    Inyecta JavaScript al momento de CREACIÓN del documento (antes de que
    cualquier script de Google pueda leer las propiedades) para ocultar las
    señales que delatan a QWebEngine como webview embebido:

    1. navigator.webdriver → false (Google lo usa como señal primaria)
    2. window.chrome.runtime → objeto simulado (Chrome real lo tiene)
    3. navigator.plugins → array con plugins falsos (Chrome real tiene >0)
    4. navigator.languages → ['es-CO', 'es', 'en'] (evita array vacío)
    """
    script = QWebEngineScript()
    script.setName("dio_anti_detection")
    script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
    script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
    script.setRunsOnSubFrames(True)
    script.setSourceCode("""
(function() {
    // 1. navigator.webdriver = false
    Object.defineProperty(navigator, 'webdriver', {
        get: function() { return false; },
        configurable: true
    });

    // 2. window.chrome con runtime simulado
    if (!window.chrome) {
        window.chrome = {};
    }
    if (!window.chrome.runtime) {
        window.chrome.runtime = {
            connect: function() { return {}; },
            sendMessage: function() {},
            onMessage: { addListener: function() {} },
            id: undefined
        };
    }

    // 3. navigator.plugins con al menos un plugin (Chrome real tiene varios)
    try {
        Object.defineProperty(navigator, 'plugins', {
            get: function() {
                return [{
                    name: 'Chrome PDF Plugin',
                    description: 'Portable Document Format',
                    filename: 'internal-pdf-viewer',
                    length: 1
                }];
            },
            configurable: true
        });
    } catch(e) {}

    // 4. navigator.languages (evita array vacío que delata webviews)
    try {
        Object.defineProperty(navigator, 'languages', {
            get: function() { return ['es-CO', 'es', 'en-US', 'en']; },
            configurable: true
        });
    } catch(e) {}
})();
""")
    return script


_make_dark_mode_script = make_dark_mode_script
_make_anti_detection_script = make_anti_detection_script
