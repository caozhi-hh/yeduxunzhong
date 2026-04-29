# ---- Stage 1: 构建前端 ----
FROM node:20-slim AS frontend-builder
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ .
RUN npm run build

# ---- Stage 2: 后端 ----
FROM python:3.11-slim

WORKDIR /app

# 安装后端依赖
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制后端代码
COPY backend/ .

# 从构建阶段复制前端静态文件
COPY --from=frontend-builder /build/out ./static

# 创建数据目录（SQLite 数据库 + sessions）
RUN mkdir -p /app/data/sessions

# 暴露端口（HF Spaces 要求 7860）
EXPOSE 7860

# 启动
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "7860"]
