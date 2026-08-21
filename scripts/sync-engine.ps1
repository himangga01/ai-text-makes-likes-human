param(
  [string]$Source = 'C:\project\2026\im-not-ai'
)

$ErrorActionPreference = 'Stop'
$expectedCommit = 'c4d03d4859acda143f0b04b4bbdb56c5e6a94db1'
$destination = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\vendor\humanize-engine'))
$skillPath = Join-Path $Source 'skills\humanize-korean\SKILL.md'

if (-not (Test-Path -LiteralPath $skillPath)) {
  throw "Humanize skill not found: $skillPath"
}

$skill = Get-Content -Raw -Encoding UTF8 -LiteralPath $skillPath
if ($skill -notmatch 'version:\s*"2\.3\.2"') {
  throw 'Expected im-not-ai version 2.3.2'
}

$commit = (git -C $Source rev-parse HEAD).Trim()
if ($commit -ne $expectedCommit) {
  throw "Unexpected upstream commit: $commit"
}

$scriptDestination = Join-Path $destination 'scripts'
$referenceDestination = Join-Path $destination 'skills\humanize-korean\references'
New-Item -ItemType Directory -Force -Path $scriptDestination | Out-Null
New-Item -ItemType Directory -Force -Path $referenceDestination | Out-Null

$scripts = @(
  'prepare_monolith_input.py',
  'sanitize_text.py',
  'verify_gates.py',
  'verify_change_rate.py',
  'checks.py',
  'reassemble_chunks.py',
  'console.py',
  'build_quick_rules.py',
  'build_diagnosis_rules.py'
)

foreach ($name in $scripts) {
  Copy-Item -Force -LiteralPath (Join-Path $Source "scripts\$name") -Destination (Join-Path $scriptDestination $name)
}

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

foreach ($name in $references) {
  Copy-Item -Force -LiteralPath (Join-Path $Source "skills\humanize-korean\references\$name") -Destination (Join-Path $referenceDestination $name)
}

Copy-Item -Force -LiteralPath (Join-Path $Source 'LICENSE') -Destination (Join-Path $destination 'LICENSE')

# Portal patch: Python's default Windows text mode translates LF to CRLF.
# These two user-content writes must preserve the source line endings exactly.
$preparePath = Join-Path $scriptDestination 'prepare_monolith_input.py'
$prepareText = Get-Content -Raw -Encoding UTF8 -LiteralPath $preparePath
$prepareText = $prepareText.Replace(
  'input_path.write_text(cleaned, encoding="utf-8")',
  'input_path.write_text(cleaned, encoding="utf-8", newline="")'
)
$reassemblePath = Join-Path $scriptDestination 'reassemble_chunks.py'
$reassembleText = Get-Content -Raw -Encoding UTF8 -LiteralPath $reassemblePath
$reassembleText = $reassembleText.Replace(
  'output_path.write_text(out, encoding="utf-8")',
  'output_path.write_text(out, encoding="utf-8", newline="")'
)

$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[IO.File]::WriteAllText($preparePath, $prepareText, $utf8NoBom)
[IO.File]::WriteAllText($reassemblePath, $reassembleText, $utf8NoBom)
[IO.File]::WriteAllText(
  (Join-Path $destination 'ENGINE_VERSION'),
  "version=2.3.2`ncommit=$commit`n",
  $utf8NoBom
)
[IO.File]::WriteAllText(
  (Join-Path $destination 'UPSTREAM.md'),
  "# Vendored Humanize Engine`n`nSource: https://github.com/epoko77-ai/im-not-ai`nVersion: 2.3.2`nCommit: $commit`n`nThe runtime is copied so the portal has no sibling-repository dependency.`n`nPortal patch: user-content writes pass newline=`"`" so Windows preserves LF/CRLF exactly.`n",
  $utf8NoBom
)

Write-Host "Vendored humanize engine 2.3.2 ($commit) to $destination"
