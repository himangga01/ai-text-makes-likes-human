import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]

@unittest.skipUnless(os.name=='nt','PowerShell signing metadata helper')
class SigningProvenanceTest(unittest.TestCase):
    def test_failed_sign_or_verification_does_not_publish_and_retry_can_succeed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);(root/'scripts').mkdir();(root/'release').mkdir();(root/'sdk/10.0.0.0/x64').mkdir(parents=True)
            (root/'sdk/10.0.0.0/x64/signtool.exe').write_bytes(b'mocked executable')
            (root/'package.json').write_text('{"version":"0.0.1"}')
            source=root/'release/HumanizeKR-0.0.1-win-x64.exe';source.write_bytes(b'unsigned')
            output=root/'release/HumanizeKR-0.0.1-win-x64-self-signed.exe'
            shim=r'''
function Get-ChildItem {
 param($LiteralPath,$Path,[switch]$Directory,[switch]$CodeSigningCert)
 if($CodeSigningCert){[PSCustomObject]@{Subject='CN=HumanizeKR Local Test Signing';Issuer='CN=HumanizeKR Local Test Signing';FriendlyName='HumanizeKR local test code signing (self-signed)';HasPrivateKey=$true;NotAfter=(Get-Date).AddDays(30);Thumbprint='MOCK'}}
 else{[PSCustomObject]@{Name='10.0.0.0';FullName=(Join-Path $PSScriptRoot '../sdk/10.0.0.0')}}
}
function New-SelfSignedCertificate {throw 'Real certificates forbidden'}
function Get-AuthenticodeSignature {
 param($LiteralPath)
 if($env:REVIEW_SIGN_MODE -eq 'fail-verify'){[PSCustomObject]@{SignerCertificate=$null};return}
 [PSCustomObject]@{SignerCertificate=[PSCustomObject]@{Thumbprint='MOCK'};SignatureType='Authenticode';Status='Valid'}
}
function New-Object {
 param($TypeName)
 if($TypeName -ne 'Security.Cryptography.X509Certificates.X509Chain'){throw 'Unexpected object'}
 $chain=[PSCustomObject]@{ChainPolicy=[PSCustomObject]@{RevocationMode=$null};ChainStatus=@()}
 $chain | Add-Member ScriptMethod Build {param($cert) return $true}
 $chain | Add-Member ScriptMethod Dispose {}
 return $chain
}
function Export-Certificate {param($Cert,$FilePath,$Type) [IO.File]::WriteAllText($FilePath,'synthetic certificate')}
$mockSignTool={
 if($args[0] -eq 'sign'){
   if($env:REVIEW_SIGN_MODE -eq 'fail-sign'){$global:LASTEXITCODE=1;return}
   [IO.File]::WriteAllText($args[-1],'synthetically signed')
 }
 $global:LASTEXITCODE=0
}
'''
            script=(ROOT/'scripts/sign-selfsigned.ps1').read_text(encoding='utf-8')
            script=script.replace('param([switch]$WhatIf, [switch]$VerifyExisting)','param([switch]$WhatIf, [switch]$VerifyExisting)\n'+shim,1)
            script=script.replace('& $signTool sign ','& $mockSignTool sign ').replace('& $signTool verify ','& $mockSignTool verify ')
            runner=root/'scripts/sign-selfsigned.ps1';runner.write_text(script,encoding='utf-8-sig')
            (root/'scripts/signing-provenance.ps1').write_bytes((ROOT/'scripts/signing-provenance.ps1').read_bytes())
            def run(mode):
                return subprocess.run(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(runner)],
                    env={**os.environ,'REVIEW_SIGN_MODE':mode,'PSModulePath':str(Path(os.environ['SystemRoot'])/'System32/WindowsPowerShell/v1.0/Modules')},
                    capture_output=True,timeout=15,creationflags=subprocess.CREATE_NO_WINDOW)
            for mode in ('fail-sign','fail-verify'):
                with self.subTest(mode=mode):
                    result=run(mode);self.assertNotEqual(result.returncode,0)
                    self.assertFalse(output.exists())
                    self.assertEqual(source.read_bytes(),b'unsigned')
                    self.assertEqual(sorted(p.name for p in (root/'release').iterdir()),[source.name])
            result=run('success');self.assertEqual(result.returncode,0,result.stderr.decode(errors='replace'))
            self.assertEqual(output.read_text(),'synthetically signed')
            metadata=json.loads((root/'release/HumanizeKR-0.0.1-self-signing.json').read_text(encoding='utf-8'))
            self.assertEqual(metadata['sourceSha256'],hashlib.sha256(source.read_bytes()).hexdigest())
            self.assertEqual(metadata['sha256'],hashlib.sha256(output.read_bytes()).hexdigest())

    def test_existing_signature_is_bound_to_both_recorded_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);source=root/'unsigned.exe';signed=root/'signed.exe';metadata=root/'signing.json'
            source.write_bytes(b'build A');signed.write_bytes(b'signed build A')
            record={'artifact':signed.name,'sourceArtifact':source.name,
                    'sourceSha256':hashlib.sha256(source.read_bytes()).hexdigest(),
                    'sha256':hashlib.sha256(signed.read_bytes()).hexdigest()}
            metadata.write_text(json.dumps(record),encoding='utf-8');before=metadata.read_bytes()
            harness=root/'run.ps1'
            harness.write_text("param($helper,$metadata,$source,$signed)\n$ErrorActionPreference='Stop'\n. $helper\nAssert-SigningProvenance -MetadataPath $metadata -SourcePath $source -SignedPath $signed\n",encoding='utf-8')
            def run():
                return subprocess.run(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(harness),
                    str(ROOT/'scripts/signing-provenance.ps1'),str(metadata),str(source),str(signed)],
                    env={**os.environ,'PSModulePath':str(Path(os.environ['SystemRoot'])/'System32/WindowsPowerShell/v1.0/Modules')},
                    capture_output=True,timeout=15,creationflags=subprocess.CREATE_NO_WINDOW)
            initial=run();self.assertEqual(initial.returncode,0,initial.stderr.decode(errors='replace'))
            source.write_bytes(b'build B')
            self.assertNotEqual(run().returncode,0)
            self.assertEqual(metadata.read_bytes(),before)
            source.write_bytes(b'build A');signed.write_bytes(b'unrelated signed file')
            self.assertNotEqual(run().returncode,0)
            self.assertEqual(metadata.read_bytes(),before)
