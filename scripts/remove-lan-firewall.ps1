param([switch]$WhatIf)

$ErrorActionPreference = 'Stop'
$name = 'AI Text Humanize Portal (Private TCP 7882)'

if ($WhatIf) {
  Write-Output "REMOVE|$name"
  exit 0
}

$rules = @(Get-NetFirewallRule -DisplayName $name -ErrorAction SilentlyContinue)
if ($rules.Count -gt 0) {
  $rules | Remove-NetFirewallRule
  Write-Host 'LAN firewall access was removed.'
} else {
  Write-Host 'No portal firewall rule exists.'
}
