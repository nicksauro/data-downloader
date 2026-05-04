<#
.SYNOPSIS
    Bootstrap script para popular profitdll/DLLs/Win64/ com binários ProfitDLL.

.DESCRIPTION
    A ProfitDLL é distribuída via instalação ProfitChart (Nelogica) e NÃO
    é commitada no repo (decisão ADR-008 — DLL Distribution Strategy).
    Este script copia os arquivos necessários da instalação local do usuário
    para o working tree, permitindo executar/testar o data-downloader sem
    redistribuir DLL proprietária.

.PARAMETER ProfitChartPath
    Caminho para a pasta bin/ da instalação ProfitChart.
    Default: C:\Profit\bin\

.PARAMETER DestinationPath
    Caminho destino dentro do repo.
    Default: ./profitdll/DLLs/Win64/ (resolvido relativo a este script)

.PARAMETER Force
    Sobrescreve arquivos existentes sem perguntar.

.EXAMPLE
    .\scripts\bootstrap-dll.ps1
    .\scripts\bootstrap-dll.ps1 -ProfitChartPath "D:\Apps\ProfitPro\bin"
    .\scripts\bootstrap-dll.ps1 -Force

.NOTES
    Owner: Gage (devops)
    Story: 0.1 — Environment Bootstrap
    Coordena com: ADR-008 (Aria), Nelo (companions list)
    Validar com: python scripts/verify-dll-companions.py
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $false)]
    [string]$ProfitChartPath = "C:\Profit\bin",

    [Parameter(Mandatory = $false)]
    [string]$DestinationPath = "",

    [Parameter(Mandatory = $false)]
    [switch]$Force
)

$ErrorActionPreference = "Stop"

# -----------------------------------------------------------------------------
# Resolver caminhos absolutos
# -----------------------------------------------------------------------------
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$RepoRoot  = Split-Path -Parent $ScriptDir

if ([string]::IsNullOrEmpty($DestinationPath)) {
    $DestinationPath = Join-Path $RepoRoot "profitdll\DLLs\Win64"
}

Write-Host ""
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host " Gage Bootstrap DLL — data-downloader (Story 0.1 / ADR-008)" -ForegroundColor Cyan
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host " Origem: $ProfitChartPath" -ForegroundColor Yellow
Write-Host " Destino: $DestinationPath" -ForegroundColor Yellow
Write-Host ""

# -----------------------------------------------------------------------------
# Validar origem
# -----------------------------------------------------------------------------
if (-not (Test-Path $ProfitChartPath)) {
    Write-Host "[ERRO] Caminho de origem nao existe: $ProfitChartPath" -ForegroundColor Red
    Write-Host ""
    Write-Host "ProfitChart nao parece estar instalado em $ProfitChartPath." -ForegroundColor Yellow
    Write-Host "Re-execute passando -ProfitChartPath com o caminho correto." -ForegroundColor Yellow
    Write-Host "Ex.: .\scripts\bootstrap-dll.ps1 -ProfitChartPath 'D:\Apps\ProfitPro\bin'"
    exit 1
}

# -----------------------------------------------------------------------------
# Garantir destino
# -----------------------------------------------------------------------------
if (-not (Test-Path $DestinationPath)) {
    Write-Host "Criando diretorio destino..." -ForegroundColor Gray
    New-Item -ItemType Directory -Path $DestinationPath -Force | Out-Null
}

# -----------------------------------------------------------------------------
# Lista canônica de arquivos esperados (coordena com verify-dll-companions.py)
# -----------------------------------------------------------------------------
$RequiredDlls = @(
    "ProfitDLL.dll",
    "libcrypto-1_1-x64.dll",
    "libssl-1_1-x64.dll",
    "libeay32.dll",
    "ssleay32.dll"
)

$RequiredDatFiles = @(
    "timezone2.dat",
    "holidays.dat",
    "exchangeinfo2.dat",
    "newagents.dat"
)

# Diretórios runtime (copia recursiva)
$RequiredDirs = @(
    "MarketHours2",
    "database"
)

# Diretórios opcionais (copia se existir)
$OptionalDirs = @(
    "PopupManagerV2",
    "strategy"
)

# -----------------------------------------------------------------------------
# Copiar arquivos individuais (DLLs + .dat)
# -----------------------------------------------------------------------------
$Errors    = @()
$Copied    = 0
$Skipped   = 0

