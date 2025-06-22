@echo off
rem -------------------------------
rem run_neptuno.bat (Python 64-bits)
rem -------------------------------

cd /d "%~dp0"

rem Inicia el servidor con Python 64-bits
start /B "" "C:\Users\Ricardo Guerrero\AppData\Local\Programs\Python\Python313\python.exe" neptuno.py

timeout /t 3 /nobreak >nul

start "" "http://localhost:5000"

echo.
echo Servidor ejecutándose. Pulsa cualquier tecla para cerrar esta ventana...
pause >nul
