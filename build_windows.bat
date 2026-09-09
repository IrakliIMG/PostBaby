@echo off
setlocal

REM Build PostBaby.exe on Windows with Python 3.11 or later installed.
if not exist .venv py -3 -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -r requirements.txt pyinstaller
python -m unittest discover -s tests -v
if errorlevel 1 exit /b %errorlevel%
pyinstaller --noconfirm --clean PostBaby.spec
if errorlevel 1 exit /b %errorlevel%
echo.
echo Executable build complete: dist\PostBaby\PostBaby.exe

set ISCC=
if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" set ISCC="%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if exist "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" set ISCC="C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if exist "C:\Program Files\Inno Setup 6\ISCC.exe" set ISCC="C:\Program Files\Inno Setup 6\ISCC.exe"

if defined ISCC (
    echo Compiling installer...
    %ISCC% installer.iss
    if errorlevel 1 exit /b %errorlevel%
    echo.
    echo Installer build complete: dist\PostBabySetup.exe
) else (
    echo Inno Setup compiler ISCC.exe not found. Skipping installer build.
)
