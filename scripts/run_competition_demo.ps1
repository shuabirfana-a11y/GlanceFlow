$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) { throw "Missing .venv. Install project dependencies first." }
Push-Location $projectRoot
try {
    & $python -m glanceflow.demo.healthcheck
    if ($LASTEXITCODE -ne 0) { throw "Demo healthcheck failed." }
    $existing = Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue
    if (-not $existing) {
        Start-Process -FilePath $python -ArgumentList "-m", "glanceflow.simulator.app" -WorkingDirectory $projectRoot -WindowStyle Hidden
        $ready = $false
        for ($attempt = 0; $attempt -lt 20; $attempt++) {
            try { Invoke-RestMethod -Uri "http://127.0.0.1:8765/api/demo/scenarios" -TimeoutSec 1 | Out-Null; $ready = $true; break } catch { Start-Sleep -Milliseconds 500 }
        }
        if (-not $ready) { throw "Demo service did not become healthy." }
    }
    Start-Process "http://127.0.0.1:8765/?scenario=GF-DEMO-01"
    Write-Host "Competition demo ready: http://127.0.0.1:8765/?scenario=GF-DEMO-01"
} finally { Pop-Location }
