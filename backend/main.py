# backend/main.py - FastAPI 后端
from fastapi import FastAPI, Depends, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse, JSONResponse
from pydantic import BaseModel, field_validator, model_validator, constr
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from tools.images import (
    generate_spot_image, extract_spots_from_text, extract_spot_details, geocode_spots,
    fetch_spot_images, images_dir, _download_to_cache,
)
from tools.export import export_to_word
from tools.search import get_weather
from tools.poi import search_places, nearby_places, looks_like_real_place
from tools import routing
from tools.photos import place_photos, place_photo_pool
from tools.websearch import web_search
from config import ZHIPU_API_KEY, ZHIPU_BASE_URL, CHAT_MODEL, AMAP_WEB_KEY, require, missing_required, ConfigError
from database import get_db, init_db
from auth import hash_password, verify_password, create_token, get_current_user
from history import save_plan, list_plans, get_plan, update_plan, update_plan_text, delete_plan as delete_plan_row
from trips import (
    create_trip, list_trips, get_trip, update_trip, delete_trip,
    add_day, delete_day, add_place, update_place, delete_place, move_place,
    # T1-D1 预算：费用 CRUD、预算设置与确定性汇总、金额/人数校验
    list_costs, add_cost, update_cost, delete_cost, update_trip_budget, compute_budget,
    yuan_to_cent, validate_travelers, COST_CATEGORIES, COST_STATUSES,
)
from prompts_en import SYSTEM_PROMPT_EN
from rate_limiter import auth_limiter, api_limiter
import json
import os
import math
import re
import html
import anyio
import requests as http_requests
from urllib.parse import urlparse

# ==================== Session 持久化 ====================
SESSION_DIR = os.path.join(os.path.dirname(__file__), "data", "sessions")
os.makedirs(SESSION_DIR, exist_ok=True)

app = FastAPI(title="野渡寻踪 API")

# ==================== 安全头中间件 ====================
@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    return response

# ==================== CORS ====================
# 2026-10-10 安全修复：原来是 allow_origins=["*"] + allow_credentials=True，
# 等于放行任意站点在受害者浏览器里带着其 JWT 调用本 API（CSRF / 数据外带）。
# 另外旧的 ALLOWED_ORIGINS 里 "https://yeduxunzhong-*.pages.dev" 是无效写法
# —— Starlette 的 allow_origins 不支持通配符，只有 allow_origin_regex 支持。
# Cloudflare Pages 的部署子域带随机 ID（如 41229068.yeduxunzhong.pages.dev），
# 因此用正则而不是枚举。
ALLOWED_ORIGIN_REGEX = (
    r"(?:https://(?:[a-z0-9-]+\.)*yeduxunzhong\.pages\.dev"
    r"|http://(?:localhost|127\.0\.0\.1)(?::\d+)?)"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[],  # 显式留空：只用下面的白名单正则，不再放行任意来源
    allow_origin_regex=ALLOWED_ORIGIN_REGEX,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ==================== 统一异常处理 ====================
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    # 避免泄露内部错误信息
    import traceback
    traceback.print_exc()  # 服务端日志保留完整错误
    return JSONResponse(
        status_code=500,
        content={"status": "error", "message": "服务器内部错误，请稍后重试"},
    )


@app.on_event("startup")
async def startup():
    await init_db()
    # R2：启动时只**列出缺失的变量名**（绝不打印任何值），让"忘了配"一眼可见。
    # 注意：缺失不影响后端启动 —— /trip、预算、地图、路线等功能不依赖这些凭据，
    # 只有用到对应能力时才会抛出明确的配置错误。
    missing = missing_required()
    if missing:
        print(f"[config] 未配置的凭据变量：{', '.join(missing)}"
              "（相关功能会在调用时给出明确配置错误；其余功能不受影响）")


# ==================== 输入清洗工具 ====================
def sanitize_text(text: str) -> str:
    """清洗用户输入，移除潜在危险字符"""
    if not text:
        return text
    # 去除首尾空白
    text = text.strip()
    # 转义 HTML
    text = html.escape(text, quote=False)
    # 移除控制字符（保留换行和制表符）
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)
    return text


# ==================== 可选认证（未登录也能用，登录后关联用户） ====================

async def optional_user(authorization: str = Header(None)) -> int:
    """返回 user_id，未登录返回 0"""
    if not authorization or not authorization.startswith("Bearer "):
        return 0
    try:
        return await get_current_user(authorization)
    except Exception:
        return 0


def client_ip(request: Request) -> str:
    """取真实客户端 IP，用于限流分桶。

    部署在 HF Spaces / Caddy 反代之后时 request.client.host 恒为代理地址，
    若直接用它，所有用户会共用同一个限流桶 —— 限流一旦生效就会误伤全部用户。
    因此优先读 X-Forwarded-For 首段，缺失时回落到 client.host。
    """
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        first = forwarded.split(",")[0].strip()
        if first:
            return first
    return request.client.host if request.client else "unknown"


# ==================== Auth 端点 ====================

class RegisterRequest(BaseModel):
    username: constr(min_length=2, max_length=20, pattern=r'^[a-zA-Z0-9_一-鿿]+$')
    password: constr(min_length=6, max_length=64)

    @field_validator('username')
    @classmethod
    def sanitize_username(cls, v: str) -> str:
        return sanitize_text(v)


class LoginRequest(BaseModel):
    username: constr(min_length=1, max_length=20)
    password: constr(min_length=1, max_length=64)

    @field_validator('username')
    @classmethod
    def sanitize_username(cls, v: str) -> str:
        return sanitize_text(v)


@app.post("/api/auth/register")
async def register(req: RegisterRequest, request: Request):
    # 速率限制
    client_ip = request.client.host if request.client else "unknown"
    auth_limiter.check(f"register:{client_ip}")

    username = req.username.strip()
    if not username:
        return {"status": "error", "message": "请输入用户名"}
    if len(req.password) < 6:
        return {"status": "error", "message": "密码至少6位"}

    db = await get_db()
    try:
        row = await db.execute_fetchall("SELECT id FROM users WHERE nickname=?", (username,))
        if row:
            return {"status": "error", "message": "用户名已存在"}

        pw_hash = hash_password(req.password)
        cursor = await db.execute(
            "INSERT INTO users (password_hash, nickname) VALUES (?, ?)",
            (pw_hash, username),
        )
        await db.commit()
        user_id = cursor.lastrowid
        token = create_token(user_id)
        return {"status": "ok", "user_id": user_id, "token": token, "nickname": username}
    finally:
        await db.close()


