$ErrorActionPreference = "Stop"

$globalRoot = (& npm root -g).Trim()
if (-not $globalRoot) {
    throw "Global npm root bulunamadi."
}

$sourceDir = Join-Path $globalRoot "openclaw"
if (-not (Test-Path $sourceDir)) {
    throw "Global openclaw paketi bulunamadi: $sourceDir"
}

$packageJsonPath = Join-Path $sourceDir "package.json"
if (-not (Test-Path $packageJsonPath)) {
    throw "openclaw package.json bulunamadi: $packageJsonPath"
}

$package = Get-Content -Raw -Path $packageJsonPath | ConvertFrom-Json
$version = $package.version
if (-not $version) {
    throw "openclaw versiyonu okunamadi."
}

$repoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$dockerfilePath = Join-Path $PSScriptRoot "Dockerfile.local"
$imageTag = "openclaw-local:$version"

Write-Host "OpenClaw kaynak dizini:" $sourceDir
Write-Host "Docker image etiketi:" $imageTag

docker build -t $imageTag -f $dockerfilePath $sourceDir
