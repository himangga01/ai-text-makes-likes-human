param(
  [Parameter(Mandatory=$true)][string]$Source
)

$ErrorActionPreference = 'Stop'
$expectedCommit = '9747f036cdc28a1a8aea4dc71fef1f7846eb96f7'
$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$patchPath = Join-Path $PSScriptRoot 'patches\humanize-engine-portal.patch'
$destination = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\vendor\humanize-engine'))
$skillPath = Join-Path $Source 'skills\humanize-korean\SKILL.md'

if (-not (Test-Path -LiteralPath $skillPath)) {
  throw "Humanize skill not found: $skillPath"
}

$skill = Get-Content -Raw -Encoding UTF8 -LiteralPath $skillPath
if ($skill -notmatch 'version:\s*"2\.3\.2"') {
  throw 'Expected im-not-ai version 2.3.2'
}

$commitOutput = & git -C $Source rev-parse HEAD
if ($LASTEXITCODE -ne 0) { throw "Source is not a readable Git checkout" }
$commit = $commitOutput.Trim()
if ($commit -ne $expectedCommit) {
  throw "Unexpected upstream commit: $commit"
}

$scripts = @(
  'prepare_monolith_input.py',
  'sanitize_text.py',
  'verify_gates.py',
  'verify_change_rate.py',
  'checks.py',
  'reassemble_chunks.py',
  'restore_modality.py',
  'strip_injected_commas.py',
  'console.py',
  'build_quick_rules.py',
  'build_diagnosis_rules.py'
)

$references = @(
  'quick-rules.md',
  'quick-rules.header.md',
  'quick-rules.footer.md',
  'diagnosis-rules.md',
  'ai-tell-taxonomy.md',
  'rewriting-playbook.md',
  'metrics.py',
  'metrics_v2.py',
  'baseline.json',
  'baseline_v2.json'
)

$dirty = @(& git -C $Source status --porcelain --untracked-files=no)
if ($LASTEXITCODE -ne 0) { throw 'Cannot inspect the source checkout' }
if ($dirty.Count -gt 0) { throw 'Uncommitted upstream changes; use a clean pinned checkout' }
$required = @('LICENSE')
$required += $scripts | ForEach-Object { "scripts/$_" }
$required += $references | ForEach-Object { "skills/humanize-korean/references/$_" }
foreach ($relative in $required) {
  if (-not (Test-Path -LiteralPath (Join-Path $Source $relative) -PathType Leaf)) {
    throw "Required upstream file is missing: $relative"
  }
}

$scriptDestination = Join-Path $destination 'scripts'
$referenceDestination = Join-Path $destination 'skills\humanize-korean\references'
New-Item -ItemType Directory -Force -Path $scriptDestination | Out-Null
New-Item -ItemType Directory -Force -Path $referenceDestination | Out-Null

foreach ($name in $scripts) {
  Copy-Item -Force -LiteralPath (Join-Path $Source "scripts\$name") -Destination (Join-Path $scriptDestination $name)
}

foreach ($name in $references) {
  Copy-Item -Force -LiteralPath (Join-Path $Source "skills\humanize-korean\references\$name") -Destination (Join-Path $referenceDestination $name)
}

Copy-Item -Force -LiteralPath (Join-Path $Source 'LICENSE') -Destination (Join-Path $destination 'LICENSE')

& git -C $repoRoot apply --check --whitespace=nowarn -- $patchPath
if ($LASTEXITCODE -ne 0) {
  throw 'Portal humanize patch no longer applies to the pinned upstream files.'
}
& git -C $repoRoot apply --whitespace=nowarn -- $patchPath
if ($LASTEXITCODE -ne 0) {
  throw 'Failed to apply portal humanize patch.'
}

$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[IO.File]::WriteAllText(
  (Join-Path $destination 'ENGINE_VERSION'),
  "version=2.3.2`ncommit=$commit`n",
  $utf8NoBom
)
[IO.File]::WriteAllText(
  (Join-Path $destination 'UPSTREAM.md'),
  "# Vendored Humanize Engine`n`nSource: https://github.com/himangga01/im-not-ai_fork`nVersion: 2.3.2`nCommit: $commit`n`nThe runtime is copied so the portal has no sibling-repository dependency.`n`nPortal patch: scripts/patches/humanize-engine-portal.patch`n`n- Preserves user-content LF/CRLF exactly with newline=`"`".`n- Adds the opt-in --portal-auto-route manifest path for short light/standard documents.`n- Feeds the source text to the v2.6 route tell counter in --chunk mode so short documents are not misrouted to light.`n- Keeps LF/CRLF intact in restore_modality.py and strip_injected_commas.py file I/O.`n",
  $utf8NoBom
)

Write-Host "Vendored humanize engine 2.3.2 ($commit) to $destination"
