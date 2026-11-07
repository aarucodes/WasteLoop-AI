@echo off
cd /d "%~dp0"
if exist "venv\Scripts\activate.bat" call "venv\Scripts\activate.bat"
echo Starting WasteLoop API at http://127.0.0.1:8000
python -m uvicorn api.main:app --host 127.0.0.1 --port 8000
pause
