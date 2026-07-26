# Coffee POS — единственный файл, который нужен для запуска.
# На чистой машине разворачивает всё с нуля, на настроенной просто стартует.
#
#   .\start.ps1            обычный запуск (только локальная сеть)
#   .\start.ps1 -Funnel    поднять Tailscale Funnel и обновить PUBLIC_URL
#   .\start.ps1 -NoBrowser не открывать браузер
#
# Запуск мышью: правой кнопкой -> Run with PowerShell. Остановить — Ctrl+C.
param(
    [switch]$Funnel,
    [switch]$NoBrowser
)

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

$port = 8080
$localUrl = "http://localhost:$port"
$venvPy = Join-Path $root ".venv\Scripts\python.exe"
$envPath = Join-Path $root ".env"
$depsMarker = Join-Path $root ".venv\.deps-hash"

function Ok($t)   { Write-Host "  [ ok ] $t" -ForegroundColor Green }
function Warn($t) { Write-Host "  [ !  ] $t" -ForegroundColor Yellow }
function Bad($t)  { Write-Host "  [ xx ] $t" -ForegroundColor Red }
function Step($t) { Write-Host ""; Write-Host $t -ForegroundColor Cyan }
function Die($t) {
    Bad $t
    Write-Host ""
    Read-Host "Enter — закрыть"
    exit 1
}

# --- Python ---------------------------------------------------------------
function Find-SystemPython {
    foreach ($c in @(@("py", "-3.13"), @("py", "-3.12"), @("py", "-3.11"), @("python"))) {
        try {
            $exe = $c[0]
            $prefix = if ($c.Count -gt 1) { $c[1] } else { $null }
            $args = if ($prefix) { @($prefix, "-c", "import sys;print(sys.version_info[:2])") }
                    else { @("-c", "import sys;print(sys.version_info[:2])") }
            $out = & $exe @args 2>$null
            if ($LASTEXITCODE -eq 0 -and $out -match '\((\d+), (\d+)\)') {
                if ([int]$Matches[1] -eq 3 -and [int]$Matches[2] -ge 11) {
                    return @{ Exe = $exe; Prefix = $prefix }
                }
            }
        } catch { }
    }
    return $null
}

function Invoke-SystemPython($py, $arguments) {
    if ($py.Prefix) { & $py.Exe $py.Prefix @arguments } else { & $py.Exe @arguments }
}

# --- .env -----------------------------------------------------------------
# .env пишем строго без BOM: Set-Content -Encoding UTF8 в PowerShell 5.1 его добавляет,
# и тогда pydantic-settings читает первый ключ как "﻿BOT_TOKEN" — то есть теряет его.
function Write-EnvLines($lines) {
    [System.IO.File]::WriteAllLines($envPath, [string[]]$lines, [System.Text.UTF8Encoding]::new($false))
}

function Read-EnvLines {
    if (-not (Test-Path $envPath)) { return @() }
    return [System.IO.File]::ReadAllLines($envPath)  # ReadAllLines снимает BOM, если он есть
}

function Get-EnvValue($key) {
    foreach ($line in (Read-EnvLines)) {
        if ($line -match "^\s*$key\s*=\s*(.*)$") { return $Matches[1].Trim() }
    }
    return $null
}

function Set-EnvValue($key, $value) {
    $lines = @()
    $found = $false
    foreach ($line in (Read-EnvLines)) {
        if ($line -match "^\s*$key\s*=") { $lines += "$key=$value"; $found = $true }
        else { $lines += $line }
    }
    if (-not $found) { $lines += "$key=$value" }
    Write-EnvLines $lines
}

# Чинит .env, испорченный прежними версиями скрипта. $true — если правка потребовалась.
function Repair-EnvBom {
    if (-not (Test-Path $envPath)) { return $false }
    $bytes = [System.IO.File]::ReadAllBytes($envPath)
    if ($bytes.Length -lt 3) { return $false }
    if ($bytes[0] -ne 0xEF -or $bytes[1] -ne 0xBB -or $bytes[2] -ne 0xBF) { return $false }
    Write-EnvLines ([System.IO.File]::ReadAllLines($envPath))
    return $true
}

# --- Tailscale ------------------------------------------------------------
function Find-Tailscale {
    $c = Get-Command tailscale -ErrorAction SilentlyContinue
    if ($c) { return $c.Source }
    foreach ($p in @("$Env:ProgramFiles\Tailscale\tailscale.exe",
                     "${Env:ProgramFiles(x86)}\Tailscale\tailscale.exe")) {
        if (Test-Path $p) { return $p }
    }
    return $null
}

function Install-ViaWinget($name, $wingetId, $finder) {
    Warn "$name не установлен."
    $wg = Get-Command winget -ErrorAction SilentlyContinue
    if (-not $wg) {
        Write-Host "      winget на этой машине нет — ставим вручную." -ForegroundColor DarkGray
        return $null
    }
    Write-Host "      Установить через winget? (Y/n): " -NoNewline
    if ((Read-Host) -match '^[nN]') { return $null }
    & winget install -e --id $wingetId --accept-source-agreements --accept-package-agreements
    return (& $finder)
}