@app.post("/api/auth/login")
async def login(req: LoginRequest, request: Request):
    # 速率限制
    client_ip = request.client.host if request.client else "unknown"
    auth_limiter.check(f"login:{client_ip}")

    username = req.username.strip()
    db = await get_db()
    try:
        row = await db.execute_fetchall("SELECT id, password_hash, nickname FROM users WHERE nickname=?", (username,))
        if not row:
            return {"status": "error", "message": "用户名不存在"}

        user = dict(row[0])
        if not verify_password(req.password, user["password_hash"]):
            return {"status": "error", "message": "密码错误"}

        token = create_token(user["id"])
        return {"status": "ok", "user_id": user["id"], "token": token, "nickname": user["nickname"]}
    finally:
        await db.close()


@app.get("/api/auth/me")
async def me(user_id: int = Depends(get_current_user)):
    db = await get_db()
    try:
        row = await db.execute_fetchall("SELECT id, phone, email, nickname, created_at FROM users WHERE id=?", (user_id,))
        if not row:
            return {"status": "error", "message": "用户不存在"}
        user = dict(row[0])
        return {"status": "ok", "user": user}
    finally:
        await db.close()

# 直接用 LLM 流式输出（**延迟构造**）
#
# R2 安全整改：ZHIPU_API_KEY 不再有硬编码兜底。为了让"缺凭据"表现为
# **明确的配置错误**而不是整站起不来，这里改成首次用到 AI 时才构造客户端：
#   · 未配置 ZHIPU_API_KEY → 调用 AI 接口时抛 ConfigError（报错只含变量名）；
#   · /trip、预算、地图、路线等**不依赖 AI** 的功能照常可用。
_llm = None


def get_llm():
    """取（首次调用时构造）LLM 客户端；缺少凭据时给出明确配置错误。"""
    global _llm
    if _llm is None:
        require(
            "ZHIPU_API_KEY",
            for_feature="AI 攻略生成（/api/recommend、/api/generate-plan、/api/modify）",
        )
        _llm = ChatAnthropic(
            model=CHAT_MODEL,
            api_key=ZHIPU_API_KEY,
            base_url=ZHIPU_BASE_URL,
            streaming=True,
            max_tokens=4096,
        )
    return _llm

SYSTEM_PROMPT = """你是"野渡寻踪"的 AI 助手，专门为预算有限的旅行者生成个性化攻略。

你的工作流程（严格按照以下步骤执行）：

**重要：用户类型与票价优惠**
用户参数中有 user_type 字段，表示用户身份。不同身份享受不同优惠，你必须在所有涉及价格的地方体现：
- 学生：景区门票通常半价（需学生证），火车票硬座半价、高铁二等座7.5折
- 老人(60+)：大部分景区免票或半价
- 军人/退役军人：很多景区免票或有专属优惠
- 儿童(1.2m以下)：景区免票，火车免票（不占座）
- 成人：无特殊优惠，按全价计算

**第 1 步：推荐景点**
推荐该城市的 6-10 个大景点，按以下格式：

---
🏞️ **大景点名称**
🎫 门票：全价XX元 / 优惠价XX元
⏰ 游玩时长：X小时 | ⭐ 推荐指数：X星
📍 位置：XX区
📝 一句话描述
🔀 顺路可玩：附近景点/美食街（3-5个）
💡 游玩tips
---

然后生成门票预约总览表（含预约渠道、放票时间、是否必须预约）。

**第 2 步：生成详细攻略**
围绕每天景点生成极其详细的攻略：
- 时间精确到每 10-30 分钟
- 交通写明具体线路（地铁几号线/公交几路/打车价格）
- 餐饮写明具体店名+菜名+人均价格
- 景点内部也要规划路线
- 每天费用明细表
- 避坑提醒和备选方案

**路线核心原则：绝对不走回头路！**
- 每天景点按地理位置单向排列
- 同一天活动在同一区域
- 住宿在当天终点和明天起点之间

**第 3 步：修改调整**
根据用户反馈灵活调整行程。"""

# 全局会话存储
sessions = {}


def _sys_prompt(lang: str) -> str:
    return SYSTEM_PROMPT_EN if lang == "en" else SYSTEM_PROMPT


def _session_path(session_id: str) -> str:
    safe_id = "".join(c for c in session_id if c.isalnum() or c in "-_")[:64]
    return os.path.join(SESSION_DIR, f"{safe_id}.json")


