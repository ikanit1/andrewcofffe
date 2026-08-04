# Состояние кассы одним взглядом: сервер, веб-интерфейс, киоск, автозапуск.
# Кнопка «Состояние кассы» на рабочем столе запускает именно этот скрипт.
$ErrorActionPreference = "SilentlyContinue"
chcp 65001 > $null
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$root = Split-Path -Parent $PSScriptRoot
$port = 8080
# Строго IPv4: localhost на Windows резолвится сначала в ::1, где никто
# не слушает, и проверка упирается в таймаут (см. run-kiosk.ps1)
$probe = "http://127.0.0.1:$port/health"

function Ok($t)   { Write-Host "  [ ok ] $t" -ForegroundColor Green }
function Bad($t)  { Write-Host "  [ xx ] $t" -ForegroundColor Red }
function Warn($t) { Write-Host "  [ !  ] $t" -ForegroundColor Yellow }
function Head($t) { Write-Host ""; Write-Host $t -ForegroundColor Cyan }

Write-Host ""
Write-Host "=== Состояние кассы ===" -ForegroundColor Cyan
Write-Host ("  " + (Get-Date -Format "dd.MM.yyyy HH:mm:ss")) -ForegroundColor DarkGray

# --- Сервер ---------------------------------------------------------------
Head "Сервер:"
$listen = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
if ($listen) {
    $srvPid = ($listen | Select-Object -First 1).OwningProcess
    $proc = Get-Process -Id $srvPid -ErrorAction SilentlyContinue
    if ($proc) {
        $up = (Get-Date) - $proc.StartTime
        $upText = if ($up.TotalHours -ge 1) { "{0:N0} ч {1:N0} мин" -f [math]::Floor($up.TotalHours), $up.Minutes }
                  else { "{0:N0} мин" -f $up.TotalMinutes }
        $ram = [math]::Round($proc.WorkingSet64 / 1MB)
        Ok "процесс работает — PID $srvPid, запущен $($proc.StartTime.ToString('HH:mm')), работает $upText, память $ram МБ"
    } else {
        Ok "порт слушается (PID $srvPid)"
    }
    Ok "порт $port открыт"
} else {
    Bad "сервер НЕ работает — порт $port никто не слушает"
    Warn "запустите ярлык «Кофейня — Касса» на рабочем столе"
}

# Авто-перезапуск: скрипт-надзиратель, который поднимает сервер после падения
$watch = Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" |
    Where-Object { $_.CommandLine -like "*run-server.ps1*" }
if ($watch) { Ok "авто-перезапуск включён (следит $(($watch | Measure-Object).Count) процесс)" }
else { Warn "надзиратель run-server.ps1 не запущен — после падения сервер сам не поднимется" }

# --- Веб-интерфейс --------------------------------------------------------
Head "Веб-интерфейс:"
$sw = [Diagnostics.Stopwatch]::StartNew()
try {
    $r = Invoke-WebRequest -UseBasicParsing $probe -TimeoutSec 5 -ErrorAction Stop
    $ms = [math]::Round($sw.Elapsed.TotalMilliseconds)
    if ($r.StatusCode -eq 200) { Ok "отвечает: код 200 за $ms мс" } else { Warn "код $($r.StatusCode)" }
    Ok "адрес в кофейне: http://localhost:$port"
    $ip = (Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object { $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.254.*" } |
        Select-Object -First 1).IPAddress
    if ($ip) { Ok "с телефона в той же сети: http://${ip}:$port" }
} catch {
    Bad "не отвечает: $($_.Exception.Message)"
}

# --- Окно кассы -------------------------------------------------------------
Head "Окно кассы:"
$kiosk = Get-CimInstance Win32_Process -Filter "Name='chrome.exe' OR Name='msedge.exe'" |
    Where-Object { $_.CommandLine -like "*CoffeePOS*kiosk-profile*" }
if ($kiosk) {
    $main = $kiosk | Sort-Object CreationDate | Select-Object -First 1
    Ok "открыто — $($main.Name), запущено $(([datetime]$main.CreationDate).ToString('HH:mm')), процессов $(($kiosk | Measure-Object).Count)"
    Write-Host "        закрыть: Alt+F4, свернуть — как у обычного окна" -ForegroundColor DarkGray
} else {
    Warn "окно кассы закрыто (сервер при этом может работать)"
}

# --- Автозапуск -----------------------------------------------------------
Head "Автозапуск при включении:"
$startupLnk = Join-Path ([Environment]::GetFolderPath("Startup")) "Кофейня — Касса.lnk"
if (Test-Path $startupLnk) { Ok "настроен — ярлык в автозагрузке" }
else { Bad "НЕ настроен — запустите deploy\install-shortcuts.ps1" }

$desktopLnk = Join-Path ([Environment]::GetFolderPath("Desktop")) "Кофейня — Касса.lnk"
if (Test-Path $desktopLnk) { Ok "кнопка на рабочем столе на месте" }
else { Warn "кнопки на рабочем столе нет — deploy\install-shortcuts.ps1" }

foreach ($t in @("CoffeePOS-Server", "CoffeePOS-Kiosk")) {
    $task = schtasks /Query /TN $t 2>$null
    if ($LASTEXITCODE -eq 0) { Ok "задача планировщика $t создана" }
}

# --- Доступ снаружи -------------------------------------------------------
Head "Доступ из интернета:"
$ts = $null
foreach ($p in @("$Env:ProgramFiles\Tailscale\tailscale.exe",
                 "${Env:ProgramFiles(x86)}\Tailscale\tailscale.exe")) {
    if (Test-Path $p) { $ts = $p; break }
}
if ($ts) {
    $f = & $ts funnel status 2>$null | Out-String
    if ($f -match "https://[\w\.\-]+") { Ok "Tailscale Funnel: $($Matches[0])" }
    else { Warn "Tailscale есть, но публикация выключена (start.ps1 -Funnel)" }
} else {
    Warn "Tailscale не установлен — касса доступна только в своей сети"
}

# --- Журнал ---------------------------------------------------------------
Head "Журнал сервера (последнее):"
$log = Join-Path $root "logs\server.log"
if (Test-Path $log) {
    Get-Content $log -Tail 4 -Encoding UTF8 | ForEach-Object {
        Write-Host "        $_" -ForegroundColor DarkGray
    }
    Write-Host "        файл: $log" -ForegroundColor DarkGray
} else {
    Warn "журнала нет (сервер ещё ни разу не запускался этим способом)"
}

Write-Host ""
Read-Host "Enter — закрыть"
