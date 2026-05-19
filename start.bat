@echo off
title Supply Chain Experiment
cd /d "%~dp0"

echo ========================================
echo   Supply Chain - Quick Start
echo ========================================
echo.

echo [1/3] Starting game server (WS:8765, HTTP:8766)...
start "Game Server" cmd /k cd /d "%~dp0" ^& python server/game_server.py --port 8765

ping -n 3 127.0.0.1 >nul

echo [2/3] Starting student agent...
start "Student Agent" cmd /k cd /d "%~dp0" ^& python student_template/student.py

ping -n 2 127.0.0.1 >nul

echo [3/3] Opening frontend in Edge...
start "" msedge "%~dp0frontend\index.html"

echo.
echo ========================================
echo   All services started!
echo   Server: localhost:8765
echo   Recordings: localhost:8766
echo   Frontend: opened in Edge
echo ========================================
echo.
echo   Press any key to STOP all services...
echo.

pause >nul

echo Stopping all services...
taskkill /fi "WINDOWTITLE eq Game Server" >nul 2>&1
taskkill /fi "WINDOWTITLE eq Student Agent" >nul 2>&1
echo Done.
ping -n 3 127.0.0.1 >nul