def _save_session(session_id: str):
    """将 session 写入 JSON 文件，下次服务器重启可恢复。"""
    data = sessions.get(session_id)
    if not data:
        return
    try:
        save_data = {k: v for k, v in data.items() if k != "messages"}
        save_data["messages_count"] = len(data.get("messages", []))
        with open(_session_path(session_id), "w", encoding="utf-8") as f:
            json.dump(save_data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[session] 保存失败: {e}")


def get_session(session_id: str):
    if session_id not in sessions:
        sessions[session_id] = {"messages": [], "plan": "", "recommendation": "", "params": {}}
        # 尝试从文件恢复
        path = _session_path(session_id)
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                sessions[session_id]["plan"] = saved.get("plan", "")
                sessions[session_id]["recommendation"] = saved.get("recommendation", "")
                sessions[session_id]["params"] = saved.get("params", {})
            except:
                pass
    return sessions[session_id]


class RecommendRequest(BaseModel):
    params: dict
    session_id: str = "default"
    language: str = "zh"

    @field_validator('session_id')
    @classmethod
    def validate_session_id(cls, v: str) -> str:
        # 限制 session_id 格式
        if not re.match(r'^[a-zA-Z0-9_-]{1,64}$', v):
            return "default"
        return v

    @field_validator('params')
    @classmethod
    def validate_params(cls, v: dict) -> dict:
        # 清洗 params 中的字符串值
        for key, val in v.items():
            if isinstance(val, str):
                v[key] = sanitize_text(val)[:500]  # 限制长度
        return v


class PlanRequest(BaseModel):
    session_id: str = "default"
    spots: list
    language: str = "zh"

    @field_validator('session_id')
    @classmethod
    def validate_session_id(cls, v: str) -> str:
        if not re.match(r'^[a-zA-Z0-9_-]{1,64}$', v):
            return "default"
        return v

    @field_validator('spots')
    @classmethod
    def validate_spots(cls, v: list) -> list:
        if len(v) > 20:
            raise ValueError("最多选择20个景点")
        return [sanitize_text(str(s))[:100] for s in v]


class ModifyRequest(BaseModel):
    session_id: str = "default"
    message: str
    preview: bool = False
    language: str = "zh"

    @field_validator('session_id')
    @classmethod
    def validate_session_id(cls, v: str) -> str:
        if not re.match(r'^[a-zA-Z0-9_-]{1,64}$', v):
            return "default"
        return v

    @field_validator('message')
    @classmethod
    def validate_message(cls, v: str) -> str:
        if len(v) > 2000:
            raise ValueError("消息不能超过2000字")
        return sanitize_text(v)


class ImageRequest(BaseModel):
    spot_name: str
    city: str = ""

    @field_validator('spot_name', 'city')
    @classmethod
    def sanitize_fields(cls, v: str) -> str:
        return sanitize_text(v)[:100]


class ExportRequest(BaseModel):
    plan_text: str
    session_id: str = "default"


def stream_llm(messages: list, max_retries: int = 2):
    """统一的 LLM 流式输出，带重试机制"""
    for attempt in range(max_retries + 1):
        full_response = ""
        try:
            for chunk in get_llm().stream(messages):
                if chunk.content:
                    full_response += chunk.content
                    yield f"data: {json.dumps({'type': 'chunk', 'content': chunk.content}, ensure_ascii=False)}\n\n"
            # 正常完成
            print(f"[stream_llm] 完成, 总长度: {len(full_response)}")
            return full_response
        except Exception as e:
            print(f"[stream_llm] 第{attempt+1}次尝试异常: {e}")
            # R2：配置缺失不是"网络波动"，重试没有意义，直接明确报告（只含变量名，不含密钥）
            if isinstance(e, ConfigError):
                yield f"data: {json.dumps({'type': 'error', 'content': str(e)}, ensure_ascii=False)}\n\n"
                return full_response
            if attempt < max_retries and len(full_response) < 200:
                # 输出太短，可能是 API 不稳定，重试
                print(f"[stream_llm] 输出太短({len(full_response)}字符)，重试...")
                # 先把已有的短内容撤回提示（前端会显示）
                _retry_msg = "\n\n⏳ 网络波动，正在重试..."
                yield f"data: {json.dumps({'type': 'chunk', 'content': _retry_msg}, ensure_ascii=False)}\n\n"
                continue
            else:
                yield f"data: {json.dumps({'type': 'error', 'content': str(e)}, ensure_ascii=False)}\n\n"
                return full_response
    return full_response


@app.post("/api/recommend")
async def recommend(req: RecommendRequest, request: Request, user_id: int = Depends(optional_user)):
    api_limiter.check(f"api:recommend:{client_ip(request)}")
    params = req.params
    session = get_session(req.session_id)

    dep = params.get('dep_datetime', '')
    ret = params.get('ret_datetime', '')
    from_city = params.get('from_city', '')
    to_city = params.get('to_city', '')

    prompt = f"""请推荐{to_city}的 8-10 个热门景点，按地理位置分组排列。

严格按以下格式输出，每个景点只输出4行，不要添加任何额外内容（不要写开头语、总结、提醒等）：

---
🏞️ **景点名**
🎫 门票：XX元 | ⏰ X小时 | ⭐ X/5
📝 一句话描述这个景点最核心的游玩体验
---

用户参数：{params.get('days',3)}天、预算{params.get('budget',3000)}元/人、{params.get('user_type','成人')}身份、{params.get('travel_type','性价比出行')}风格。"""

    # 查询目的地天气，注入 prompt
    weather_info = get_weather(to_city)
    if not weather_info.startswith("天气查询失败"):
        prompt += f"\n\n**目的地实时天气：**\n{weather_info}\n请在推荐中给出穿衣建议和天气注意事项。"

    messages = [SystemMessage(content=_sys_prompt(req.language)), HumanMessage(content=prompt)]
    session["messages"] = messages
    session["params"] = params

    def stream():
        full_response = yield from stream_llm(messages)
        session["messages"].append(AIMessage(content=full_response))
        session["recommendation"] = full_response
        _save_session(req.session_id)
        spots = extract_spots_from_text(full_response)
        spot_details = extract_spot_details(full_response)
        coords = geocode_spots(spots, to_city)
        yield f"data: {json.dumps({'type': 'done', 'spots': spots, 'spot_details': spot_details, 'coords': coords}, ensure_ascii=False)}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")


@app.post("/api/generate-plan")
async def generate_plan(req: PlanRequest, request: Request, user_id: int = Depends(optional_user)):
    api_limiter.check(f"api:generate-plan:{client_ip(request)}")
    session = get_session(req.session_id)
    params = session.get("params", {})

    dep = params.get('dep_datetime', '')
    ret = params.get('ret_datetime', '')
    from_city = params.get('from_city', '')
    to_city = params.get('to_city', '')
    budget = params.get('budget', 3000)
    user_type = params.get('user_type', '成人')
    travel_type = params.get('travel_type', '性价比出行')
    transport_go = params.get('transport_go', '高铁')
    transport_back = params.get('transport_back', '高铁')
    accommodation = params.get('accommodation', '经济酒店')
    companions = params.get('companions_count', 1)
    companion_type = params.get('companion_type', '独自出行')

    prompt = f"""我选好了以下景点：{', '.join(req.spots)}

请根据以下信息帮我安排详细行程攻略：
- 出发城市：{from_city}，目的城市：{to_city}
- 到达日期：{dep}，返程日期：{ret}
- 预算：{budget}元/人，用户类型：{user_type}（注意在门票价格中体现优惠）
- 交通：去程{transport_go}，返程{transport_back}
- 住宿：{accommodation}
- 同行：{companions}人，{companion_type}

**必须包含以下内容：**

1. **门票预约提醒**（放在最前面）
针对每个需要预约的景点，写明：
- **具体预约时间**：例如"4月24日20:00开始预约5月1日的天安门门票"
- 预约渠道（微信小程序名/APP名）
- 提前几天放票
- 紧急程度

2. **每日详细行程**
- 时间精确到每 10-30 分钟
- 交通写明具体线路（地铁几号线/公交几路/打车价格）
- 餐饮写明具体店名+菜名+人均价格
- 景点内部游览路线
- 每天费用明细表

3. **注意事项**（放在最后）
- 安全提醒（贵重物品、人流密集处注意防盗）
- 天气提醒（建议带什么衣物、雨具）
- 当地风俗禁忌
- 紧急联系电话（当地报警、急救、旅游投诉电话）
- 常见骗局和避坑提醒
- 特殊人群注意事项（如果用户类型是学生/老人/儿童，给出对应提醒）

**路线核心原则：绝对不走回头路！**
- 每天景点按地理位置单向排列
- 同一天活动在同一区域"""

    # 查询目的地天气，注入 prompt
    weather_info = get_weather(to_city)
    if not weather_info.startswith("天气查询失败"):
        prompt += f"\n\n**目的地实时天气：**\n{weather_info}\n请在攻略中根据天气给出穿衣建议、雨天备选方案。"

    messages = [SystemMessage(content=_sys_prompt(req.language)), HumanMessage(content=prompt)]
    session["messages"] = messages

    def stream():
        full_response = yield from stream_llm(messages)
        session["plan"] = full_response
        session["messages"].append(AIMessage(content=full_response))
        _save_session(req.session_id)
        yield f"data: {json.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")


