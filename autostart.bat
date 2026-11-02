@echo off
rem Turn "start the bot when Windows starts" on or off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0autostart.ps1"
