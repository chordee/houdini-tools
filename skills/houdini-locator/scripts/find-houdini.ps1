function Show-Entry($installPath, $versionLabel) {
    Write-Host "--- Houdini $versionLabel ---"
    Write-Host "Install Path : $installPath"
    $hython  = Join-Path $installPath "bin\hython.exe"
    $houdini = Join-Path $installPath "bin\houdini.exe"
    if (Test-Path $hython)  { Write-Host "hython       : $hython" }
    if (Test-Path $houdini) { Write-Host "houdini      : $houdini" }
    Write-Host ""
}

function Get-VersionLabel($path) {
    $base = Split-Path -Leaf $path
    if ($base -match '^Houdini\s+(.+)$') { return $Matches[1] }
    if ($base -match '^hfs(.+)$')        { return $Matches[1] }
    return "(unknown version)"
}

# Track which install roots have already been printed so HFS and the scan
# results don't list the same install twice.
$seen = @{}

# 1. HFS env var takes priority, if it points at a real install.
$hfsResolved = $null
if ($env:HFS) {
    $hfsHython = Join-Path $env:HFS "bin\hython.exe"
    if (Test-Path $hfsHython) {
        $hfsResolved = (Resolve-Path $env:HFS).Path
        Write-Host "[Source: HFS env var]"
        Show-Entry $hfsResolved (Get-VersionLabel $hfsResolved)
        $seen[$hfsResolved.ToLowerInvariant()] = $true
    } else {
        Write-Host "[HFS env var set to '$($env:HFS)' but bin\hython.exe not found there — falling back to scan]"
        Write-Host ""
    }
}

# 2. Standard SideFX install root scan.
$sesiRoot = "C:\Program Files\Side Effects Software"
if (-not (Test-Path $sesiRoot)) {
    if (-not $hfsResolved) {
        Write-Host "Side Effects Software directory not found and no valid HFS env var."
    }
    exit
}

$versions = Get-ChildItem -Path $sesiRoot -Directory | Where-Object { $_.Name -like "Houdini *" }
if (-not $versions -and -not $hfsResolved) {
    Write-Host "No Houdini installations found."
    exit
}

foreach ($ver in $versions) {
    $key = $ver.FullName.ToLowerInvariant()
    if ($seen.ContainsKey($key)) { continue }
    $versionNum = $ver.Name -replace "^Houdini ", ""
    Show-Entry $ver.FullName $versionNum
    $seen[$key] = $true
}
