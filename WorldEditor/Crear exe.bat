@echo off
rem Crea "World Editor.exe" en esta carpeta con PyInstaller (instalado en el .venv del proyecto).
cd /d "%~dp0.."
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --onefile --windowed --name "World Editor" --paths . --distpath WorldEditor --workpath build\worldeditor --specpath build\worldeditor WorldEditor\world_editor.py
if errorlevel 1 (echo No se pudo crear el .exe & pause & exit /b 1)
echo Listo: WorldEditor\World Editor.exe
