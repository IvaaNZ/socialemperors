@echo off
rem World Editor: islas de mision, arena de duelos y aldeas (punto 24 del bloque E).
rem Usa el Python del proyecto (la carpeta de arriba).
cd /d "%~dp0.."
if exist ".venv\Scripts\pythonw.exe" (
    start "" ".venv\Scripts\pythonw.exe" WorldEditor\world_editor.py
) else (
    start "" pythonw WorldEditor\world_editor.py
)
