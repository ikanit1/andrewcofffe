# Запуск POS-сервера из venv с авто-перезапуском при падении; лог в logs/server.log
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$py = Join-Path $root ".venv\Scripts\python.exe"
$logDir = Join-Path $root "logs"
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }
$log = Join-Path $logDir "server.log"
while ($true) {
    "[{0}] запуск сервера" -f (Get-Date) | Add-Content $log
    & $py -m app.main *>> $log
    "[{0}] сервер завершился, перезапуск через 3с" -f (Get-Date) | Add-Content $log
    Start-Sleep -Seconds 3
}
