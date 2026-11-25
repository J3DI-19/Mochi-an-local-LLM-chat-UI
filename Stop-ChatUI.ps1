<#
Stop-ChatUI.ps1 - stop the Local AI Chat server, its internet link (cloudflared / Tailscale Funnel), and SearXNG web search.
  -All / -UnloadModels   also stop the RDNA4 engine (ie-serve) and unload all LM Studio models to free VRAM.
  -Port N                default 8765
#>
param([int]$Port = 8765, [switch]$All, [switch]$UnloadModels)
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$pidf = Join-Path $here 'server.pid'
$ids = @()
if (Test-Path $pidf) { $ids += [int](Get-Content $pidf) }
$ids += Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | ForEach-Object OwningProcess
$stopped = 0
foreach ($id in ($ids | Select-Object -Unique)) {
  $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$id" -ErrorAction SilentlyContinue
  if ($proc -and $proc.CommandLine -like '*chat-ui*server.py*') { Stop-Process -Id $id -Force; $stopped++; Write-Host "stopped chat server pid $id" }
}
Remove-Item $pidf -ErrorAction SilentlyContinue

# SearXNG web search (Mochi-only, started on demand by server.py)
$sxpf = Join-Path $here 'data\searxng.pid'
$sxIds = @()
if (Test-Path $sxpf) {
  $sxid = 0; [void][int]::TryParse((Get-Content $sxpf -Raw).Trim(), [ref]$sxid)
  if ($sxid) { $sxIds += $sxid }
}
$sxIds += (Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -like '*run_searxng.py*' }).ProcessId
foreach ($id in ($sxIds | Where-Object { $_ } | Select-Object -Unique)) {
  $p = Get-CimInstance Win32_Process -Filter "ProcessId=$id" -ErrorAction SilentlyContinue
  if ($p -and $p.CommandLine -like '*run_searxng.py*') { Stop-Process -Id $id -Force; Write-Host "stopped SearXNG web search pid $id" }
}
Remove-Item $sxpf -ErrorAction SilentlyContinue

# the internet link dies with the server (job object); this also catches a leftover one. Only Mochi's own cloudflared (pid file + exe path).
$tpf = Join-Path $here 'data\cloudflared.pid'
if (Test-Path $tpf) {
  $tid = 0; [void][int]::TryParse((Get-Content $tpf -Raw).Trim(), [ref]$tid)
  $tp = if ($tid) { Get-Process -Id $tid -ErrorAction SilentlyContinue }
  if ($tp -and $tp.Path -eq 'C:\Dev\Tools\cloudflared\cloudflared.exe') { Stop-Process -Id $tid -Force; Write-Host "stopped internet link (cloudflared pid $tid)" }
  Remove-Item $tpf -ErrorAction SilentlyContinue
}
# Tailscale Funnel config outlives the server, so turn off a Funnel that points at Mochi (other Tailscale settings are left alone)
$ts = 'C:\Program Files\Tailscale\tailscale.exe'
if (Test-Path $ts) {
  $fj = (& $ts funnel status --json 2>$null) -join "`n"
  if ($fj -match '"AllowFunnel"' -and $fj -match "(127\.0\.0\.1|localhost):$Port") { & $ts funnel --https=443 off 2>&1 | Out-Null; Write-Host 'turned off the Tailscale Funnel link' }
}

if ($All -or $UnloadModels) {
  $stopEng = Join-Path (Split-Path -Parent $here) 'bench-config\Stop-Qwen27B.ps1'
  if (Test-Path $stopEng) { & $stopEng }
  $lms = Join-Path $env:USERPROFILE '.lmstudio\bin\lms.exe'
  if (Test-Path $lms) { & $lms unload --all 2>$null | Out-Host }
}
if (-not $stopped) { Write-Host 'Local AI Chat was not running' }