function Copy-FileWithCheck {
    param(
        [string]$SourceName,
        [string]$Category
    )
    $src = Join-Path $ProfitChartPath $SourceName
    $dst = Join-Path $DestinationPath $SourceName

    if (-not (Test-Path $src)) {
        Write-Host "  [FALTA] $SourceName ($Category)" -ForegroundColor Red
        $script:Errors += "${Category}: $SourceName nao encontrado em $ProfitChartPath"
        return
    }

    if ((Test-Path $dst) -and (-not $Force)) {
        Write-Host "  [SKIP]  $SourceName (ja existe; use -Force para sobrescrever)" -ForegroundColor DarkGray
        $script:Skipped++
        return
    }

    try {
        Copy-Item -Path $src -Destination $dst -Force:$Force
        Write-Host "  [OK]    $SourceName" -ForegroundColor Green
        $script:Copied++
    }
    catch {
        Write-Host "  [ERRO]  $SourceName -> $_" -ForegroundColor Red
        $script:Errors += "${Category}: $SourceName falhou: $_"
    }
}

Write-Host "[1/3] Copiando DLLs..." -ForegroundColor Cyan
foreach ($dll in $RequiredDlls) {
    Copy-FileWithCheck -SourceName $dll -Category "DLL"
}

Write-Host ""
Write-Host "[2/3] Copiando arquivos .dat..." -ForegroundColor Cyan
foreach ($dat in $RequiredDatFiles) {
    Copy-FileWithCheck -SourceName $dat -Category "DAT"
}

# -----------------------------------------------------------------------------
# Copiar diretórios
# -----------------------------------------------------------------------------
function Copy-DirWithCheck {
    param(
        [string]$DirName,
        [bool]$Required = $true
    )
    $src = Join-Path $ProfitChartPath $DirName
    $dst = Join-Path $DestinationPath $DirName

    if (-not (Test-Path $src)) {
        if ($Required) {
            Write-Host "  [FALTA] $DirName/ (obrigatorio)" -ForegroundColor Red
            $script:Errors += "DIR obrigatorio $DirName/ ausente em $ProfitChartPath"
        }
        else {
            Write-Host "  [SKIP]  $DirName/ (opcional, nao presente)" -ForegroundColor DarkGray
        }
        return
    }

    try {
        Copy-Item -Path $src -Destination $dst -Recurse -Force:$Force -ErrorAction Stop
        Write-Host "  [OK]    $DirName/" -ForegroundColor Green
        $script:Copied++
    }
    catch {
        Write-Host "  [ERRO]  $DirName/ -> $_" -ForegroundColor Red
        $script:Errors += "DIR $DirName/ falhou: $_"
    }
}

Write-Host ""
Write-Host "[3/3] Copiando diretorios runtime..." -ForegroundColor Cyan
foreach ($dir in $RequiredDirs) {
    Copy-DirWithCheck -DirName $dir -Required $true
}
foreach ($dir in $OptionalDirs) {
    Copy-DirWithCheck -DirName $dir -Required $false
}

# -----------------------------------------------------------------------------
# Relatório final
# -----------------------------------------------------------------------------
Write-Host ""
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host " Resumo:" -ForegroundColor Cyan
Write-Host "   Copiados : $Copied" -ForegroundColor Green
Write-Host "   Pulados  : $Skipped" -ForegroundColor DarkGray
Write-Host "   Erros    : $($Errors.Count)" -ForegroundColor $(if ($Errors.Count -gt 0) { "Red" } else { "Green" })
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host ""

if ($Errors.Count -gt 0) {
    Write-Host "[FALHA] Bootstrap incompleto. Detalhes:" -ForegroundColor Red
    foreach ($e in $Errors) {
        Write-Host "  - $e" -ForegroundColor Red
    }
    Write-Host ""
    Write-Host "Sugestao: confirme que ProfitChart esta instalado e atualizado," -ForegroundColor Yellow
    Write-Host "          e que o caminho passado contem os binarios listados." -ForegroundColor Yellow
    Write-Host "Validar: python scripts/verify-dll-companions.py" -ForegroundColor Yellow
    exit 1
}

Write-Host "[OK] Bootstrap concluido." -ForegroundColor Green
Write-Host ""
Write-Host "Proximo passo: validar instalacao executando" -ForegroundColor Cyan
Write-Host "  python scripts/verify-dll-companions.py" -ForegroundColor White
Write-Host ""
exit 0
