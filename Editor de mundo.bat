@echo off
rem Editor de mundo: islas de mision, arena de duelos y aldeas (punto 24 del bloque E).
cd /d "%~dp0"
if exist ".venv\Scripts\pythonw.exe" (
    start "" ".venv\Scripts\pythonw.exe" world_editor.py
) else (
    start "" pythonw world_editor.py
)
