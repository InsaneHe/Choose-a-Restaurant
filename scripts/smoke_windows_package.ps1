param(
    [string]$ReleasePath = "dist\ChooseRestaurant",
    [string]$SourceRestaurants = "data\restaurants.json",
    [int]$Port = 8000
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$release = [System.IO.Path]::GetFullPath((Join-Path $projectRoot $ReleasePath))
$sourceData = [System.IO.Path]::GetFullPath((Join-Path $projectRoot $SourceRestaurants))
$temporaryRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("ChooseRestaurant-v2-04-" + [guid]::NewGuid().ToString("N"))
$localAppData = Join-Path $temporaryRoot "UserLocalAppData"
$outsideWorkingDirectory = Join-Path $temporaryRoot "OutsideProject"
$releaseA = Join-Path $temporaryRoot "ReleaseA"
$releaseB = Join-Path $temporaryRoot "ReleaseB"
$baseUrl = "http://127.0.0.1:$Port/"
$process = $null
$listener = $null

function Start-IsolatedPackage([string]$Executable, [string]$Arguments) {
    $stdout = Join-Path $temporaryRoot ("stdout-" + [guid]::NewGuid().ToString("N") + ".log")
    $stderr = Join-Path $temporaryRoot ("stderr-" + [guid]::NewGuid().ToString("N") + ".log")
    $start = [System.Diagnostics.ProcessStartInfo]::new()
    $start.FileName = $Executable
    $start.Arguments = $Arguments
    $start.WorkingDirectory = $outsideWorkingDirectory
    $start.UseShellExecute = $false
    $start.CreateNoWindow = $true
    $start.RedirectStandardInput = $true
    $start.RedirectStandardOutput = $true
    $start.RedirectStandardError = $true
    $start.Environment["LOCALAPPDATA"] = $localAppData
    $start.Environment["PATH"] = "$env:SystemRoot\System32"
    foreach ($name in @("PYTHONHOME", "PYTHONPATH", "VIRTUAL_ENV", "AMAP_WEB_SERVICE_KEY", "AMAP_JS_API_KEY", "AMAP_JS_SECURITY_KEY", "AMAP_SECURITY_JS_CODE")) {
        [void]$start.Environment.Remove($name)
    }
    $started = [System.Diagnostics.Process]::new()
    $started.StartInfo = $start
    [void]$started.Start()
    return $started
}

function Wait-ForHealth([int]$Seconds = 20) {
    $deadline = [DateTime]::UtcNow.AddSeconds($Seconds)
    while ([DateTime]::UtcNow -lt $deadline) {
        try {
            $health = Invoke-RestMethod -Uri ($baseUrl + "api/health") -TimeoutSec 1
            if ($health.status -eq "ok") { return }
        }
        catch {}
        Start-Sleep -Milliseconds 150
    }
    throw "Packaged service did not become healthy."
}

function Stop-Package {
    if ($null -ne $script:process -and -not $script:process.HasExited) {
        $script:process.Kill()
        [void]$script:process.WaitForExit(5000)
    }
    $script:process = $null
}

if (-not (Test-Path -LiteralPath (Join-Path $release "ChooseRestaurant.exe"))) {
    throw "Release executable not found: $release"
}

New-Item -ItemType Directory -Path $temporaryRoot, $localAppData, $outsideWorkingDirectory | Out-Null
Copy-Item -LiteralPath $release -Destination $releaseA -Recurse
Copy-Item -LiteralPath $release -Destination $releaseB -Recurse

try {
    $process = Start-IsolatedPackage (Join-Path $releaseA "ChooseRestaurant.exe") "--no-browser --port $Port"
    Wait-ForHealth
    $homepage = Invoke-WebRequest -UseBasicParsing -Uri $baseUrl
    $static = Invoke-WebRequest -UseBasicParsing -Uri ($baseUrl + "static/app.js")
    $runtime = Invoke-RestMethod -Uri ($baseUrl + "api/runtime/info")
    $initialRestaurants = Invoke-RestMethod -Uri ($baseUrl + "api/restaurants")
    $noKey = Invoke-RestMethod -Uri ($baseUrl + "api/map/config")
    if ($homepage.StatusCode -ne 200 -or $static.StatusCode -ne 200) { throw "Static assets failed." }
    if ($runtime.mode -ne "packaged" -or $initialRestaurants.Count -ne 17) { throw "First-run package state is incorrect." }
    if ($noKey.js_api_enabled -or $noKey.web_service_enabled) { throw "No-key state is incorrect." }

    $importBody = @{ json_text = Get-Content -LiteralPath $sourceData -Raw -Encoding UTF8 } | ConvertTo-Json -Compress
    $imported = Invoke-RestMethod -Method Post -Uri ($baseUrl + "api/data/import") -ContentType "application/json" -Body $importBody
    if ($imported.count -ne 17) { throw "Import did not produce 17 restaurants." }
    Invoke-RestMethod -Method Patch -Uri ($baseUrl + "api/restaurants/1") -ContentType "application/json" -Body (@{ tags = @("隔离验收", "Persisted") } | ConvertTo-Json -Compress) | Out-Null
    Invoke-RestMethod -Method Patch -Uri ($baseUrl + "api/restaurants/1/selection-status") -ContentType "application/json" -Body (@{ selection_status = "archived" } | ConvertTo-Json -Compress) | Out-Null
    $singleRandom = Invoke-RestMethod -Method Post -Uri ($baseUrl + "api/random")
    if ($singleRandom.total -ne 16 -or $singleRandom.restaurant.id -eq 1) { throw "Single random did not exclude the archived restaurant." }

    $generated = @{
        web_service_key = "web-" + [guid]::NewGuid().ToString("N")
        js_api_key = "js-" + [guid]::NewGuid().ToString("N")
        js_security_key = "security-" + [guid]::NewGuid().ToString("N")
    }
    Invoke-RestMethod -Method Post -Uri ($baseUrl + "api/settings/amap") -ContentType "application/json" -Body ($generated | ConvertTo-Json -Compress) | Out-Null
    $configured = Invoke-RestMethod -Uri ($baseUrl + "api/settings/amap")
    if (-not ($configured.web_service_configured -and $configured.js_api_configured -and $configured.js_security_configured)) { throw "Protected configuration status is incorrect." }
    $credentialPath = Join-Path $localAppData "ChooseRestaurant\config\amap-credentials.dat"
    if (-not (Test-Path -LiteralPath $credentialPath) -or (Get-Item -LiteralPath $credentialPath).Length -eq 0) { throw "Protected configuration file was not created." }
    $backupCount = (Get-ChildItem -LiteralPath (Join-Path $localAppData "ChooseRestaurant\data\backups") -File).Count
    if ($backupCount -ne 1) { throw "Import backup count is incorrect." }

    Stop-Package
    $serviceStopped = $false
    try { Invoke-WebRequest -UseBasicParsing -Uri $baseUrl -TimeoutSec 2 | Out-Null }
    catch { $serviceStopped = $true }
    if (-not $serviceStopped) { throw "Service was still reachable after process exit." }

    $process = Start-IsolatedPackage (Join-Path $releaseB "ChooseRestaurant.exe") "--no-browser --port $Port"
    Wait-ForHealth
    $restarted = Invoke-RestMethod -Uri ($baseUrl + "api/restaurants")
    $first = $restarted | Where-Object { $_.id -eq 1 }
    $restartedSettings = Invoke-RestMethod -Uri ($baseUrl + "api/settings/amap")
    if ($restarted.Count -ne 17 -or $first.selection_status -ne "archived" -or $first.tags.Count -ne 2) { throw "User data did not survive replacement/restart." }
    if (-not $restartedSettings.web_service_configured) { throw "Protected configuration did not survive restart." }

    $backupDirectory = Join-Path $localAppData "ChooseRestaurant\data\backups"
    $initialBackup = Get-ChildItem -LiteralPath $backupDirectory -File | Select-Object -First 1
    $initialBackupRecords = Get-Content -LiteralPath $initialBackup.FullName -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($initialBackupRecords.Count -ne 17) { throw "The import backup was not the published 17-record template." }
    $restoreBody = @{ json_text = Get-Content -LiteralPath $initialBackup.FullName -Raw -Encoding UTF8 } | ConvertTo-Json -Compress
    $restored = Invoke-RestMethod -Method Post -Uri ($baseUrl + "api/data/import") -ContentType "application/json" -Body $restoreBody
    if ($restored.count -ne 17) { throw "Restoring the pre-import backup did not produce 17 records." }
    $restoredRecords = Invoke-RestMethod -Uri ($baseUrl + "api/restaurants")
    if ($restoredRecords.Count -ne 17 -or @($restoredRecords | Where-Object { $_.selection_status -ne "active" -or $_.tags.Count -ne 0 }).Count -ne 0) {
        throw "Restored V1 records did not use active/empty-tag defaults."
    }
    $allBackups = @(Get-ChildItem -LiteralPath $backupDirectory -File)
    if ($allBackups.Count -ne 2) { throw "Restore did not preserve both migration generations." }
    $v2Backup = $allBackups | Where-Object { $_.FullName -ne $initialBackup.FullName } | Select-Object -First 1
    $v2BackupRecords = Get-Content -LiteralPath $v2Backup.FullName -Raw -Encoding UTF8 | ConvertFrom-Json
    $v2First = $v2BackupRecords | Where-Object { $_.id -eq 1 }
    if ($v2BackupRecords.Count -ne 17 -or $v2First.selection_status -ne "archived" -or $v2First.tags.Count -ne 2) {
        throw "Restoring the old backup did not preserve a recoverable backup of the V2 state."
    }
    Stop-Package

    $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $Port)
    $listener.Start()
    $process = Start-IsolatedPackage (Join-Path $releaseB "ChooseRestaurant.exe") "--port $Port"
    Start-Sleep -Milliseconds 500
    if ($process.HasExited) { throw "Port-conflict message did not pause for acknowledgement." }
    $process.StandardInput.WriteLine("")
    $process.StandardInput.Close()
    if (-not $process.WaitForExit(10000)) { throw "Port-conflict process did not exit after acknowledgement." }
    if ($process.ExitCode -ne 2) { throw "Port-conflict exit code was $($process.ExitCode), expected 2." }
    $process = $null
    $listener.Stop()
    $listener = $null

    [pscustomobject]@{
        ReleaseExecutable = Join-Path $release "ChooseRestaurant.exe"
        IsolatedPath = $outsideWorkingDirectory
        PythonRemovedFromPath = $true
        InitialTemplateCount = 17
        ImportedCount = 17
        RandomActiveCountAfterArchive = $singleRandom.total
        BackupCountAfterImport = $backupCount
        RestoredPublishedTemplateCount = 17
        BackupCountAfterRestore = $allBackups.Count
        RestorePreservedV2Backup = $true
        RestartPreservedTagsAndArchive = $true
        ProtectedConfigurationPersisted = $true
        StaticAndApiPassed = $true
        NoKeyStatePassed = $true
        PortConflictExitCode = 2
        PortConflictPausedForAcknowledgement = $true
        ServiceStoppedAfterExit = $true
    }
}
finally {
    Stop-Package
    if ($null -ne $listener) { $listener.Stop() }
    $resolvedRoot = [System.IO.Path]::GetFullPath($temporaryRoot)
    $systemTemp = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())
    if ($resolvedRoot.StartsWith($systemTemp, [System.StringComparison]::OrdinalIgnoreCase) -and (Test-Path -LiteralPath $resolvedRoot)) {
        Remove-Item -LiteralPath $resolvedRoot -Recurse -Force
    }
}
