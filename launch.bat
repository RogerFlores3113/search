@echo off
:: local-browser-agent — launch script for Windows
:: Requires: uv (https://docs.astral.sh/uv/)
::
:: First run: uv sync (downloads deps into .venv automatically)
:: Subsequent runs: starts instantly

where uv >nul 2>&1
if %errorlevel% neq 0 (
    echo uv is required but not installed.
    echo Install: powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
    pause
    exit /b 1
)

cd /d "%~dp0"
uv run python -m agent %*
