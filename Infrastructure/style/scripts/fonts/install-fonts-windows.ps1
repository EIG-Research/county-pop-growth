# Install the EIG primary fonts (Open Sans, Source Serif 4) for the current user on Windows.
#   powershell -ExecutionPolicy Bypass -File Infrastructure\style\scripts\fonts\install-fonts-windows.ps1
# Sources and SHA-256 checksums come from font-sources.tsv next to this script. Each file
# is installed only when its checksum matches, so a failed or altered download installs
# nothing. Every font is attempted; the script exits 1 if any was not installed.
$ErrorActionPreference = "Stop"

$sources = Join-Path $PSScriptRoot "font-sources.tsv"
$fontDir = Join-Path $env:LOCALAPPDATA "Microsoft\Windows\Fonts"
$regPath = "HKCU:\Software\Microsoft\Windows NT\CurrentVersion\Fonts"
$tmpDir = Join-Path $env:TEMP "eig-fonts"

if (-not (Test-Path $sources)) {
  Write-Error "Font source list not found: $sources" -ErrorAction Continue
  exit 1
}

New-Item -ItemType Directory -Path $fontDir -Force | Out-Null
New-Item -ItemType Directory -Path $tmpDir -Force | Out-Null
# The per-user Fonts key does not exist until a first per-user font is installed.
if (-not (Test-Path $regPath)) {
  New-Item -Path $regPath -Force | Out-Null
}

# Skip the comment lines; the first remaining line is the header.
$rows = Get-Content $sources |
  Where-Object { $_.Trim() -ne "" -and -not $_.StartsWith("#") } |
  ConvertFrom-Csv -Delimiter "`t"

$failed = @()
foreach ($row in $rows) {
  $tmpFile = Join-Path $tmpDir $row.file
  $destFile = Join-Path $fontDir $row.file
  Write-Host "Downloading $($row.family) $($row.style)..."
  try {
    Invoke-WebRequest -Uri $row.url -OutFile $tmpFile -UseBasicParsing
  } catch {
    Write-Warning "Download failed: $($row.url)"
    Remove-Item $tmpFile -ErrorAction SilentlyContinue
    $failed += $row.file
    continue
  }
  $actual = (Get-FileHash -Path $tmpFile -Algorithm SHA256).Hash.ToLowerInvariant()
  if ($actual -ne $row.sha256.ToLowerInvariant()) {
    Write-Warning "Checksum mismatch for $($row.file): expected $($row.sha256), got $actual; not installed."
    Remove-Item $tmpFile -ErrorAction SilentlyContinue
    $failed += $row.file
    continue
  }
  Copy-Item $tmpFile $destFile -Force
  Remove-Item $tmpFile -ErrorAction SilentlyContinue
  # Per-user fonts are registered by full path.
  New-ItemProperty `
    -Path $regPath `
    -Name "$($row.family) $($row.style) (TrueType)" `
    -Value $destFile `
    -PropertyType String `
    -Force | Out-Null
}

if ($failed.Count -gt 0) {
  Write-Error "$($failed.Count) font file(s) were not installed: $($failed -join ', ')" -ErrorAction Continue
  exit 1
}
Write-Host "Fonts installed. Restart R, Python, or Stata sessions before plotting."
