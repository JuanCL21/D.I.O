# D.I.O. — Script de empaquetado para Windows con PyInstaller.
# Genera un ejecutable standalone en dist\dio.exe.

Write-Host "═══════════════════════════════════════════"
Write-Host " D.I.O. — Empaquetado (Windows)"
Write-Host "═══════════════════════════════════════════"

# Verificar que PyInstaller está instalado
try {
    python -m PyInstaller --version | Out-Null
} catch {
    Write-Host "[!] PyInstaller no encontrado. Instalando…"
    pip install pyinstaller
}

# Limpiar builds anteriores
if (Test-Path build)  { Remove-Item -Recurse -Force build }
if (Test-Path dist)   { Remove-Item -Recurse -Force dist }
Get-ChildItem -Filter "*.spec" | Remove-Item -Force

# Empaquetar como ejecutable único
python -m PyInstaller `
    --onefile `
    --name dio `
    --add-data "config.py;." `
    --hidden-import PyQt6.QtWebEngineWidgets `
    --hidden-import PyQt6.QtWebEngineCore `
    --noconfirm `
    --clean `
    dio.py

Write-Host ""
Write-Host "✓ Ejecutable generado en: dist\dio.exe"
Write-Host "  Ejecutar con: .\dist\dio.exe"
