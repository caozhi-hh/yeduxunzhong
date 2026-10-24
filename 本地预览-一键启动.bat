@echo off
chcp 65001 >nul
title 野渡寻踪 - 本地预览 一键启动

echo ================================================
echo  野渡寻踪 本地预览
echo  前端 http://localhost:3000
echo  后端 http://127.0.0.1:8000
echo ================================================
echo.

echo [0/3] 清理占用 8000 / 3000 的旧进程 ...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr /r ":8000 .*LISTENING"') do taskkill /f /pid %%a >nul 2>&1
for /f "tokens=5" %%a in ('netstat -ano ^| findstr /r ":3000 .*LISTENING"') do taskkill /f /pid %%a >nul 2>&1
echo       完成
echo.

echo [1/3] 启动后端（新窗口）...
start "野渡寻踪-后端" "%~dp0本地-后端.bat"

echo [2/3] 启动前端（新窗口）...
start "野渡寻踪-前端" "%~dp0本地-前端.bat"

echo [3/3] 等待约 35 秒（后端首次 import 较慢），然后自动打开浏览器 ...
timeout /t 35 /nobreak >nul
start "" http://localhost:3000

echo.
echo ================================================
echo  已就绪：http://localhost:3000
echo.
echo  首次使用请先注册 / 登录（推荐页与攻略页都要求登录）。
echo  目的地建议填「拉萨」——已验证能配到图。
echo.
echo  关闭那两个新开的黑窗口即停止服务。
echo ================================================
pause