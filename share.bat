@echo off
chcp 65001 >nul
cd /d "%~dp0"
title 智护三高 · 对外分享
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0share.ps1"
