@echo off
chcp 65001 >nul
cd /d "%~dp0"
title 智护三高 · 三高共病 AI 健康管理智能体

echo.
echo   ============================================
echo    智护三高 · 正在启动，请稍候...
echo   ============================================
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo   [错误] 没有找到 python 命令。
    echo   请先安装 Python 3.9 或更高版本，并在安装时勾选 "Add python.exe to PATH"。
    echo.
    pause
    exit /b 1
)

python app.py
echo.
echo   服务已停止。按任意键关闭窗口。
pause >nul
