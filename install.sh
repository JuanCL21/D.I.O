#!/usr/bin/env bash
# ==============================================================================
#  D.I.O. (Divisor Integrado Operativo) — Instalador Automático (Linux / macOS)
# ==============================================================================
set -e

REPO_URL="https://github.com/JuanCL21/D.I.O.git"
DEFAULT_TARGET_DIR="${HOME}/.local/share/dio"

BOLD='\033[1m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${BOLD}${CYAN}════════════════════════════════════════════════════════════════${NC}"
echo -e "${BOLD}${CYAN}   D.I.O. (Divisor Integrado Operativo) — Instalador Automático  ${NC}"
echo -e "${BOLD}${CYAN}════════════════════════════════════════════════════════════════${NC}\n"

# 1. Determinar directorio de instalación
if [ -f "$(pwd)/dio.py" ]; then
    INSTALL_DIR="$(pwd)"
    echo -e "${GREEN}✓ Ejecutando desde directorio del proyecto:${NC} ${INSTALL_DIR}"
elif [ -n "${BASH_SOURCE[0]:-}" ] && [ -f "$(dirname "${BASH_SOURCE[0]}")/dio.py" ]; then
    INSTALL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    echo -e "${GREEN}✓ Directorio del proyecto detectado:${NC} ${INSTALL_DIR}"
else
    INSTALL_DIR="${DEFAULT_TARGET_DIR}"
    echo -e "${CYAN}→ Instalando en:${NC} ${INSTALL_DIR}"
    if [ ! -d "${INSTALL_DIR}" ]; then
        echo -e "${CYAN}→ Clonando repositorio público desde GitHub...${NC}"
        mkdir -p "$(dirname "${INSTALL_DIR}")"
        git clone "${REPO_URL}" "${INSTALL_DIR}"
    else
        echo -e "${CYAN}→ Actualizando repositorio existente...${NC}"
        git -C "${INSTALL_DIR}" pull origin main || true
    fi
fi

cd "${INSTALL_DIR}"

# 2. Verificar Python 3
if ! command -v python3 &>/dev/null; then
    echo -e "${RED}[✗] Error: Python 3 no está instalado en este equipo.${NC}"
    echo -e "    En Debian/Ubuntu instálalo con: ${YELLOW}sudo apt update && sudo apt install -y python3 python3-pip python3-venv${NC}"
    exit 1
fi

PY_VERSION=$(python3 --version 2>&1)
echo -e "${GREEN}✓ Python detectado:${NC} ${PY_VERSION}"

# 3. Crear entorno virtual (con soporte para sistemas de archivos de red/SSHFS)
echo -e "\n${CYAN}→ Configurando entorno virtual Python (venv)...${NC}"
VENV_DIR="${INSTALL_DIR}/venv"

# Si crear venv en el directorio actual falla (por ejemplo, en montajes SSHFS/NFS), usar ~/.local/share/dio/venv
if ! python3 -m venv "${VENV_DIR}" 2>/dev/null; then
    echo -e "${YELLOW}[!] Sistema de archivos con restricciones detectado, creando venv en almacenamiento local...${NC}"
    VENV_DIR="${HOME}/.local/share/dio/venv"
    mkdir -p "${HOME}/.local/share/dio"
    rm -rf "${VENV_DIR}"
    python3 -m venv "${VENV_DIR}" || {
        echo -e "${RED}[✗] Error al crear entorno virtual.${NC}"
        echo -e "    En Debian/Ubuntu ejecute: ${YELLOW}sudo apt install -y python3-venv python3-pip${NC}"
        exit 1
    }
fi
echo -e "${GREEN}✓ Entorno virtual preparado en:${NC} ${VENV_DIR}"

# 4. Instalar dependencias
echo -e "\n${CYAN}→ Instalando dependencias (PyQt6, QtWebEngine, browser-cookie3)...${NC}"
"${VENV_DIR}/bin/pip" install --upgrade pip --quiet
"${VENV_DIR}/bin/pip" install -r "${INSTALL_DIR}/requirements.txt" --quiet
echo -e "${GREEN}✓ Dependencias instaladas correctamente.${NC}"

