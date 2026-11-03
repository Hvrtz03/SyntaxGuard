@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
title SyntaxGuard

echo ========================================================
echo   SyntaxGuard - detector de spam y phishing
echo ========================================================

if exist ".venv\Scripts\python.exe" goto :tiene_venv

echo [1/3] Creando entorno virtual (solo la primera vez)...
set "PY="
py -3.11 --version >nul 2>&1
if not errorlevel 1 set "PY=py -3.11"
if defined PY goto :crear_venv
py -3.10 --version >nul 2>&1
if not errorlevel 1 set "PY=py -3.10"
if defined PY goto :crear_venv
python --version >nul 2>&1
if not errorlevel 1 set "PY=python"
if defined PY goto :crear_venv

echo.
echo No encontre Python. Instala Python 3.10 o 3.11 desde https://www.python.org/downloads/
echo y marca la casilla "Add Python to PATH" durante la instalacion.
goto :error

:crear_venv
%PY% -m venv .venv
if errorlevel 1 goto :error

:tiene_venv
if exist ".venv\.sg_listo" goto :arrancar

echo [2/3] Instalando dependencias (solo la primera vez, requiere internet y tarda unos minutos)...
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :error
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :error
".venv\Scripts\python.exe" -m spacy download en_core_web_sm
if errorlevel 1 goto :error
echo listo> ".venv\.sg_listo"

:arrancar
if not exist ".env" copy ".env.example" ".env" >nul
echo [3/3] Iniciando SyntaxGuard...
echo.
".venv\Scripts\python.exe" run.py %*
if errorlevel 1 goto :error
goto :fin

:error
echo.
echo Algo salio mal. Lee el mensaje de arriba.
pause
exit /b 1

:fin
pause
