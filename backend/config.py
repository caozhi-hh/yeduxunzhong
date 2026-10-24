# config.py - 智谱 GLM 模型配置
import os
import secrets
from pathlib import Path

# ==================== 代理绕过（2026-10-11 实测踩到）====================
# 本机 User 级环境变量里残留 HTTP_PROXY/HTTPS_PROXY=http://127.0.0.1:7897，
# Clash 退出后这两个值仍然存在 → requests / httpx 全部 ProxyError，
# 表现为"智谱调不通""图抓不到"，但代码本身没问题。
# 本项目的部署目标（HF Spaces）与智谱/Unsplash 直连都不需要代理，故强制绕过。
# （与 xiaozhiAI 的 core/llm.py 同一套做法）
os.environ["NO_PROXY"] = "*"
os.environ["no_proxy"] = "*"

# ==================== 本地 .env 支持（2026-10-11 新增）====================
# 这个项目原先只读环境变量、没有 .env，导致本地填 key 很不方便。
# 现在支持 backend/.env；用 override=False 保证**已存在的环境变量优先**
# （HF Spaces 的 Secrets 不会被仓库里的 .env 覆盖）。
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent / ".env", override=False)
except Exception:
    pass  # 没装 python-dotenv 也不影响：直接读环境变量即可

# ==================== 凭据读取策略（R2 整改）====================
# 这里**不再提供任何硬编码的密钥兜底值**。
#
# 为什么必须去掉兜底：
#   1. 仓库里出现过的默认值已经随 git 历史公开（`backend/config.py`、根 `config.py`、
#      `frontend/.env.production` 都在历史里），留作兜底等于"继续使用已泄露的凭据"，
#      而且每次克隆都会把泄露面再扩散一次。
#   2. 忘了配置时会静默跑在一个失效 key 上，表现为难以定位的 401，
#      而不是"明确告诉你缺了哪个变量"。
#
# 现在的约定：密钥**只**从环境变量（含 backend/.env，先于本模块加载）读取；
# 缺失时 `require()` 抛 ConfigError，报错信息里只有**变量名**与用途，绝不回显任何值。
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
            "请配置到 backend/.env（本地）或部署平台的 Secrets（线上）；"
            "本项目不提供任何硬编码兜底密钥。"
        )
    return value


# 需要在启动日志里提醒的凭据（**只列变量名**，不涉及任何值）
WATCHED_SECRETS = ("ZHIPU_API_KEY", "UNSPLASH_ACCESS_KEY", "PIXABAY_API_KEY", "AMAP_WEB_KEY")


def missing_required() -> list[str]:
    """返回当前缺失的凭据变量名列表，供启动日志提示。"""
    return [n for n in WATCHED_SECRETS if not _secret(n)]


# 智谱 GLM 对话配置（Anthropic 协议端点）
# 说明：模型名与 base_url 不是凭据，保留可用的默认值；密钥一律无兜底。
# 免费档用 glm-4-flash；充值后把 CHAT_MODEL 改成旗舰档即可，协议与 base_url 都不用动。
ZHIPU_API_KEY = _secret("ZHIPU_API_KEY")
ZHIPU_BASE_URL = os.environ.get("ZHIPU_BASE_URL", "https://open.bigmodel.cn/api/anthropic")
CHAT_MODEL = os.environ.get("CHAT_MODEL", "glm-4-flash")

# Unsplash 图片搜索（真实景点照片；backend 不走 AI 生图）
UNSPLASH_ACCESS_KEY = _secret("UNSPLASH_ACCESS_KEY")

# ==================== Pixabay（推荐图源，2026-10-11 加入）====================
# 换它的原因（实测）：Unsplash 免费（Demo）档只有 **50 次/小时**
# （响应头 x-ratelimit-limit: 50，用尽后 403 "Rate Limit Exceeded"），
# 一次推荐就花 8–15 次 → 一小时只够 3–6 次使用，实测 9 个景点只配到 4 张图。
# Pixabay 免费档是 **100 次/60 秒（= 6000/小时，120 倍）**，且条款**要求/允许先把图片
# 下载到服务器再展示**（与 Unsplash 的 hotlink 相反）→ 落盘自托管，
# 顺带解决"国外 CDN 国内加载慢"，浏览器也能正常缓存。
# 取值地址：https://pixabay.com/api/docs/ （登录后页面上直接显示 key，免费）
# 填了就自动优先用 Pixabay，留空则回退 Unsplash。
PIXABAY_API_KEY = _secret("PIXABAY_API_KEY")

# 高德地图 Web 服务 API Key（用于地理编码；**无硬编码兜底**，缺失时相关接口明确报错）
AMAP_WEB_KEY = _secret("AMAP_WEB_KEY")

# ==================== JWT 认证 ====================
# 2026-10-10 安全修复：这里原本是一个硬编码的公开常量且已进 git，
# 任何人都能用它本地签发合法 token，冒充任意 user_id 读取他人攻略（账户体系级沦陷）。
# 现改为「环境变量优先 + 本地自动生成并持久化」：
#   1. 部署环境（HF Spaces）走 JWT_SECRET Secret
#   2. 本地首次运行生成 64 位随机密钥写入 backend/.jwt_secret（已加入 .gitignore），
#      之后重启复用 —— 避免"每次重启把用户全登出"
# ⚠️ 轮换后所有旧 token 立即失效，用户需要重新登录一次。
_JWT_SECRET_FILE = Path(__file__).resolve().parent / ".jwt_secret"


def _load_jwt_secret() -> str:
    """按「环境变量 → 本地密钥文件 → 新生成」顺序取得 JWT 签名密钥。"""
    from_env = os.environ.get("JWT_SECRET", "").strip()
    if from_env:
        return from_env

    try:
        if _JWT_SECRET_FILE.exists():
            stored = _JWT_SECRET_FILE.read_text(encoding="utf-8").strip()
            if len(stored) >= 32:
                return stored

        generated = secrets.token_hex(32)
        _JWT_SECRET_FILE.write_text(generated, encoding="utf-8")
        print(
            f"[config] 已生成新的本地 JWT 密钥 → {_JWT_SECRET_FILE.name}"
            "（生产环境请改用 JWT_SECRET 环境变量）"
        )
        return generated
    except OSError as exc:
        # 目录不可写（只读容器等）：退化为进程内随机密钥。服务不崩，但重启后需重新登录。
        print(f"[config][警告] 无法持久化 JWT 密钥（{exc}），本次使用进程内随机密钥，重启后需重新登录")
        return secrets.token_hex(32)


JWT_SECRET = _load_jwt_secret()
JWT_EXPIRE_DAYS = 7