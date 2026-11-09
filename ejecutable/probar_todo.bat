@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0.."
title SyntaxGuard - pruebas completas con el modelo real
set "PY=.venv\Scripts\python.exe"
set "INF=PRUEBAS_REALES_FASE5.txt"

if not exist "%PY%" (
  echo Primero ejecuta ejecutable\iniciar.bat una vez para crear el entorno e instalar las dependencias.
  pause
  exit /b 1
)

echo SyntaxGuard - pruebas con el MODELO REAL> "%INF%"
echo Fecha: %date% %time%>> "%INF%"
echo.>> "%INF%"
set "FALLOS=0"

call :correr "1. Regresion Fase 1: smoke_test.py (detector y API)" backend\scripts\smoke_test.py
call :correr "2. Regresion Fase 2/3: smoke_test_correo.py (extraccion de correos)" backend\scripts\smoke_test_correo.py
call :correr "3. Regresion: smoke_test_frontend.py" backend\scripts\smoke_test_frontend.py
call :correr "4. Regresion Fase 4: smoke_test_fase4.py" backend\scripts\smoke_test_fase4.py
call :correr "5. Fase 5: almacen y servicios (detector simulado SOLO para esta prueba de datos)" backend\scripts\test_almacen_servicio.py
call :correr "6. Fase 5: API completa con el MODELO REAL" backend\scripts\smoke_test_fase5.py
rem La prueba 7 (interfaz en Chromium de la Fase 5) se retiro de esta lista: la interfaz no inicia sesion hasta la Fase 6B.
call :correr "8. Fase 6A: autenticacion y seguridad (API y modelo reales)" backend\scripts\test_auth_fase6.py
call :correr "9. Fase 6A: aislamiento entre usuarios e IDOR (API y modelo reales)" backend\scripts\test_aislamiento_fase6.py
call :correr "10. Fase 6A: migracion SQLite y registros antiguos sin propietario" backend\scripts\test_migracion_fase6.py
call :correr "11. Concurrencia del detector (informativa)" backend\scripts\probar_concurrencia.py

echo.
echo ================================================
if "%FALLOS%"=="0" goto sin_fallos
goto con_fallos
:sin_fallos
echo TODAS LAS PRUEBAS PASARON
goto fin
:con_fallos
echo HUBO %FALLOS% PRUEBAS CON FALLO
:fin
echo Informe guardado en: %CD%\%INF%
echo ================================================
pause
exit /b %FALLOS%

:correr
echo.
echo ---- %~1
echo.>> "%INF%"
echo ==== %~1>> "%INF%"
"%PY%" %~2 %~3 >> "%INF%" 2>&1
if errorlevel 1 (echo   RESULTADO: FALLO & echo RESULTADO: FALLO>> "%INF%" & set /a FALLOS+=1) else (echo   RESULTADO: OK & echo RESULTADO: OK>> "%INF%")
exit /b 0


