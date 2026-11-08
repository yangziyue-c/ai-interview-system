param(
    [switch]$VerifyOnly
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$manifestPath = Join-Path $repoRoot "runtime_assets.manifest.json"
$zstdPath = Join-Path $repoRoot "tools/bin/zstd.exe"

if (-not (Test-Path -LiteralPath $manifestPath)) {
    throw "Runtime asset manifest not found: $manifestPath"
}

$utf8 = New-Object System.Text.UTF8Encoding($false)
$manifestJson = [System.IO.File]::ReadAllText($manifestPath, $utf8)
$manifest = $manifestJson | ConvertFrom-Json

function Get-ExpectedAsset([string]$relativePath) {
    for ($i = 0; $i -lt $manifest.assets.Count; $i++) {
        $candidate = $manifest.assets[$i]
        if ($candidate.path -eq $relativePath) {
            return $candidate
        }
    }
    throw "Runtime asset is not declared in the manifest: $relativePath"
}

function Test-AssetFile([string]$fullPath, $expected) {
    if (-not (Test-Path -LiteralPath $fullPath -PathType Leaf)) {
        return $false
    }

    $item = Get-Item -LiteralPath $fullPath
    if ($item.Length -ne [long]$expected.bytes) {
        return $false
    }

    $actual = (Get-FileHash -LiteralPath $fullPath -Algorithm SHA256).Hash.ToLowerInvariant()
    return $actual -eq $expected.sha256.ToLowerInvariant()
}

function Join-FileParts([string[]]$sources, [string]$outputPath) {
    $output = [System.IO.File]::Open(
        $outputPath,
        [System.IO.FileMode]::Create,
        [System.IO.FileAccess]::Write,
        [System.IO.FileShare]::None
    )
    try {
        foreach ($source in $sources) {
            $input = [System.IO.File]::OpenRead($source)
            try {
                $input.CopyTo($output, 4194304)
            }
            finally {
                $input.Dispose()
            }
        }
    }
    finally {
        $output.Dispose()
    }
}

Push-Location $repoRoot
try {
    $packageTotal = 0
    for ($i = 0; $i -lt $manifest.packageFiles.Count; $i++) {
        $packageFile = $manifest.packageFiles[$i]
        $path = Join-Path $repoRoot $packageFile.path
        if (-not (Test-AssetFile $path $packageFile)) {
            throw "Runtime package file is missing or corrupted: $($packageFile.path)"
        }
        $packageTotal += [long]$packageFile.bytes
    }

    if ($packageTotal -ne [long]$manifest.packageBytes) {
        throw "Runtime package size mismatch: expected $($manifest.packageBytes), got $packageTotal"
    }

    Write-Host "Committed runtime package verified: $($manifest.packageFiles.Count) files, $packageTotal bytes."
    if ($VerifyOnly) {
        return
    }

    if (-not (Test-Path -LiteralPath $zstdPath -PathType Leaf)) {
        throw "zstd decoder not found: tools/bin/zstd.exe"
    }

    for ($jobIndex = 0; $jobIndex -lt $manifest.restoreJobs.Count; $jobIndex++) {
        $job = $manifest.restoreJobs[$jobIndex]
        $outputPath = Join-Path $repoRoot $job.output
        $expected = Get-ExpectedAsset $job.output

        if (Test-AssetFile $outputPath $expected) {
            Write-Host "Already present: $($job.output)"
            continue
        }

        $outputParent = Split-Path -Parent $outputPath
        New-Item -ItemType Directory -Force -Path $outputParent | Out-Null
        $tempPath = "$outputPath.restore.tmp"
        if ([System.IO.File]::Exists($tempPath)) {
            [System.IO.File]::Delete($tempPath)
        }

        $sources = @()
        for ($sourceIndex = 0; $sourceIndex -lt $job.sources.Count; $sourceIndex++) {
            $sources += Join-Path $repoRoot $job.sources[$sourceIndex]
        }

        try {
            if ($job.method -eq "zstd") {
                & $zstdPath -d -f $sources[0] -o $tempPath
                if ($LASTEXITCODE -ne 0) {
                    throw "zstd extraction failed: $($job.sources[0])"
                }
            }
            elseif ($job.method -eq "concat") {
                Join-FileParts $sources $tempPath
            }
            else {
                throw "Unknown restore method: $($job.method)"
            }

            if (-not (Test-AssetFile $tempPath $expected)) {
                throw "Restored file failed verification: $($job.output)"
            }

            if ([System.IO.File]::Exists($outputPath)) {
                [System.IO.File]::Delete($outputPath)
            }
            [System.IO.File]::Move($tempPath, $outputPath)
            Write-Host "Restored: $($job.output)"
        }
        finally {
            if ([System.IO.File]::Exists($tempPath)) {
                [System.IO.File]::Delete($tempPath)
            }
        }
    }

    for ($assetIndex = 0; $assetIndex -lt $manifest.assets.Count; $assetIndex++) {
        $asset = $manifest.assets[$assetIndex]
        $path = Join-Path $repoRoot $asset.path
        if (-not (Test-AssetFile $path $asset)) {
            throw "Runtime asset verification failed: $($asset.path)"
        }
    }
    Write-Host "Runtime assets verified: $($manifest.assets.Count) files."

    for ($copyIndex = 0; $copyIndex -lt $manifest.runtimeCopies.Count; $copyIndex++) {
        $copy = $manifest.runtimeCopies[$copyIndex]
        $source = Join-Path $repoRoot $copy.source
        if (-not (Test-Path -LiteralPath $source)) {
            throw "Missing runtime copy source: $($copy.source)"
        }

        for ($targetIndex = 0; $targetIndex -lt $copy.targets.Count; $targetIndex++) {
            $targetRelative = $copy.targets[$targetIndex]
            $target = Join-Path $repoRoot $targetRelative
            $targetParent = Split-Path -Parent $target
            New-Item -ItemType Directory -Force -Path $targetParent | Out-Null

            if ((Get-Item -LiteralPath $source).PSIsContainer) {
                New-Item -ItemType Directory -Force -Path $target | Out-Null
                Copy-Item -Path (Join-Path $source "*") -Destination $target -Recurse -Force
            }
            else {
                Copy-Item -LiteralPath $source -Destination $target -Force
            }
            Write-Host "Restored runtime copy: $targetRelative"
        }
    }

    Write-Host "Runtime assets are ready."
}
finally {
    Pop-Location
}
