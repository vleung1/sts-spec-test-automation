@echo off
REM STS Test Runner - Windows double-click launcher
REM Double-click this file in Explorer to start the test runner UI.

cd /d "%~dp0"

REM Activate venv if it exists
if exist ".venv\Scripts\activate.bat" (
    call ".venv\Scripts\activate.bat"
    echo Activated .venv
)

REM Try python, then py
where python >nul 2>&1
if %ERRORLEVEL% == 0 (
    set PYTHON=python
) else (
    where py >nul 2>&1
    if %ERRORLEVEL% == 0 (
        set PYTHON=py
    ) else (
        echo Python not found. Install Python 3.9+ and add it to PATH.
        pause
        exit /b 1
    )
)

%PYTHON% launcher.py
if %ERRORLEVEL% neq 0 (
    echo.
    echo Something went wrong. See the error above.
    pause
)