Write-Host ""
Write-Host "=== Coffee POS ===" -ForegroundColor Cyan

# =========================================================================
# 1. Окружение Python
# =========================================================================
Step "Окружение:"

if (-not (Test-Path $venvPy)) {
    Warn "Виртуального окружения нет — создаю."
    $sysPy = Find-SystemPython
    if (-not $sysPy) {
        Bad "Python 3.11+ не найден."
        $wg = Get-Command winget -ErrorAction SilentlyContinue
        if ($wg) {
            Write-Host "      Установить Python 3.13 через winget? (Y/n): " -NoNewline
            if ((Read-Host) -notmatch '^[nN]') {
                & winget install -e --id Python.Python.3.13 --accept-source-agreements --accept-package-agreements
                Write-Host "      Закройте это окно и запустите start.ps1 заново — нужен новый PATH." -ForegroundColor Yellow
            }
        } else {
            Write-Host "      Скачайте с https://www.python.org/downloads/ и поставьте," -ForegroundColor Yellow
            Write-Host "      обязательно отметив «Add python.exe to PATH». Затем запустите start.ps1 снова." -ForegroundColor Yellow
            Start-Process "https://www.python.org/downloads/"
        }
        Die "Без Python дальше нельзя."
    }
    Invoke-SystemPython $sysPy @("-m", "venv", ".venv")
    if (-not (Test-Path $venvPy)) { Die "Не удалось создать .venv" }
    Ok "Виртуальное окружение создано"
} else {
    Ok "Python-окружение на месте"
}

# Зависимости — переустанавливаем, только если requirements.txt изменился
$reqHash = (Get-FileHash (Join-Path $root "requirements.txt") -Algorithm SHA256).Hash
$knownHash = if (Test-Path $depsMarker) { (Get-Content $depsMarker -Raw).Trim() } else { "" }
if ($reqHash -ne $knownHash) {
    Warn "Ставлю зависимости (это займёт минуту)…"
    & $venvPy -m pip install --upgrade pip --quiet
    & $venvPy -m pip install -r requirements.txt --quiet
    if ($LASTEXITCODE -ne 0) { Die "pip install завершился с ошибкой" }
    Set-Content -Path $depsMarker -Value $reqHash -Encoding UTF8
    Ok "Зависимости установлены"
} else {
    Ok "Зависимости актуальны"
}

# =========================================================================
# 2. Настройки
# =========================================================================
if (-not (Test-Path $envPath)) {
    Warn "Файла .env нет — создаю."
    # Не [RandomNumberGenerator]::GetBytes(int) — статический оверлоад появился
    # только в .NET 6+, а в Windows PowerShell 5.1 (.NET Framework) его нет.
    $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
    $secretBytes = New-Object byte[] 32
    $rng.GetBytes($secretBytes)
    $rng.Dispose()
    $secret = [Convert]::ToBase64String($secretBytes)
    Write-Host ""
    Write-Host "      Токен Telegram-бота от @BotFather." -ForegroundColor Cyan
    Write-Host "      Enter — пропустить: касса будет работать, но без уведомлений и бэкапов в чат." -ForegroundColor DarkGray
    $token = Read-Host "      BOT_TOKEN"
    Write-EnvLines @(
        "BOT_TOKEN=$token"
        "STORAGE_SECRET=$secret"
        "PUBLIC_URL=$localUrl"
        "DATABASE_URL=sqlite:///pos.db"
        "BACKUP_ENABLED=true"
        "BACKUP_TIME=03:00"
        "BACKUP_KEEP_DAYS=14"
        "BACKUPS_DIR=backups"
    )
    Ok ".env создан, STORAGE_SECRET сгенерирован"
}

if (Repair-EnvBom) {
    Warn "В .env был BOM — приложение не видело первый ключ. Исправлено."
}

$secret = Get-EnvValue "STORAGE_SECRET"
if (-not $secret -or $secret -eq "change-me-in-env") {
    Die "STORAGE_SECRET не задан в .env — без него сессии подделываемы."
}
Ok "Настройки (.env) прочитаны"

# =========================================================================
# 3. База и пользователи
# =========================================================================
$users = "0"
try {
    # init_db() создаёт таблицы, если pos.db ещё не существует — на самом первом
    # запуске без него запрос упал бы с "no such table: users" прямо в консоль.
    $users = (& $venvPy -c "from app.db import init_db, SessionLocal; init_db(); from app.models import User; s=SessionLocal(); print(s.query(User).count()); s.close()").Trim()
} catch { $users = "0" }

if ($users -eq "0") {
    Warn "В базе нет пользователей — нужен владелец."
    Write-Host "      Ваш Telegram ID (узнать: напишите боту /start, он ответит числом)." -ForegroundColor Cyan
    $ownerId = Read-Host "      Telegram ID владельца"
    if ($ownerId -match '^\d+$') {
        & $venvPy seed.py $ownerId
        Ok "Создан владелец (PIN 9999) и кассир (PIN 1234) — смените их после входа"
    } else {
        Warn "ID пропущен. Войти не получится, пока не выполните: .venv\Scripts\python seed.py <id>"
    }
} else {
    Ok "База на месте, пользователей: $users"
}

