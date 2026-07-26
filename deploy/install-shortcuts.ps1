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
$statusName = "Состояние кассы.lnk"
$desktopLnk = Join-Path $desktop $name
$startupLnk = Join-Path $startup $name
$statusLnk = Join-Path $desktop $statusName
$statusScript = Join-Path $PSScriptRoot "status.ps1"

function Ok($t)   { Write-Host "  [ ok ] $t" -ForegroundColor Green }
function Warn($t) { Write-Host "  [ !  ] $t" -ForegroundColor Yellow }

Write-Host ""
Write-Host "=== Ярлыки Coffee POS ===" -ForegroundColor Cyan
Write-Host ""

if ($Remove) {
    foreach ($p in @($desktopLnk, $startupLnk, $statusLnk)) {
        if (Test-Path $p) { Remove-Item $p -Force; Ok "удалён: $p" }
        else { Warn "не найден: $p" }
    }
    Write-Host ""
    Read-Host "Enter — закрыть"
    exit 0
}

if (-not (Test-Path $launcher)) { throw "Не найден $launcher" }

function New-Shortcut($path, $description, $script, $visible = $false) {
    $shell = New-Object -ComObject WScript.Shell
    $lnk = $shell.CreateShortcut($path)
    $lnk.TargetPath = "$Env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
    if ($visible) {
        # Окно состояния должно быть видно — его и открывают, чтобы почитать
        $lnk.Arguments = "-NoLogo -ExecutionPolicy Bypass -File `"$script`""
        $lnk.WindowStyle = 1
    } else {
        # Запуск кассы: окно скрыто, консоль не мигает у кассира перед глазами
        $lnk.Arguments = "-NoLogo -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$script`""
        $lnk.WindowStyle = 7
    }
    $lnk.WorkingDirectory = $root
    $lnk.Description = $description
    if (Test-Path $icon) { $lnk.IconLocation = "$icon,0" }
    $lnk.Save()
    [Runtime.InteropServices.Marshal]::ReleaseComObject($shell) | Out-Null
}

New-Shortcut $desktopLnk "Открыть кассу кофейни" $launcher
Ok "Кнопка запуска на рабочем столе: $name"

New-Shortcut $statusLnk "Проверить: сервер, веб-интерфейс, киоск, автозапуск" $statusScript $true
Ok "Кнопка проверки на рабочем столе: $statusName"

if ($NoAutostart) {
    Warn "Автозапуск не настраивался (флаг -NoAutostart)"
} else {
    New-Shortcut $startupLnk "Автозапуск кассы кофейни" $launcher
    Ok "Автозапуск при входе в систему настроен"
    Write-Host "        папка: $startup" -ForegroundColor DarkGray
}

Write-Host ""
Write-Host "Готово. Касса открывается двойным щелчком по ярлыку на рабочем столе." -ForegroundColor Cyan
Write-Host "Убрать: .\deploy\install-shortcuts.ps1 -Remove" -ForegroundColor DarkGray
Write-Host ""
Read-Host "Enter — закрыть"
