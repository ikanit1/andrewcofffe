# Кнопка «Касса»: поднимает сервер, если он не запущен, и открывает кассу на весь экран.
# Безопасно запускать повторно — второй сервер не поднимется, просто откроется окно.
$ErrorActionPreference = "Stop"
chcp 65001 > $null
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$port = 8080
$venvPy = Join-Path $root ".venv\Scripts\python.exe"
$envPath = Join-Path $root ".env"

function Fail($text) {
    Write-Host ""
    Write-Host $text -ForegroundColor Red
    Write-Host "Запустите start.ps1 — он развернёт окружение и всё настроит." -ForegroundColor Yellow
    Write-Host ""
    Read-Host "Enter — закрыть"
    exit 1
}

if (-not (Test-Path $venvPy)) { Fail "Нет виртуального окружения (.venv)." }
if (-not (Test-Path $envPath)) { Fail "Нет файла настроек (.env)." }

# Уже запущен? Тогда только открываем окно.
$busy = $false
try {
    if (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction Stop) { $busy = $true }
} catch { }

if (-not $busy) {
    Write-Host "Запускаю сервер кассы…" -ForegroundColor Cyan
    Start-Process powershell -WindowStyle Hidden -ArgumentList @(
        "-ExecutionPolicy", "Bypass", "-File", (Join-Path $PSScriptRoot "run-server.ps1")
    )
} else {
    Write-Host "Сервер уже работает." -ForegroundColor Green
}

# run-kiosk.ps1 сам ждёт готовности сервера и открывает окно кассы
& (Join-Path $PSScriptRoot "run-kiosk.ps1")
