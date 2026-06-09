param(
    [string]$OutputPath = "release\image_all-platform.zip",
    [bool]$IncludeRuntimeData = $true
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $repoRoot

$packageFiles = git ls-files -co --exclude-standard
if (-not $packageFiles) {
    throw "No files found to package."
}

$outputDir = Split-Path -Parent $OutputPath
if ($outputDir) {
    New-Item -ItemType Directory -Force -Path $outputDir | Out-Null
}

if (Test-Path $OutputPath) {
    Remove-Item $OutputPath -Force
}

$stagingRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("image-all-package-" + [System.Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Force -Path $stagingRoot | Out-Null

try {
    function Copy-PackageFile {
        param(
            [string]$SourcePath,
            [string]$TargetRelativePath
        )
        if (-not (Test-Path $SourcePath)) {
            return
        }
        $target = Join-Path $stagingRoot $TargetRelativePath
        $targetDir = Split-Path -Parent $target
        if ($targetDir) {
            New-Item -ItemType Directory -Force -Path $targetDir | Out-Null
        }
        Copy-Item -LiteralPath $SourcePath -Destination $target -Force
    }

    foreach ($file in $packageFiles) {
        $target = Join-Path $stagingRoot $file
        $targetDir = Split-Path -Parent $target
        if ($targetDir) {
            New-Item -ItemType Directory -Force -Path $targetDir | Out-Null
        }
        Copy-Item -LiteralPath $file -Destination $target -Force
    }

    if ($IncludeRuntimeData) {
        if (Test-Path "platform_runtime\platform.db") {
            python -B scripts\checkpoint_platform_db.py platform_runtime\platform.db
        }
        Copy-PackageFile -SourcePath ".env" -TargetRelativePath ".env"
        Copy-PackageFile -SourcePath "platform_runtime\config.json" -TargetRelativePath "platform_runtime\config.json"
        Copy-PackageFile -SourcePath "platform_runtime\platform.db" -TargetRelativePath "platform_runtime\platform.db"
        Copy-PackageFile -SourcePath "platform_runtime\platform.db-wal" -TargetRelativePath "platform_runtime\platform.db-wal"
        Copy-PackageFile -SourcePath "platform_runtime\platform.db-shm" -TargetRelativePath "platform_runtime\platform.db-shm"
    }

    Compress-Archive -Path (Join-Path $stagingRoot "*") -DestinationPath $OutputPath -Force
}
finally {
    if (Test-Path $stagingRoot) {
        Remove-Item $stagingRoot -Recurse -Force
    }
}

Write-Host "Created $OutputPath"
if ($IncludeRuntimeData) {
    Write-Host "Included .env, platform_runtime/config.json and platform_runtime/platform.db*"
}
