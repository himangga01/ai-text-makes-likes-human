function Assert-SigningProvenance {
  param([string]$MetadataPath, [string]$SourcePath, [string]$SignedPath)
  if (-not (Test-Path -LiteralPath $MetadataPath -PathType Leaf)) {
    throw 'Existing signing metadata is required; preserve the signed artifact and sign a new version.'
  }
  $record = Get-Content -Raw -Encoding UTF8 -LiteralPath $MetadataPath | ConvertFrom-Json
  $sourceHash = (Get-FileHash -LiteralPath $SourcePath -Algorithm SHA256).Hash
  $signedHash = (Get-FileHash -LiteralPath $SignedPath -Algorithm SHA256).Hash
  if ($record.sourceArtifact -ne [IO.Path]::GetFileName($SourcePath) -or
      $record.artifact -ne [IO.Path]::GetFileName($SignedPath) -or
      $record.sourceSha256 -ne $sourceHash -or $record.sha256 -ne $signedHash) {
    throw 'The existing signed artifact does not belong to the current unsigned build. Preserve it and sign a new version; metadata was not changed.'
  }
}
