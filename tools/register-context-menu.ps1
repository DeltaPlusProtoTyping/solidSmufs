# Adds "Open with WMC Viewer" to the right-click menu of CAD and mesh files, for this Windows user
# only (no admin). Double-click still opens files in whatever program owns them (SolidWorks, etc.).
#   powershell -ExecutionPolicy Bypass -File tools\register-context-menu.ps1           # add
#   powershell -ExecutionPolicy Bypass -File tools\register-context-menu.ps1 -Remove   # take it out
param([switch]$Remove)

$root = Split-Path -Parent $PSScriptRoot
$pythonw = Join-Path $root '.venv\Scripts\pythonw.exe'
$launcher = Join-Path $root 'wmcviewer.pyw'
$icon = Join-Path $root 'solidsmufs\web\img\icon.ico'
$extensions = @(
    '.step', '.stp', '.igs', '.iges', '.brep', '.brp',
    '.sldprt', '.sldasm',
    '.x_t', '.x_b', '.xmt_txt', '.xmt_bin',
    '.stl', '.obj', '.ply', '.off', '.3mf', '.glb', '.gltf'
)

foreach ($ext in $extensions) {
    $key = "HKCU:\Software\Classes\SystemFileAssociations\$ext\shell\WMCViewer"
    if ($Remove) {
        if (Test-Path $key) { Remove-Item $key -Recurse }
        continue
    }
    New-Item -Path "$key\command" -Force | Out-Null
    Set-Item -Path $key -Value 'Open with WMC Viewer'
    New-ItemProperty -Path $key -Name 'Icon' -Value $icon -PropertyType String -Force | Out-Null
    Set-Item -Path "$key\command" -Value "`"$pythonw`" `"$launcher`" `"%1`""
}

if ($Remove) { Write-Output 'Removed "Open with WMC Viewer" from the right-click menu.' }
else { Write-Output "Added `"Open with WMC Viewer`" for $($extensions.Count) file types." }
