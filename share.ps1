# 一键对外分享：启动应用（带密码）+ 打开 Cloudflare 临时隧道 + 复制体验链接
# 用法：右键「使用 PowerShell 运行」，或双击 share.bat
$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

$Password = "judge2026"      # 评委访问密码，可自行修改
$Port = 8600

Write-Host ""
Write-Host "  智护三高 · 对外分享模式" -ForegroundColor Cyan
Write-Host "  ============================================" -ForegroundColor DarkGray

# 0. 检查 cloudflared
$cf = Join-Path $PSScriptRoot "bin\cloudflared.exe"
if (-not (Test-Path $cf)) {
    Write-Host "  [错误] 找不到 bin\cloudflared.exe" -ForegroundColor Red
    Write-Host "  请先下载：https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe"
    Write-Host "  重命名为 cloudflared.exe 放到 bin 目录下。"
    Read-Host "按回车退出"
    exit 1
}

# 1. 停掉占用端口的老进程
$old = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
       Select-Object -First 1 -ExpandProperty OwningProcess
if ($old) { Stop-Process -Id $old -Force -ErrorAction SilentlyContinue; Start-Sleep -Seconds 1 }

# 2. 启动应用（带密码，只监听本机，由隧道对外）
Write-Host "  [1/3] 启动应用 ..." -ForegroundColor Yellow
Start-Process -FilePath "python" `
    -ArgumentList "app.py", "--no-browser", "--port", $Port, "--password", $Password `
    -WorkingDirectory $PSScriptRoot -WindowStyle Minimized
Start-Sleep -Seconds 4

try {
    $health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/health" -TimeoutSec 10
    Write-Host "        应用已就绪（评委模式：$($health.judge_mode)，管理接口：$($health.admin_api)）"
} catch {
    Write-Host "  [错误] 应用没起来，看看 data\server.err.log" -ForegroundColor Red
    Read-Host "按回车退出"
    exit 1
}

# 3. 启动隧道
Write-Host "  [2/3] 建立公网隧道（约需 10-20 秒）..." -ForegroundColor Yellow
$log = Join-Path $PSScriptRoot "data\tunnel.log"
$err = Join-Path $PSScriptRoot "data\tunnel.err.log"
Remove-Item $log, $err -ErrorAction SilentlyContinue
Start-Process -FilePath $cf `
    -ArgumentList "tunnel", "--url", "http://127.0.0.1:$Port", "--no-autoupdate" `
    -WorkingDirectory $PSScriptRoot -WindowStyle Minimized `
    -RedirectStandardOutput $log -RedirectStandardError $err

$url = $null
for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep -Seconds 1
    $text = (Get-Content $log -Raw -ErrorAction SilentlyContinue) +
            (Get-Content $err -Raw -ErrorAction SilentlyContinue)
    if ($text -match "https://[a-z0-9-]+\.trycloudflare\.com") { $url = $matches[0]; break }
}

if (-not $url) {
    Write-Host "  [错误] 隧道没起来，看看 data\tunnel.err.log" -ForegroundColor Red
    Read-Host "按回车退出"
    exit 1
}

# 4. 生成体验链接并复制
$link = "$url/?k=$Password"
$link | Set-Clipboard
Write-Host "  [3/3] 完成" -ForegroundColor Green
Write-Host ""
Write-Host "  体验链接（已复制到剪贴板，直接粘贴给评委）：" -ForegroundColor Green
Write-Host ""
Write-Host "    $link" -ForegroundColor Cyan
Write-Host ""
Write-Host "  ────────────────────────────────────────────" -ForegroundColor DarkGray
Write-Host "  · 每位评委打开都是自己的一份演示数据，互不影响"
Write-Host "  · 关掉这个窗口 / 电脑休眠，链接就会失效"
Write-Host "  · 重新运行会生成一个新链接"
Write-Host "  ────────────────────────────────────────────" -ForegroundColor DarkGray
Write-Host ""
Read-Host "按回车退出（窗口关掉后服务仍在运行，链接仍有效）"
