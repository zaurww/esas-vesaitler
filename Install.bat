@echo off
REM Esas Vesaitler -- one-time setup. Run this once after unzipping.
REM Installs Python if missing, installs the one library the program
REM needs, and puts a desktop shortcut to the launcher next to it.
REM Safe to run again -- it skips whatever is already done.
REM
REM Kept plain ASCII throughout on purpose, including comments: cmd.exe
REM reads a .bat file's own bytes on whatever codepage is active when
REM parsing starts, and a stray multi-byte character -- even inside a REM
REM line -- was found here to corrupt parsing of the rest of the file.
REM The launcher's real name has a non-ASCII letter in it, so this script
REM never spells it out itself; see make_shortcut.ps1 for why, and for
REM how the shortcut avoids needing that name at all.
cd /d "%~dp0"
chcp 65001 >nul

echo.
echo   Esas Vesaitler -- qurasdirma
echo.

if not exist "ev.py" (
    echo   XETA: ev.py bu qovluqda tapilmadi.
    echo   Fayllari yenidan acin ve bu scripti onlarin yaninda ishe salin.
    echo.
    pause
    exit /b 1
)

where python >nul 2>nul
if not errorlevel 1 goto :havepython

echo   Python tapilmadi. Avtomatik qurulur, bir nece deqiqe gozleyin...
where winget >nul 2>nul
if errorlevel 1 goto :pydirect

winget install --id Python.Python.3.12 -e --scope user --silent --accept-package-agreements --accept-source-agreements
if not errorlevel 1 goto :pathrefresh
echo   winget alinmadi, Python birbasha python.org-dan yuklenir...

:pydirect
REM No winget (older Windows 10), or winget failed: fetch the official
REM installer and run it silently for this user only -- no admin rights,
REM and PrependPath=1 does what the "Add python.exe to PATH" box does.
set "PYINST=%TEMP%\python-3.12.10-amd64.exe"
powershell -NoProfile -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol='Tls12'; Invoke-WebRequest -UseBasicParsing -Uri 'https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe' -OutFile $env:PYINST"
if errorlevel 1 goto :pyfail
if not exist "%PYINST%" goto :pyfail
"%PYINST%" /quiet InstallAllUsers=0 PrependPath=1 Include_launcher=0 Include_test=0
if errorlevel 1 goto :pyfail
del "%PYINST%" >nul 2>nul
goto :pathrefresh

:pyfail
echo.
echo   XETA: Python avtomatik qurulmadi. Internet elaqesini yoxlayin
echo   ve bu faili yeniden ishe salin. Olmasa, elle qurashdirin:
echo   https://www.python.org/downloads/
echo   Qurarken "Add python.exe to PATH" qutusunu isaretleyin.
echo.
pause
exit /b 1

:pathrefresh

REM winget updates the registry, not this already-open console's PATH.
REM Re-read PATH from both hives so "python" is usable without closing
REM the window.
for /f "usebackq tokens=2,*" %%A in (`reg query "HKCU\Environment" /v Path 2^>nul`) do set "UPATH=%%B"
for /f "usebackq tokens=2,*" %%A in (`reg query "HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Environment" /v Path 2^>nul`) do set "MPATH=%%B"
set "PATH=%MPATH%;%UPATH%"

where python >nul 2>nul
if not errorlevel 1 goto :havepython

echo.
echo   Python qurashdirildi, amma bu pencere onu hele gormur.
echo   Bu pencereni baglayib bu scripti yeniden ishe salin.
echo.
pause
exit /b 0

:havepython
echo   Python tapildi:
python --version

echo   Kitabxanalar qurulur...
python -m pip install -r requirements.txt --quiet
if errorlevel 1 (
    echo.
    echo   XETA: kitabxanalar qurulmadi. Internet elaqesini yoxlayin
    echo   ve bu faili yeniden ishe salin.
    echo.
    pause
    exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0make_shortcut.ps1" -AppDir "%CD%"
if errorlevel 1 (
    echo.
    echo   Qeyd: masaustu qisayolu yaradila bilmedi, amma proqram ozu hazirdir.
    echo   Baslayici fayla iki dene basaraq ishe sala bilersiniz.
    echo.
)

echo.
echo   Hazirdir. Masaustunde "Esas Vesaitler" qisayolu yaradildi.
echo   Proqrami ishe salmaq ucun ona iki dene basin.
echo.
pause
