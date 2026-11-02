# Put a SolidSmurfs shortcut on the desktop (drop files on it to open them).
#   powershell -ExecutionPolicy Bypass -File tools\make-shortcut.ps1
$root = Split-Path -Parent $PSScriptRoot
$desktop = [Environment]::GetFolderPath('Desktop')
foreach ($name in 'SolidSmufs.lnk', 'WMC Viewer.lnk') {  # the app's earlier names
    $old = Join-Path $desktop $name
    if (Test-Path $old) { Remove-Item $old }
}
$link = (New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $desktop 'SolidSmurfs.lnk'))
$link.TargetPath = Join-Path $root '.venv\Scripts\pythonw.exe'
$link.Arguments = '-m solidsmufs'
$link.WorkingDirectory = $root
$link.IconLocation = (Join-Path $root 'solidsmufs\web\img\solidsmurfs.ico') + ',0'
$link.Description = 'SolidSmurfs - Wagner Machine 3D part viewer'
$link.Save()
Write-Output "Created $(Join-Path $desktop 'SolidSmurfs.lnk')"
