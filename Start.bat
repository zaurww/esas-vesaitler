@echo off
REM Esas Vesaitler -- start the local UI.
REM Double-click this file. It does not depend on any other session:
REM the window that opens IS the server, closing it stops the program.
REM
REM Kept plain ASCII with CRLF line endings on purpose, like Install.bat
REM (see its header). cmd.exe re-reads a running .bat by byte offset, and
REM after "chcp 65001" below a single multi-byte letter shifted every later
REM line: "echo" came out as "cho" on a real user's machine.
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
  echo.
  echo   Python tapilmadi. Once "Install.bat" faili ishe salin -- o,
  echo   Python-u ozu qurar ve masaustunde qisayol yaradar.
  echo.
  echo   Elle qurmaq isteseniz: python.org saytindan qurasdirin
  echo   ve "Add python.exe to PATH" secimini isaretleyin.
  echo.
  pause
  exit /b 1
)

REM The one library the program needs. Install.bat installs it, but people
REM start this file without running setup first -- install it here too
REM rather than stop on an ImportError.
python -c "import openpyxl" >nul 2>nul
if errorlevel 1 (
  echo.
  echo   Lazim olan kitabxana qurulur ^(openpyxl^)...
  python -m pip install -r requirements.txt --quiet
  if errorlevel 1 (
    echo.
    echo   XETA: kitabxana qurulmadi. Internet elaqesini yoxlayin
    echo   ve ya "Install.bat" faylini ishe salin.
    echo.
    pause
    exit /b 1
  )
)

set PYTHONIOENCODING=utf-8
chcp 65001 >nul
echo.
echo   Esas Vesaitler -- yuklenir...
echo   Bu pencereni baglamayin: proqram burada isleyir.
echo.
python ev.py
echo.
echo   Proqram dayandirildi.
pause
