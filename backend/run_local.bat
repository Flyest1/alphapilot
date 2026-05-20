@echo off
set PYTHON_EXE=C:\venvs\py310\Scripts\python.exe
cd /d %~dp0
%PYTHON_EXE% -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
pause
