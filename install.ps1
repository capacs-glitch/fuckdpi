# install.ps1 — установка FuckDPI для Windows 11.
# Запуск: irm https://raw.githubusercontent.com/capacs-glitch/fuckdpi/main/install.ps1 | iex
$ErrorActionPreference = "Stop"

$Repo = "capacs-glitch/fuckdpi"
$ToolName = "fuckdpi"
$InstallDir = "$env:LOCALAPPDATA\$ToolName"
$CfgDir = "$env:LOCALAPPDATA\$ToolName"

Write-Host "==> FuckDPI - установка для Windows 11" -ForegroundColor Cyan
Write-Host ""

# 1. Скачиваем
Write-Host "[1/6] скачиваю fuckdpi..."
New-Item -ItemType Directory -Force -Path "$env:TEMP\fuckdpi-install" | Out-Null
git clone --depth 1 "https://github.com/$Repo.git" "$env:TEMP\fuckdpi-install\fuckdpi" 2>$null
if (-not (Test-Path "$env:TEMP\fuckdpi-install\fuckdpi")) {
    Write-Host "ошибка клонирования; установи git: winget install Git.Git" -ForegroundColor Red
    exit 1
}

# 2. Копируем
Write-Host "[2/6] копирую файлы..."
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
Copy-Item "$env:TEMP\fuckdpi-install\fuckdpi\fuckdpi-windows.py" -Destination "$InstallDir\$ToolName.py" -Force
Copy-Item "$env:TEMP\fuckdpi-install\fuckdpi\*.ps1" -Destination $InstallDir -Force -ErrorAction SilentlyContinue

# 3. Конфиги
Write-Host "[3/6] создаю конфиги..."
New-Item -ItemType Directory -Force -Path $CfgDir | Out-Null

# 4. sing-box
Write-Host "[4/6] проверяю sing-box..."
$singBox = Get-Command sing-box -ErrorAction SilentlyContinue
if (-not $singBox) {
    Write-Host "  ставлю sing-box через winget..."
    winget install -e --id SagerNet.sing-box --accept-source-agreements --accept-package-agreements
} else {
    Write-Host "  sing-box: $($singBox.Source)"
}

# 5. zapret-win-bundle (winws)
Write-Host "[5/6] проверяю winws (zapret)..."
$winwsPath = "$InstallDir\winws.exe"
if (-not (Test-Path $winwsPath)) {
    Write-Host "  скачиваю zapret-win-bundle..."
    $zapretUrl = "https://github.com/bol-van/zapret-win-bundle/releases/latest/download/zapret-win-bundle.zip"
    $zipPath = "$env:TEMP\zapret-win-bundle.zip"
    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -Uri $zapretUrl -OutFile $zipPath -TimeoutSec 120
        Expand-Archive -Path $zipPath -DestinationPath "$env:TEMP\zapret" -Force
        $winws = Get-ChildItem -Path "$env:TEMP\zapret" -Recurse -Filter "winws.exe" | Select-Object -First 1
        if ($winws) {
            Copy-Item $winws.FullName -Destination $winwsPath -Force
            # Копируем WinDivert
            $windivert = Get-ChildItem -Path "$env:TEMP\zapret" -Recurse -Filter "windivert*.sys" | Select-Object -First 1
            if ($windivert) {
                Copy-Item $windivert.DirectoryName -Destination "$InstallDir\windivert" -Recurse -Force
            }
            Write-Host "  winws установлен" -ForegroundColor Green
        }
    } catch {
        Write-Host "  ошибка скачивания zapret: $_" -ForegroundColor Yellow
        Write-Host "  скачай вручную: https://github.com/bol-van/zapret-win-bundle"
    }
} else {
    Write-Host "  winws уже установлен"
}

# 6. PATH
Write-Host "[6/6] обновляю PATH..."
$CurrentPath = [Environment]::GetEnvironmentVariable("Path", "User")
if ($CurrentPath -notlike "*$InstallDir*") {
    [Environment]::SetEnvironmentVariable("Path", "$CurrentPath;$InstallDir", "User")
    $env:Path = "$env:Path;$InstallDir"
    Write-Host "  добавлено в PATH" -ForegroundColor Green
}

# Готово
Write-Host ""
Write-Host "==> Установка завершена!" -ForegroundColor Green
Write-Host ""
Write-Host "  fuckdpi              -- интерфейс"
Write-Host "  fuckdpi key <URL>    -- добавить ключ"
Write-Host "  fuckdpi vpn select   -- VPN по списку"
Write-Host "  fuckdpi vpn all      -- VPN весь трафик"
Write-Host "  fuckdpi fuckdpi select -- FuckDPI по списку"
Write-Host "  fuckdpi fuckdpi all  -- FuckDPI весь трафик"
Write-Host ""
Write-Host "Перезапусти терминал для применения PATH." -ForegroundColor Yellow
