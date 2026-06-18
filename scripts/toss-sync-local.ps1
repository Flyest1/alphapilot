$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent $scriptDir
$backendDir = Join-Path $repoRoot "backend"
$envFile = Join-Path $backendDir ".env"
$outLog = Join-Path $env:TEMP "alphapilot-toss-sync-uvicorn.out.log"
$errLog = Join-Path $env:TEMP "alphapilot-toss-sync-uvicorn.err.log"

function Read-DotEnv {
    param([string]$Path)

    $values = @{}
    foreach ($line in Get-Content -Path $Path) {
        $trimmed = $line.Trim()
        if ($trimmed.Length -eq 0 -or $trimmed.StartsWith("#")) {
            continue
        }

        $parts = $line -split "=", 2
        if ($parts.Count -ne 2) {
            continue
        }

        $key = $parts[0].Trim()
        $value = $parts[1].Trim()
        if (
            ($value.StartsWith('"') -and $value.EndsWith('"')) -or
            ($value.StartsWith("'") -and $value.EndsWith("'"))
        ) {
            $value = $value.Substring(1, $value.Length - 2)
        }

        $values[$key] = $value
    }

    return $values
}

function Test-BackendHealth {
    try {
        Invoke-RestMethod -Uri "http://127.0.0.1:8000/health" -TimeoutSec 2 | Out-Null
        return $true
    }
    catch {
        return $false
    }
}

function Stop-StartedBackend {
    param($Process)

    if ($null -eq $Process) {
        return
    }

    try {
        if (-not $Process.HasExited) {
            Write-Host "Stopping local backend started by this script..."
            Stop-Process -Id $Process.Id -Force -ErrorAction SilentlyContinue
        }
    }
    catch {
        Write-Host "Could not stop local backend process cleanly: $($_.Exception.Message)"
    }
}

if (-not (Test-Path $envFile)) {
    Write-Host "Missing backend\.env."
    Write-Host "Create backend\.env and fill Supabase, API_ACCESS_TOKEN, and Toss Invest values first."
    exit 1
}

Write-Host "Checking backend\.env..."
$envValues = Read-DotEnv -Path $envFile
$requiredKeys = @(
    "SUPABASE_URL",
    "SUPABASE_SERVICE_ROLE_KEY",
    "SUPABASE_ANON_KEY",
    "API_ACCESS_TOKEN",
    "TOSS_INVEST_CLIENT_ID",
    "TOSS_INVEST_CLIENT_SECRET"
)

$missing = @()
foreach ($key in $requiredKeys) {
    if (-not $envValues.ContainsKey($key)) {
        $missing += "$key missing"
        continue
    }

    $value = $envValues[$key]
    if ([string]::IsNullOrWhiteSpace($value) -or $value.StartsWith("REPLACE_ME")) {
        $missing += "$key empty"
    }
}

if ($missing.Count -gt 0) {
    $missing | ForEach-Object { Write-Host $_ }
    exit 1
}

if (
    -not $envValues.ContainsKey("TOSS_INVEST_ACCOUNT_ID") -or
    [string]::IsNullOrWhiteSpace($envValues["TOSS_INVEST_ACCOUNT_ID"])
) {
    Write-Host "TOSS_INVEST_ACCOUNT_ID is empty. The backend will call Toss accounts API to auto-select an account."
}

$backendProcess = $null
$startedBackend = $false

try {
    Write-Host "Checking local backend..."
    if (Test-BackendHealth) {
        Write-Host "Existing local backend is already running. It will be left running after sync."
    }
    else {
        Write-Host "Starting local backend on http://127.0.0.1:8000 ..."
        Remove-Item -Path $outLog, $errLog -Force -ErrorAction SilentlyContinue

        $backendProcess = Start-Process `
            -FilePath "python" `
            -ArgumentList @("-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000") `
            -WorkingDirectory $backendDir `
            -WindowStyle Hidden `
            -RedirectStandardOutput $outLog `
            -RedirectStandardError $errLog `
            -PassThru
        $startedBackend = $true

        $healthy = $false
        for ($i = 1; $i -le 30; $i++) {
            if (Test-BackendHealth) {
                $healthy = $true
                break
            }

            Start-Sleep -Seconds 1
        }

        if (-not $healthy) {
            Write-Host "Local backend did not become healthy in time."
            if (Test-Path $errLog) {
                Write-Host "Backend error log:"
                Get-Content -Path $errLog -Tail 80
            }
            exit 1
        }
    }

    Write-Host "Running Toss Invest read-only holdings sync..."
    $token = $envValues["API_ACCESS_TOKEN"]
    $result = Invoke-RestMethod `
        -Method POST `
        -Uri "http://127.0.0.1:8000/api/toss/sync" `
        -Headers @{ Authorization = "Bearer $token" } `
        -TimeoutSec 120

    $duplicates = @($result.duplicate_manual_assets)
    Write-Host ("Summary: synced={0}, created={1}, updated={2}, stale={3}, manual_duplicates={4}" -f `
        $result.synced_count,
        $result.created_count,
        $result.updated_count,
        $result.stale_count,
        $duplicates.Count)

    if ($duplicates.Count -gt 0) {
        Write-Host "Manual duplicate tickers:"
        $duplicates | Select-Object -First 30 | ForEach-Object {
            Write-Host ("- {0} {1}" -f $_.market, $_.ticker)
        }

        if ($duplicates.Count -gt 30) {
            Write-Host ("- ... and {0} more" -f ($duplicates.Count - 30))
        }
    }

    Write-Host "Done."
    exit 0
}
catch {
    $errorText = ""
    if ($_.ErrorDetails.Message) {
        $errorText = $_.ErrorDetails.Message
    }
    else {
        $errorText = $_.Exception.Message
    }

    Write-Host $errorText
    if ($errorText -match "GET /api/v1/accounts: 403") {
        Write-Host "Toss denied account list lookup. Check Toss Invest Open API account/asset permission, IP allowlist, or set TOSS_INVEST_ACCOUNT_ID if Toss provides your accountSeq."
    }

    Write-Host "Toss sync failed."
    exit 1
}
finally {
    if ($startedBackend) {
        Stop-StartedBackend -Process $backendProcess
    }
}
