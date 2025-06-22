@echo off
rem -------------------------------
rem run_neptuno.bat
rem   - Inicia Neptuno en esta ventana con Python 32-bits
rem   - Abre navegador en localhost:5000
rem   - Mantiene la consola abierta
rem -------------------------------

rem Ir al directorio del script
cd /d "%~dp0"

rem Lanzar el servidor en background (same window) con Python 32-bits
start /B "" "C:\Python313-32\python.exe" neptuno.py

rem Darle tiempo a Flask para que inicie
timeout /t 3 /nobreak >nul

rem Abrir la aplicación en el navegador por defecto
start "" "http://localhost:5000"

rem Finalmente, mantener la ventana abierta
echo.
echo Servidor ejecutándose. Pulsa cualquier tecla para cerrar esta ventana...
pause >nul
