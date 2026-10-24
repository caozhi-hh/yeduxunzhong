# config.py - 模型配置（根目录/旧 Streamlit 入口使用）
#
# ⚠️ R2 安全整改（2026-10-23）：
# 本文件此前为 ZHIPU_API_KEY / ARK_API_KEY 提供了**硬编码兜底值**，而它已被 Git 跟踪，
# 等于把真实凭据写进了仓库（且随历史公开）。现已全部移除：
#   · 密钥只从环境变量读取，**没有任何默认值**；
#   · 缺失时抛 ConfigError，明确告知缺哪个变量，绝不退回硬编码密钥。
# 需要凭据时请配置到环境变量或本地 .env（不要提交）。
import os

# ==================== 代理绕过（2026-10-11 实测踩到）====================
# 本机 User 级环境变量残留 HTTP_PROXY/HTTPS_PROXY=http://127.0.0.1:7897，
# Clash 退出后仍然存在 → requests / httpx 全部 ProxyError（表现为"智谱调不通/图抓不到"）。
# 直连智谱与 Unsplash 都不需要代理，故强制绕过。
os.environ["NO_PROXY"] = "*"
os.environ["no_proxy"] = "*"


class ConfigError(RuntimeError):
    """缺少必要凭据。报错只给变量名与配置方式，不包含任何密钥内容。"""


def _secret(name: str) -> str:
    """只从环境变量读密钥，**没有默认值**。返回 "" 表示未配置。"""
    return os.environ.get(name, "").strip()


def require(name: str, *, for_feature: str) -> str:
    """取必需凭据；缺失则抛明确错误（而不是退回某个硬编码密钥）。"""
    value = _secret(name)
    if not value:
        raise ConfigError(
            f"缺少必需的环境变量 {name}（用于 {for_feature}）。"
            "请配置到 .env（本地）或部署平台的 Secrets（线上）；"
            "本项目不提供任何硬编码兜底密钥。"
        )
    return value


# ==================== 对话模型：智谱 GLM (Anthropic 协议端点) ====================
# 模型名与 base_url 不是凭据，保留可用默认值；密钥一律无兜底。
# 免费档用 glm-4-flash；充值后把 ZHIPU_MODEL 改成旗舰档即可，协议与 base_url 都不用动。
ZHIPU_API_KEY = _secret("ZHIPU_API_KEY")
ZHIPU_BASE_URL = os.environ.get("ZHIPU_BASE_URL", "https://open.bigmodel.cn/api/anthropic")
ZHIPU_MODEL = os.environ.get("ZHIPU_MODEL", "glm-4-flash")

# ==================== 图片生成模型：豆包 Seedream (火山方舟) ====================
# 密钥来自环境变量，无硬编码兜底。
ARK_API_KEY = _secret("ARK_API_KEY")
ARK_BASE_URL = os.environ.get("ARK_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3")
IMAGE_MODEL = os.environ.get("IMAGE_MODEL", "ep-m-20260423213453-2fw7b")
IMAGE_SIZE = os.environ.get("IMAGE_SIZE", "2K")