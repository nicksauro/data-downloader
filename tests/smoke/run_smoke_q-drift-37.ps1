# tests/smoke/run_smoke_q-drift-37.ps1
# ----------------------------------------------------------------------------
# Smoke Q-DRIFT-37 mitigation validation - chunk_strategy per-symbol policy.
#
# Story 4.16 (Pichau directive 2026-05-06) introduziu policy:
#   WINFUT  -> 1 dia util/chunk (override por queue saturation risk)
#   WDOFUT  -> 5 dias uteis/chunk
#   demais  -> 5 dias uteis/chunk (DEFAULT_CHUNK_DAYS)
#
# Este smoke valida em smoke real (Pichau Windows local, NAO CI/VM) que:
#   1. queue_dropped == 0 em janela 5d para o simbolo testado
#   2. translate_invalid_price_skips reportado (Q-DRIFT-38 telemetry)
#   3. completeness_pct calculado a partir do volume real entregue vs baseline
#
# Acceptance evidence historica de referencia:
#   - Smoke real Pichau 2026-05-04
#     (docs/qa/SMOKE_EVIDENCE/1.7b-followup-20260505T231037Z-MVP-GATE-PASS.md)
#     -> 1.574.806 trades em 28-30/04 + LAST_PACKET correto + queue_dropped=0
#
# Output: tests/smoke/.last_q-drift-37_counters.json (gitignored).
#
# IMPORTANTE: este smoke roda SOMENTE no Windows local do Pichau (DLL real,
# licenca Nelogica single-session - ADR-022 / Q17-CLOSED). NAO funciona em VM
# nem em CI Linux.
# ----------------------------------------------------------------------------
[CmdletBinding()]
param(
    [string]$Symbol      = "WINFUT",
    [int]   $Days        = 5,
    [string]$Exchange    = "F",
    [string]$BundleDir   = "dist\data_downloader",
    [int]   $MetricsPort = 9091,
    [string]$OutFile     = "tests\smoke\.last_q-drift-37_counters.json"
)

$ErrorActionPreference = "Stop"

# ---- 1. Localiza o bundle CLI exe (PyInstaller dist) ----
$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$cli      = Join-Path $repoRoot (Join-Path $BundleDir "data_downloader-cli.exe")

if (-not (Test-Path $cli)) {
    Write-Host "Q-DRIFT-37 SMOKE FAIL - CLI bundle ausente em: $cli" -ForegroundColor Red
    Write-Host "Rode antes: scripts\bootstrap-dll.ps1 + PyInstaller build (ver docs/build/)." -ForegroundColor Yellow
    exit 2
}

# ---- 2. Calcula janela [start, end] = ultimos $Days dias uteis ----
# Recuamos $Days+2 dias corridos para garantir que pegamos $Days dias uteis
# mesmo com fim de semana - chunker B3 desconta sabado/domingo/feriado.
$end       = (Get-Date).Date.AddDays(-1)
$start     = $end.AddDays(-($Days + 2))
$startStr  = $start.ToString("yyyy-MM-dd")
$endStr    = $end.ToString("yyyy-MM-dd")

Write-Host "Q-DRIFT-37 smoke ($Symbol $startStr -> $endStr, exchange=$Exchange, metrics-port=$MetricsPort)" -ForegroundColor Cyan
Write-Host "Mitigation chunk_strategy: WINFUT=1d/chunk, demais=5d/chunk (Story 4.16)." -ForegroundColor DarkGray

# ---- 3. Captura stdout+stderr para parse posterior do download.complete ----
$logFile = Join-Path $repoRoot "tests\smoke\.last_q-drift-37_run.log"
if (Test-Path $logFile) { Remove-Item $logFile -Force }

# Roda em foreground; pipe combina stdout+stderr no log.
& $cli download $Symbol --start $startStr --end $endStr --exchange $Exchange --metrics-port $MetricsPort 2>&1 | Tee-Object -FilePath $logFile
$rc = $LASTEXITCODE

if ($rc -ne 0) {
    Write-Host "Q-DRIFT-37 SMOKE FAIL (download rc=$rc) - log: $logFile" -ForegroundColor Red
    exit 1
}

# ---- 4. Parse counters do download.complete log line ----
# Estrutura tipica do log structlog (ver download_primitive.py:832-857):
#   download.complete chunk_id=... symbol=... trades_count=519357
#   queue_dropped=0 translate_invalid_price_skips=6
#   last_packet_seen=True ...
$logText = Get-Content $logFile -Raw

# Helper: extrai ultimo valor inteiro de "key=N" no log (structlog console).
function Get-IntCounter {
    param(
        [string]$Text,
        [string]$Key,
        [int]   $Default = -1
    )
    # Pattern construido como string isolada para evitar interpolacao $ em [regex]::new.
    $pattern  = $Key + '=([0-9]+)'
    $allMatch = [regex]::Matches($Text, $pattern)
    if ($allMatch.Count -eq 0) { return $Default }
    # Pega a ultima ocorrencia (ultimo download.complete agregado).
    return [int]$allMatch[$allMatch.Count - 1].Groups[1].Value
}

