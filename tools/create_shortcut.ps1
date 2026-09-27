# create_shortcut.ps1 - adds ScreenQA to your Start menu (and, if you want, the desktop). Step 19.
#
# Run from the project folder AFTER building the .exe:
#     .\tools\create_shortcut.ps1              (Start menu only)
#     .\tools\create_shortcut.ps1 -Desktop     (Start menu and desktop)
#
# To remove them later, just delete the "ScreenQA" shortcut(s).

param([switch]$Desktop)

$exe = Join-Path $PSScriptRoot "..\dist\ScreenQA\ScreenQA.exe"
if (-not (Test-Path $exe)) {
    Write-Host "ScreenQA.exe not found - build it first:  python -m PyInstaller ScreenQA.spec --noconfirm"
    exit 1
}
$exe = (Resolve-Path $exe).Path

$folders = @([Environment]::GetFolderPath("Programs"))           # Start menu > All apps
if ($Desktop) { $folders += [Environment]::GetFolderPath("Desktop") }

$shell = New-Object -ComObject WScript.Shell                        # Windows' built-in shortcut maker
foreach ($folder in $folders) {
    $path = Join-Path $folder "ScreenQA.lnk"
    $link = $shell.CreateShortcut($path)
    $link.TargetPath = $exe
    $link.WorkingDirectory = Split-Path $exe
    $link.IconLocation = "$exe,0"
    $link.Description = "ScreenQA - Screen Question Assistant"
    $link.Save()
    Write-Host "Created $path"
}
