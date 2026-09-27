@echo off
rem ===========================================================================
rem  CodingDude one-shot setup
rem  Installs EVERYTHING a fresh machine needs to run CodingDude:
rem    1. uv (Python package manager)      - installed if missing
rem    2. Python 3.12 + project venv       - via `uv sync`
rem    3. Semgrep CLI (security gate)      - via `uv tool install`
rem    4. Node.js check (frontend build)   - warns if missing
rem    5. Frontend production build        - via `npm ci && npm run build`
rem
rem  Safe to re-run at any time; every step is idempotent.
rem  After setup, run start-codingdude.bat to launch the server.
rem ===========================================================================
setlocal enableextensions
title CodingDude setup

set "REPO=%~dp0"
cd /d "%REPO%"
set "UV=%USERPROFILE%\.local\bin\uv.exe"

echo ==============================================
echo  CodingDude setup
echo ==============================================
echo.

rem --- 1. uv -----------------------------------------------------------------
if exist "%UV%" (
  echo [1/5] uv already installed: %UV%
) else (
  echo [1/5] Installing uv...
  powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "irm https://astral.sh/uv/install.ps1 | iex"
  if not exist "%UV%" (
    echo ERROR: uv install failed. Install manually: https://docs.astral.sh/uv/
    pause & exit /b 1
  )
)

rem --- 2. Python venv + dependencies ------------------------------------------
echo [2/5] Syncing Python 3.12 venv and project dependencies...
call "%UV%" sync || (echo ERROR: uv sync failed & pause & exit /b 1)

rem --- 3. Semgrep CLI ---------------------------------------------------------
echo [3/5] Installing Semgrep CLI (security gate engine)...
call "%UV%" tool install semgrep 2>nul || call "%UV%" tool upgrade semgrep || (
  echo WARNING: Semgrep install failed - the security gate will run in
  echo          Bandit/regex-only mode until this succeeds.
)

rem --- 4. Node.js -------------------------------------------------------------
where node >nul 2>nul
if errorlevel 1 (
  echo [4/5] WARNING: Node.js not found. The frontend will NOT be built.
  echo        Install Node 20+ from https://nodejs.org and re-run this script.
  goto :done
)

rem --- 5. Frontend build ------------------------------------------------------
echo [4/5] Node found.
echo [5/5] Building frontend...
pushd frontend
call npm ci || (echo ERROR: npm ci failed & popd & pause & exit /b 1)
call npm run build || (echo ERROR: frontend build failed & popd & pause & exit /b 1)
popd

:done
echo.
echo ==============================================
echo  Setup complete. Launch with start-codingdude.bat
echo ==============================================
pause
exit /b 0