$tradesCount             = Get-IntCounter -Text $logText -Key 'trades_count'                  -Default 0
$queueDropped            = Get-IntCounter -Text $logText -Key 'queue_dropped'                 -Default -1
$invalidPriceSkips       = Get-IntCounter -Text $logText -Key 'translate_invalid_price_skips' -Default 0
$translateFailures       = Get-IntCounter -Text $logText -Key 'translate_failures'            -Default 0
$translateNlErrors       = Get-IntCounter -Text $logText -Key 'translate_nl_errors'           -Default 0
$translateSentinelSkips  = Get-IntCounter -Text $logText -Key 'translate_sentinel_skips'      -Default 0

# Sanity check - se o regex nao achou queue_dropped, o log mudou de formato.
if ($queueDropped -lt 0) {
    Write-Host "Q-DRIFT-37 SMOKE INCONCLUSIVE - queue_dropped nao encontrado no log." -ForegroundColor Yellow
    Write-Host "Verifique formato do download.complete em download_primitive.py." -ForegroundColor Yellow
    exit 3
}

# ---- 5. Calcula completeness_pct (heuristica baseline empirico) ----
# Baseline empirico (smoke real 2026-05-04, evidence MVP-GATE-PASS):
#   - WINFUT 5d ~ 1.5M-2.5M trades   (mitigado via chunk=1d, sem overflow)
#   - WDOFUT 5d ~ 1.5M-2.0M trades
# Se nao houver baseline para o simbolo, reporta NA.
$baselinePerDay = @{
    "WINFUT" = 350000
    "WDOFUT" = 350000
    "INDFUT" = 200000
    "DOLFUT" = 150000
}

$completenessPct = "NA"
$symbolUpper = $Symbol.ToUpper()
if ($baselinePerDay.ContainsKey($symbolUpper)) {
    $expected = $baselinePerDay[$symbolUpper] * $Days
    if ($expected -gt 0) {
        $pct = [math]::Round(($tradesCount / $expected) * 100, 1)
        $completenessPct = [string]$pct
    }
}

# ---- 6. Snapshot Prometheus /metrics (best-effort - exporter ainda vivo?) ----
# O exporter para junto com o processo download. Para v1.1.0 basta o agregado
# do download.complete log; o snapshot e ilustrativo (provavelmente vazio).
$promSnapshotLines = 0
$promSnapshotNote  = "(exporter offline pos-download - captura via log apenas)"
try {
    $resp = Invoke-WebRequest -Uri "http://localhost:$MetricsPort/metrics" `
                              -TimeoutSec 2 -UseBasicParsing -ErrorAction Stop
    if ($resp -and $resp.Content) {
        $promSnapshotLines = ($resp.Content -split "`n").Count
        $promSnapshotNote  = "captured"
    }
} catch {
    # esperado - exporter ja encerrou junto com o download.
    $promSnapshotLines = 0
    $promSnapshotNote  = "(exporter offline pos-download - captura via log apenas)"
}

# ---- 7. Persiste counters JSON ----
$counters = [ordered]@{
    smoke_id                        = "Q-DRIFT-37"
    smoke_run_at                    = (Get-Date).ToString("yyyy-MM-ddTHH:mm:ssK")
    symbol                          = $Symbol
    exchange                        = $Exchange
    window_start                    = $startStr
    window_end                      = $endStr
    days_requested                  = $Days
    chunk_strategy_mitigation       = "WINFUT=1d/chunk; demais=5d/chunk (Story 4.16)"
    download_rc                     = $rc
    trades_count                    = $tradesCount
    queue_dropped                   = $queueDropped
    translate_invalid_price_skips   = $invalidPriceSkips
    translate_failures              = $translateFailures
    translate_nl_errors             = $translateNlErrors
    translate_sentinel_skips        = $translateSentinelSkips
    completeness_pct                = $completenessPct
    log_file                        = $logFile
    prometheus_snapshot_lines       = $promSnapshotLines
    prometheus_snapshot_note        = $promSnapshotNote
}

$outPath = Join-Path $repoRoot $OutFile
$counters | ConvertTo-Json -Depth 4 | Out-File $outPath -Encoding utf8
Write-Host "Q-DRIFT-37 counters -> $outPath" -ForegroundColor DarkGray

# ---- 8. Verdict ----
if ($queueDropped -ne 0) {
    Write-Host "Q-DRIFT-37 REGRESSION DETECTED: queue_dropped=$queueDropped (esperado 0)" -ForegroundColor Red
    Write-Host "Mitigacao chunk_strategy NAO foi suficiente para $Symbol nesta janela." -ForegroundColor Red
    Write-Host "Reabrir Q-DRIFT-37 (CLOSED-MITIGATED -> HYPOTHESIS) e revisar policy." -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "Q-DRIFT-37 MITIGATION OK" -ForegroundColor Green
Write-Host "  trades_count                  = $tradesCount" -ForegroundColor Green
Write-Host "  queue_dropped                 = 0" -ForegroundColor Green
Write-Host "  translate_invalid_price_skips = $invalidPriceSkips (Q-DRIFT-38)" -ForegroundColor Green
Write-Host "  completeness_pct              = $completenessPct%" -ForegroundColor Green
exit 0
