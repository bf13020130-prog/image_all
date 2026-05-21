param(
    [string]$OutputPath = "release\image_all-platform.zip"
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
    foreach ($file in $packageFiles) {
        $target = Join-Path $stagingRoot $file
        $targetDir = Split-Path -Parent $target
        if ($targetDir) {
            New-Item -ItemType Directory -Force -Path $targetDir | Out-Null
        }
        Copy-Item -LiteralPath $file -Destination $target -Force
    }

    Compress-Archive -Path (Join-Path $stagingRoot "*") -DestinationPath $OutputPath -Force
}
finally {
    if (Test-Path $stagingRoot) {
        Remove-Item $stagingRoot -Recurse -Force
    }
}

Write-Host "Created $OutputPath"
