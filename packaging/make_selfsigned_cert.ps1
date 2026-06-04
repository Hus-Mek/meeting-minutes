<#
.SYNOPSIS
    Create a self-signed code-signing certificate for internal/fleet signing of
    the Meeting Minutes EXE + installer.

.DESCRIPTION
    Generates a code-signing cert in the current user's store and exports:
      * a .pfx (private key) — for the GitHub Actions secrets, and
      * a .cer (public)      — to deploy to Trusted Publishers + Trusted Root
                                across the fleet (Group Policy), which is what
                                actually suppresses SmartScreen on those PCs.

    It also prints the base64 of the .pfx to paste into the WINDOWS_PFX_BASE64
    GitHub secret (set WINDOWS_PFX_PASSWORD to the password you pass here).

    Run on a Windows machine in PowerShell:
        ./make_selfsigned_cert.ps1 -Password 'a-strong-passphrase'

    Self-signed certs only establish trust on machines that explicitly trust the
    .cer. For external distribution you need an EV/OV cert from a public CA — see
    PACKAGING.md.

.PARAMETER Password
    Passphrase protecting the exported .pfx (also set as WINDOWS_PFX_PASSWORD).

.PARAMETER Subject
    The certificate subject / publisher name shown in file properties.

.PARAMETER OutDir
    Directory to write the .pfx / .cer into (default: current directory).

.PARAMETER Years
    Validity period in years (default 5).
#>
param(
  [Parameter(Mandatory = $true)][string]$Password,
  [string]$Subject = "CN=Hawaz Meeting Minutes",
  [string]$OutDir = ".",
  [int]$Years = 5
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $OutDir)) { New-Item -ItemType Directory -Force -Path $OutDir | Out-Null }

$cert = New-SelfSignedCertificate `
  -Type CodeSigningCert `
  -Subject $Subject `
  -CertStoreLocation "Cert:\CurrentUser\My" `
  -KeyAlgorithm RSA -KeyLength 2048 `
  -KeyExportPolicy Exportable `
  -NotAfter (Get-Date).AddYears($Years)

$pfxPath = Join-Path $OutDir "meetingminutes-codesign.pfx"
$cerPath = Join-Path $OutDir "meetingminutes-codesign.cer"
$secure = ConvertTo-SecureString $Password -AsPlainText -Force

Export-PfxCertificate -Cert $cert -FilePath $pfxPath -Password $secure | Out-Null
Export-Certificate   -Cert $cert -FilePath $cerPath | Out-Null

Write-Host ""
Write-Host "Certificate created:"
Write-Host "  Thumbprint : $($cert.Thumbprint)"
Write-Host "  PFX (keep secret) : $pfxPath"
Write-Host "  CER (deploy to fleet Trusted Publishers + Trusted Root) : $cerPath"
Write-Host ""
Write-Host "GitHub secrets to set:"
Write-Host "  WINDOWS_PFX_PASSWORD = <the password you just passed>"
Write-Host "  WINDOWS_PFX_BASE64   = (the base64 below)"
Write-Host ""
[Convert]::ToBase64String([IO.File]::ReadAllBytes($pfxPath))
