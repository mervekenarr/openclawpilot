param(
    [string]$OllamaBaseUrl = "http://172.16.41.43:11434",
    [string]$OllamaModel = "qwen2.5:14b",
    [string]$GatewayToken = "",
    [switch]$ForceBuild
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
        [string[]]$Arguments
    )

    & docker compose @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Docker Compose komutu basarisiz oldu: docker compose $($Arguments -join ' ')"
    }
}

function Invoke-OpenClawConfig {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments
    )

    $composeArgs = @(
        "run",
        "--rm",
        "--no-deps",
        "--entrypoint",
        "node",
        "openclaw-gateway",
        "dist/index.js"
    ) + $Arguments

    Invoke-OpenClawCompose -Arguments $composeArgs
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
$env:OPENCLAW_GATEWAY_BIND = "lan"
$env:OPENCLAW_GATEWAY_TOKEN = $GatewayToken

Write-Host ""
Write-Host "OpenClaw Docker kurulumu basliyor..." -ForegroundColor Cyan
Write-Host "Runtime home:" $runtimeHome
Write-Host "Runtime workspace:" $runtimeWorkspace
Write-Host "Ollama:" $OllamaBaseUrl " | model:" $OllamaModel
Write-Host ""

$packageJsonPath = Join-Path ((Join-Path ((& npm root -g).Trim()) "openclaw")) "package.json"
$package = Get-Content -Raw -Path $packageJsonPath | ConvertFrom-Json
$version = $package.version
$env:OPENCLAW_IMAGE = "openclaw-local:$version"
$composeEnvPath = Join-Path $runtimeDir ".env"

Write-Host "1/5 - Docker image hazirlaniyor..." -ForegroundColor Yellow
& docker image inspect $env:OPENCLAW_IMAGE *> $null
$imageExists = $LASTEXITCODE -eq 0

if ($ForceBuild -or -not $imageExists) {
    Write-Host "Docker image build ediliyor:" $env:OPENCLAW_IMAGE -ForegroundColor Yellow
    & powershell -ExecutionPolicy Bypass -File (Join-Path $runtimeDir "build-openclaw.ps1")
    if ($LASTEXITCODE -ne 0) {
        throw "OpenClaw image build basarisiz oldu."
    }
} else {
    Write-Host "Mevcut image kullaniliyor:" $env:OPENCLAW_IMAGE -ForegroundColor DarkYellow
}

[System.IO.File]::WriteAllText(
    $composeEnvPath,
    @(
        "OPENCLAW_IMAGE=$($env:OPENCLAW_IMAGE)"
        "OPENCLAW_GATEWAY_BIND=lan"
    ) -join "`r`n",
    (New-Object System.Text.UTF8Encoding($false))
)

Write-Host "2/5 - Konfigürasyon ve Guvenlik ayarlari yaziliyor..." -ForegroundColor Yellow
Invoke-OpenClawConfig -Arguments @("config", "set", "gateway.mode", "local")
Invoke-OpenClawConfig -Arguments @("config", "set", "gateway.bind", "lan")
Invoke-OpenClawConfig -Arguments @("config", "set", "gateway.auth.mode", "token")
Invoke-OpenClawConfig -Arguments @("config", "set", "gateway.auth.token", $GatewayToken)
Invoke-OpenClawConfig -Arguments @("config", "set", "gateway.controlUi.allowedOrigins", "[`"http://127.0.0.1:18789`",`"http://localhost:18789`"]", "--strict-json")
Invoke-OpenClawConfig -Arguments @("config", "set", "browser.enabled", "false", "--strict-json")

Invoke-OpenClawConfig -Arguments @("config", "set", "models.providers.ollama.apiKey", "ollama-local")
Invoke-OpenClawConfig -Arguments @("config", "set", "models.providers.ollama.baseUrl", $OllamaBaseUrl)
Invoke-OpenClawConfig -Arguments @("config", "set", "models.providers.ollama.api", "ollama")
Invoke-OpenClawConfig -Arguments @("config", "set", "agents.defaults.model.primary", "ollama/$OllamaModel")

$batchConfigHost = Join-Path $runtimeHome "config-set.batch.json"
$batchConfigContainer = "/home/node/.openclaw/config-set.batch.json"
$batchConfig = @(
    @{
        path = "models.providers.ollama.models"
        value = @(
            @{
                id = $OllamaModel
                name = $OllamaModel
                reasoning = $false
                input = @("text")
                cost = @{
                    input = 0
                    output = 0
                    cacheRead = 0
                    cacheWrite = 0
                }
                contextWindow = 32768
                maxTokens = 81920
            }
        )
    },
    @{
        path = "agents.defaults.models"
        value = @{
            ("ollama/$OllamaModel") = @{}
        }
    }
)

$batchJson = $batchConfig | ConvertTo-Json -Depth 8
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($batchConfigHost, $batchJson, $utf8NoBom)

Invoke-OpenClawConfig -Arguments @("config", "set", "--batch-file", $batchConfigContainer)
Remove-Item -LiteralPath $batchConfigHost -Force -ErrorAction SilentlyContinue

Write-Host "3/5 - Ilk onboarding calistiriliyor..." -ForegroundColor Yellow
Invoke-OpenClawConfig -Arguments @("onboard", "--mode", "local", "--no-install-daemon")

Write-Host "4/5 - Skill'ler runtime workspace'e kopyalaniyor..." -ForegroundColor Yellow
$skillsSource = Join-Path $runtimeDir "skills"
$skillsTarget = Join-Path $runtimeWorkspace "skills"
New-Item -ItemType Directory -Force -Path $skillsTarget | Out-Null
Get-ChildItem -LiteralPath $skillsSource | ForEach-Object {
    Copy-Item -LiteralPath $_.FullName -Destination $skillsTarget -Recurse -Force
}

Write-Host "5/5 - Gateway baslatiliyor..." -ForegroundColor Yellow
Invoke-OpenClawCompose -Arguments @("up", "-d", "openclaw-gateway")
Start-Sleep -Seconds 5
Invoke-OpenClawCompose -Arguments @("ps")

Write-Host ""
Write-Host "OpenClaw Docker kurulumu tamamlandi." -ForegroundColor Green
Write-Host "Dashboard: http://127.0.0.1:18789/"
Write-Host "Token: $GatewayToken"
Write-Host ""
Write-Host "Kontrol: docker compose run --rm openclaw-cli skills list" -ForegroundColor Cyan
