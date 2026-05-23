<#
.SYNOPSIS
    Подписывает установочный пакет Aurora MMM Optimizer цифровой подписью
    EV Code Signing certificate (когда сертификат ООО будет готов).

.DESCRIPTION
    Wrapper для signtool.exe. На вход берёт путь к NSIS-инсталлятору
    (или массив путей), на выходе — тот же файл с цифровой подписью.

    Сейчас (2026-05-16) сертификата ООО нет — скрипт работает в DRY-RUN
    режиме (показывает что будет подписано), либо использует
    self-signed сертификат для smoke-теста инфраструктуры подписи.

    Когда сертификат будет готов:
      1. Установить EV сертификат в Windows certificate store (LocalMachine\My)
      2. Задать env var SIGNING_CERT_THUMBPRINT с SHA-1 thumbprint
      3. Запустить: ./sign_installer.ps1 -InstallerPath <path>

.PARAMETER InstallerPath
    Путь к .exe файлу установщика (NSIS output).

.PARAMETER DryRun
    Если задан — только показывает signtool команду без выполнения.
    Это режим по умолчанию пока ООО не оформлено.

.PARAMETER UseSelfSigned
    Использовать self-signed сертификат (для smoke-теста инфраструктуры).
    Создаст временный сертификат если его нет.

.EXAMPLE
    ./sign_installer.ps1 -InstallerPath .\target\release\bundle\nsis\Aurora-Setup.exe -DryRun

.EXAMPLE
    # После получения EV сертификата:
    $env:SIGNING_CERT_THUMBPRINT = "ABC123..."
    ./sign_installer.ps1 -InstallerPath .\target\release\bundle\nsis\Aurora-Setup.exe

.NOTES
    Требуется signtool.exe из Windows SDK (обычно в
    C:\Program Files (x86)\Windows Kits\10\bin\10.0.x.0\x64\signtool.exe).
#>

param(
    [Parameter(Mandatory = $true)]
    [string]$InstallerPath,

    [switch]$DryRun,
    [switch]$UseSelfSigned
)

$ErrorActionPreference = 'Stop'

# Поиск signtool.exe
function Find-Signtool {
    $candidates = @(
        "${env:ProgramFiles(x86)}\Windows Kits\10\bin\*\x64\signtool.exe",
        "${env:ProgramFiles}\Windows Kits\10\bin\*\x64\signtool.exe"
    )

    foreach ($pattern in $candidates) {
        $found = Get-ChildItem -Path $pattern -ErrorAction SilentlyContinue |
                 Sort-Object -Property FullName -Descending |
                 Select-Object -First 1
        if ($found) {
            return $found.FullName
        }
    }

    throw "signtool.exe не найден. Установите Windows SDK."
}

# Получаем сертификат для подписи
function Get-SigningCertificate {
    if ($UseSelfSigned) {
        # Smoke test: self-signed сертификат в текущем пользователе
        $existing = Get-ChildItem -Path Cert:\CurrentUser\My |
                    Where-Object { $_.Subject -eq "CN=Aurora MMM Optimizer Test" } |
                    Select-Object -First 1
        if (-not $existing) {
            Write-Host "Создаю self-signed сертификат для smoke-теста..."
            $existing = New-SelfSignedCertificate `
                -Type CodeSigningCert `
                -Subject "CN=Aurora MMM Optimizer Test" `
                -KeyAlgorithm RSA `
                -KeyLength 2048 `
                -CertStoreLocation Cert:\CurrentUser\My `
                -KeyUsage DigitalSignature `
                -KeyExportPolicy NonExportable
        }
        return $existing.Thumbprint
    }

    if (-not $env:SIGNING_CERT_THUMBPRINT) {
        throw @"
SIGNING_CERT_THUMBPRINT не задан.

Сертификат ООО ещё не получен. Используйте -DryRun для проверки
инфраструктуры или -UseSelfSigned для smoke-теста signtool.

Когда сертификат будет готов:
  `$env:SIGNING_CERT_THUMBPRINT = "<SHA-1 hex thumbprint>"
  ./sign_installer.ps1 -InstallerPath <path>
"@
    }

    return $env:SIGNING_CERT_THUMBPRINT
}

# Главный путь
if (-not (Test-Path $InstallerPath)) {
    throw "Файл установщика не найден: $InstallerPath"
}

$signtool = Find-Signtool
Write-Host "signtool.exe: $signtool"

if ($DryRun) {
    Write-Host ""
    Write-Host "=== DRY RUN ===" -ForegroundColor Yellow
    Write-Host "Команда которая будет выполнена при наличии сертификата:"
    Write-Host ""
    Write-Host "  $signtool sign \\"
    Write-Host "    /sha1 <SIGNING_CERT_THUMBPRINT> \\"
    Write-Host "    /tr http://timestamp.digicert.com \\"
    Write-Host "    /td sha256 \\"
    Write-Host "    /fd sha256 \\"
    Write-Host "    /d 'Aurora MMM Optimizer' \\"
    Write-Host "    /du 'https://auroraai.pro' \\"
    Write-Host "    $InstallerPath"
    Write-Host ""
    Write-Host "Pending: сертификат EV Code Signing от ООО." -ForegroundColor Yellow
    exit 0
}

$thumbprint = Get-SigningCertificate

Write-Host "Подписываю $InstallerPath..."

$signArgs = @(
    'sign',
    '/sha1', $thumbprint,
    '/tr', 'http://timestamp.digicert.com',
    '/td', 'sha256',
    '/fd', 'sha256',
    '/d', 'Aurora MMM Optimizer',
    '/du', 'https://auroraai.pro',
    $InstallerPath
)

& $signtool @signArgs

if ($LASTEXITCODE -ne 0) {
    throw "signtool exited with code $LASTEXITCODE"
}

# Проверяем что подпись применилась
Write-Host ""
Write-Host "Проверка подписи..."
& $signtool verify /pa /v $InstallerPath

Write-Host ""
Write-Host "✓ Установщик подписан: $InstallerPath" -ForegroundColor Green
