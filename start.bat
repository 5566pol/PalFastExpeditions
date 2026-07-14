@echo off
chcp 65001 >nul

:: 自动请求管理员权限
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [提示] 正在请求管理员权限...
    powershell -Command "Start-Process '%~f0' -Verb RunAs"
    exit /b
)

echo ========================================
echo   PalFastExpeditions v0.1-beta
echo ========================================
echo.
echo [√] 已以管理员权限运行
echo.

cd /d "%~dp0"

:: 检查虚拟环境
if not exist "venv\Scripts\python.exe" (
    echo [错误] 未找到虚拟环境，请先安装依赖：
    echo   python -m venv venv
    echo   venv\Scripts\pip install -r requirements.txt
    pause
    exit /b 1
)

:: 检查 Tesseract
if not exist "D:\Program Files\Tesseract-OCR\tesseract.exe" (
    echo [警告] 未找到 Tesseract OCR 默认安装路径
    echo 请确保已安装 Tesseract OCR 并在程序中设置正确路径
    echo 下载地址: https://github.com/tesseract-ocr/tesseract/releases/
    echo.
)

:: 运行程序
echo 正在启动程序...
echo.
venv\Scripts\python.exe main.py

pause
