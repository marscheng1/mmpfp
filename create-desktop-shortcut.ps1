param([switch]$Force)

$ErrorActionPreference = 'Stop'
$projectPath = $PSScriptRoot
$pythonPath = Join-Path $projectPath '.venv\Scripts\pythonw.exe'
$launcherPath = Join-Path $projectPath 'launch-desktop.vbs'
$scriptHostPath = Join-Path ([Environment]::GetFolderPath('System')) 'wscript.exe'
$shortcutPath = Join-Path $projectPath 'MMPFP.lnk'

if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw 'Virtual environment missing. Run: uv sync --extra desktop'
}
if (-not (Test-Path -LiteralPath $launcherPath)) {
    throw 'launch-desktop.vbs is missing.'
}
if ((Test-Path -LiteralPath $shortcutPath) -and -not $Force) {
    throw 'MMPFP.lnk already exists. Use -Force to replace it.'
}

$shortcutShell = New-Object -ComObject WScript.Shell
$shortcut = $shortcutShell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $scriptHostPath
$shortcut.Arguments = '//Nologo "' + $launcherPath + '"'
$shortcut.WorkingDirectory = $projectPath
$shortcut.Description = 'MMPFP background application (open window from the tray)'
$shortcut.Save()
Write-Output "Created: $shortcutPath"
