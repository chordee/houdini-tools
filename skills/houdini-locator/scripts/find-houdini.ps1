$sesiRoot = "C:\Program Files\Side Effects Software"

if (-not (Test-Path $sesiRoot)) {
    Write-Host "Side Effects Software directory not found."
    exit
}

$versions = Get-ChildItem -Path $sesiRoot -Directory | Where-Object { $_.Name -like "Houdini *" }

if (-not $versions) {
    Write-Host "No Houdini installations found."
    exit
}

foreach ($ver in $versions) {
    $versionNum = $ver.Name -replace "^Houdini ", ""
    Write-Host "--- Houdini $versionNum ---"
    Write-Host "Install Path : $($ver.FullName)"

    $hython  = Join-Path $ver.FullName "bin\hython.exe"
    $houdini = Join-Path $ver.FullName "bin\houdini.exe"

    if (Test-Path $hython)  { Write-Host "hython       : $hython" }
    if (Test-Path $houdini) { Write-Host "houdini      : $houdini" }
    Write-Host ""
}
