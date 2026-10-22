@echo off
rem Double-click this file to start Company Analyzer and open it in your browser.
rem Keep this window open while you use the dashboard; close it to stop the dashboard.
cd /d "%~dp0"
echo Starting Company Analyzer... your browser will open in a few seconds.
start "" /b cmd /c "timeout /t 3 /nobreak >nul & start http://127.0.0.1:8600"
".venv\Scripts\python.exe" -m webapp.server
pause
