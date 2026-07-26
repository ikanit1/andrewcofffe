# Coffee POS — запуск одной кнопкой: проверка окружения, сервер, браузер.
# Запуск: правой кнопкой по файлу -> Run with PowerShell. Остановить — Ctrl+C.
$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

# Консоль и Python на UTF-8, иначе кириллица в журнале сервера превращается в кашу
chcp 65001 > $null
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"

$root = $PSScriptRoot
if (-not $root) { $root = (Get-Location).Path }
Set-Location $root

$url = "http://localhost:8080"
$py = Join-Path $root ".venv\Scripts\python.exe"
$envPath = Join-Path $root ".env"

function Ok($t)   { Write-Host "  [ ok ] $t" -ForegroundColor Green }
function Warn($t) { Write-Host "  [ !  ] $t" -ForegroundColor Yellow }
function Bad($t)  { Write-Host "  [ xx ] $t" -ForegroundColor Red }
function Die($t) {
    Bad $t
    Write-Host ""
    Read-Host "Enter — закрыть"
    exit 1
}

Write-Host ""
Write-Host "=== Coffee POS ===" -ForegroundColor Cyan
Write-Host ""
Write-Host "Проверка перед запуском:"

# 1. Python-окружение
if (-not (Test-Path $py)) { Die "Нет папки .venv. Сначала запустите install.ps1 (установка с нуля)." }
Ok "Python-окружение на месте"

# 2. Настройки
if (-not (Test-Path $envPath)) { Die "Нет файла .env. Сначала запустите install.ps1." }
$token = ""
$secret = ""
foreach ($line in (Get-Content $envPath -Encoding UTF8)) {
    if ($line -match '^\s*BOT_TOKEN\s*=\s*(.*)$')       { $token = $Matches[1].Trim() }
    if ($line -match '^\s*STORAGE_SECRET\s*=\s*(.*)$')  { $secret = $Matches[1].Trim() }
}
if ($secret -eq "" -or $secret -eq "change-me-in-env") {
    Die "STORAGE_SECRET не задан в .env — без него сессии подделываемы, приложение не стартует."
}
Ok "Настройки (.env) прочитаны"

# 3. Telegram — единственная проверка, которая говорит правду: спросить сам Telegram
$botOk = $false
if ($token -eq "") {
    Warn "BOT_TOKEN пуст — Telegram отключён. Касса работает, но не будет уведомлений и бэкапов в чат."
} else {
    try {
        $me = Invoke-RestMethod -Uri "https://api.telegram.org/bot$token/getMe" -TimeoutSec 10
        $botOk = $true
        Ok "Telegram-бот на связи: @$($me.result.username)"
    } catch {
        Warn "Telegram не принял токен — бот не запустится, касса будет работать без него."
        Warn "Возьмите токен у @BotFather и впишите в .env в строку BOT_TOKEN="
    }
}

# 4. База
if (-not (Test-Path (Join-Path $root "pos.db"))) {
    Warn "Базы pos.db нет — будет создана пустая. Пользователей задаёт seed.py."
} else {
    $users = (& $py -c "from app.db import SessionLocal; from app.models import User; s=SessionLocal(); print(s.query(User).count()); s.close()") 2>$null
    if ($users -and $users.Trim() -ne "0") {
        Ok "База на месте, пользователей: $($users.Trim())"
    } else {
        Warn "В базе нет пользователей — войти не получится. Выполните: .venv\Scripts\python seed.py <ваш_telegram_id>"
    }
}

# 5. Порт
$busy = $false
try {
    if (Get-NetTCPConnection -LocalPort 8080 -State Listen -ErrorAction Stop) { $busy = $true }
} catch { }
if ($busy) { Die "Порт 8080 уже занят — касса, похоже, уже запущена. Откройте $url" }
Ok "Порт 8080 свободен"

# 6. Браузер откроется сам, когда сервер ответит на /health
Start-Job -ScriptBlock {
    param($u)
    for ($i = 0; $i -lt 60; $i++) {
        try {
            if ((Invoke-WebRequest -UseBasicParsing "$u/health" -TimeoutSec 2).StatusCode -eq 200) {
                Start-Process $u
                break
            }
        } catch { }
        Start-Sleep -Seconds 1
    }
} -ArgumentList $url | Out-Null

Write-Host ""
Write-Host "Запускаю сервер. Касса откроется в браузере: $url" -ForegroundColor Cyan
if ($botOk) {
    Write-Host "Telegram-бот запускается вместе с сервером." -ForegroundColor Cyan
} else {
    Write-Host "Telegram-бот НЕ запустится — см. предупреждение выше." -ForegroundColor Yellow
}
Write-Host "Остановить — Ctrl+C в этом окне." -ForegroundColor DarkGray
Write-Host ""
Write-Host "--- журнал сервера ---" -ForegroundColor DarkGray

# Сервер в этом же окне: журнал виден живьём, Ctrl+C останавливает
& $py -m app.main

Write-Host ""
Write-Host "Сервер остановлен." -ForegroundColor Cyan
Read-Host "Enter — закрыть"