# =========================================================================
# 4. Telegram — спрашиваем сам Telegram, а не наличие строки в .env
# =========================================================================
$token = Get-EnvValue "BOT_TOKEN"
$botOk = $false
if (-not $token) {
    Warn "BOT_TOKEN пуст — Telegram отключён. Касса работает, уведомлений и бэкапов в чат не будет."
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

# =========================================================================
# 5. Tailscale Funnel (только по флагу -Funnel)
# =========================================================================
if ($Funnel) {
    Step "Публичный доступ (Tailscale Funnel):"
    Write-Host "      Внимание: касса станет доступна из интернета всем, у кого есть адрес." -ForegroundColor Yellow

    $ts = Find-Tailscale
    if (-not $ts) {
        $ts = Install-ViaWinget "Tailscale" "Tailscale.Tailscale" ${function:Find-Tailscale}
    }
    if (-not $ts) {
        Write-Host "      Скачайте с https://tailscale.com/download/windows, поставьте" -ForegroundColor Yellow
        Write-Host "      и запустите start.ps1 -Funnel снова." -ForegroundColor Yellow
        Start-Process "https://tailscale.com/download/windows"
        Die "Без Tailscale публичный адрес не получить."
    }
    Ok "Tailscale найден"

    # Вход в сеть. Требует браузерной авторизации — один раз на машину.
    $st = $null
    try { $st = & $ts status --json 2>$null | ConvertFrom-Json } catch { }
    if (-not $st -or -not $st.Self -or $st.BackendState -ne "Running") {
        Warn "Машина не в сети Tailscale — открываю вход в браузере."
        & $ts up
        try { $st = & $ts status --json 2>$null | ConvertFrom-Json } catch { }
        if (-not $st -or $st.BackendState -ne "Running") { Die "Вход в Tailscale не завершён." }
    }
    Ok "В сети Tailscale: $($st.Self.HostName)"

    $dns = $st.Self.DNSName.TrimEnd(".")
    if (-not $dns) { Die "Не удалось определить имя машины в Tailscale." }
    $publicUrl = "https://$dns"

    Warn "Поднимаю Funnel на порт $port…"
    & $ts funnel --bg $port
    if ($LASTEXITCODE -ne 0) {
        Warn "Funnel не поднялся. Первый запуск может требовать подтверждения по ссылке выше."
        Die "Повторите start.ps1 -Funnel после подтверждения."
    }

    Set-EnvValue "PUBLIC_URL" $publicUrl
    Ok "Funnel поднят, PUBLIC_URL = $publicUrl"
    Write-Host "      Адрес постоянный: кнопка «Открыть кассу» в боте больше не протухнет." -ForegroundColor DarkGray
    Write-Host "      Выключить публикацию: tailscale funnel --https=443 off" -ForegroundColor DarkGray
} else {
    $pub = Get-EnvValue "PUBLIC_URL"
    if ($pub -and $pub -notmatch "localhost|127\.0\.0\.1") {
        Warn "PUBLIC_URL = $pub, но Funnel сейчас не поднимается (нет флага -Funnel)."
        Warn "Кнопка «Открыть кассу» в боте работать не будет. Запустите: .\start.ps1 -Funnel"
    }
}

# =========================================================================
# 6. Порт и запуск
# =========================================================================
Step "Запуск:"
$busy = $false
try {
    if (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction Stop) { $busy = $true }
} catch { }
if ($busy) { Die "Порт $port уже занят — касса, похоже, уже запущена. Откройте $localUrl" }
Ok "Порт $port свободен"

if (-not $NoBrowser) {
    Start-Job -ScriptBlock {
        param($u, $probe)
        for ($i = 0; $i -lt 60; $i++) {
            try {
                if ((Invoke-WebRequest -UseBasicParsing $probe -TimeoutSec 3).StatusCode -eq 200) {
                    Start-Process $u
                    break
                }
            } catch { }
            Start-Sleep -Seconds 1
        }
        # Готовность проверяем строго по IPv4: сервер слушает 0.0.0.0, а localhost
        # на Windows резолвится сначала в ::1 — запрос ждёт отказа от IPv6 и
        # не укладывается в таймаут, из-за чего браузер не открывался вовремя.
    } -ArgumentList $localUrl, "http://127.0.0.1:$port/health" | Out-Null
}

Write-Host ""
Write-Host "Касса: $localUrl" -ForegroundColor Cyan
if ($Funnel) { Write-Host "Снаружи: $publicUrl" -ForegroundColor Cyan }
if ($botOk) {
    Write-Host "Telegram-бот запускается вместе с сервером." -ForegroundColor Cyan
} else {
    Write-Host "Telegram-бот НЕ запустится — см. предупреждение выше." -ForegroundColor Yellow
}
Write-Host "Остановить — Ctrl+C в этом окне." -ForegroundColor DarkGray
Write-Host ""
Write-Host "--- журнал сервера ---" -ForegroundColor DarkGray

& $venvPy -m app.main

Write-Host ""
Write-Host "Сервер остановлен." -ForegroundColor Cyan
Read-Host "Enter — закрыть"
