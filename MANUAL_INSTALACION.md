# Manual de Instalacion y Configuracion — D.I.O. (Divisor Integrado Operativo)

Este documento detalla los requerimientos tecnicos, dependencias del sistema y procedimientos de instalacion para desplegar D.I.O. en entornos Linux, Windows y macOS.

---

## 1. Descripcion General

D.I.O. (Divisor Integrado Operativo) es una aplicacion de escritorio desarrollada en Python y QtWebEngine (Chromium) que permite ejecutar multiples instancias web en una cuadricula personalizable a pantalla completa, manteniendo perfiles de sesion independientes y persistentes para cada panel.

---

## 2. Requerimientos del Sistema

* **Sistema Operativo:**
  * Linux: Debian 11+, Ubuntu 20.04+, Arch Linux, Fedora 36+ (Compatible con X11, Wayland y Hyprland).
  * Windows: Windows 10 / Windows 11 (64-bit).
  * macOS: macOS 11 Big Sur o superior.
* **Python:** Version 3.10, 3.11, 3.12 o 3.13 (64-bit).
* **Memoria RAM:** Minimo 4 GB (Recomendado 8 GB o mas para grids de 4 o mas paneles activos).
* **Almacenamiento:** 500 MB de espacio libre para perfiles de navegacion y cache.

---

## 3. Dependencias del Proyecto

### 3.1 Dependencias Python (`requirements.txt`)

* `PyQt6 >= 6.6.0`: Framework principal de interfaz grafica.
* `PyQt6-WebEngine >= 6.6.0`: Motor de renderizado web basado en Chromium.
* `browser-cookie3 >= 0.19.0`: Modulo para importacion de cookies y sesiones desde navegadores instalados.

### 3.2 Dependencias de Desarrollo y Pruebas (`requirements-dev.txt`)

* `pytest >= 7.0.0`: Framework de ejecucion de pruebas unitarias y de integracion.
* `pytest-qt >= 4.2.0`: Extension de pruebas automatizadas para interfaces Qt.
* `pytest-mock >= 3.10.0`: Libreria de simulacion y mocks para pruebas.

---

## 4. Instalacion Paso a Paso

### 4.1 Instalacion en Linux (Debian / Ubuntu / Linux Mint)

1. Clonar el repositorio o descargar el codigo fuente:
   ```bash
   git clone https://github.com/tu-usuario/D.I.O.git
   cd D.I.O
   ```

2. Instalar dependencias del sistema y Python (si no estan instaladas):
   ```bash
   sudo apt update
   sudo apt install -y python3 python3-pip python3-venv
   ```

3. Crear y activar un entorno virtual:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   ```

4. Instalar las dependencias de Python:
   ```bash
   pip install --upgrade pip
   pip install -r requirements.txt
   ```

5. Opcional: Instalar el acceso directo de escritorio:
   ```bash
   chmod +x build.sh
   ./build.sh
   ```

---

### 4.2 Instalacion en Linux (Arch Linux / Manjaro)

```bash
cd D.I.O
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

---

### 4.3 Instalacion en Windows (PowerShell)

1. Abrir PowerShell en el directorio del proyecto:
   ```powershell
   cd D.I.O
   ```

2. Crear y activar entorno virtual:
   ```powershell
   python -m venv venv
   .\venv\Scripts\Activate.ps1
   ```

3. Instalar librerias requeridas:
   ```powershell
   python -m pip install --upgrade pip
   pip install -r requirements.txt
   ```

4. Opcional: Generar ejecutable (.exe) usando el script de compilacion:
   ```powershell
   .\build.ps1
   ```

---

### 4.4 Instalacion en macOS

1. Abrir Terminal en la carpeta del proyecto:
   ```bash
   cd D.I.O
   ```

2. Crear entorno virtual:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

---

## 5. Modos de Ejecucion

Una vez instalado, D.I.O. se ejecuta directamente con Python pasando los parametros deseados:

