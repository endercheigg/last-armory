@echo off
cd /d "%~dp0"
python LastArmory.py
if errorlevel 1 pause
