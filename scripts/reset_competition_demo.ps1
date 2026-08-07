$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$targets = @(
    (Join-Path $projectRoot "work\uploads"),
    (Join-Path $projectRoot "work\wearable-captures"),
    (Join-Path $projectRoot "work\demo")
)
foreach ($target in $targets) {
    $full = [System.IO.Path]::GetFullPath($target)
    if (-not $full.StartsWith((Join-Path $projectRoot "work"), [System.StringComparison]::OrdinalIgnoreCase)) { throw "Unsafe reset target: $full" }
    if (Test-Path -LiteralPath $full) { Remove-Item -LiteralPath $full -Recurse -Force }
}
Write-Host "Demo sessions, Memory Calendar process state, transactions, and temporary captures are reset."
