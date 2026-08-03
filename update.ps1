# Обновление Coffee POS: тянем код, ставим зависимости, перезапускаем сервер.
# База данных (pos.db) не трогается — она в .gitignore, git её не перезаписывает.
$ErrorActionPreference = "Stop"
chcp 65001 > $null
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$root = $PSScriptRoot
if (-not $root) { $root = (Get-Location).Path }
Set-Location $root

function Ok($t)   { Write-Host "  [ ok ] $t" -ForegroundColor Green }
function Warn($t) { Write-Host "  [ !  ] $t" -ForegroundColor Yellow }
function Bad($t)  { Write-Host "  [ xx ] $t" -ForegroundColor Red }

Write-Host ""
Write-Host "=== Обновление Coffee POS ===" -ForegroundColor Cyan
Write-Host ""

$before = if (Test-Path "$root\VERSION") { (Get-Content "$root\VERSION" -TotalCount 1).Trim() } else { "неизвестна" }
Write-Host "Текущая версия: $before"
Write-Host ""

# Резервная копия базы до обновления: код обновление не портит, но если что-то
# пойдёт не так с миграцией схемы, откатиться будет к чему.
if (Test-Path "$root\pos.db") {
    $stamp = Get-Date -Format "yyyy-MM-dd_HHmm"
    New-Item -ItemType Directory -Force -Path "$root\backups" | Out-Null
    Copy-Item "$root\pos.db" "$root\backups\pos-before-update-$stamp.db" -Force
    Ok "Копия базы: backups\pos-before-update-$stamp.db"
}

# Обновление кода. git — только если это клон; установка из ZIP истории не имеет.
if (Test-Path "$root\.git") {
    $git = Get-Command git -ErrorAction SilentlyContinue
    if (-not $git) {
        Bad "Git не установлен, а проект склонирован через git."
        Write-Host "      Поставьте Git с https://git-scm.com/download/win и повторите." -ForegroundColor Yellow
        Read-Host "Enter — закрыть"
        exit 1
    }
    # Remote и ветку указываем явно: голый "git pull" требует настроенной связи
    # с origin, а на установках, развёрнутых не через clone, её нет — обновление
    # падало с "There is no tracking information for the current branch".
    $branch = (git rev-parse --abbrev-ref HEAD).Trim()
    if ($LASTEXITCODE -ne 0 -or -not $branch) {
        Bad "Не удалось определить ветку git — код не обновлён."
        Read-Host "Enter — закрыть"
        exit 1
    }
    if ($branch -eq "HEAD") {
        Bad "Репозиторий не на ветке (detached HEAD)."
        Write-Host "      Выполните: git checkout master — и повторите обновление." -ForegroundColor Yellow
        Read-Host "Enter — закрыть"
        exit 1
    }
    git pull --ff-only origin $branch
    if ($LASTEXITCODE -ne 0) {
        Bad "git pull не удался — код не обновлён."
        Write-Host "      Чаще всего это локальные правки поверх. Разберитесь с ними и повторите." -ForegroundColor Yellow
        Read-Host "Enter — закрыть"
        exit 1
    }
    # Связь с origin прописываем на будущее: дальше хватит обычного git pull
    git branch --set-upstream-to=origin/$branch $branch 2>$null | Out-Null
    Ok "Код обновлён (ветка $branch)"
} else {
    Warn "Это установка из ZIP — обновлять нечем: истории git нет."
    Write-Host ""
    Write-Host "      Как обновить такую установку:" -ForegroundColor Cyan
    Write-Host "      1. Скачайте свежий ZIP: Code -> Download ZIP на GitHub"
    Write-Host "      2. Распакуйте ПОВЕРХ этой папки, согласившись на замену файлов"
    Write-Host "      3. Запустите start.ps1"
    Write-Host ""
    Write-Host "      pos.db, .env и backups в архиве отсутствуют — данные не пострадают." -ForegroundColor DarkGray
    Write-Host ""
    Read-Host "Enter — закрыть"
    exit 0
}

$venvPy = Join-Path $root ".venv\Scripts\python.exe"
if (Test-Path $venvPy) {
    & $venvPy -m pip install -r requirements.txt --quiet
    Ok "Зависимости актуальны"
} else {
    Warn "Окружения .venv нет — его создаст start.ps1 при запуске"
}

# Перезапуск: задача автозапуска, если она заведена install.ps1
$task = schtasks /Query /TN "CoffeePOS-Server" 2>$null
if ($LASTEXITCODE -eq 0) {
    schtasks /End /TN "CoffeePOS-Server" 2>$null | Out-Null
    Start-Sleep -Seconds 2
    schtasks /Run /TN "CoffeePOS-Server" | Out-Null
    Ok "Сервер перезапущен"
} else {
    Warn "Автозапуск не настроен — запустите кассу через start.ps1"
}

$after = if (Test-Path "$root\VERSION") { (Get-Content "$root\VERSION" -TotalCount 1).Trim() } else { "неизвестна" }
Write-Host ""
if ($after -ne $before) {
    Write-Host "Готово: $before -> $after" -ForegroundColor Green
} else {
    Write-Host "Готово. Версия не изменилась ($after) — обновлять было нечего." -ForegroundColor Cyan
}
Write-Host "База данных не тронута: продажи, меню и остатки на месте." -ForegroundColor DarkGray
Write-Host ""
Read-Host "Enter — закрыть"
