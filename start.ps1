
# LLM Council - PowerShell Start Script

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
    Write-Host "Starting frontend on http://localhost:5173..."
    $frontend = Start-Process -FilePath "npm.cmd" `
        -ArgumentList "run dev" `
        -WorkingDirectory (Join-Path $root "frontend") `
        -PassThru -NoNewWindow

    Write-Host ""
    Write-Host "LLM Council is running!" -ForegroundColor Green
    Write-Host "Backend:  http://localhost:8001"
    Write-Host "Frontend: http://localhost:5173"
    Write-Host ""
    Write-Host "Press Ctrl+C to stop both servers."

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
