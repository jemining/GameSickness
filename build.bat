@echo off
set PYTHON=

for %%P in (
    "C:\Python313\python.exe"
    "C:\Python312\python.exe"
    "C:\Python311\python.exe"
    "C:\Python310\python.exe"
    "C:\Python39\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python39\python.exe"
) do (
    if exist %%~P (
        set PYTHON=%%~P
        goto :found_python
    )
)

python --version >nul 2>&1
if %errorlevel% equ 0 ( set PYTHON=python & goto :found_python )

py --version >nul 2>&1
if %errorlevel% equ 0 ( set PYTHON=py & goto :found_python )

echo [ERROR] Python not found.
echo Install Python 3.9+ from https://www.python.org/downloads/
echo Make sure to check "Add Python to PATH" during install.
pause
exit /b 1

:found_python
echo [OK] Python: %PYTHON%
%PYTHON% --version

echo.
echo [1/3] Installing packages...
%PYTHON% -m pip install pystray pillow pyinstaller
if %errorlevel% neq 0 ( echo [ERROR] pip install failed. & pause & exit /b 1 )

echo.
echo [2/3] Building EXE...
%PYTHON% -m PyInstaller ^
    --onefile ^
    --windowed ^
    --name "3DMermy_Crosshair" ^
    --hidden-import "pystray._win32" ^
    --hidden-import "pystray.backend.win32" ^
    --hidden-import "PIL._tkinter_finder" ^
    --hidden-import "PIL.Image" ^
    --hidden-import "PIL.ImageDraw" ^
    "%~dp0crosshair.py"

if %errorlevel% neq 0 ( echo [ERROR] Build failed. & pause & exit /b 1 )

echo.
echo [3/3] Done! Launching...
start "" "%~dp0dist\3DMermy_Crosshair.exe"