@app.post("/api/modify")
async def modify(req: ModifyRequest, request: Request, user_id: int = Depends(optional_user)):
    api_limiter.check(f"api:modify:{client_ip(request)}")
    session = get_session(req.session_id)

    if req.preview:
        # preview 模式：只返回简短方案摘要，不修改攻略
        context = (
            f"当前攻略内容：\n{session.get('plan', '')[:3000]}\n\n"
            f"用户修改要求：{req.message}\n\n"
            "⚠️ 你现在只需要给出修改方案的简短摘要（3-5句话），告诉用户你打算怎么改。"
            "不要输出完整的攻略细节，只说大致调整思路。"
            "例如：'我会将Day2的XX景点移到Day1下午，Day2改为游览YY和ZZ，预算节省约XX元。'"
        )
    else:
        # apply 模式：输出完整修改后的攻略
        context = (
            f"当前攻略内容：\n{session.get('plan', '')[:4000]}\n\n"
            f"用户确认了以下修改方案，请执行并输出完整的新攻略：{req.message}\n\n"
            "⚠️ 输出修改后的完整攻略（包含未修改的天和修改过的天）。"
            "保持原有攻略的格式和详细程度，只调整用户要求的部分。"
        )

    messages = [SystemMessage(content=_sys_prompt(req.language)), HumanMessage(content=context)]
    session["messages"] = messages

    def stream():
        full_response = yield from stream_llm(messages)
        if not req.preview:
            session["plan"] = full_response
            session["messages"].append(AIMessage(content=full_response))
            _save_session(req.session_id)
        yield f"data: {json.dumps({'type': 'done', 'preview': req.preview}, ensure_ascii=False)}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")


@app.post("/api/generate-image")
async def generate_image(req: ImageRequest):
    result = generate_spot_image(req.spot_name, req.city)
    return result


def _build_word(params: dict, plan_text: str):
    itinerary = {
        "title": "旅行攻略",
        "overview": plan_text,
        "dep_date": params.get("dep_datetime", ""),
        "ret_date": params.get("ret_datetime", ""),
        "budget_total": params.get("budget", ""),
        "user_type": params.get("user_type", ""),
        "from_city": params.get("from_city", ""),
        "to_city": params.get("to_city", ""),
    }
    filepath = export_to_word(itinerary)
    return FileResponse(filepath, filename=os.path.basename(filepath))


@app.post("/api/export-word")
async def export_word_post(req: ExportRequest):
    session = get_session(req.session_id)
    return _build_word(session.get("params", {}), req.plan_text)


@app.get("/api/export-word")
async def export_word_get(session_id: str = "default", title: str = "旅行攻略"):
    session = get_session(session_id)
    params = session.get("params", {})
    plan_text = session.get("plan", "")
    return _build_word(params, plan_text)


class GeocodeRequest(BaseModel):
    spots: list
    city: str = ""

    @field_validator('spots')
    @classmethod
    def validate_spots(cls, v: list) -> list:
        if len(v) > 20:
            raise ValueError("最多20个景点")
        return [sanitize_text(str(s))[:100] for s in v]

    @field_validator('city')
    @classmethod
    def sanitize_city(cls, v: str) -> str:
        return sanitize_text(v)[:50]


@app.post("/api/geocode")
async def geocode(req: GeocodeRequest, request: Request):
    """将景点名列表转换为经纬度，使用高德地理编码 API。"""
    api_limiter.check(f"api:geocode:{client_ip(request)}")
    if not AMAP_WEB_KEY:
        return {"status": "error", "message": "未配置高德地图 API Key"}

    results = []
    for spot_name in req.spots:
        try:
            address = f"{req.city}{spot_name}" if req.city else spot_name
            resp = requests.get(
                "https://restapi.amap.com/v3/geocode/geo",
                params={"address": address, "key": AMAP_WEB_KEY, "output": "JSON"},
                timeout=8,
            )
            resp.raise_for_status()
            data = resp.json()
            geocodes = data.get("geocodes", [])
            if geocodes:
                loc = geocodes[0].get("location", "")
                if loc:
                    lng, lat = loc.split(",")
                    results.append({
                        "name": spot_name,
                        "lng": float(lng),
                        "lat": float(lat),
                        "formatted_address": geocodes[0].get("formatted_address", ""),
                    })
                    continue
            results.append({"name": spot_name, "lng": 0, "lat": 0, "formatted_address": ""})
        except Exception:
            results.append({"name": spot_name, "lng": 0, "lat": 0, "formatted_address": ""})

    return {"status": "ok", "spots": results}


# ==================== History 端点 ====================

class SavePlanRequest(BaseModel):
    plan_id: int | None = None   # 带 id 表示就地更新（避免同一攻略刷屏式新增）
    title: str = ""
    from_city: str = ""
    to_city: str = ""
    days: int = 3
    budget: int = 3000
    travel_type: str = ""
    user_type: str = ""
    dep_date: str = ""
    ret_date: str = ""
    spots: list = []
    recommendation: str = ""
    plan_text: str = ""
    params: dict = {}

    @field_validator('title', 'from_city', 'to_city')
    @classmethod
    def sanitize_strings(cls, v: str) -> str:
        return sanitize_text(v)[:200]

    @field_validator('days')
    @classmethod
    def validate_days(cls, v: int) -> int:
        if v < 1 or v > 30:
            return 3
        return v

    @field_validator('budget')
    @classmethod
    def validate_budget(cls, v: int) -> int:
        if v < 0 or v > 1000000:
            return 3000
        return v


@app.get("/api/history")
async def api_list_history(user_id: int = Depends(get_current_user)):
    plans = await list_plans(user_id)
    return {"status": "ok", "plans": plans}


@app.post("/api/history")
async def api_save_history(req: SavePlanRequest, user_id: int = Depends(get_current_user)):
    # 带 plan_id → 就地更新同一条（对话里每改一版只回写，不再新增）
    if req.plan_id:
        updated = await update_plan(user_id, req.plan_id, req.model_dump())
        if updated:
            return {"status": "ok", "plan_id": req.plan_id, "updated": True}
        # 归属不符或该记录已被删除 → 退回新增，保证用户的改动不会丢
    plan_id = await save_plan(user_id, req.model_dump())
    return {"status": "ok", "plan_id": plan_id, "updated": False}


