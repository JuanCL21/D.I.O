#!/usr/bin/env bash
# D.I.O. — Script de empaquetado para Linux/macOS con PyInstaller.
# Genera un ejecutable standalone en dist/dio.
set -euo pipefail

echo "═══════════════════════════════════════════"
echo " D.I.O. — Empaquetado (Linux/macOS)"
echo "═══════════════════════════════════════════"

# Verificar que PyInstaller está instalado
if ! python3 -m PyInstaller --version &>/dev/null; then
    echo "[!] PyInstaller no encontrado. Instalando…"
    pip install pyinstaller
fi

# Limpiar builds anteriores
rm -rf build/ dist/ *.spec

# Empaquetar como ejecutable único
python3 -m PyInstaller \
    --onefile \
    --name dio \
    --add-data "config.py:." \
    --hidden-import PyQt6.QtWebEngineWidgets \
    --hidden-import PyQt6.QtWebEngineCore \
    --noconfirm \
    --clean \
    dio.py

echo ""
echo "✓ Ejecutable generado en: dist/dio"
echo "  Ejecutar con: ./dist/dio"
echo "  Copiar a PATH: sudo cp dist/dio /usr/local/bin/"
