@echo off
chcp 65001 >nul
title 野渡寻踪 - 本地前端
cd /d "%~dp0frontend"

REM 清掉残留的代理环境变量
set NO_PROXY=*
set no_proxy=*
set HTTP_PROXY=
set HTTPS_PROXY=
set NEXT_TELEMETRY_DISABLED=1

echo ================================================
echo  野渡寻踪 前端  http://localhost:3000
echo  后端地址取自 frontend\.env.local (http://localhost:8000)
echo  （本窗口必须保持打开；Ctrl+C 停止）
echo ================================================
echo.
npm run dev
echo.
echo 前端已退出。
pause