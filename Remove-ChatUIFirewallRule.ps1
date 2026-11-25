<# Remove-ChatUIFirewallRule.ps1 - remove the "Local AI Chat (LAN TCP 8765)" inbound rule. Needs an elevated PowerShell. #>
#Requires -RunAsAdministrator
$name = 'Local AI Chat (LAN TCP 8765)'
if (Get-NetFirewallRule -DisplayName $name -ErrorAction SilentlyContinue) { Remove-NetFirewallRule -DisplayName $name; Write-Host "removed '$name'" }
else { Write-Host "rule '$name' not found" }
