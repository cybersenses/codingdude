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
