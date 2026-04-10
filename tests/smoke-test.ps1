# Smoke Test — Aurora AI Agency
# Verifies: binary size, cargo test, clippy, svelte-check, help files

$ErrorActionPreference = "Continue"
$pass = 0
$fail = 0

function Test-Step($name, $script) {
    Write-Host "`n--- $name ---" -ForegroundColor Cyan
    try {
        $result = & $script
        if ($LASTEXITCODE -ne 0 -and $null -ne $LASTEXITCODE) {
            throw "Exit code: $LASTEXITCODE"
        }
        Write-Host "  PASS" -ForegroundColor Green
        $script:pass++
    } catch {
        Write-Host "  FAIL: $_" -ForegroundColor Red
        $script:fail++
    }
}

$root = Split-Path $PSScriptRoot -Parent

Push-Location $root

Test-Step "Binary exists and >2MB" {
    $exe = Get-ChildItem "src-tauri/target/release/bundle/nsis/*.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $exe) { throw "NSIS exe not found" }
    $sizeMB = [math]::Round($exe.Length / 1MB, 1)
    if ($exe.Length -lt 2MB) { throw "Binary too small: ${sizeMB}MB" }
    Write-Host "  Found: $($exe.Name) (${sizeMB}MB)"
}

Test-Step "cargo test" {
    cargo test --manifest-path src-tauri/Cargo.toml 2>&1 | Out-Host
    if ($LASTEXITCODE -ne 0) { throw "Tests failed" }
}

Test-Step "cargo clippy (zero warnings)" {
    cargo clippy --manifest-path src-tauri/Cargo.toml -- -D warnings 2>&1 | Out-Host
    if ($LASTEXITCODE -ne 0) { throw "Clippy warnings found" }
}

Test-Step "svelte-check" {
    npm run check 2>&1 | Out-Host
    if ($LASTEXITCODE -ne 0) { throw "svelte-check failed" }
}

Test-Step "Help files present (7+)" {
    $helpFiles = Get-ChildItem "src-tauri/help/*.html" -ErrorAction SilentlyContinue
    $count = ($helpFiles | Measure-Object).Count
    if ($count -lt 7) { throw "Only $count help files found (need 7+)" }
    Write-Host "  Found $count HTML help files"
}

Pop-Location

Write-Host "`n=============================" -ForegroundColor Cyan
Write-Host "Results: $pass passed, $fail failed" -ForegroundColor $(if ($fail -eq 0) { "Green" } else { "Red" })
Write-Host "=============================" -ForegroundColor Cyan

if ($fail -gt 0) { exit 1 }
