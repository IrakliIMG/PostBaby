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
echo Build complete: dist\PostBaby\PostBaby.exe
