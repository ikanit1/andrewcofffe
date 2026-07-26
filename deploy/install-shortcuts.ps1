# Ставит ярлык кассы на рабочий стол и (по желанию) автозапуск при входе в систему.
# Прав администратора НЕ требует: ярлыки кладутся в папки текущего пользователя.
#
#   .\deploy\install-shortcuts.ps1              ярлык на столе + автозапуск
#   .\deploy\install-shortcuts.ps1 -NoAutostart только ярлык на столе
#   .\deploy\install-shortcuts.ps1 -Remove      убрать оба ярлыка
param(
    [switch]$NoAutostart,
    [switch]$Remove
)

$ErrorActionPreference = "Stop"
chcp 65001 > $null
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$root = Split-Path -Parent $PSScriptRoot
$launcher = Join-Path $PSScriptRoot "start-pos.ps1"
$icon = Join-Path $PSScriptRoot "coffee-pos.ico"

$desktop = [Environment]::GetFolderPath("Desktop")
$startup = [Environment]::GetFolderPath("Startup")
$name = "Кофейня — Касса.lnk"
$desktopLnk = Join-Path $desktop $name
$startupLnk = Join-Path $startup $name

function Ok($t)   { Write-Host "  [ ok ] $t" -ForegroundColor Green }
function Warn($t) { Write-Host "  [ !  ] $t" -ForegroundColor Yellow }

Write-Host ""
Write-Host "=== Ярлыки Coffee POS ===" -ForegroundColor Cyan
Write-Host ""

if ($Remove) {
    foreach ($p in @($desktopLnk, $startupLnk)) {
        if (Test-Path $p) { Remove-Item $p -Force; Ok "удалён: $p" }
        else { Warn "не найден: $p" }
    }
    Write-Host ""
    Read-Host "Enter — закрыть"
    exit 0
}

if (-not (Test-Path $launcher)) { throw "Не найден $launcher" }

function New-Shortcut($path, $description) {
    $shell = New-Object -ComObject WScript.Shell
    $lnk = $shell.CreateShortcut($path)
    # powershell.exe с -File: окно скрыто, консоль не мигает у кассира перед глазами
    $lnk.TargetPath = "$Env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
    $lnk.Arguments = "-NoLogo -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$launcher`""
    $lnk.WorkingDirectory = $root
    $lnk.Description = $description
    if (Test-Path $icon) { $lnk.IconLocation = "$icon,0" }
    $lnk.WindowStyle = 7   # свернуть окно PowerShell
    $lnk.Save()
    [Runtime.InteropServices.Marshal]::ReleaseComObject($shell) | Out-Null
}

New-Shortcut $desktopLnk "Открыть кассу кофейни"
Ok "Ярлык на рабочем столе: $name"

if ($NoAutostart) {
    Warn "Автозапуск не настраивался (флаг -NoAutostart)"
} else {
    New-Shortcut $startupLnk "Автозапуск кассы кофейни"
    Ok "Автозапуск при входе в систему настроен"
    Write-Host "        папка: $startup" -ForegroundColor DarkGray
}

Write-Host ""
Write-Host "Готово. Касса открывается двойным щелчком по ярлыку на рабочем столе." -ForegroundColor Cyan
Write-Host "Убрать: .\deploy\install-shortcuts.ps1 -Remove" -ForegroundColor DarkGray
Write-Host ""
Read-Host "Enter — закрыть"
