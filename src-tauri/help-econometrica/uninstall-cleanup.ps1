#Requires -Version 5.1
<#
    AURORA AI AGENCY - ROSST
    Очистка остаточных файлов после деинсталляции

    Запускать ПОСЛЕ удаления приложения через Windows
    (Пуск → Настройки → Приложения → Установленные приложения).
    Запуск: правой кнопкой → "Выполнить с помощью PowerShell"
#>

$ErrorActionPreference = "Stop"

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]"Administrator")
if (-not $isAdmin) {
    Start-Process powershell.exe "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`"" -Verb RunAs; exit
}

$AppName  = "AURORA AI AGENCY - ROSST"
$Vaults   = @(
    "lawyer-contracts.vault", "lawyer-claims.vault", "lawyer-advertising.vault",
    "creative-group.vault", "communication-strategist.vault",
    "media-analyst.vault", "communication-analyst.vault"
)
$VaultDir = "C:\ProgramData\AIAgency\vaults"
$LicFile  = "$env:APPDATA\AIAgency\license.json"
$SessDir  = "$env:LOCALAPPDATA\AIAgency\sessions"

Clear-Host
Write-Host ""
Write-Host "  =============================================" -ForegroundColor DarkRed
Write-Host "   $AppName" -ForegroundColor White
Write-Host "   Очистка остаточных файлов" -ForegroundColor Gray
Write-Host "  =============================================" -ForegroundColor DarkRed
Write-Host ""
Write-Host "  Будут удалены:" -ForegroundColor Yellow
Write-Host "  • Vault-файлы: все 7 файлов кабинетов" -ForegroundColor Gray
Write-Host "  • Лицензия:    $LicFile" -ForegroundColor Gray
Write-Host "  • Сессии:      $SessDir" -ForegroundColor Gray
Write-Host ""
Write-Host "  ВНИМАНИЕ: Действие необратимо!" -ForegroundColor Red
Write-Host ""

$confirm = Read-Host "  Продолжить? (y/N)"
if ($confirm -notmatch '^[yYдД]$') {
    Write-Host "  Отменено." -ForegroundColor DarkGray
    Write-Host ""
    $null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
    exit 0
}

Write-Host ""
$removed = 0
$skipped = 0

function Remove-Safe {
    param($Path, $Label, [switch]$Recurse)
    if (Test-Path $Path) {
        try {
            if ($Recurse) { Remove-Item $Path -Recurse -Force }
            else { Remove-Item $Path -Force }
            Write-Host "  [OK] Удалено: $Label" -ForegroundColor Green
            $script:removed++
        } catch {
            Write-Host "  [!!] Ошибка: $Label — $_" -ForegroundColor Red
        }
    } else {
        Write-Host "  [--] Не найдено (пропущено): $Label" -ForegroundColor DarkGray
        $script:skipped++
    }
}

function Remove-EmptyDir {
    param($Path)
    if ((Test-Path $Path) -and (@(Get-ChildItem $Path -Recurse -ErrorAction SilentlyContinue).Count -eq 0)) {
        Remove-Item $Path -Recurse -Force -ErrorAction SilentlyContinue
        Write-Host "  [OK] Пустая папка удалена: $Path" -ForegroundColor DarkGreen
    }
}

foreach ($vault in $Vaults) { Remove-Safe (Join-Path $VaultDir $vault) $vault }
Remove-EmptyDir $VaultDir
Remove-EmptyDir "C:\ProgramData\AIAgency"

Remove-Safe $LicFile "license.json"
Remove-EmptyDir "$env:APPDATA\AIAgency"

Remove-Safe $SessDir "sessions\" -Recurse
Remove-EmptyDir "$env:LOCALAPPDATA\AIAgency"

Write-Host ""
Write-Host "  =============================================" -ForegroundColor DarkGreen
Write-Host "  Готово. Удалено: $removed, пропущено: $skipped" -ForegroundColor Green
Write-Host "  =============================================" -ForegroundColor DarkGreen
Write-Host ""
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
