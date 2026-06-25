# Build MyDb as a standalone Windows .exe with PyInstaller.
#
# Usage (from a PowerShell terminal in the project folder):
#     .\build_exe.ps1
#
# Result: dist\MyDb.exe — a single file that runs without Python installed.
# The app stores its database (mydb.sqlite3) next to the .exe.

$ErrorActionPreference = "Stop"

python -m pip install -r requirements-dev.txt
python -m PyInstaller --onefile --windowed --name MyDb app.py

Write-Host ""
Write-Host "Done. Your program is at: dist\MyDb.exe"
