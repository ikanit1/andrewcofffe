# Ждём готовности сервера и открываем кассу в браузере (kiosk); фолбэк — обычное окно
$ErrorActionPreference = "SilentlyContinue"
$url = "http://localhost:8080"
for ($i = 0; $i -lt 60; $i++) {
    try {
        $r = Invoke-WebRequest -UseBasicParsing "$url/health" -TimeoutSec 2
        if ($r.StatusCode -eq 200) { break }
    } catch {}
    Start-Sleep -Seconds 1
}
$edge = Join-Path ${Env:ProgramFiles(x86)} "Microsoft\Edge\Application\msedge.exe"
if (-not (Test-Path $edge)) {
    $edge = Join-Path $Env:ProgramFiles "Microsoft\Edge\Application\msedge.exe"
}
if (Test-Path $edge) {
    & $edge --kiosk $url --edge-kiosk-type=fullscreen --no-first-run --disable-features=TranslateUI
} else {
    Start-Process $url
}
