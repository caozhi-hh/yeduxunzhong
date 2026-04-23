@echo off
chcp 65001 >nul
echo ================================
echo   野渡寻踪 - AI 旅行攻略生成器
echo ================================
echo.

REM 检查 Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到 Python，请先安装 Python 3.10+
    pause
    exit /b 1
)

REM 安装依赖
echo [1/2] 正在安装依赖...
pip install -r requirements.txt -q

REM 启动应用
echo [2/2] 正在启动应用...
echo 启动后浏览器访问 http://localhost:8501
echo 按 Ctrl+C 停止服务
echo.
python -m streamlit run app.py --server.port 8501
pause
