@echo off
title Afinia - Backend
echo Iniciando backend de Flask de Afinia...
cd /d "%~dp0backend"
if exist venv\Scripts\activate.bat (
    call venv\Scripts\activate.bat
)
python run.py
pause

