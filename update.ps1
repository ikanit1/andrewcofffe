# Обновление Coffee POS: тянем код, ставим зависимости, перезапускаем сервер
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
Set-Location $root
git pull
& (Join-Path $root ".venv\Scripts\python.exe") -m pip install -r requirements.txt
schtasks /End /TN "CoffeePOS-Server" 2>$null
Start-Sleep -Seconds 2
schtasks /Run /TN "CoffeePOS-Server"
Write-Host "Обновлено и перезапущено." -ForegroundColor Green
