@echo off
chcp 65001
cd /d "%~dp0"
netstat -ano | findstr ":8765"
if not errorlevel 1 goto openbrowser
echo Starting XJ admin server on port 8765...
start "XJ Admin Server" cmd /k "chcp 65001 && python -m uvicorn app.main:app --host 127.0.0.1 --port 8765"
timeout /t 3
:openbrowser
start "" http://127.0.0.1:8765/admin
