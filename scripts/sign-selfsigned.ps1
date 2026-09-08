param([switch]$WhatIf, [switch]$VerifyExisting)

$ErrorActionPreference = 'Stop'
$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$releaseRoot = [IO.Path]::GetFullPath((Join-Path $repoRoot 'release'))
$package = Get-Content -Raw -Encoding UTF8 -LiteralPath (Join-Path $repoRoot 'package.json') | ConvertFrom-Json
$version = [string]$package.version
if ($version -notmatch '^\d+\.\d+\.\d+(?:-[A-Za-z0-9.-]+)?$') { throw 'Invalid package version' }
$source = Join-Path $releaseRoot "HumanizeKR-$version-win-x64.exe"
$output = Join-Path $releaseRoot "HumanizeKR-$version-win-x64-self-signed.exe"
$certificateFile = Join-Path $releaseRoot 'HumanizeKR-Local-CodeSigning.cer'
$metadataFile = Join-Path $releaseRoot "HumanizeKR-$version-self-signing.json"
$subject = 'CN=HumanizeKR Local Test Signing'
$friendlyName = 'HumanizeKR local test code signing (self-signed)'
if (-not (Test-Path -LiteralPath $source -PathType Leaf)) { throw 'Build the portable EXE first' }
if ((Test-Path -LiteralPath $output) -and -not $VerifyExisting -and -not $WhatIf) { throw "Output already exists; preserved: $output" }
if ($VerifyExisting -and -not (Test-Path -LiteralPath $output)) { throw 'There is no signed copy to verify' }

$sdkRoot = Join-Path ([Environment]::GetFolderPath('ProgramFilesX86')) 'Windows Kits\10\bin'
$signTool = Get-ChildItem -LiteralPath $sdkRoot -Directory |
  Where-Object { $_.Name -match '^\d+\.\d+\.\d+\.\d+$' } |
  Sort-Object { [version]$_.Name } -Descending |
  ForEach-Object { Join-Path $_.FullName 'x64\signtool.exe' } |
  Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } |
  Select-Object -First 1
if (-not $signTool) { throw 'Windows SDK x64 SignTool was not found' }

if ($WhatIf) {
  [PSCustomObject]@{
    Source = $source
    Output = $output
    CertificateSubject = $subject
    CertificateStore = 'Cert:\CurrentUser\My'
    PrivateKey = 'RSA 3072, non-exportable'
    PublicCertificate = $certificateFile
    SignTool = $signTool
    TrustedRootChanges = $false
    Timestamp = 'None (local test signature)'
    Scope = 'Portable distribution EXE; embedded third-party files are unchanged'
  } | ConvertTo-Json
  exit 0
}

# This certificate is a local test identity, never a publicly trusted publisher.
# Persist the non-exportable private key in the current user's personal store.
# Do not import anything into Root or TrustedPublisher.
$certificate = Get-ChildItem -Path Cert:\CurrentUser\My -CodeSigningCert |
  Where-Object { $_.Subject -eq $subject -and $_.Issuer -eq $subject -and $_.FriendlyName -eq $friendlyName -and $_.HasPrivateKey -and $_.NotAfter -gt (Get-Date).AddDays(1) } |
  Sort-Object NotAfter -Descending | Select-Object -First 1
if (-not $certificate) {
  if ($VerifyExisting) { throw 'The local signing certificate was not found' }
  $certificate = New-SelfSignedCertificate -Type CodeSigningCert -Subject $subject `
    -FriendlyName $friendlyName -CertStoreLocation 'Cert:\CurrentUser\My' `
    -Provider 'Microsoft Software Key Storage Provider' -KeyAlgorithm RSA -KeyLength 3072 `
    -HashAlgorithm SHA256 -KeyExportPolicy NonExportable -KeyUsage DigitalSignature `
    -NotBefore (Get-Date).AddMinutes(-5) -NotAfter (Get-Date).AddYears(2)
}

$originalHash = (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash.ToLowerInvariant()
if (-not $VerifyExisting) {
  Copy-Item -LiteralPath $source -Destination $output
  & $signTool sign /fd SHA256 /sha1 $certificate.Thumbprint /s My /d 'HumanizeKR - local test signature' $output
  if ($LASTEXITCODE -ne 0) { throw 'SignTool signing failed; the original EXE is unchanged' }
}
$signature = Get-AuthenticodeSignature -LiteralPath $output
if (-not $signature.SignerCertificate -or $signature.SignerCertificate.Thumbprint -ne $certificate.Thumbprint) {
  throw 'The output does not contain the expected signer certificate'
}
if ($signature.Status -eq 'HashMismatch' -or $signature.SignatureType -ne 'Authenticode') {
  throw 'Authenticode verification failed'
}

$previousPreference = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
$verification = (& $signTool verify /pa /v $output 2>&1 | Out-String -Width 4096)
$verificationExit = $LASTEXITCODE
$ErrorActionPreference = $previousPreference
# Self-signed certificates are intentionally not installed as trusted roots.
# Accept only successful verification or the specific untrusted-root failure.
$chain = New-Object Security.Cryptography.X509Certificates.X509Chain
$chain.ChainPolicy.RevocationMode = [Security.Cryptography.X509Certificates.X509RevocationMode]::NoCheck
$chainValid = $chain.Build($signature.SignerCertificate)
$chainStatuses = @($chain.ChainStatus | ForEach-Object { [string]$_.Status })
$onlyUntrustedRoot = $chainStatuses.Count -eq 1 -and $chainStatuses[0] -eq 'UntrustedRoot'
$expectedTrustError = $verification -match '0x800B0109|certificate\s+which\s+is\s+not\s+trusted\s+by\s+the\s+trust\s+provider'
$chain.Dispose()
if ($verificationExit -ne 0 -and -not ($onlyUntrustedRoot -and $expectedTrustError)) {
  throw "Unexpected SignTool verification failure: $verification"
}
if ((Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash.ToLowerInvariant() -ne $originalHash) {
  throw 'The original EXE changed during signing'
}
Export-Certificate -Cert $certificate -FilePath $certificateFile -Type CERT | Out-Null
$hash = (Get-FileHash -LiteralPath $output -Algorithm SHA256).Hash.ToLowerInvariant()
$utf8 = [Text.UTF8Encoding]::new($false)
[IO.File]::WriteAllText("$output.sha256", "$hash  $([IO.Path]::GetFileName($output))`n", $utf8)
$metadata = [ordered]@{
  artifact = [IO.Path]::GetFileName($output)
  sourceArtifact = [IO.Path]::GetFileName($source)
  sourceSha256 = $originalHash
  sha256 = $hash
  subject = $certificate.Subject
  thumbprint = $certificate.Thumbprint
  notAfter = $certificate.NotAfter.ToUniversalTime().ToString('o')
  signatureType = [string]$signature.SignatureType
  authenticodeStatus = [string]$signature.Status
  verificationExitCode = $verificationExit
  certificateChainStatus = $chainStatuses
  trustedByDefault = $false
  trustedRootModified = $false
  timestamped = $false
  privateKeyExported = $false
  signatureScope = 'Portable distribution EXE'
}
[IO.File]::WriteAllText($metadataFile, ($metadata | ConvertTo-Json), $utf8)
$metadata | ConvertTo-Json
