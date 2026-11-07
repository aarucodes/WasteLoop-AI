@echo off
cd /d "%~dp0"
if exist "venv\Scripts\activate.bat" call "venv\Scripts\activate.bat"
echo Starting WasteLoop Streamlit at http://localhost:8501
python -m streamlit run app/streamlit_app.py
pause
