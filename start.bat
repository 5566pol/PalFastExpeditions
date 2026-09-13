@echo off
chcp 65001 >nul 2>&1

:: ========== 自动获取管理员权限 ==========
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [INFO] 正在请求管理员权限...
    powershell -Command "Start-Process -FilePath '%~f0' -Verb RunAs -WorkingDirectory '%~dp0'"
    exit /b
)

title PalFastExpeditions
cd /d "%~dp0"

echo ========================================
echo   PalFastExpeditions v0.6-beta
echo ========================================
echo.

:: 检查虚拟环境
if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] .venv not found
    echo   python -m venv .venv
    echo   .venv\Scripts\pip install -r requirements.txt
    pause
    exit /b 1
)

:: 运行程序
echo Starting...
echo.
.venv\Scripts\python.exe main.py
echo.
echo Program exited with code: %errorlevel%
pause