```bash
# Ejecucion estandar (Grid 2x2 con preset de Inteligencias Artificiales)
python3 dio.py

# Grid 2x3 con preset personalizado
python3 dio.py --grid 2x3 --preset ia_grid

# Grid 2x2 para 4 cuentas de WhatsApp Web
python3 dio.py --grid 2x2 --preset whatsapp_4

# Grid 2x4 para 8 bandejas de correo
python3 dio.py --grid 2x4 --preset correos_8

# Modo bajo consumo de memoria (Desactiva aceleracion GPU en equipos modestos)
python3 dio.py --low-memory

# Seleccionar monitor especifico en configuraciones multimonitor
python3 dio.py --monitor 1
```

---

## 6. Parametros de Linea de Comandos

| Parametro | Descripcion | Valor Predeterminado |
|---|---|---|
| `--grid RxC` | Dimensiones de la cuadricula (Filas x Columnas). Ejemplos: `2x2`, `2x3`, `3x3`. | `2x2` |
| `--preset NOMBRE` | Nombre del perfil de URLs definido en la configuracion. | `ia_grid` |
| `--config RUTA` | Ruta a un archivo `config.json` alternativo. | `~/.dio/config.json` |
| `--monitor N` | Indice del monitor donde se mostrara la ventana (0 = principal). | `0` |
| `--low-memory` | Reduce el consumo de RAM/VRAM limitando procesos y GPU. | `False` |
| `--no-dark-mode` | Desactiva el modo oscuro forzado en los paneles. | `False` |
| `--no-adblock` | Desactiva el bloqueo de publicidad y rastreadores. | `False` |
| `--ask-download-location` | Solicita confirmacion de ruta antes de cada descarga. | `False` |

---

## 7. Atajos de Teclado Globales

* `F11`: Alternar entre modo pantalla completa y modo ventana normal.
* `Ctrl + Shift + R`: Recargar todos los paneles de forma simultanea.
* `Ctrl + Shift + A`: Silenciar o reactivar el audio de todos los paneles.
* `Ctrl + M`: Silenciar o reactivar el audio del panel activo.
* `Ctrl + Shift + I`: Abrir dialogo de importacion de cookies desde navegadores del sistema.
* `Escape`: Salir de la aplicacion de forma segura guardando el estado de la sesion.

---

## 8. Estructura de Archivos y Directorios

```text
D.I.O/
├── dio.py                  # Script principal y controlador de la aplicacion
├── config.py               # Manejo de configuracion, presets y persistencia
├── requirements.txt        # Dependencias de produccion
├── requirements-dev.txt    # Dependencias de desarrollo y testing
├── MANUAL_INSTALACION.md   # Manual de instalacion tecnica sin emojis
├── README.md               # Documentacion principal del repositorio
├── MANUAL.md               # Guia de usuario y referencia operativa
├── dio.desktop             # Archivo lanzador para entornos Linux (GNOME/KDE)
├── build.sh                # Script de empaquetado para Linux
├── build.ps1               # Script de empaquetado para Windows
├── assets/                 # Iconos y recursos graficos
├── config/                 # Archivos de configuracion por defecto
└── tests/                  # Suite de pruebas automatizadas
```

---

## 9. Solucion de Problemas Comunes

### Error: `ModuleNotFoundError: No module named 'PyQt6'`
* **Causa:** Las dependencias no fueron instaladas en el entorno Python activo.
* **Solucion:** Asegurese de activar el entorno virtual (`source venv/bin/activate`) y ejecutar `pip install -r requirements.txt`.

### Advertencias de Wayland en Linux
* **Causa:** El compositor Wayland puede requerir compatibilidad explicita con Qt.
* **Solucion:** Ejecute definiendo la variable de entorno:
  ```bash
  QT_QPA_PLATFORM=xcb python3 dio.py
  ```
  o
  ```bash
  QT_QPA_PLATFORM=wayland python3 dio.py
  ```
