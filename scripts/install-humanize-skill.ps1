param(
  [Parameter(Mandatory=$true)][ValidateSet('Claude','Codex')][string]$HostName,
  [ValidateSet('User','Project')][string]$Scope = 'User',
  [string]$ProjectRoot = (Get-Location).Path,
  [string]$Archive,
  [switch]$Replace
)
$ErrorActionPreference = 'Stop'
if (-not $Archive) {
  $release = if ((Split-Path -Leaf $PSScriptRoot) -eq 'release') { $PSScriptRoot } else { Join-Path $PSScriptRoot '..\release' }
  $Archive = (Get-ChildItem -LiteralPath $release -Filter "humanize-kr-$($HostName.ToLowerInvariant())-*-win-x64.zip" | Sort-Object LastWriteTime -Descending | Select-Object -First 1).FullName
}
if (-not $Archive -or -not (Test-Path -LiteralPath $Archive)) { throw 'Build or download the skill ZIP first.' }
$base = if ($Scope -eq 'User') { [Environment]::GetFolderPath('UserProfile') } else { [IO.Path]::GetFullPath($ProjectRoot) }
$hostDirectory = if ($HostName -eq 'Claude') { '.claude' } else { '.agents' }
$hostRoot = [IO.Path]::GetFullPath((Join-Path $base $hostDirectory))
$destination = [IO.Path]::GetFullPath((Join-Path $hostRoot 'skills\humanize-kr'))
if (-not $destination.StartsWith($hostRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw 'Invalid skill destination' }
$archiveHash = (Get-FileHash -LiteralPath $Archive -Algorithm SHA256).Hash
$receipt = Join-Path $destination '.installed-archive.sha256'
if (Test-Path -LiteralPath $destination) {
  if ((Test-Path -LiteralPath $receipt) -and (Get-Content -Raw -LiteralPath $receipt).Trim() -eq $archiveHash) {
    Write-Output "Already installed: $destination"; exit 0
  }
  if (-not $Replace) { throw "Existing skill preserved: $destination. Use -Replace to back it up and install the new package." }
  $backup = Join-Path $hostRoot ('skill-backups\humanize-kr-' + [guid]::NewGuid().ToString('N'))
  New-Item -ItemType Directory -Path (Split-Path -Parent $backup) -Force | Out-Null
  Copy-Item -LiteralPath $destination -Destination $backup -Recurse
  Write-Output "Backup: $backup"
}
Add-Type -AssemblyName System.IO.Compression.FileSystem
$zip = [IO.Compression.ZipFile]::OpenRead([IO.Path]::GetFullPath($Archive))
try {
  foreach ($entry in $zip.Entries) {
    if (-not $entry.FullName.StartsWith('humanize-kr/')) { throw 'Unexpected archive layout' }
    $relative = $entry.FullName.Substring('humanize-kr/'.Length)
    if (-not $relative) { continue }
    $file = [IO.Path]::GetFullPath((Join-Path $destination $relative))
    if (-not $file.StartsWith($destination + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw 'Unsafe ZIP path' }
  }
  foreach ($entry in $zip.Entries) {
    if ($entry.FullName.EndsWith('/')) { continue }
    $file = [IO.Path]::GetFullPath((Join-Path $destination $entry.FullName.Substring('humanize-kr/'.Length)))
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $file) | Out-Null
    [IO.Compression.ZipFileExtensions]::ExtractToFile($entry, $file, $true)
  }
} finally { $zip.Dispose() }
[IO.File]::WriteAllText($receipt, $archiveHash, [Text.UTF8Encoding]::new($false))
Write-Output "Installed $HostName skill: $destination"
