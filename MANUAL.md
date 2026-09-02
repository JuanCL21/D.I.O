# Manual de Usuario — D.I.O. (Divisor Integrado Operativo)

D.I.O. es un entorno de escritorio multipanel que ejecuta multiples instancias independientes y aisladas de Chromium (mediante PyQt6 y QtWebEngine) en una cuadricula simetrica a pantalla completa sin bordes ni distracciones.

---

## 1. Atajos de Teclado (Comandos Rapidos)

Dentro de D.I.O., todo el control de navegacion, ventanas, volumen y paneles se realiza mediante combinaciones de teclado:

| Atajo de Teclado | Accion | Descripcion |
|---|---|---|
| F1 | Configuracion y Manual | Abre o cierra el panel modal con las opciones de configuracion y manual interactivo. |
| Ctrl + Shift + N | Nueva Ventana D.I.O. | Lanza una nueva instancia independiente de D.I.O. |
| Ctrl + N | Nuevo Panel | Agrega un nuevo panel a la cuadricula actual solicitando la URL o termino de busqueda. |
| Ctrl + W | Cerrar Panel | Cierra y destruye el panel activo, reorganizando automaticamente el grid restante. |
| Ctrl + E | Nivelar / Equilibrar Grid | Reorganiza y equilibra instantaneamente el tamano de todas las ventanas de forma simetrica. |
| Ctrl + Alt + 3 / 6 | 3 Columnas x 2 Filas | Reorganiza directamente la cuadricula en 3 columnas y 2 filas (2x3). |
| Ctrl + Alt + 2 / 4 | 2 Columnas x 2 Filas | Reorganiza directamente la cuadricula en 2 columnas y 2 filas (2x2). |
| Ctrl + Alt + 1 | 3 Columnas Horizontales | Reorganiza en 3 columnas en una sola fila (1x3). |
| Ctrl + G | Menu de Cuadricula | Abre el selector rapido para elegir entre distintas disposiciones (2x3, 3x2, 2x2, 1x3). |
| Ctrl + L | Navegar o Buscar | Abre el Omnibox en el panel activo para escribir una URL o buscar en la web. |
| Ctrl + 1 a 9 | Foco Directo | Mueve el foco del teclado inmediatamente al panel correspondiente (1 al 9). |
| Ctrl + R | Recargar Panel | Recarga la pagina web del panel que tiene el foco. |
| Ctrl + Shift + R | Recargar Todo | Recarga todos los paneles de la pantalla simultaneamente. |
| Alt + Flecha Izquierda | Atras | Retrocede en el historial de navegacion del panel activo. |
| Alt + Flecha Derecha | Adelante | Avanza en el historial de navegacion del panel activo. |
| Ctrl + M | Silenciar / Activar Audio | Alterna el audio del panel activo. |
| Ctrl + Shift + A | Silenciar Todo | Silencia o reactiva el audio de todos los paneles a la vez. |
| Ctrl + Shift + I | Importar Sesion / Cookies | Abre el asistente para importar cookies de navegadores del sistema. |
| F11 | Pantalla Completa | Alterna entre modo pantalla completa y ventana estandar. |
| Escape / Ctrl + Q | Salir y Guardar | Cierra D.I.O. guardando el estado actual de los paneles en `~/.dio/session.json`. |

---

## 2. Acceso Directo y Menu de Aplicaciones

D.I.O. cuenta con integracion directa en el sistema operativo:
* **Menu de Aplicaciones / Lanzador**: Busca "D.I.O." en el menu de aplicaciones de tu entorno (GNOME, KDE, XFCE, Rofi, Wofi).
* **Escritorio**: Acceso directo disponible en `~/Escritorio/dio.desktop`.
* **Menu contextual**: Al hacer clic derecho sobre el icono en el menu o dock, puedes iniciar directamente presets especificos ("Iniciar Preset IAs", "Iniciar Preset WhatsApp", "Iniciar Preset Correos", "Modo Bajo Consumo").

---

## 3. Comandos de Inicio y Parametros (CLI)

D.I.O. se puede ejecutar desde la terminal mediante `python3 dio.py` con las siguientes opciones:

```bash
python3 dio.py [OPCIONES]
```

### Opciones Disponibles:

| Argumento | Ejemplo | Descripcion | Valor por Defecto |
|---|---|---|---|
| `--grid RxC` | `--grid 2x3` | Define el numero de Filas (R) x Columnas (C). | `2x2` |
| `--preset NOMBRE` | `--preset ia_grid` | Carga un conjunto predefinido de URLs. | `ia_grid` |
| `--monitor N` | `--monitor 1` | Abre la aplicacion en el monitor indicado (0=principal, 1=secundario). | `0` |
| `--low-memory` | `--low-memory` | Desactiva aceleracion por GPU para ahorrar RAM y VRAM. | Desactivado |
| `--no-dark-mode` | `--no-dark-mode` | Desactiva la inyeccion de modo oscuro forzado. | Desactivado |
| `--no-adblock` | `--no-adblock` | Desactiva el motor de bloqueo de anuncios y rastreadores. | Desactivado |
| `--ask-download-location` | `--ask-download-location` | Pregunta la carpeta de destino en cada descarga. | Desactivado |

---

## 4. Estructura de Configuracion (`config.json`)

El archivo de configuracion se almacena en `~/.dio/config.json`. Puede ser editado directamente con cualquier editor de texto para anadir o modificar presets de URLs:

```json
{
  "active_preset": "ia_grid",
  "presets": {
    "ia_grid": [
      "https://gemini.google.com",
      "https://chatgpt.com",
      "https://claude.ai",
      "https://deepseek.com"
    ],
    "whatsapp_4": [
      "https://web.whatsapp.com",
      "https://web.whatsapp.com",
      "https://web.whatsapp.com",
      "https://web.whatsapp.com"
    ]
  },
  "default_grid": "2x2",
  "dark_mode": true,
  "adblock_enabled": true,
  "auto_grant_permissions": true
}
```
