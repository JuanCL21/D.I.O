# ==============================================================================
#  D.I.O. (Divisor Integrado Operativo) — Instalador Automático para Windows
# ==============================================================================
$ErrorActionPreference = "Stop"

$RepoUrl = "https://github.com/JuanCL21/D.I.O.git"
$InstallDir = "$env:USERPROFILE\.dio-app"

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "   D.I.O. (Divisor Integrado Operativo) — Instalador Windows" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan

# 1. Determinar directorio
if (Test-Path "$PSScriptRoot\dio.py") {
    $InstallDir = $PSScriptRoot
    Write-Host "[✓] Usando directorio actual: $InstallDir" -ForegroundColor Green
} else {
    Write-Host "[*] Descargando D.I.O. en $InstallDir..." -ForegroundColor Cyan
    if (!(Test-Path $InstallDir)) {
        git clone $RepoUrl $InstallDir
    } else {
        Set-Location $InstallDir
        git pull origin main
    }
}

Set-Location $InstallDir

# 2. Verificar Python
try {
    $pyVersion = python --version
    Write-Host "[✓] Python detectado: $pyVersion" -ForegroundColor Green
} catch {
    Write-Host "[✗] Error: Python no esta instalado o no esta en el PATH." -ForegroundColor Red
    Write-Host "    Descargalo desde https://www.python.org/downloads/ y marca 'Add Python to PATH'." -ForegroundColor Yellow
    exit 1
}

# 3. Entorno virtual
Write-Host "[*] Creando entorno virtual..." -ForegroundColor Cyan
if (!(Test-Path "venv")) {
    python -m venv venv
}

# 4. Instalar dependencias
Write-Host "[*] Instalando dependencias..." -ForegroundColor Cyan
.\venv\Scripts\python.exe -m pip install --upgrade pip --quiet
.\venv\Scripts\python.exe -m pip install -r requirements.txt --quiet

# 5. Crear acceso directo en el Escritorio
$WshShell = New-Object -ComObject WScript.Shell
$ShortcutPath = "$env:USERPROFILE\Desktop\D.I.O.lnk"
$Shortcut = $WshShell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = "$InstallDir\venv\Scripts\pythonw.exe"
$Shortcut.Arguments = "`"$InstallDir\dio.py`""
$Shortcut.WorkingDirectory = $InstallDir
if (Test-Path "$InstallDir\assets\icon.ico") {
    $Shortcut.IconLocation = "$InstallDir\assets\icon.ico"
}
$Shortcut.Description = "Divisor Integrado Operativo"
$Shortcut.Save()

Write-Host "============================================================" -ForegroundColor Green
Write-Host " ¡Instalacion completada con exito!" -ForegroundColor Green
Write-Host " Acceso directo creado en tu Escritorio: D.I.O." -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
