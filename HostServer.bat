@echo off
cd /d "%~dp0"
title Last Armory Server
python ArmoryServer.py %*
pause
