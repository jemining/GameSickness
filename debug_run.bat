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
        goto :found
    )
)

python --version >nul 2>&1
if %errorlevel% equ 0 ( set PYTHON=python & goto :found )

py --version >nul 2>&1
if %errorlevel% equ 0 ( set PYTHON=py & goto :found )

echo Python not found.
pause
exit /b 1

:found
echo Python: %PYTHON%
echo Running crosshair.py ...
echo ----------------------------------------
%PYTHON% "%~dp0crosshair.py"
echo ----------------------------------------
echo Done.
pause
