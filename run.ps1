# 智护三高 · 启动脚本（PowerShell）
# 用法：右键“使用 PowerShell 运行”，或在终端执行：
#   powershell -ExecutionPolicy Bypass -File .\run.ps1

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot
chcp 65001 > $null

Write-Host ""
Write-Host "  ============================================" -ForegroundColor Cyan
Write-Host "   智护三高 · 正在启动，请稍候..." -ForegroundColor Cyan
Write-Host "  ============================================" -ForegroundColor Cyan
Write-Host ""

$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    Write-Host "  [错误] 没有找到 python 命令。请先安装 Python 3.9+ 并加入 PATH。" -ForegroundColor Red
    Read-Host "按 Enter 退出"
    exit 1
}

python app.py
Write-Host ""
Read-Host "服务已停止，按 Enter 退出"
