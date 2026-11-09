# Installs this prebuilt copy of SolidSmurfs for the current Windows user only: no admin needed. Packed beside
# SolidSmurfs.exe in the Windows zip, and run by "Install SolidSmurfs.cmd" there. It:
#   - copies the app to %LOCALAPPDATA%\Programs\SolidSmurfs (replacing an older copy there),
#   - adds a Start menu shortcut (and, with -Desktop, a desktop one),
#   - adds "Open with SolidSmurfs" to the right-click menu of the files it opens (double-click stays with their programs),
#   - lists it under Settings > Apps, where it can be uninstalled.
#   powershell -ExecutionPolicy Bypass -File install-solidsmurfs.ps1 [-Desktop] [-Uninstall]
param([switch]$Uninstall, [switch]$Desktop)
$ErrorActionPreference = 'Stop'

$dest = Join-Path $env:LOCALAPPDATA 'Programs\SolidSmurfs'
$exe = Join-Path $dest 'SolidSmurfs.exe'
$startLink = Join-Path ([Environment]::GetFolderPath('Programs')) 'SolidSmurfs.lnk'
$deskLink = Join-Path ([Environment]::GetFolderPath('Desktop')) 'SolidSmurfs.lnk'
$appsKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\SolidSmurfs'

function Running-From($folder) {
    # copies of SolidSmurfs started from that folder (its window and its document workers)
    @(Get-CimInstance Win32_Process -Filter "Name = 'SolidSmurfs.exe'" | Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith($folder, 'OrdinalIgnoreCase') })
}

if (Running-From $dest) {
    Write-Output 'SolidSmurfs is running from its installed folder. Close it, then run this again.'
    exit 1
}

if ($Uninstall) {
    Set-Location $env:TEMP  # not in the folder being removed
    $menu = Join-Path $dest 'register-context-menu.ps1'
    if (Test-Path $menu) { & $menu -Remove | Out-Null }
    foreach ($f in $startLink, $deskLink) { if (Test-Path $f) { Remove-Item $f } }
    if (Test-Path $appsKey) { Remove-Item $appsKey -Recurse }
    if (Test-Path $dest) { Remove-Item $dest -Recurse -Force }
    Write-Output 'SolidSmurfs is uninstalled. (Your settings stay in %APPDATA%\SolidSmufs; delete that folder to remove them too.)'
    exit 0
}

$here = $PSScriptRoot
if (-not (Test-Path (Join-Path $here 'SolidSmurfs.exe'))) {
    Write-Output "There's no SolidSmurfs.exe beside this script: run it from the unzipped SolidSmurfs folder."
    exit 1
}
if ($here.TrimEnd('\') -ine $dest) {
    Write-Output "Copying SolidSmurfs to $dest ..."
    New-Item -ItemType Directory -Force $dest | Out-Null
    # a mirror: files an older version had and this one doesn't are removed
    robocopy $here $dest /MIR /NFL /NDL /NJH /NJS /NP | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "Copying failed (robocopy code $LASTEXITCODE)." }
}
# files from a downloaded zip carry the internet's mark, which makes Windows ask before each run
Get-ChildItem $dest -Recurse -File | Unblock-File

$shell = New-Object -ComObject WScript.Shell
$links = @($startLink) + $(if ($Desktop) { @($deskLink) } else { @() })
foreach ($path in $links) {
    $link = $shell.CreateShortcut($path)
    $link.TargetPath = $exe
    $link.WorkingDirectory = $dest
    $link.IconLocation = "$exe,0"
    $link.Description = 'SolidSmurfs - Wagner Machine 3D part viewer'
    $link.Save()
}

& (Join-Path $dest 'register-context-menu.ps1') -Exe $exe

$versionFile = Join-Path $dest 'VERSION.txt'
$version = if (Test-Path $versionFile) { (Get-Content $versionFile -Raw).Trim() } else { '' }
$sizeKb = [int]((Get-ChildItem $dest -Recurse -File | Measure-Object Length -Sum).Sum / 1KB)
New-Item -Path $appsKey -Force | Out-Null
$values = @{
    DisplayName = 'SolidSmurfs'; DisplayVersion = $version; Publisher = 'Wagner Machine Co.'; DisplayIcon = "$exe,0"
    InstallLocation = $dest
    UninstallString = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$dest\install-solidsmurfs.ps1`" -Uninstall"
}
foreach ($k in $values.Keys) { New-ItemProperty -Path $appsKey -Name $k -Value $values[$k] -PropertyType String -Force | Out-Null }
foreach ($k in 'NoModify', 'NoRepair') { New-ItemProperty -Path $appsKey -Name $k -Value 1 -PropertyType DWord -Force | Out-Null }
New-ItemProperty -Path $appsKey -Name 'EstimatedSize' -Value $sizeKb -PropertyType DWord -Force | Out-Null

Write-Output "SolidSmurfs $version is installed for $env:USERNAME. Start it from the Start menu, or right-click a part and pick Open with SolidSmurfs."
Write-Output "(The folder you unzipped can be deleted now.)"