@app.get("/api/history/{plan_id}")
async def api_get_history(plan_id: int, user_id: int = Depends(get_current_user)):
    plan = await get_plan(plan_id, user_id)
    if not plan:
        return {"status": "error", "message": "攻略不存在"}
    return {"status": "ok", "plan": plan}


@app.delete("/api/history/{plan_id}")
async def api_delete_history(plan_id: int, user_id: int = Depends(get_current_user)):
    ok = await delete_plan_row(plan_id, user_id)
    if not ok:
        return {"status": "error", "message": "删除失败"}
    return {"status": "ok"}



# ==================== 真实地点（POI）====================
# 这一层是"把景点从模型编造换成查真实数据"的关键，全部免 key
# （Photon 搜索 + Overpass 附近 POI）。参考项目共同的做法：
# 真实数据提供事实，模型只负责组织与建议。

class PoiSearchRequest(BaseModel):
    query: str
    limit: int = 8
    near_lat: float | None = None
    near_lon: float | None = None
    max_km: float = 0        # >0 时丢弃离 near 超过该距离的结果（防"搜到大阪的大昭寺"）
    city: str = ""           # 用于给照片搜索补地理上下文（实测裸名字搜出的图大量不可用）

    @field_validator('query')
    @classmethod
    def validate_query(cls, v: str) -> str:
        return sanitize_text(v)[:60]


class PoiNearbyRequest(BaseModel):
    lat: float
    lon: float
    radius: int = 3000
    limit: int = 20


class PoiPhotosRequest(PoiSearchRequest):
    """候选图片池请求（T1：九宫格动态补位用）。

    单独继承而不是给 PoiSearchRequest 加字段：`offset` 只对取图有意义，
    塞进搜索请求会把两个契约混在一起。
    """
    offset: int = 0


@app.post("/api/poi/search")
async def api_poi_search(req: PoiSearchRequest, request: Request):
    """按名字搜真实地点（免 key）。

    返回带经纬度的真实地点，供前端"加入某一天"使用；
    模型给出的景点名也可以先过这里校验存不存在。
    """
    if not req.query.strip():
        return {"status": "ok", "places": []}
    api_limiter.check(f"api:poi-search:{client_ip(request)}")
    near = ((req.near_lat, req.near_lon)
            if req.near_lat is not None and req.near_lon is not None else None)
    # requests 是同步 IO，必须丢进线程（HF 免费档只有 1 个 worker）
    try:
        places = await anyio.to_thread.run_sync(
            lambda: search_places(req.query, req.limit, near, req.max_km)
        )
    except Exception as exc:  # noqa: BLE001
        # T1-E2：搜索失败必须是**可读的降级**，不能整站 500。
        # 重新定位依赖这个接口；上游搜索服务不可用时，前端要能显示
        # "搜索失败，原坐标保持不变"并允许重试，而不是让页面崩掉。
        print(f"[poi] search 失败: {type(exc).__name__}: {exc}")
        return JSONResponse(
            status_code=200,
            content={
                "status": "error",
                "places": [],
                "message": f"地点搜索暂时不可用（{type(exc).__name__}），请稍后重试",
            },
        )
    return {"status": "ok", "places": places}


@app.post("/api/poi/nearby")
async def api_poi_nearby(req: PoiNearbyRequest, request: Request):
    """查某个坐标附近的景点类 POI（Overpass，免 key）。"""
    api_limiter.check(f"api:poi-nearby:{client_ip(request)}")
    places = await anyio.to_thread.run_sync(
        lambda: nearby_places(req.lat, req.lon, req.radius, req.limit)
    )
    return {"status": "ok", "places": places}


@app.post("/api/poi/verify")
async def api_poi_verify(req: PoiSearchRequest, request: Request):
    """校验一个「景点名」在真实数据里存不存在。

    用途是做**机械校验**：模型给出的景点如果查不到，前端就该标出来，
    而不是当成真景点直接展示（Migo 的 validate.js、见好的 checklist.py 都是这个思路）。
    """
    api_limiter.check(f"api:poi-verify:{client_ip(request)}")
    result = await anyio.to_thread.run_sync(
        lambda: looks_like_real_place(req.query, "")
    )
    return {"status": "ok", **result}


# ==================== 结构化行程 ====================
# 与 /api/history 的区别：history 存的是「一整篇攻略文本」，这里存的是**可编辑的行程实体**
# （行程 → 每天 → 地点）。地点带经纬度，所以地图能画、能拖拽换天、能改时段。

class TripCreateRequest(BaseModel):
    title: str = ""
    city: str = ""
    days: int = 3
    start_date: str = ""
    end_date: str = ""


class TripUpdateRequest(BaseModel):
    title: str | None = None
    city: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    note: str | None = None


# ==================== 预算 / 费用请求模型（T1-D1）====================
# 金额校验策略：金额一律在**服务端**做区间与类型校验（前端校验只是体验优化）。
# 金额以"元"从前端提交（用户看到的就是元），服务端立刻转成整数分存储与计算。

class TripBudgetRequest(BaseModel):
    """设置整趟旅行的总预算上限与人数。

    ⚠️ 语义提醒：这是**整趟旅行的总预算**，不是人均预算。
    旧链路 plans.budget 是"人均"语义且与行程无关，两者不可混用。
    """
    budget_total_yuan: float | None = None   # None = 清空预算上限
    travelers: int | None = None

    @field_validator('travelers')
    @classmethod
    def check_travelers(cls, v):
        if v is None:
            return None
        try:
            return validate_travelers(v)
        except ValueError as exc:
            raise ValueError(str(exc)) from exc

    @field_validator('budget_total_yuan')
    @classmethod
    def check_budget(cls, v):
        if v is None:
            return None
        try:
            yuan_to_cent(v)          # 只做校验；转换在路由里做并保留分
        except ValueError as exc:
            raise ValueError(str(exc)) from exc
        return v


