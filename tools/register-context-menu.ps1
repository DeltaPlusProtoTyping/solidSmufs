# Adds "Open with SolidSmurfs" to the right-click menu of CAD, mesh, drawing, PDF, G-code, picture and zip files, for this Windows user
# only (no admin). Double-click still opens files in whatever program owns them (SolidWorks, etc.).
#   powershell -ExecutionPolicy Bypass -File tools\register-context-menu.ps1           # add
#   powershell -ExecutionPolicy Bypass -File tools\register-context-menu.ps1 -Remove   # take it out
param([switch]$Remove)

$root = Split-Path -Parent $PSScriptRoot
$pythonw = Join-Path $root '.venv\Scripts\pythonw.exe'
$launcher = Join-Path $root 'solidsmurfs.pyw'
$icon = Join-Path $root 'solidsmufs\web\img\solidsmurfs.ico'
$extensions = @(
    '.step', '.stp', '.igs', '.iges', '.brep', '.brp',
    '.sldprt', '.sldasm',
    '.x_t', '.x_b', '.xmt_txt', '.xmt_bin',
    '.stl', '.obj', '.ply', '.off', '.3mf', '.glb', '.gltf',
    '.dxf', '.dwg', '.plt', '.hpgl', '.hgl', '.svg', '.pdf', '.prc', '.u3d',
    '.slddrw', '.eprt', '.easm', '.edrw', '.eprtx', '.easmx', '.edrwx',
    '.nc', '.tap', '.gcode', '.gc', '.ngc', '.cnc', '.eia', '.mpf', '.min', '.ptp',
    '.png', '.jpg', '.jpeg', '.bmp', '.gif', '.tif', '.tiff', '.webp', '.tga',
    '.zip'
)

foreach ($ext in $extensions) {
    $shell = "HKCU:\Software\Classes\SystemFileAssociations\$ext\shell"
    $old = "$shell\WMCViewer"  # the entry under the app's earlier name
    if (Test-Path $old) { Remove-Item $old -Recurse }
    $key = "$shell\SolidSmurfs"
    if ($Remove) {
        if (Test-Path $key) { Remove-Item $key -Recurse }
        continue
    }
    New-Item -Path "$key\command" -Force | Out-Null
    Set-Item -Path $key -Value 'Open with SolidSmurfs'
    New-ItemProperty -Path $key -Name 'Icon' -Value $icon -PropertyType String -Force | Out-Null
    Set-Item -Path "$key\command" -Value "`"$pythonw`" `"$launcher`" `"%1`""
}

if ($Remove) { Write-Output 'Removed "Open with SolidSmurfs" from the right-click menu.' }
else { Write-Output "Added `"Open with SolidSmurfs`" for $($extensions.Count) file types." }
