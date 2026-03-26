param(
    [string]$OllamaBaseUrl = "http://172.16.41.43:11434",
    [string]$OllamaModel = "qwen2.5:14b",
    [string]$GatewayToken = ""
)

$ErrorActionPreference = "Stop"

function New-RandomHexToken {
    param([int]$Bytes = 32)
    $buffer = New-Object byte[] $Bytes
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($buffer)
    -join ($buffer | ForEach-Object { $_.ToString("x2") })
}

function Invoke-OpenClawCompose {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Args
    )

    & docker compose @Args
    if ($LASTEXITCODE -ne 0) {
        throw "Docker Compose komutu basarisiz oldu: docker compose $($Args -join ' ')"
    }
}

function Invoke-OpenClawConfig {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Args
    )

    $composeArgs = @(
        "run",
        "--rm",
        "--no-deps",
        "--entrypoint",
        "node",
        "openclaw-gateway",
        "dist/index.js"
    ) + $Args

    Invoke-OpenClawCompose -Args $composeArgs
}

$runtimeDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $runtimeDir

if (-not $GatewayToken) {
    $GatewayToken = New-RandomHexToken
}

$runtimeHome = Join-Path $runtimeDir "runtime-home"
$runtimeWorkspace = Join-Path $runtimeDir "runtime-workspace"
New-Item -ItemType Directory -Force -Path $runtimeHome, $runtimeWorkspace | Out-Null

$env:OPENCLAW_CONFIG_DIR = $runtimeHome
$env:OPENCLAW_WORKSPACE_DIR = $runtimeWorkspace
$env:OPENCLAW_GATEWAY_BIND = "loopback"
$env:OPENCLAW_GATEWAY_TOKEN = $GatewayToken

Write-Host ""
Write-Host "OpenClaw Docker kurulumu basliyor..." -ForegroundColor Cyan
Write-Host "Runtime home:" $runtimeHome
Write-Host "Runtime workspace:" $runtimeWorkspace
Write-Host "Ollama:" $OllamaBaseUrl " | model:" $OllamaModel
Write-Host ""

Write-Host "1/5 - Docker image build ediliyor..." -ForegroundColor Yellow
& powershell -ExecutionPolicy Bypass -File (Join-Path $runtimeDir "build-openclaw.ps1")
if ($LASTEXITCODE -ne 0) {
    throw "OpenClaw image build basarisiz oldu."
}

$packageJsonPath = Join-Path ((Join-Path ((& npm root -g).Trim()) "openclaw")) "package.json"
$package = Get-Content -Raw -Path $packageJsonPath | ConvertFrom-Json
$version = $package.version
$env:OPENCLAW_IMAGE = "openclaw-local:$version"

Write-Host "2/5 - Ilk onboarding calistiriliyor..." -ForegroundColor Yellow
Invoke-OpenClawConfig -Args @("onboard", "--mode", "local", "--no-install-daemon")

Write-Host "3/5 - Guvenlik ayarlari yaziliyor..." -ForegroundColor Yellow
Invoke-OpenClawConfig -Args @("config", "set", "gateway.mode", "local")
Invoke-OpenClawConfig -Args @("config", "set", "gateway.bind", "loopback")
Invoke-OpenClawConfig -Args @("config", "set", "gateway.auth.mode", "token")
Invoke-OpenClawConfig -Args @("config", "set", "gateway.auth.token", $GatewayToken)
Invoke-OpenClawConfig -Args @("config", "set", "browser.enabled", "false", "--strict-json")

$modelsJson = "[{`"id`":`"$OllamaModel`",`"name`":`"$OllamaModel`",`"reasoning`":false,`"input`":[`"text`"],`"cost`":{`"input`":0,`"output`":0,`"cacheRead`":0,`"cacheWrite`":0},`"contextWindow`":8192,`"maxTokens`":81920}]"
$defaultsJson = "{`"ollama/$OllamaModel`":{}}"

Invoke-OpenClawConfig -Args @("config", "set", "models.providers.ollama.apiKey", "ollama-local")
Invoke-OpenClawConfig -Args @("config", "set", "models.providers.ollama.baseUrl", $OllamaBaseUrl)
Invoke-OpenClawConfig -Args @("config", "set", "models.providers.ollama.api", "ollama")
Invoke-OpenClawConfig -Args @("config", "set", "models.providers.ollama.models", $modelsJson, "--strict-json")
Invoke-OpenClawConfig -Args @("config", "set", "agents.defaults.model.primary", "ollama/$OllamaModel")
Invoke-OpenClawConfig -Args @("config", "set", "agents.defaults.models", $defaultsJson, "--strict-json")

Write-Host "4/5 - Skill'ler runtime workspace'e kopyalaniyor..." -ForegroundColor Yellow
$skillsSource = Join-Path $runtimeDir "skills"
$skillsTarget = Join-Path $runtimeWorkspace "skills"
New-Item -ItemType Directory -Force -Path $skillsTarget | Out-Null
Get-ChildItem -LiteralPath $skillsSource | ForEach-Object {
    Copy-Item -LiteralPath $_.FullName -Destination $skillsTarget -Recurse -Force
}

Write-Host "5/5 - Gateway baslatiliyor..." -ForegroundColor Yellow
Invoke-OpenClawCompose -Args @("up", "-d", "openclaw-gateway")
Start-Sleep -Seconds 5
Invoke-OpenClawCompose -Args @("ps")

Write-Host ""
Write-Host "OpenClaw Docker kurulumu tamamlandi." -ForegroundColor Green
Write-Host "Dashboard: http://127.0.0.1:18789/"
Write-Host "Token: $GatewayToken"
Write-Host ""
Write-Host "Kontrol: docker compose run --rm openclaw-cli skills list" -ForegroundColor Cyan
