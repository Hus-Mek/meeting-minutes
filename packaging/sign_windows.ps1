<#
.SYNOPSIS
    Authenticode-sign a Windows binary (the app EXE or the installer) with the
    code-signing certificate supplied via environment, if one is configured.

.DESCRIPTION
    Reads a base64-encoded PFX from $env:WINDOWS_PFX_BASE64 and its password from
    $env:WINDOWS_PFX_PASSWORD, then signs -Path with SHA-256 + an RFC 3161
    timestamp so signatures stay valid after the cert expires.

    Designed to be a NO-OP when no certificate is configured: if
    WINDOWS_PFX_BASE64 is empty it prints a notice and exits 0. The CI step that
    calls it is additionally gated on the secret being present, so unsigned
    builds (e.g. forks, or before the cert is set up) still succeed.

    Self-signed certs only suppress SmartScreen / "Unknown publisher" on machines
    that TRUST the cert (deploy the .cer to Trusted Publishers + Trusted Root —
    see PACKAGING.md). They do not provide external/global trust.

.PARAMETER Path
    The file to sign (e.g. dist\MeetingMinutes\MeetingMinutes.exe).
#>
param(
  [Parameter(Mandatory = $true)][string]$Path,
  [string]$TimestampServer = "http://timestamp.digicert.com"
)

$ErrorActionPreference = "Stop"

if (-not $env:WINDOWS_PFX_BASE64) {
  Write-Host "No WINDOWS_PFX_BASE64 configured; skipping signing of '$Path'."
  exit 0
}
if (-not (Test-Path $Path)) {
  throw "Cannot sign: file not found: $Path"
}

# Temp path for the decoded PFX (RUNNER_TEMP on CI, else the system temp dir).
$tempRoot = if ($env:RUNNER_TEMP) { $env:RUNNER_TEMP } else { [IO.Path]::GetTempPath() }
$pfxPath = Join-Path $tempRoot "mm-codesign.pfx"

try {
  # Write the PFX INSIDE the try so the finally below always removes the private-key
  # file, even if the base64 decode / write itself throws (no leak on a shared runner).
  [IO.File]::WriteAllBytes($pfxPath, [Convert]::FromBase64String($env:WINDOWS_PFX_BASE64))

  # Load with the private key. The (file, password, flags) constructor works across
  # Windows PowerShell 5.1 and PowerShell 7, avoiding Get-PfxCertificate -Password
  # version differences.
  $cert = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2(
    $pfxPath, $env:WINDOWS_PFX_PASSWORD,
    [System.Security.Cryptography.X509Certificates.X509KeyStorageFlags]::Exportable -bor
    [System.Security.Cryptography.X509Certificates.X509KeyStorageFlags]::PersistKeySet)

  $sig = Set-AuthenticodeSignature -FilePath $Path -Certificate $cert `
    -HashAlgorithm SHA256 -TimestampServer $TimestampServer

  if ($sig.Status -ne "Valid") {
    throw "Signing failed for '$Path': $($sig.Status) - $($sig.StatusMessage)"
  }
  Write-Host "Signed '$Path' ($($sig.Status))."
}
finally {
  Remove-Item $pfxPath -Force -ErrorAction SilentlyContinue
}