class CostCreateRequest(BaseModel):
    """新增一条费用。amount_yuan 表示**该条费用的总金额**（不是人均）。"""
    category: str = "other"
    title: str = ""
    amount_yuan: float
    status: str = "estimated"
    note: str = ""
    day_id: int | None = None
    place_id: int | None = None
    # 幂等键：同一次用户提交用同一个 token，重复请求不会产生第二条费用
    client_token: str | None = None

    @field_validator('category')
    @classmethod
    def check_category(cls, v: str) -> str:
        if v not in COST_CATEGORIES:
            raise ValueError(f"分类非法，可选：{'/'.join(COST_CATEGORIES)}")
        return v

    @field_validator('status')
    @classmethod
    def check_status(cls, v: str) -> str:
        if v not in COST_STATUSES:
            raise ValueError(f"状态非法，可选：{'/'.join(COST_STATUSES)}")
        return v

    @field_validator('title', 'note')
    @classmethod
    def clean_text(cls, v: str) -> str:
        return sanitize_text(v or "")

    @field_validator('amount_yuan')
    @classmethod
    def check_amount(cls, v):
        yuan_to_cent(v)              # 拒绝负数/NaN/无穷/非法输入
        return v


class CostUpdateRequest(BaseModel):
    """编辑一条费用：只改传进来的字段。"""
    category: str | None = None
    title: str | None = None
    amount_yuan: float | None = None
    status: str | None = None
    note: str | None = None
    day_id: int | None = None
    place_id: int | None = None

    @field_validator('category')
    @classmethod
    def check_category(cls, v):
        if v is None:
            return None
        if v not in COST_CATEGORIES:
            raise ValueError(f"分类非法，可选：{'/'.join(COST_CATEGORIES)}")
        return v

    @field_validator('status')
    @classmethod
    def check_status(cls, v):
        if v is None:
            return None
        if v not in COST_STATUSES:
            raise ValueError(f"状态非法，可选：{'/'.join(COST_STATUSES)}")
        return v

    @field_validator('amount_yuan')
    @classmethod
    def check_amount(cls, v):
        if v is None:
            return None
        yuan_to_cent(v)
        return v

    @field_validator('title', 'note')
    @classmethod
    def clean_text(cls, v):
        return None if v is None else sanitize_text(v)


class PlaceCreateRequest(BaseModel):
    name: str
    lat: float | None = None
    lon: float | None = None
    address: str = ""
    kind: str = ""
    source: str = "openstreetmap"
    source_url: str = ""
    start_time: str = ""
    duration_min: int = 0
    note: str = ""

    @field_validator('name')
    @classmethod
    def validate_name(cls, v: str) -> str:
        return sanitize_text(v)[:80]

    @field_validator('lon')
    @classmethod
    def check_lon(cls, v):
        """经度必须是有限数且在 -180~180（T1-E1）。

        越界值会让地图直接抛错或把视野拉爆，所以在接口层就拒掉（422），
        而不是先落库再让前端去容错。缺坐标允许为 None —— 前端显示"缺少坐标"状态。
        """
        if v is None:
            return None
        if not math.isfinite(v):
            raise ValueError("坐标必须是有限数值")
        if not -180.0 <= v <= 180.0:
            raise ValueError("经度必须在 -180 ~ 180 之间")
        return v

    @field_validator('lat')
    @classmethod
    def check_lat(cls, v):
        if v is None:
            return None
        if not math.isfinite(v):
            raise ValueError("坐标必须是有限数值")
        if not -90.0 <= v <= 90.0:
            raise ValueError("纬度必须在 -90 ~ 90 之间")
        return v


class PlaceUpdateRequest(BaseModel):
    name: str | None = None
    lat: float | None = None
    lon: float | None = None
    address: str | None = None
    kind: str | None = None
    start_time: str | None = None
    duration_min: int | None = None
    note: str | None = None

    @field_validator('lon')
    @classmethod
    def check_lon(cls, v):
        if v is None:
            return None
        if not math.isfinite(v):
            raise ValueError("坐标必须是有限数值")
        if not -180.0 <= v <= 180.0:
            raise ValueError("经度必须在 -180 ~ 180 之间")
        return v

    @field_validator('lat')
    @classmethod
    def check_lat(cls, v):
        if v is None:
            return None
        if not math.isfinite(v):
            raise ValueError("坐标必须是有限数值")
        if not -90.0 <= v <= 90.0:
            raise ValueError("纬度必须在 -90 ~ 90 之间")
        return v

    @model_validator(mode='after')
    def check_coords_paired(self):
        """坐标必须成对给且都不能为 null（T1-E2）。

        为什么要有这条：只提交一半或提交 null 会被数据层的
        「None 值过滤」静默丢掉 —— 接口返回 200 看起来成功，实际什么都没改，
        属于"假装成功"。所以在接口层直接拒绝，让调用方知道请求没被接受。
        """
        present = {k for k in ("lat", "lon") if k in self.model_fields_set}
        if not present:
            return self
        if present != {"lat", "lon"}:
            raise ValueError("lat 与 lon 必须同时提供")
        if self.lat is None or self.lon is None:
            raise ValueError("lat 与 lon 不能为 null（本接口不支持清空坐标）")
        return self


class MovePlaceRequest(BaseModel):
    to_day_id: int
    to_index: int = 0


@app.get("/api/trips")
async def api_list_trips(user_id: int = Depends(get_current_user)):
    return {"status": "ok", "trips": await list_trips(user_id)}


@app.post("/api/trips")
async def api_create_trip(req: TripCreateRequest, user_id: int = Depends(get_current_user)):
    trip_id = await create_trip(user_id, sanitize_text(req.title)[:60], sanitize_text(req.city)[:30],
                                req.days, req.start_date[:20], req.end_date[:20])
    return {"status": "ok", "trip_id": trip_id}


@app.get("/api/trips/{trip_id}")
async def api_get_trip(trip_id: int, user_id: int = Depends(get_current_user)):
    trip = await get_trip(trip_id, user_id)
    if not trip:
        raise HTTPException(status_code=404, detail="行程不存在")
    return {"status": "ok", "trip": trip}


@app.patch("/api/trips/{trip_id}")
async def api_update_trip(trip_id: int, req: TripUpdateRequest, user_id: int = Depends(get_current_user)):
    ok = await update_trip(trip_id, user_id, req.model_dump(exclude_none=True))
    if not ok:
        raise HTTPException(status_code=404, detail="行程不存在")
    return {"status": "ok"}


@app.delete("/api/trips/{trip_id}")
async def api_delete_trip(trip_id: int, user_id: int = Depends(get_current_user)):
    ok = await delete_trip(trip_id, user_id)
    if not ok:
        raise HTTPException(status_code=404, detail="行程不存在")
    return {"status": "ok"}


@app.post("/api/trips/{trip_id}/days")
async def api_add_day(trip_id: int, user_id: int = Depends(get_current_user)):
    day_id = await add_day(trip_id, user_id)
    if day_id is None:
        raise HTTPException(status_code=404, detail="行程不存在")
    return {"status": "ok", "day_id": day_id}


