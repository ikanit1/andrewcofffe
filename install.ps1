# Установщик Coffee POS для Windows. Запуск: правой кнопкой -> Run with PowerShell
$ErrorActionPreference = "Stop"

# 1. Самоподнятие до администратора (нужно для schtasks/winget)
$admin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()
    ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) {
    Start-Process powershell "-ExecutionPolicy Bypass -File `"$PSCommandPath`"" -Verb RunAs
    exit
}

$root = $PSScriptRoot
Set-Location $root
Write-Host "=== Установка Coffee POS ===" -ForegroundColor Cyan

# 2. Python: подойдёт любой 3.11+, а не только 3.13 — на машине может стоять
#    более новый, и winget есть не везде, поэтому жёстко на него не завязываемся.
function Find-SystemPython {
    foreach ($c in @(@("py","-3.13"), @("py","-3.12"), @("py","-3.11"), @("py","-3"), @("python"))) {
        try {
            $exe = $c[0]
            $prefix = if ($c.Count -gt 1) { $c[1] } else { $null }
            $a = if ($prefix) { @($prefix,"-c","import sys;print(sys.version_info[:2])") }
                 else { @("-c","import sys;print(sys.version_info[:2])") }
            $out = & $exe @a 2>$null
            if ($LASTEXITCODE -eq 0 -and $out -match '\((\d+), (\d+)\)') {
                if ([int]$Matches[1] -eq 3 -and [int]$Matches[2] -ge 11) {
                    return @{ Exe = $exe; Prefix = $prefix }
                }
            }
        } catch { }
    }
    return $null
}

# 3. venv + зависимости
if (-not (Test-Path (Join-Path $root ".venv"))) {
    $sysPy = Find-SystemPython
    if (-not $sysPy) {
        $wg = Get-Command winget -ErrorAction SilentlyContinue
        if ($wg) {
            Write-Host "Python 3.11+ не найден — ставлю через winget..." -ForegroundColor Yellow
            winget install -e --id Python.Python.3.13 --accept-source-agreements --accept-package-agreements
            Write-Host "Закройте окно и запустите install.ps1 заново — нужен обновлённый PATH." -ForegroundColor Yellow
            Read-Host "Enter — закрыть"
            exit 1
        }
        Write-Host "Python 3.11+ не найден, winget на этой машине тоже нет." -ForegroundColor Red
        Write-Host "Скачайте Python с https://www.python.org/downloads/ (галочка «Add python.exe to PATH»)" -ForegroundColor Yellow
        Start-Process "https://www.python.org/downloads/"
        Read-Host "Enter — закрыть"
        exit 1
    }
    if ($sysPy.Prefix) { & $sysPy.Exe $sysPy.Prefix -m venv .venv }
    else { & $sysPy.Exe -m venv .venv }
}
$venvPy = Join-Path $root ".venv\Scripts\python.exe"
& $venvPy -m pip install --upgrade pip
& $venvPy -m pip install -r requirements.txt

# 4. .env (если нет)
$envPath = Join-Path $root ".env"
if (-not (Test-Path $envPath)) {
    # Не [RandomNumberGenerator]::GetBytes(int) — статический оверлоад появился
    # только в .NET 6+, а в Windows PowerShell 5.1 (.NET Framework) его нет.
    $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
    $secretBytes = New-Object byte[] 32
    $rng.GetBytes($secretBytes)
    $rng.Dispose()
    $secret = [Convert]::ToBase64String($secretBytes)
    $token = Read-Host "Токен Telegram-бота (Enter — пропустить, бэкапы будут только локально)"
    # Строго без BOM: Set-Content -Encoding UTF8 в PowerShell 5.1 его добавляет,
    # и pydantic-settings читает первый ключ как "﻿BOT_TOKEN" — то есть теряет его.
    [System.IO.File]::WriteAllLines($envPath, [string[]]@(
        "BOT_TOKEN=$token"
        "STORAGE_SECRET=$secret"
        "PUBLIC_URL=http://localhost:8080"
        "DATABASE_URL=sqlite:///pos.db"
        "BACKUP_ENABLED=true"
        "BACKUP_TIME=03:00"
        "BACKUP_KEEP_DAYS=14"
        "BACKUPS_DIR=backups"
    ), [System.Text.UTF8Encoding]::new($false))
    Write-Host ".env создан (секрет сгенерирован)." -ForegroundColor Green
}

# 5. Заполнить базу, если пустая
$count = & $venvPy -c "from app.db import SessionLocal; from app.models import User; s=SessionLocal(); print(s.query(User).count()); s.close()"
if ($count.Trim() -eq "0") {
    $ownerId = Read-Host "Telegram ID владельца (для входа и бэкапов)"
    & $venvPy seed.py $ownerId
    Write-Host "Создан владелец (PIN 9999) и кассир (PIN 1234) — смените PIN после входа." -ForegroundColor Yellow
}

# 6. Задачи автозапуска (при входе в систему)
$srv = "powershell -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$root\deploy\run-server.ps1`""
$ksk = "powershell -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$root\deploy\run-kiosk.ps1`""
schtasks /Create /TN "CoffeePOS-Server" /TR $srv /SC ONLOGON /RL HIGHEST /F
schtasks /Create /TN "CoffeePOS-Kiosk"  /TR $ksk /SC ONLOGON /F

# 7. Ярлык на рабочем столе (в папке пользователя, права администратора не нужны)
& (Join-Path $root "deploy\install-shortcuts.ps1") -NoAutostart

# 8. Стартуем сейчас и открываем кассу
Start-Process powershell "-WindowStyle Hidden -ExecutionPolicy Bypass -File `"$root\deploy\run-server.ps1`""
for ($i = 0; $i -lt 60; $i++) {
    try { if ((Invoke-WebRequest -UseBasicParsing "http://localhost:8080/health" -TimeoutSec 2).StatusCode -eq 200) { break } } catch {}
    Start-Sleep -Seconds 1
}
Start-Process "http://localhost:8080"

Write-Host ""
Write-Host "Готово. Дальше:" -ForegroundColor Cyan
Write-Host " • Смените PIN владельца/кассира."
Write-Host " • Зарегистрируйте Kaspi-терминал: http://localhost:8080/admin/kaspi"
Write-Host " • Проверьте бэкап кнопкой «Сделать бэкап сейчас» в дашборде."
