<#
Start-ChatUI.ps1 - start the Local AI Chat server (hidden) and open it in the default browser. Reuses it if already running.
  -NoBrowser   don't open a browser
  -Lan         start in LAN mode (private networks only, login required; needs a password). Used by the autostart entry.
  -Port N      default 8765
Stop it with Stop-ChatUI.ps1.
#>
param([int]$Port = 8765, [switch]$NoBrowser, [switch]$Lan)
$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$url  = "http://127.0.0.1:$Port/"
$logs = Join-Path $here 'logs'; New-Item -ItemType Directory -Force $logs | Out-Null
$pidf = Join-Path $here 'server.pid'
function Test-Up { try { $null = Invoke-WebRequest "$($url)api/auth/state" -UseBasicParsing -TimeoutSec 2; $true } catch { $false } }
if (-not (Test-Up)) {
  if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) { throw "port $Port is used by another program; pass -Port N" }
  # stdlib-only server: use the installed Python (no new installs); fall back to the build-deps venv
  $cands = @("$env:LOCALAPPDATA\Programs\Python\Python313\python.exe", "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
             (Join-Path (Split-Path -Parent $here) 'build-deps\gguf-venv\Scripts\python.exe'))
  $py = $cands | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
  if (-not $py) { $c = Get-Command python.exe -ErrorAction SilentlyContinue | Where-Object { $_.Source -notlike '*WindowsApps*' } | Select-Object -First 1; if ($c) { $py = $c.Source } }
  if (-not $py) { throw 'no Python found' }
  $a = @('-u', "`"$(Join-Path $here 'server.py')`"", '--port', $Port, '--log', "`"$(Join-Path $logs 'server.log')`"")
  if ($Lan) { $a += '--lan' }
  # no -Redirect*: the server logs to a file itself, so it inherits no console/pipe handles from whoever launched this script
  $p = Start-Process -FilePath $py -ArgumentList $a -WorkingDirectory $here -WindowStyle Hidden -PassThru
  Set-Content -Path $pidf -Value $p.Id
  $t0 = Get-Date
  while (-not (Test-Up)) {
    if ($p.HasExited) { throw "chat server exited (code $($p.ExitCode)); see $logs\server.log" }
    if ((Get-Date) - $t0 -gt [TimeSpan]::FromSeconds(20)) { throw 'chat server did not answer within 20 s' }
    Start-Sleep -Milliseconds 300
  }
  Write-Host "Local AI Chat started (pid $($p.Id)): $url"
} else { Write-Host "Local AI Chat already running: $url" }
if (-not $NoBrowser) { Start-Process $url }
