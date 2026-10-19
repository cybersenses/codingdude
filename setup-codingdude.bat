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
rem  CodingDude one-shot setup
rem  Installs EVERYTHING a fresh machine needs to run CodingDude:
rem    1. uv (Python package manager)      - installed if missing
rem    2. Python 3.12 + project venv       - via `uv sync`
rem    3. Semgrep CLI (security gate)      - via `uv tool install`
rem    4. Node.js check (frontend + MCP)   - warns if missing
rem    5. MCP server binaries              - codegraph + github-mcp-server
rem    6. GitHub CLI (gh)                  - installed if missing
rem    7. Frontend production build        - via `npm ci && npm run build`
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
  echo [1/7] uv already installed: %UV%
) else (
  echo [1/7] Installing uv...
  powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "irm https://astral.sh/uv/install.ps1 | iex"
  if not exist "%UV%" (
    echo ERROR: uv install failed. Install manually: https://docs.astral.sh/uv/
    pause & exit /b 1
  )
)

rem --- 2. Python venv + dependencies ------------------------------------------
echo [2/7] Syncing Python 3.12 venv and project dependencies...
call "%UV%" sync || (echo ERROR: uv sync failed & pause & exit /b 1)

rem --- 3. Semgrep CLI ---------------------------------------------------------
echo [3/7] Installing Semgrep CLI (security gate engine)...
call "%UV%" tool install semgrep 2>nul || call "%UV%" tool upgrade semgrep || (
  echo WARNING: Semgrep install failed - the security gate will run in
  echo          Bandit/regex-only mode until this succeeds.
)

rem --- 4. Node.js -------------------------------------------------------------
set "HAS_NODE=0"
where node >nul 2>nul && set "HAS_NODE=1"
if "%HAS_NODE%"=="0" (
  echo [4/7] WARNING: Node.js not found. Frontend build, codegraph and the
  echo        zai-vision MCP server will be skipped.
  echo        Install Node 20+ from https://nodejs.org and re-run this script.
  goto :ghcli
)

rem --- 5. MCP server binaries --------------------------------------------------
echo [5/7] Installing MCP server binaries...
rem codegraph: semantic code intelligence MCP (bundles its own node runtime).
call npm install -g @colbymchenry/codegraph || (
  echo WARNING: codegraph install failed - codegraph MCP will be unavailable.
)
rem github MCP: vendored with the deploy, copied to the per-user tools dir.
if not exist "%USERPROFILE%\tools\github-mcp" mkdir "%USERPROFILE%\tools\github-mcp"
if exist "%USERPROFILE%\tools\github-mcp\github-mcp-server.exe" (
  echo        github-mcp-server.exe already present - leaving it in place.
) else copy /y "%REPO%tools\github-mcp\github-mcp-server.exe" "%USERPROFILE%\tools\github-mcp\" >nul || (
  echo WARNING: could not copy github-mcp-server.exe - github MCP will be
  echo          unavailable on this machine.
)
echo        Note: %USERPROFILE%\.codingdude\mcp.json is seeded from PATH on
echo        first boot. If an old entry is broken, delete mcp.json and re-run
echo        start-codingdude.bat to re-seed it.

:ghcli
rem --- 6. GitHub CLI -----------------------------------------------------------
where gh >nul 2>nul
if errorlevel 1 (
  echo [6/7] Installing GitHub CLI...
  winget install --id GitHub.cli -e --accept-source-agreements --accept-package-agreements || (
    echo WARNING: gh install failed - GitHub features will be degraded.
  )
) else (
  echo [6/7] GitHub CLI already installed.
)

if "%HAS_NODE%"=="0" goto :done

rem --- 7. Frontend build -------------------------------------------------------
echo [7/7] Building frontend...
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
