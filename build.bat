@echo off
chcp 65001 >nul
echo ============================================
echo   PalFastExpeditions v0.2-beta - 构建脚本
echo ============================================
echo.

:: 检查虚拟环境
if not exist "venv\Scripts\python.exe" (
    echo [错误] 未找到虚拟环境，请先运行: python -m venv venv
    pause
    exit /b 1
)

:: 安装 PyInstaller
echo [1/3] 检查 PyInstaller...
venv\Scripts\pip.exe show pyinstaller >nul 2>&1
if errorlevel 1 (
    echo     正在安装 PyInstaller...
    venv\Scripts\pip.exe install pyinstaller -q
)

:: 清理旧构建
echo [2/3] 清理旧构建...
if exist "dist" rmdir /s /q "dist"
if exist "build" rmdir /s /q "build"

:: 构建
echo [3/3] 开始构建...
venv\Scripts\pyinstaller.exe ^
    --noconfirm ^
    --onefile ^
    --windowed ^
    --name "PalFastExpeditions" ^
    --add-data "config;config" ^
    --add-data "venv\Lib\site-packages\rapidocr_onnxruntime;rapidocr_onnxruntime" ^
    --hidden-import "pynput.keyboard._win32" ^
    --hidden-import "pynput.mouse._win32" ^
    --hidden-import "pynput._util.win32" ^
    --hidden-import "rapidocr_onnxruntime" ^
    --hidden-import "onnxruntime" ^
    main.py

if errorlevel 1 (
    echo.
    echo [错误] 构建失败！
    pause
    exit /b 1
)

:: 创建输出目录结构
if not exist "dist\screenshots" mkdir "dist\screenshots"
if not exist "dist\config" mkdir "dist\config"

echo.
echo ============================================
echo   构建完成！
echo   输出: dist\PalFastExpeditions.exe
echo ============================================
echo.
pause