@app.delete("/api/trips/days/{day_id}")
async def api_delete_day(day_id: int, user_id: int = Depends(get_current_user)):
    if not await delete_day(day_id, user_id):
        raise HTTPException(status_code=404, detail="日程不存在")
    return {"status": "ok"}


@app.post("/api/trips/days/{day_id}/places")
async def api_add_place(day_id: int, req: PlaceCreateRequest, user_id: int = Depends(get_current_user)):
    place_id = await add_place(day_id, user_id, req.model_dump())
    if place_id is None:
        raise HTTPException(status_code=404, detail="日程不存在")
    return {"status": "ok", "place_id": place_id}


@app.patch("/api/trips/places/{place_id}")
async def api_update_place(place_id: int, req: PlaceUpdateRequest, user_id: int = Depends(get_current_user)):
    if not await update_place(place_id, user_id, req.model_dump(exclude_none=True)):
        raise HTTPException(status_code=404, detail="地点不存在")
    return {"status": "ok"}


@app.delete("/api/trips/places/{place_id}")
async def api_delete_place(place_id: int, user_id: int = Depends(get_current_user)):
    if not await delete_place(place_id, user_id):
        raise HTTPException(status_code=404, detail="地点不存在")
    return {"status": "ok"}


@app.post("/api/trips/places/{place_id}/move")
async def api_move_place(place_id: int, req: MovePlaceRequest, user_id: int = Depends(get_current_user)):
    """拖拽落地的后端：把地点移到另一天或同一天内的新位置。"""
    if not await move_place(place_id, user_id, req.to_day_id, req.to_index):
        raise HTTPException(status_code=404, detail="地点或目标日程不存在")
    return {"status": "ok"}


# ==================== 真实道路路线（T1-F1）====================
# 设计要点：
#   * **纯查询**：只读行程与景点，不改顺序、不写库（无任何 INSERT/UPDATE）。
#   * 按 `day_index` 取当天景点，**保持用户编排的 sort_order**。
#   * 供应商逻辑全在 tools/routing.py，这里只做鉴权、参数校验与转发
#     —— 这样换小程序端也能直接复用同一接口。
#   * 缺坐标的景点被跳过并逐个报告原因，不会伪造坐标、也不会让整个请求失败。

@app.get("/api/trips/{trip_id}/route")
async def api_trip_route(
    trip_id: int,
    day_index: int = 0,
    mode: str = "driving",
    user_id: int = Depends(get_current_user),
):
    """取某一天的真实道路路线（几何 + 分段距离/耗时 + 当日汇总）。"""
    if day_index < 0 or day_index > 29:
        raise HTTPException(status_code=422, detail="day_index 需在 0–29 之间")
    if mode not in routing.SUPPORTED_MODES:
        raise HTTPException(
            status_code=422,
            detail=f"mode 非法，可选：{'/'.join(routing.SUPPORTED_MODES)}",
        )

    trip = await get_trip(trip_id, user_id)      # 内含 WHERE user_id = ? 的归属校验
    if not trip:
        raise HTTPException(status_code=404, detail="行程不存在")

    days = trip.get("days") or []
    if day_index >= len(days):
        raise HTTPException(status_code=422, detail=f"该行程没有第 {day_index + 1} 天")

    day = days[day_index]
    stops = [
        {
            "place_id": p.get("id"),
            "name": p.get("name") or "",
            "lat": p.get("lat"),
            "lon": p.get("lon"),
        }
        for p in (day.get("places") or [])
    ]

    # 计算是同步阻塞 IO（requests/urllib），必须丢进线程，别堵事件循环
    plan = await anyio.to_thread.run_sync(
        lambda: routing.plan_day(stops, mode=mode)
    )
    return {
        "status": "ok",
        "trip_id": trip_id,
        "day_index": day_index,
        "day_id": day.get("id"),
        "date": day.get("date") or "",
        "place_count": len(stops),
        "route": plan,
    }


# ==================== 预算 / 费用端点（T1-D1）====================
# 设计要点：
#   * 所有操作都先确认"这趟行程属于当前用户"（trips.py 内做 JOIN 校验），
#     不属于就 404 —— 猜 id 也读不到、改不了别人的账。
#   * 合计一律由 compute_budget() 在服务端用整数分算出来，前端只负责展示。
#   * 不存储任何可计算得出的合计，避免出现"两处数字对不上"。

def _bad_request(message: str) -> HTTPException:
    """金额/人数等**输入**问题用 422（区别于 404 的"没有权限或不存在"）。"""
    return HTTPException(status_code=422, detail=message)


@app.get("/api/trips/{trip_id}/budget")
async def api_get_trip_budget(trip_id: int, user_id: int = Depends(get_current_user)):
    """一次拿全：费用明细 + 预算汇总（前端一次渲染，不用自己加总）。"""
    costs = await list_costs(trip_id, user_id)
    if costs is None:
        raise HTTPException(status_code=404, detail="行程不存在")
    summary = await compute_budget(trip_id, user_id)
    if summary is None:
        raise HTTPException(status_code=404, detail="行程不存在")
    return {"status": "ok", "costs": costs, "budget": summary,
            "categories": COST_CATEGORIES, "statuses": COST_STATUSES}


@app.patch("/api/trips/{trip_id}/budget")
async def api_set_trip_budget(trip_id: int, req: TripBudgetRequest,
                             user_id: int = Depends(get_current_user)):
    """设置**整趟旅行总预算**与人数。

    只传一个字段时另一个保持不变；显式传 budget_total_yuan=null 表示清空预算上限。
    """
    body = req.model_dump(exclude_unset=True)
    try:
        travelers = body.get("travelers")          # 校验已由 TripBudgetRequest 完成
        budget_cent = (None if "budget_total_yuan" not in body
                       else yuan_to_cent(body["budget_total_yuan"], allow_none=True))
    except ValueError as exc:
        raise _bad_request(str(exc)) from exc

    if not await update_trip_budget(trip_id, user_id, travelers, budget_cent):
        raise HTTPException(status_code=404, detail="行程不存在")
    summary = await compute_budget(trip_id, user_id)
    return {"status": "ok", "budget": summary}


@app.post("/api/trips/{trip_id}/costs")
async def api_add_cost(trip_id: int, req: CostCreateRequest,
                       user_id: int = Depends(get_current_user)):
    """新增一条费用。带 client_token 时重复提交只会得到同一条记录（幂等）。"""
    try:
        amount_cent = yuan_to_cent(req.amount_yuan)
    except ValueError as exc:
        raise _bad_request(str(exc)) from exc

    payload = req.model_dump()
    payload["amount_cent"] = amount_cent
    cost_id = await add_cost(trip_id, user_id, payload)
    if cost_id is None:
        raise HTTPException(status_code=404, detail="行程不存在")

    summary = await compute_budget(trip_id, user_id)
    return {"status": "ok", "cost_id": cost_id, "budget": summary}


