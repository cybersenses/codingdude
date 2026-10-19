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
rem Run all quality gates from the project venv (ruff, mypy, pytest).
rem Usage: gates.bat          - full suite
rem        gates.bat tests/foo.py - pytest on specific paths only
setlocal
cd /d "%~dp0"

where uv >nul 2>nul || (echo [gates] uv not found - run setup-codingdude.bat first & exit /b 1)

echo [gates] ruff ...
uv run ruff check src tests || exit /b 1
echo [gates] mypy ...
uv run mypy || exit /b 1
echo [gates] pytest %* ...
uv run pytest -q %*
exit /b %ERRORLEVEL%
