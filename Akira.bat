@echo off
REM Launch Akira with no console window.
REM
REM Paths are relative to this file (%~dp0 is the folder it lives in), so the
REM repository can sit anywhere. pythonw.exe rather than python.exe: the latter
REM leaves a black console window open behind the app for as long as it runs.
REM
REM If Akira fails to start and simply vanishes, run "Akira (console).bat"
REM instead -- it keeps the traceback on screen.
cd /d "%~dp0"
start "" pythonw.exe "%~dp0shell.py"
