#!/usr/bin/env bash
# D.I.O. — Script de generacion de AppImage autonomo
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${ROOT_DIR}"

echo "=========================================="
echo "D.I.O. — Compilacion y empaquetado AppImage"
echo "=========================================="

# 1. Asegurar dependencias de build
if ! python3 -m PyInstaller --version >/dev/null 2>&1; then
    echo "[*] Instalando PyInstaller..."
    python3 -m pip install pyinstaller
fi

# 2. Limpiar compilaciones previas
echo "[*] Limpiando directorios de build..."
rm -rf build/ dist/dio dist/*.AppImage

# 3. Compilacion con PyInstaller
echo "[*] Compilando binario con PyInstaller..."
python3 -m PyInstaller \
    --onefile \
    --name dio \
    --add-data "dio:dio" \
    --add-data "assets:assets" \
    --hidden-import PyQt6.QtWebEngineWidgets \
    --hidden-import PyQt6.QtWebEngineCore \
    --hidden-import PyQt6.QtCore \
    --hidden-import PyQt6.QtGui \
    --hidden-import PyQt6.QtWidgets \
    --hidden-import PyQt6.QtNetwork \
    --noconfirm \
    --clean \
    dio.py

if [ ! -f "dist/dio" ]; then
    echo "[ERROR] Fallo la compilacion de dist/dio."
    exit 1
fi
echo "[OK] Binario generado en dist/dio"

# 4. Estructurar AppDir
echo "[*] Preparando estructura de AppDir..."
APPDIR="${ROOT_DIR}/build/AppDir"
rm -rf "${APPDIR}"
mkdir -p "${APPDIR}/usr/bin"
mkdir -p "${APPDIR}/usr/share/applications"
mkdir -p "${APPDIR}/usr/share/icons/hicolor/256x256/apps"

cp dist/dio "${APPDIR}/usr/bin/dio"
chmod +x "${APPDIR}/usr/bin/dio"

# Icono
cp assets/icon.png "${APPDIR}/dio.png"
cp assets/icon.png "${APPDIR}/usr/share/icons/hicolor/256x256/apps/dio.png"

# Archivo Desktop conforme al estandar AppImage
cat << 'EOF' > "${APPDIR}/dio.desktop"
[Desktop Entry]
Name=D.I.O.
GenericName=Divisor Integrado Operativo
Comment=Grid de navegadores web con sesiones aisladas
Exec=dio %u
Icon=dio
Type=Application
Categories=Utility;Network;WebBrowser;Development;
Terminal=false
StartupNotify=true
StartupWMClass=D.I.O.
EOF

cp "${APPDIR}/dio.desktop" "${APPDIR}/usr/share/applications/dio.desktop"

# Entrypoint AppRun
cp scripts/AppRun "${APPDIR}/AppRun"
chmod +x "${APPDIR}/AppRun"

# 5. Obtener appimagetool si no existe
echo "[*] Verificando appimagetool..."
APPIMAGE_TOOL=""
if command -v appimagetool >/dev/null 2>&1; then
    APPIMAGE_TOOL="appimagetool"
else
    mkdir -p tools
    if [ ! -f "tools/appimagetool" ]; then
        echo "[*] Descargando appimagetool..."
        curl -fsSL -o tools/appimagetool \
            "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage" || \
        curl -fsSL -o tools/appimagetool \
            "https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-x86_64.AppImage"
        chmod +x tools/appimagetool
    fi
    APPIMAGE_TOOL="${ROOT_DIR}/tools/appimagetool"
fi

# 6. Generar AppImage
OUTPUT_APPIMAGE="${ROOT_DIR}/dist/D.I.O-x86_64.AppImage"
echo "[*] Generando archivo AppImage en ${OUTPUT_APPIMAGE}..."

# Exportar ARCH requerido por appimagetool
export ARCH="x86_64"

# Si no hay FUSE disponible en el entorno de build, usar --appimage-extract-and-run
if [ -x "${APPIMAGE_TOOL}" ] && [ "${APPIMAGE_TOOL}" != "appimagetool" ]; then
    "${APPIMAGE_TOOL}" --appimage-extract-and-run "${APPDIR}" "${OUTPUT_APPIMAGE}" || \
    "${APPIMAGE_TOOL}" "${APPDIR}" "${OUTPUT_APPIMAGE}"
else
    appimagetool "${APPDIR}" "${OUTPUT_APPIMAGE}"
fi

chmod +x "${OUTPUT_APPIMAGE}"
echo "=========================================="
echo "[OK] AppImage generado exitosamente:"
echo "     ${OUTPUT_APPIMAGE}"
ls -lh "${OUTPUT_APPIMAGE}"
echo "=========================================="
