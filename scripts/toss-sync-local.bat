@echo off
chcp 65001 >nul
powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "%~dp0toss-sync-local.ps1"
exit /b %ERRORLEVEL%
