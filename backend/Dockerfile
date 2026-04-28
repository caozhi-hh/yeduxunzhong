FROM python:3.11-slim

WORKDIR /app

# 安装依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制后端代码
COPY . .

# 创建数据目录（SQLite 数据库 + sessions）
RUN mkdir -p /app/data/sessions

# 暴露端口（HF Spaces 要求 7860）
EXPOSE 7860

# 启动
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "7860"]
