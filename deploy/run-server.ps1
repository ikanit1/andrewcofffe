# Сервер кассы с авто-перезапуском при падении; журнал в logs/server.log.
$ErrorActionPreference = "Stop"
chcp 65001 > $null
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
# Без этого кириллица в журнале превращается в кашу
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"
# Оператор >> в PowerShell 5.1 пишет UTF-16, и журнал получается «буквами через
# пробел». Переключаем перенаправление на UTF-8.
$PSDefaultParameterValues['Out-File:Encoding'] = 'utf8'

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$py = Join-Path $root ".venv\Scripts\python.exe"
$logDir = Join-Path $root "logs"
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }
$log = Join-Path $logDir "server.log"

function Write-Log($text) {
    # Журнал не должен ронять сервер: если файл занят другим экземпляром,
    # просто пропускаем запись.
    try {
        "[{0}] {1}" -f (Get-Date -Format "dd.MM.yyyy HH:mm:ss"), $text |
            Add-Content -Path $log -Encoding utf8 -ErrorAction Stop
    } catch { }
}

if (-not (Test-Path $py)) {
    Write-Log "НЕТ окружения .venv — запустите start.ps1"
    exit 1
}

# Второй сервер на том же порту не поднимется: и задача автозапуска, и ярлык
# на столе могут сработать почти одновременно.
try {
    if (Get-NetTCPConnection -LocalPort 8080 -State Listen -ErrorAction Stop) {
        Write-Log "порт 8080 уже занят — сервер, похоже, запущен; выходим"
        exit 0
    }
} catch { }

# Признак для приложения: этот цикл поднимет сервер снова, если процесс выйдет.
# Только при нём кнопка обновления в админке может себя перезапустить.
$env:COFFEEPOS_SUPERVISED = "1"

while ($true) {
    Write-Log "запуск сервера"

    # Перенаправление делает cmd, а не PowerShell. Причина: uvicorn пишет журнал
    # в stderr, а PowerShell 5.1 заворачивает stderr нативной программы в объект
    # ошибки — при ErrorActionPreference=Stop это обрывало скрипт (автозапуск
    # молча не работал), а на Continue засоряло журнал блоками «CategoryInfo».
    & cmd /c "`"$py`" -m app.main >> `"$log`" 2>&1"
    $code = $LASTEXITCODE

    Write-Log "сервер завершился (код $code), перезапуск через 3 с"
    Start-Sleep -Seconds 3
}
