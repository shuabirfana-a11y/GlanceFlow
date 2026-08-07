$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$failed = $false
function Check($name, $condition) {
    $status = if ($condition) { "PASS" } else { $script:failed = $true; "FAIL" }
    Write-Host ($name.PadRight(24, ".") + " " + $status)
}
Push-Location $projectRoot
try {
    Check "Python" (Test-Path -LiteralPath $python)
    if (Test-Path -LiteralPath $python) {
        & $python -c "import fastapi, pydantic, rapidocr_onnxruntime, glanceflow"
        Check "Dependencies" ($LASTEXITCODE -eq 0)
        & $python -m glanceflow.demo.healthcheck | Out-Host
        Check "Healthcheck" ($LASTEXITCODE -eq 0)
    }
    Check "RapidOCR" (Test-Path "src\glanceflow\ocr\provider.py")
    Check "Demo assets" ((Get-ChildItem "data\synthetic_posters\*.png").Count -ge 8)
    Check "Memory Calendar" (Test-Path "src\glanceflow\calendar\memory_provider.py")
    Check "Demo scenarios" ((Get-ChildItem "demo\scenarios\GF-DEMO-*.json").Count -eq 8)
    Check "Outputs" ((Test-Path "outputs\demo\scenario_results.json") -and (Test-Path "outputs\demo\repeatability_results.json"))
    $portUse = Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue
    Check "Port 8765" (-not $portUse)
    $scenarioText = Get-Content "demo\scenarios\*.json" -Raw
    Check "Offline mode" (($scenarioText -notmatch "https?://") -and ($scenarioText -notmatch "google"))
    if ($failed) { Write-Host "`nNOT_READY_FOR_FINAL_DEMO"; exit 1 }
    Write-Host "`nREADY_FOR_FINAL_DEMO"
} finally { Pop-Location }
