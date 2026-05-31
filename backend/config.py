# config.py - Qwen 模型配置
import os

# 通义千问 API 配置
ARK_API_KEY = os.environ.get("ARK_API_KEY", "")
ARK_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"

# 对话模型：Qwen Max
CHAT_MODEL = "qwen-max"

# 图片生成模型：通义万相
IMAGE_MODEL = "wanx2.1-t2i-turbo"

# 图片尺寸
IMAGE_SIZE = "1280*720"

# Unsplash 图片搜索（真实景点照片）
UNSPLASH_ACCESS_KEY = os.environ.get("UNSPLASH_ACCESS_KEY", "")

# 高德地图 Web 服务 API Key（用于地理编码）
AMAP_WEB_KEY = os.environ.get("AMAP_WEB_KEY", "")

# JWT 认证
JWT_SECRET = os.environ.get("JWT_SECRET", "")
JWT_EXPIRE_DAYS = 7
