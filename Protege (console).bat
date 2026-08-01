@echo off
REM Launch Protege with a console attached, so a crash leaves its traceback on
REM screen instead of the window simply vanishing.
REM
REM Paths are relative to this file rather than hardcoded: %~dp0 is the folder
REM the script lives in, so the repository can sit anywhere. Set PROTEGE_VAULT
REM beforehand to point at a vault other than the default one beside it.
cd /d "%~dp0"

if "%PROTEGE_VAULT%"=="" set "PROTEGE_VAULT=%~dp0..\Obsidian Vault"

python run.py --vault "%PROTEGE_VAULT%"
pause