@app.patch("/api/trips/costs/{cost_id}")
async def api_update_cost(cost_id: int, req: CostUpdateRequest,
                          user_id: int = Depends(get_current_user)):
    """编辑一条费用（只改传入字段）。"""
    body = req.model_dump(exclude_unset=True)
    if "amount_yuan" in body:
        try:
            body["amount_cent"] = yuan_to_cent(body.pop("amount_yuan"))
        except ValueError as exc:
            raise _bad_request(str(exc)) from exc
    else:
        body.pop("amount_yuan", None)

    if not await update_cost(cost_id, user_id, body):
        raise HTTPException(status_code=404, detail="费用不存在或无权限")
    return {"status": "ok"}


@app.delete("/api/trips/costs/{cost_id}")
async def api_delete_cost(cost_id: int, user_id: int = Depends(get_current_user)):
    if not await delete_cost(cost_id, user_id):
        raise HTTPException(status_code=404, detail="费用不存在或无权限")
    return {"status": "ok"}


@app.post("/api/poi/photos")
async def api_poi_photos(req: PoiPhotosRequest, request: Request):
    """取一个真实地点的**候选图片池**（支持分页，供九宫格动态补位）。

    为什么单独一个接口而不是塞进 /api/poi/search：
    每次取图都要花一次搜索额度，搜索框输入时不该顺手触发。
    前端在"用户想看图"时（搜索结果出来、或点开某个地点）才调它。

    分页参数 `offset`（本轮新增）：九宫格要"初始 9 张 + 选中后补位"，
    而单次请求受来源能力限制（Tavily 每次约 5 张），所以按 offset 翻页拿后续候选。
    返回里同时给 total / has_more / next_offset，前端据此判断"是否还有候选"，
    而不是靠猜或造假图。
    """
    api_limiter.check(f"api:poi-photos:{client_ip(request)}")
    pool = await anyio.to_thread.run_sync(
        lambda: place_photo_pool(
            req.query, sanitize_text(req.city)[:30],
            limit=max(1, min(req.limit, 12)), offset=max(0, req.offset),
        )
    )
    return {"status": "ok", **pool}


@app.post("/api/web/search")
async def api_web_search(req: PoiSearchRequest, request: Request):
    """搜公开攻略内容（携程/马蜂窝/小红书/知乎…）与配图。

    ⚠️ **不抓取小红书**（其 robots.txt 为 Disallow: /）。这里走正规搜索 API 拿**公开结果**，
    只展示标题、链接、摘要与配图，正文请点链接去原站看 —— 这是合规做法。
    """
    api_limiter.check(f"api:web-search:{client_ip(request)}")
    data = await anyio.to_thread.run_sync(lambda: web_search(req.query, req.limit))
    return {"status": "ok", **data}


# ==================== 景点图片 ====================

class SpotImagesRequest(BaseModel):
    city: str = ""
    spots: list = []

    @field_validator('city')
    @classmethod
    def validate_city(cls, v: str) -> str:
        return sanitize_text(v)[:50]


@app.post("/api/spot-images")
async def api_spot_images(req: SpotImagesRequest, request: Request):
    """批量返回景点的真实照片 + 署名。

    Unsplash 走 hotlink（条款要求），所以返回的 image_url 是图源 CDN 的绝对地址，
    由浏览器直接加载；key 留在服务端，前端不再需要 NEXT_PUBLIC_UNSPLASH_KEY。

    抓图是同步 requests，**必须丢进线程执行**：HF 免费档只有 1 个 worker，
    同步 IO 写在 async 路由里会把事件循环堵死（审计里"线上整体卡死"的根因）。
    """
    api_limiter.check(f"api:spot-images:{client_ip(request)}")
    images = await anyio.to_thread.run_sync(
        lambda: fetch_spot_images(req.city, req.spots)
    )
    return {"status": "ok", "images": images}


@app.get("/api/images/{filename}")
async def api_serve_image(filename: str):
    """自托管图片通道：给「条款要求先下载到服务器」的图源用（如 Pixabay）。

    Unsplash 不走这里（它要求 hotlink）。路径做 realpath 前缀校验防目录穿越。
    """
    base = os.path.realpath(images_dir())
    path = os.path.realpath(os.path.join(base, filename))
    if not path.startswith(base + os.sep) or not os.path.isfile(path):
        return JSONResponse(status_code=404, content={"status": "error", "message": "图片不存在"})
    return FileResponse(path, headers={"Cache-Control": "public, max-age=86400"})


# 懒加载代理**只允许**这几个图源主机（防止被当成任意 URL 的开放代理 → SSRF）
_PROXY_ALLOWED_HOSTS = {"cdn.pixabay.com", "pixabay.com"}
_PROXY_ALLOWED_SUFFIX = ".pixabay.com"


@app.get("/api/image-proxy")
async def api_image_proxy(src: str, request: Request):
    """按需把图源图片下载到本机并返回（放大图专用，首次点开才走这里）。

    为什么需要它：Pixabay 条款要求"先下载到服务器"，但把 8 张放大图（约 3MB）
    在列表阶段就全部预下载会白白拖慢首屏 —— 于是改成用户点开时才取，取完落盘缓存。

    ⚠️ 安全：这是一个"按 URL 取图"的接口，**必须限制目标主机**，
    否则就成了任意 URL 的开放代理（SSRF）。这里只放行 Pixabay 的域名。
    """
    api_limiter.check(f"api:image-proxy:{client_ip(request)}")
    try:
        parsed = urlparse(src)
    except Exception:
        return JSONResponse(status_code=400, content={"status": "error", "message": "非法地址"})

    host = (parsed.hostname or "").lower()
    if parsed.scheme not in ("http", "https") or not (
        host in _PROXY_ALLOWED_HOSTS or host.endswith(_PROXY_ALLOWED_SUFFIX)
    ):
        return JSONResponse(
            status_code=403,
            content={"status": "error", "message": f"该图源不在白名单内：{host or '(空)'}"},
        )

    filename, why = await anyio.to_thread.run_sync(lambda: _download_to_cache(src))
    if not filename:
        return JSONResponse(status_code=502, content={"status": "error", "message": why or "图片下载失败"})
    path = os.path.join(images_dir(), filename)
    return FileResponse(path, headers={"Cache-Control": "public, max-age=86400"})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
