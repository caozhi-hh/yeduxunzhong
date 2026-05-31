# config.py - 豆包模型配置
import os

# 火山方舟 API 配置
ARK_API_KEY = os.environ.get("ARK_API_KEY", "")
ARK_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"

# 对话模型：豆包1.8（最强，256k上下文，支持工具调用）
CHAT_MODEL = "ep-m-20260421212710-7gf4b"

# 图片生成模型：Seedream 4.5
IMAGE_MODEL = "ep-m-20260423213453-2fw7b"

# 图片尺寸（Seedream 4.5 用 "2K" 格式）
IMAGE_SIZE = "2K"
