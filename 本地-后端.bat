@echo off
chcp 65001 >nul
title 野渡寻踪 - 本地后端
cd /d "%~dp0backend"

REM 清掉残留的代理环境变量（否则 requests/httpx 会走已关闭的 Clash）
set NO_PROXY=*
set no_proxy=*
set HTTP_PROXY=
set HTTPS_PROXY=

echo ================================================
echo  野渡寻踪 后端  http://127.0.0.1:8000
echo  文档: http://127.0.0.1:8000/docs
echo  （本窗口必须保持打开；Ctrl+C 停止）
echo ================================================
echo.
python -m uvicorn main:app --host 127.0.0.1 --port 8000
echo.
echo 后端已退出。
pause