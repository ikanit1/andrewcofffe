# Ждём готовности сервера и открываем кассу на весь экран (режим киоска).
# Ищем Edge, затем Chrome; если браузера нет — открываем окно по умолчанию.
$ErrorActionPreference = "SilentlyContinue"
$url = "http://localhost:8080"
# Проверяем готовность строго по IPv4. Сервер слушает 0.0.0.0 (только IPv4),
# а localhost на Windows резолвится сначала в ::1 — запрос ждёт отказа от IPv6
# и не укладывается в таймаут. Из-за этого проверка не проходила никогда,
# и касса открывалась только после всех 60 попыток.
$probe = "http://127.0.0.1:8080/health"

for ($i = 0; $i -lt 60; $i++) {
    try {
        $r = Invoke-WebRequest -UseBasicParsing $probe -TimeoutSec 3
        if ($r.StatusCode -eq 200) { break }
    } catch {}
    Start-Sleep -Seconds 1
}

function Find-Browser {
    # Порядок: Edge (штатный для Windows), затем Chrome. Проверяем и папку
    # пользователя, и App Paths реестра — Edge не всегда лежит в Program Files.
    $candidates = @(
        @{ Path = "$Env:ProgramFiles\Microsoft\Edge\Application\msedge.exe";           Kind = "edge" }
        @{ Path = "${Env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe";    Kind = "edge" }
        @{ Path = "$Env:LOCALAPPDATA\Microsoft\Edge\Application\msedge.exe";           Kind = "edge" }
        @{ Path = "$Env:ProgramFiles\Google\Chrome\Application\chrome.exe";            Kind = "chrome" }
        @{ Path = "${Env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe";     Kind = "chrome" }
        @{ Path = "$Env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe";            Kind = "chrome" }
    )
    foreach ($c in $candidates) {
        if (Test-Path $c.Path) { return $c }
    }
    foreach ($exe in @(@{n="msedge.exe";k="edge"}, @{n="chrome.exe";k="chrome"})) {
        $reg = "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\$($exe.n)"
        if (Test-Path $reg) {
            $p = (Get-ItemProperty $reg)."(default)"
            if ($p -and (Test-Path $p)) { return @{ Path = $p; Kind = $exe.k } }
        }
    }
    return $null
}

$browser = Find-Browser
if (-not $browser) {
    Start-Process $url
    return
}

# Отдельный профиль: если браузер уже открыт с обычным профилем, окно киоска
# без этого прицепится к нему обычной вкладкой и на весь экран не развернётся.
$profileDir = Join-Path $Env:LOCALAPPDATA "CoffeePOS\kiosk-profile"
if (-not (Test-Path $profileDir)) { New-Item -ItemType Directory -Path $profileDir -Force | Out-Null }

# Киоск уже открыт? Второй экземпляр с тем же профилем не займёт его и сразу
# закроется — со стороны это выглядит как «окно мигнуло и пропало».
$running = Get-CimInstance Win32_Process -Filter "Name='chrome.exe' OR Name='msedge.exe'" |
    Where-Object { $_.CommandLine -like "*CoffeePOS*kiosk-profile*" }
if ($running) { return }

# Не $args: это служебная переменная PowerShell, её переопределение ненадёжно
$browserArgs = @(
    "--kiosk", $url,
    "--user-data-dir=$profileDir",
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-features=TranslateUI"
)
if ($browser.Kind -eq "edge") { $browserArgs += "--edge-kiosk-type=fullscreen" }

& $browser.Path @browserArgs
