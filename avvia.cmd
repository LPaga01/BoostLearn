@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" goto dependencies
if exist "C:\Python312\python.exe" (
    "C:\Python312\python.exe" -m venv .venv
) else (
    py -3.12 -m venv .venv
)
if errorlevel 1 goto error
:dependencies
".venv\Scripts\python.exe" -c "import streamlit, chromadb, pypdf, dotenv, agno, reportlab; from google import genai" >nul 2>&1
if not errorlevel 1 goto ready
echo Installazione delle dipendenze. Serve una connessione Internet.
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto error
:ready
if not exist ".env" copy /Y .env.example .env >nul
".venv\Scripts\python.exe" -m streamlit run app.py
if errorlevel 1 goto error
exit /b 0
:error
echo.
echo Avvio non riuscito. Leggi il messaggio sopra e le istruzioni in README.md.
pause
exit /b 1
