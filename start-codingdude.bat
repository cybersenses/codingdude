@REM CodingDude — a personal coding agent.
@REM Copyright (C) 2025 Cyberflex (https://www.cyberflex.io)
@REM 
@REM This program is free software: you can redistribute it and/or modify
@REM it under the terms of the GNU Affero General Public License as published
@REM by the Free Software Foundation, either version 3 of the License, or
@REM (at your option) any later version.
@REM 
@REM This program is distributed in the hope that it will be useful,
@REM but WITHOUT ANY WARRANTY; without even the implied warranty of
@REM MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
@REM GNU Affero General Public License for more details.
@REM 
@REM You should have received a copy of the GNU Affero General Public License
@REM along with this program.  If not, see <https://www.gnu.org/licenses/>.
@echo off
rem ===========================================================================
rem  CodingDude launcher
rem  Double-click this file, or point a Desktop shortcut at it, to start the
rem  local agent server and open the UI. Close the "CodingDude server" window
rem  to stop the agent.
rem
rem  Usage:  start-codingdude.bat [port]      (default port 8765)
rem ===========================================================================
setlocal enableextensions
title CodingDude

rem Repo root = the folder this .bat lives in (keep it at the repo root).
set "REPO=%~dp0"
set "PORT=8765"
if not "%~1"=="" set "PORT=%~1"
set "PY=%REPO%.venv\Scripts\python.exe"
set "URL=http://127.0.0.1:%PORT%"

echo CodingDude
echo   repo: %REPO%
echo   port: %PORT%
echo.

if not exist "%PY%" (
  echo ERROR: Python venv not found at:
  echo   %PY%
  echo.
  echo Run "uv sync" in the repo first, then run this again.
  echo.
  pause
  exit /b 1
)

rem --- already running? just open the UI ------------------------------------
netstat -ano | findstr "127.0.0.1:%PORT%" | findstr /i "LISTENING" >nul 2>nul
if not errorlevel 1 (
  echo Server already listening on port %PORT%. Opening the UI...
  start "" "%URL%"
  exit /b 0
)

rem --- start the server in its own window -----------------------------------
echo Starting the agent server in a new window...
start "CodingDude server" /D "%REPO%" "%PY%" -m codingdude.cli serve --port %PORT%

rem --- wait for it to come up, then open the UI -----------------------------
set /a tries=0
:wait
set /a tries+=1
timeout /t 1 /nobreak >nul
netstat -ano | findstr "127.0.0.1:%PORT%" | findstr /i "LISTENING" >nul 2>nul
if not errorlevel 1 goto open
if %tries% lss 30 goto wait

echo.
echo WARNING: the server did not come up within 30 seconds.
echo Check the "CodingDude server" window for errors.
echo.
pause
exit /b 1

:open
echo Server is up. Opening %URL%
start "" "%URL%"
exit /b 0
