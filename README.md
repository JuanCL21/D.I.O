# D.I.O. — Divisor Integrado Operativo

Aplicacion de escritorio que renderiza multiples instancias web de Chromium en una cuadricula simetrica, dentro de una unica ventana a pantalla completa sin bordes. Ideal para monitorear en paralelo agentes de IA, cuentas de correo o WhatsApp Web, cada uno con sesion persistente e independiente.

---

## Caracteristicas Principales

* **Grid flexible**: Disposiciones 2x2, 2x3 o cualquier RxC personalizada con divisores arrastrables (QSplitter).
* **Sesiones aisladas**: Cada panel tiene su propio perfil Chromium persistente en disco (`~/.dio/profiles/panel_N/`). Inicia sesion una vez y queda registrado entre reinicios.
* **Persistencia de layout**: Al cerrar, guarda URLs actuales, tamanos de paneles y preset activo. Al reabrir, restaura el estado previo.
* **Configuracion externa**: Los presets se almacenan en `~/.dio/config.json`, editable sin tocar codigo Python.
* **Pantalla completa sin bordes**: Sin barra de titulo, sin barra de tareas, fondo oscuro para maxima productividad.
* **Indicador de carga**: Overlay visual con porcentaje por panel mientras las paginas cargan.
* **Control de Audio**: Silencia paneles individuales (`Ctrl+M`) o todos a la vez (`Ctrl+Shift+A`).
* **Permisos de hardware inteligentes**: Gestion automatica de permisos para microfono y camara en dominios confiables.
* **Gestion de descargas**: Guarda automaticamente en carpetas organizadas por preset o solicita confirmacion.
* **Modo oscuro forzado**: Activado por defecto via flags de Chromium y CSS de respaldo.
* **AdBlocker nativo**: Bloqueo de peticiones a redes de rastreo y anuncios.
* **Gestion de popups y OAuth**: Dialogos dedicados para flujos de autenticacion ("Continuar con Google/Microsoft").
* **Importacion de cookies**: Importa sesiones directamente desde navegadores instalados con `Ctrl+Shift+I`.
* **Multi-monitor**: Seleccion de pantalla para despliegue con `--monitor N`.
* **Modo bajo consumo**: Opcion `--low-memory` para optimizar consumo de RAM y VRAM.
* **Multiplataforma**: Linux (X11, Wayland, Hyprland), Windows 10/11 y macOS.

---

## Requisitos del Sistema

* Python 3.10 o superior (compatible con 3.11, 3.12 y 3.13).
* Gestor de paquetes `pip`.

---

## Instalación Súper Fácil (1 solo comando)

### En Linux / macOS:
```bash
curl -sSL https://raw.githubusercontent.com/JuanCL21/D.I.O/main/install.sh | bash
```

### En Windows (PowerShell):
```powershell
irm https://raw.githubusercontent.com/JuanCL21/D.I.O/main/install.ps1 | iex
```

---

## Instalación Manual

```bash
# 1. Clonar el repositorio (Público, no requiere contraseñas ni tokens)
git clone https://github.com/JuanCL21/D.I.O.git
cd D.I.O

# 2. Ejecutar instalador incluido
chmod +x install.sh
./install.sh
```

Para una guia detallada por sistema operativo, consulte [MANUAL_INSTALACION.md](MANUAL_INSTALACION.md).

---

## Modos de Uso

### Comandos de Ejemplo

```bash
# Grid 2x2 con preset predeterminado (IAs)
python3 dio.py

# Grid 2x3 con preset de Inteligencia Artificial
python3 dio.py --grid 2x3 --preset ia_grid

# Grid 2x2 para 4 instancias de WhatsApp Web
python3 dio.py --grid 2x2 --preset whatsapp_4

# Grid 2x4 para 8 bandejas de correo
python3 dio.py --grid 2x4 --preset correos_8

# Modo bajo consumo de memoria
python3 dio.py --low-memory

# Desactivar modo oscuro forzado o bloqueador de anuncios
python3 dio.py --no-dark-mode --no-adblock
```

---

## Argumentos de Linea de Comandos

| Argumento | Descripcion | Valor Predeterminado |
|---|---|---|
| `--grid RxC` | Filas x Columnas de la cuadricula (ej: `2x2`, `2x3`, `3x3`) | `2x2` |
| `--preset NOMBRE` | Nombre del preset definido en `~/.dio/config.json` | `ia_grid` |
| `--config RUTA` | Ruta a un archivo de configuracion alternativo | `~/.dio/config.json` |
| `--monitor N` | Monitor en el que se abrira la ventana (0, 1, 2...) | `0` |
| `--low-memory` | Reduce consumo de memoria desactivando GPU | `False` |
| `--no-dark-mode` | Desactiva el modo oscuro forzado | `False` |
| `--no-adblock` | Desactiva el bloqueo de publicidad | `False` |
| `--ask-download-location` | Pregunta donde guardar cada archivo descargado | `False` |

---

## Atajos de Teclado

| Teclas | Accion |
|---|---|
| `F11` | Alternar pantalla completa / ventana normal |
| `Ctrl + Shift + R` | Recargar todos los paneles |
| `Ctrl + Shift + A` | Silenciar o reactivar audio global |
| `Ctrl + M` | Silenciar o reactivar audio del panel activo |
| `Ctrl + Shift + D` | Desacoplar panel activo a ventana flotante independiente |
| `Ctrl + Alt + 1..9` | Conmutar entre los 9 workspaces virtuales independientes |
| `Ctrl + Shift + I` | Importar cookies desde navegador local |
| `Escape` | Salir guardando la sesion |

---

## Formato de Presets Compartibles

D.I.O. permite empaquetar la configuracion del usuario (`config.toml`) y sus adaptadores de IA personalizados (`~/.dio/adapters/*.json`) en un paquete comprimido (`.dio.tar.gz`) sin incluir cookies ni credenciales personales:

```bash
# Exportar preset actual con adapters
dio-cli export-preset --output mi_preset.dio.tar.gz --name "IA Cockpit" --description "Configuracion optimizada"

# Importar preset en otra maquina o cuenta
dio-cli import-preset mi_preset.dio.tar.gz --overwrite
```

---

## Seguridad y Privacidad de Perfiles

> [!WARNING]
> **ADVERTENCIA DE SEGURIDAD**: El directorio `~/.dio/profiles/` almacena perfiles persistentes de Chromium, incluyendo cookies, almacenamiento local (LocalStorage) y tokens de sesion web en texto plano (con permisos restrictivos de sistema de archivos `0700` para carpetas y `0600` para archivos).
> **NO sincronice `~/.dio/profiles` a servicios de backup o sincronizacion en la nube sin cifrado previo** (ej. Nextcloud, Dropbox, Google Drive, OneDrive o sincronizadores genericos). Para respaldar o transferir su configuracion de forma segura, utilice unicamente `dio-cli export-preset`, que exporta exclusivamente layouts y selectores sin exponer datos de sesion.

---

## Distribucion e Instalacion via AppImage

D.I.O. se distribuye tambien como un AppImage autonomo que empaqueta el runtime de Python, PyQt6, PyQt6-WebEngine y las librerias nativas requeridas para correr en cualquier distribucion Linux moderna sin instalacion previa:

```bash
# Otorgar permisos de ejecucion y lanzar
chmod +x D.I.O-x86_64.AppImage
./D.I.O-x86_64.AppImage
```

---

## Licencia

Este proyecto esta bajo licencia MIT. Consulte el archivo LICENSE para mas detalles.
