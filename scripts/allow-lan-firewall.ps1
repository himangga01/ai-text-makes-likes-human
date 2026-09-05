param([switch]$WhatIf)

$ErrorActionPreference = 'Stop'
$name = 'AI Text Humanize Portal (Private TCP 7882)'

if ($WhatIf) {
  Write-Output "CREATE|$name|Private|TCP|7882"
  exit 0
}

$existing = Get-NetFirewallRule -DisplayName $name -ErrorAction SilentlyContinue
if (-not $existing) {
  New-NetFirewallRule `
    -DisplayName $name `
    -Direction Inbound `
    -Action Allow `
    -Protocol TCP `
    -LocalPort 7882 `
    -Profile Private | Out-Null
  Write-Host 'LAN firewall access is enabled for Private networks on TCP 7882.'
} else {
  Write-Host 'The portal firewall rule already exists.'
}
