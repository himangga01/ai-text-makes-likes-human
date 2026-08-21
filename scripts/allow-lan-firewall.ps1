param([switch]$WhatIf)

$ErrorActionPreference = 'Stop'
$name = 'AI Text Humanize Portal (Private TCP 3210)'

if ($WhatIf) {
  Write-Output "CREATE|$name|Private|TCP|3210"
  exit 0
}

$existing = Get-NetFirewallRule -DisplayName $name -ErrorAction SilentlyContinue
if (-not $existing) {
  New-NetFirewallRule `
    -DisplayName $name `
    -Direction Inbound `
    -Action Allow `
    -Protocol TCP `
    -LocalPort 3210 `
    -Profile Private | Out-Null
  Write-Host 'LAN firewall access is enabled for Private networks on TCP 3210.'
} else {
  Write-Host 'The portal firewall rule already exists.'
}