# 5. Crear binario lanzador en ~/.local/bin/dio
mkdir -p "${HOME}/.local/bin"
LAUNCHER="${HOME}/.local/bin/dio"
cat << 'LAUNCHER_EOF' > "${LAUNCHER}"
#!/usr/bin/env bash
PROJECT_DIR="__PROJECT_DIR__"
VENV_PYTHON="__VENV_PYTHON__"
exec "${VENV_PYTHON}" "${PROJECT_DIR}/dio.py" "$@"
LAUNCHER_EOF

sed -i "s|__PROJECT_DIR__|${INSTALL_DIR}|g" "${LAUNCHER}"
sed -i "s|__VENV_PYTHON__|${VENV_DIR}/bin/python3|g" "${LAUNCHER}"
chmod +x "${LAUNCHER}"
echo -e "${GREEN}✓ Lanzador de terminal creado en:${NC} ${LAUNCHER}"

# 6. Crear acceso directo en el menú de aplicaciones de escritorio (.desktop)
mkdir -p "${HOME}/.local/share/applications"
ICON_PATH="${INSTALL_DIR}/assets/icon.png"
if [ ! -f "${ICON_PATH}" ]; then
    ICON_PATH="web-browser"
fi

cat << DESKTOP_EOF > "${HOME}/.local/share/applications/dio.desktop"
[Desktop Entry]
Name=D.I.O.
GenericName=Divisor Integrado Operativo
Comment=Grid de navegadores web con sesiones aisladas
Exec="${VENV_DIR}/bin/python3" "${INSTALL_DIR}/dio.py"
Path=${INSTALL_DIR}
Icon=${ICON_PATH}
Type=Application
Categories=Utility;Network;WebBrowser;Development;
Terminal=false
StartupNotify=true
StartupWMClass=D.I.O.
Keywords=browser;grid;dio;ia;chatgpt;claude;whatsapp;
Actions=IA;WhatsApp;Correos;LowMemory;

[Desktop Action IA]
Name=Iniciar Preset IAs (2x3)
Exec="${VENV_DIR}/bin/python3" "${INSTALL_DIR}/dio.py" --grid 2x3 --preset ia_grid

[Desktop Action WhatsApp]
Name=Iniciar Preset WhatsApp (2x2)
Exec="${VENV_DIR}/bin/python3" "${INSTALL_DIR}/dio.py" --grid 2x2 --preset whatsapp_4

[Desktop Action Correos]
Name=Iniciar Preset Correos (2x4)
Exec="${VENV_DIR}/bin/python3" "${INSTALL_DIR}/dio.py" --grid 2x4 --preset correos_8

[Desktop Action LowMemory]
Name=Iniciar en Modo Bajo Consumo
Exec="${VENV_DIR}/bin/python3" "${INSTALL_DIR}/dio.py" --low-memory
DESKTOP_EOF

chmod +x "${HOME}/.local/share/applications/dio.desktop"

if command -v update-desktop-database &>/dev/null; then
    update-desktop-database "${HOME}/.local/share/applications" 2>/dev/null || true
fi

echo -e "\n${BOLD}${GREEN}════════════════════════════════════════════════════════════════${NC}"
echo -e "${BOLD}${GREEN}   ¡Instalación de D.I.O. completada con éxito!                 ${NC}"
echo -e "${BOLD}${GREEN}════════════════════════════════════════════════════════════════${NC}"
echo -e "  ${BOLD}Formas de uso:${NC}"
echo -e "  1. Busca ${CYAN}'D.I.O.'${NC} en el menú de aplicaciones de tu sistema."
echo -e "  2. Escribe ${CYAN}dio${NC} en cualquier terminal."
echo -e "  3. Ejecuta directamente: ${CYAN}${VENV_DIR}/bin/python3 ${INSTALL_DIR}/dio.py${NC}\n"
