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
$skillsRoot = [IO.Path]::GetDirectoryName($destination)
New-Item -ItemType Directory -Path $skillsRoot -Force | Out-Null
# A kernel-held handle serializes installers and is released even on process exit.
# Keep the empty lock file; deleting it after unlock creates a successor race.
$installLock = [IO.File]::Open((Join-Path $skillsRoot '.humanize-kr.install.lock'), [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
$stage = $null
try {
  $archiveHash = (Get-FileHash -LiteralPath $Archive -Algorithm SHA256).Hash
  $receipt = Join-Path $destination '.installed-archive.sha256'
  if (Test-Path -LiteralPath $destination) {
    if ((Test-Path -LiteralPath $receipt) -and (Get-Content -Raw -LiteralPath $receipt).Trim() -eq $archiveHash) {
      Write-Output "Already installed: $destination"; return
    }
    if (-not $Replace) { throw "Existing skill preserved: $destination. Use -Replace to back it up and install the new package." }
  }
  $stage = [IO.Path]::GetFullPath((Join-Path $skillsRoot ('.humanize-kr-stage-' + [guid]::NewGuid().ToString('N'))))
  New-Item -ItemType Directory -Path $stage | Out-Null
  Add-Type -AssemblyName System.IO.Compression.FileSystem
  $zip = [IO.Compression.ZipFile]::OpenRead([IO.Path]::GetFullPath($Archive))
  try {
    $seen = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
    foreach ($entry in $zip.Entries) {
      if (-not $entry.FullName.StartsWith('humanize-kr/')) { throw 'Unexpected archive layout' }
      $relative = $entry.FullName.Substring('humanize-kr/'.Length)
      if (-not $relative) { continue }
      $file = [IO.Path]::GetFullPath((Join-Path $stage $relative))
      if (-not $file.StartsWith($stage + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw 'Unsafe ZIP path' }
      if (-not $seen.Add($file)) { throw 'Duplicate ZIP path' }
      if ($entry.FullName.EndsWith('/')) { continue }
      New-Item -ItemType Directory -Force -Path (Split-Path -Parent $file) | Out-Null
      [IO.Compression.ZipFileExtensions]::ExtractToFile($entry, $file, $false)
    }
  } finally { $zip.Dispose() }
  if (-not (Test-Path -LiteralPath (Join-Path $stage 'SKILL.md') -PathType Leaf)) { throw 'Skill entry point is missing' }
  [IO.File]::WriteAllText((Join-Path $stage '.installed-archive.sha256'), $archiveHash, [Text.UTF8Encoding]::new($false))
  $backup = $null
  if (Test-Path -LiteralPath $destination) {
    $backup = [IO.Path]::GetFullPath((Join-Path $hostRoot ('skill-backups\humanize-kr-' + [guid]::NewGuid().ToString('N'))))
    if (-not $backup.StartsWith($hostRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw 'Invalid backup path' }
    New-Item -ItemType Directory -Path (Split-Path -Parent $backup) -Force | Out-Null
    [IO.Directory]::Move($destination, $backup)
  }
  try { [IO.Directory]::Move($stage, $destination); $stage = $null }
  catch {
    if ($backup -and -not (Test-Path -LiteralPath $destination)) { [IO.Directory]::Move($backup, $destination) }
    throw
  }
  if ($backup) { Write-Output "Backup: $backup" }
  Write-Output "Installed $HostName skill: $destination"
} finally {
  try {
    if ($stage -and (Test-Path -LiteralPath $stage)) {
      $resolvedStage = [IO.Path]::GetFullPath($stage)
      if ([IO.Path]::GetDirectoryName($resolvedStage) -ne $skillsRoot -or [IO.Path]::GetFileName($resolvedStage) -notmatch '^\.humanize-kr-stage-[a-f0-9]{32}$') { throw 'Invalid staging cleanup path' }
      Remove-Item -LiteralPath $resolvedStage -Recurse -Force
    }
  } finally { $installLock.Dispose() }
}
