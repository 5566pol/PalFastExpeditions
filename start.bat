@echo off
chcp 65001 >nul 2>&1
title PalFastExpeditions

cd /d "%~dp0"

echo ========================================
echo   PalFastExpeditions v0.2-beta
echo ========================================
echo.

:: 检查虚拟环境
if not exist "venv\Scripts\python.exe" (
    echo [ERROR] venv not found
    echo   python -m venv venv
    echo   venv\Scripts\pip install -r requirements.txt
    pause
    exit /b 1
)

:: 运行程序
echo Starting...
echo.
venv\Scripts\python.exe main.py
echo.
echo Program exited with code: %errorlevel%
pause
