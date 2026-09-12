@echo off
REM The previous Tkinter application, kept runnable during the rebuild.
REM
REM This is the knowledge-lock version: everything starts locked and is
REM unlocked by teaching it. It is being replaced, not maintained -- see
REM docs/REBUILD.md. Nothing in it has been deleted.
cd /d "%~dp0"

if "%AKIRA_VAULT%"=="" set "AKIRA_VAULT=%USERPROFILE%\Documents\Obsidian Vault"

python run.py --vault "%AKIRA_VAULT%"
pause
