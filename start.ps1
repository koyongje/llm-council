
# LLM Council - PowerShell Start Script
# Usage: .\start.ps1           (this PC only)
#        .\start.ps1 -Remote   (also reachable from your other devices via Tailscale)

param([switch]$Remote)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot

Write-Host "Starting LLM Council..." -ForegroundColor Cyan

# Check commands
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw "uv is not installed or not in PATH."
}
if (-not (Get-Command npm.cmd -ErrorAction SilentlyContinue)) {
    throw "npm is not installed or not in PATH."
}

$frontendUrl = "http://localhost:5173"
$env:LLM_COUNCIL_HOST = "localhost"
if ($Remote) {
    # Bind the frontend to this PC's Tailscale IP only (not the LAN); the
    # backend stays on 127.0.0.1 behind the Vite proxy.
    $ts = Get-Command tailscale -ErrorAction SilentlyContinue
    $tsExe = if ($ts) { $ts.Source } else { "C:\Program Files\Tailscale\tailscale.exe" }
    if (-not (Test-Path $tsExe)) {
        throw "Tailscale is not installed. Install it from https://tailscale.com/download and sign in."
    }
    $tsIp = (& $tsExe ip -4 | Select-Object -First 1)
    if (-not $tsIp) {
        throw "Tailscale has no IPv4 address. Is it running and signed in?"
    }
    $env:LLM_COUNCIL_HOST = $tsIp.Trim()
    $frontendUrl = "http://$($env:LLM_COUNCIL_HOST):5173"
}
$backend = $null
$frontend = $null

try {
    # Start backend
    Write-Host "Starting backend on http://localhost:8001..."
    $backend = Start-Process -FilePath "uv.exe" `
        -ArgumentList "run python -m backend.main" `
        -WorkingDirectory $root `
        -PassThru -NoNewWindow

    Start-Sleep -Seconds 2

    if ($backend.HasExited) {
        throw "Backend exited unexpectedly."
    }

    # Start frontend
    Write-Host "Starting frontend on $frontendUrl..."
    $frontend = Start-Process -FilePath "npm.cmd" `
        -ArgumentList "run dev" `
        -WorkingDirectory (Join-Path $root "frontend") `
        -PassThru -NoNewWindow

    Write-Host ""
    Write-Host "LLM Council is running!" -ForegroundColor Green
    Write-Host "Backend:  http://localhost:8001"
    Write-Host "Frontend: $frontendUrl"
    Write-Host ""
    Write-Host "Press Ctrl+C to stop both servers."

    # Open the browser once the frontend responds (up to 30 s)
    for ($i = 0; $i -lt 30; $i++) {
        try {
            Invoke-WebRequest $frontendUrl -UseBasicParsing -TimeoutSec 1 | Out-Null
            Start-Process $frontendUrl
            break
        }
        catch {
            Start-Sleep -Seconds 1
        }
    }

    # Keep script running
    while ($true) {
        Start-Sleep -Seconds 1
        if ($backend.HasExited -or $frontend.HasExited) {
            Write-Host "A server process has exited."
            break
        }
    }
}
finally {
    Write-Host "Stopping LLM Council..."

    foreach ($proc in @($backend, $frontend)) {
        if ($null -ne $proc -and -not $proc.HasExited) {
            taskkill.exe /PID $proc.Id /T /F 2>$null
        }
    }
}
