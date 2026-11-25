<#
Add-ChatUIFirewallRule.ps1 - allow phones/tablets on your home network to reach Local AI Chat's LAN mode.
Creates ONE inbound Windows Firewall rule: TCP port 8765, Private network profile only (not Public/Domain), named
"Local AI Chat (LAN TCP 8765)". Needs an elevated (Run as administrator) PowerShell. Undo with Remove-ChatUIFirewallRule.ps1.
#>
#Requires -RunAsAdministrator
$name = 'Local AI Chat (LAN TCP 8765)'
if (Get-NetFirewallRule -DisplayName $name -ErrorAction SilentlyContinue) { Write-Host "rule '$name' already exists"; exit 0 }
New-NetFirewallRule -DisplayName $name -Description 'Local AI Chat (C:\Dev\Tools\RDNA4-Infer\chat-ui) LAN mode; login required by the app.' `
  -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8765 -Profile Private -RemoteAddress LocalSubnet | Out-Null
Get-NetFirewallRule -DisplayName $name | Format-List DisplayName, Enabled, Direction, Action, Profile
