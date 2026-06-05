# config.py - Qwen 模型配置
import os

# 通义千问 API 配置
ARK_API_KEY = os.environ.get("ARK_API_KEY", "sk-9e8036d16b7048fca350b07e50be0773")
ARK_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"

# 对话模型：Qwen Plus（比 Max 更稳定，适合流式输出）
CHAT_MODEL = "qwen-plus"

# 图片生成模型：通义万相
IMAGE_MODEL = "wanx2.1-t2i-turbo"

# 图片尺寸
IMAGE_SIZE = "1280*720"

# Unsplash 图片搜索（真实景点照片）
UNSPLASH_ACCESS_KEY = os.environ.get("UNSPLASH_ACCESS_KEY", "J_De4v5TH483Ht4PIeolG2qUp4rxDzCF_bYJCUaCZnE")

# 高德地图 Web 服务 API Key（用于地理编码）
AMAP_WEB_KEY = os.environ.get("AMAP_WEB_KEY", "41df325e119de0a6fef31ea53d2f259c")

# JWT 认证
JWT_SECRET = os.environ.get("JWT_SECRET", "yeduxunzhong-jwt-secret-2026")
JWT_EXPIRE_DAYS = 7
