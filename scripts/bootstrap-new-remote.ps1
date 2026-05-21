param(
    [Parameter(Mandatory = $true)]
    [string]$RemoteUrl,
    [string]$Branch = "main",
    [string]$CommitMessage = "Initial import"
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $repoRoot

git switch --orphan bootstrap-temp | Out-Null
git add -A

try {
    git commit -m $CommitMessage
} catch {
    throw "Git commit failed. Check that your identity is configured and that there are staged changes."
}

git branch -M $Branch
if (git remote get-url origin 2>$null) {
    git remote set-url origin $RemoteUrl
} else {
    git remote add origin $RemoteUrl
}
git push -u origin $Branch
