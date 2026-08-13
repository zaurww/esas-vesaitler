@echo off
REM Əsas Vəsaitlər -- start the local UI.
REM Double-click this file. It does not depend on any other session:
REM the window that opens IS the server, closing it stops the program.
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
  echo.
  echo   Python tapilmadi. python.org saytindan qurasdirin
  echo   ve "Add python.exe to PATH" secimini isaretleyin.
  echo.
  pause
  exit /b 1
)

set PYTHONIOENCODING=utf-8
chcp 65001 >nul
echo.
echo   Esas Vesaitler -- yuklenir...
echo   Bu pencereni baglamayin: proqram burada islеyir.
echo.
python ev.py
echo.
echo   Proqram dayandirildi.
pause
