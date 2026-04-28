# backend/main.py - FastAPI 后端
from fastapi import FastAPI, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse
from pydantic import BaseModel
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from tools.images import generate_spot_image, extract_spots_from_text, geocode_spots
from tools.export import export_to_word
from tools.search import get_weather
from config import ARK_API_KEY, ARK_BASE_URL, CHAT_MODEL, AMAP_WEB_KEY
from database import get_db, init_db
from auth import hash_password, verify_password, create_token, get_current_user
from history import save_plan, list_plans, get_plan, update_plan_text, delete_plan as delete_plan_row
from prompts_en import SYSTEM_PROMPT_EN
import json
import os
import requests as http_requests

# ==================== Session 持久化 ====================
SESSION_DIR = os.path.join(os.path.dirname(__file__), "data", "sessions")
os.makedirs(SESSION_DIR, exist_ok=True)

app = FastAPI(title="野渡寻踪 API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup():
    await init_db()


# ==================== 可选认证（未登录也能用，登录后关联用户） ====================

async def optional_user(authorization: str = Header(None)) -> int:
    """返回 user_id，未登录返回 0"""
    if not authorization or not authorization.startswith("Bearer "):
        return 0
    try:
        return await get_current_user(authorization)
    except Exception:
        return 0


# ==================== Auth 端点 ====================

class RegisterRequest(BaseModel):
    phone: str = ""
    email: str = ""
    password: str
    nickname: str = ""


class LoginRequest(BaseModel):
    phone: str = ""
    email: str = ""
    password: str


@app.post("/api/auth/register")
async def register(req: RegisterRequest):
    if not req.phone and not req.email:
        return {"status": "error", "message": "请提供手机号或邮箱"}
    if len(req.password) < 6:
        return {"status": "error", "message": "密码至少6位"}

    db = await get_db()
    try:
        # 检查唯一性
        if req.phone:
            row = await db.execute_fetchall("SELECT id FROM users WHERE phone=?", (req.phone,))
            if row:
                return {"status": "error", "message": "手机号已注册"}
        if req.email:
            row = await db.execute_fetchall("SELECT id FROM users WHERE email=?", (req.email,))
            if row:
                return {"status": "error", "message": "邮箱已注册"}

        pw_hash = hash_password(req.password)
        cursor = await db.execute(
            "INSERT INTO users (phone, email, password_hash, nickname) VALUES (?, ?, ?, ?)",
            (req.phone or None, req.email or None, pw_hash, req.nickname or req.phone or req.email),
        )
        await db.commit()
        user_id = cursor.lastrowid
        token = create_token(user_id)
        return {"status": "ok", "user_id": user_id, "token": token, "nickname": req.nickname or req.phone or req.email}
    finally:
        await db.close()


@app.post("/api/auth/login")
async def login(req: LoginRequest):
    db = await get_db()
    try:
        if req.phone:
            row = await db.execute_fetchall("SELECT id, password_hash, nickname FROM users WHERE phone=?", (req.phone,))
        elif req.email:
            row = await db.execute_fetchall("SELECT id, password_hash, nickname FROM users WHERE email=?", (req.email,))
        else:
            return {"status": "error", "message": "请提供手机号或邮箱"}

        if not row:
            return {"status": "error", "message": "账号不存在"}

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

# 直接用 LLM 流式输出
llm = ChatOpenAI(
    model=CHAT_MODEL,
    api_key=ARK_API_KEY,
    base_url=ARK_BASE_URL,
    streaming=True,
)

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


class PlanRequest(BaseModel):
    session_id: str
    spots: list
    language: str = "zh"


class ModifyRequest(BaseModel):
    session_id: str
    message: str
    preview: bool = False
    language: str = "zh"


class ImageRequest(BaseModel):
    spot_name: str
    city: str = ""


class ExportRequest(BaseModel):
    plan_text: str
    session_id: str = "default"


def stream_llm(messages: list):
    """统一的 LLM 流式输出"""
    full_response = ""
    try:
        for chunk in llm.stream(messages):
            if chunk.content:
                full_response += chunk.content
                yield f"data: {json.dumps({'type': 'chunk', 'content': chunk.content}, ensure_ascii=False)}\n\n"
    except Exception as e:
        yield f"data: {json.dumps({'type': 'error', 'content': str(e)}, ensure_ascii=False)}\n\n"
    return full_response


@app.post("/api/recommend")
async def recommend(req: RecommendRequest, user_id: int = Depends(optional_user)):
    params = req.params
    session = get_session(req.session_id)

    dep = params.get('dep_datetime', '')
    ret = params.get('ret_datetime', '')
    from_city = params.get('from_city', '')
    to_city = params.get('to_city', '')

    prompt = f"""我想从{from_city}去{to_city}旅行{params.get('days',3)}天，{dep}到达，{ret}返程。预算{params.get('budget',3000)}元，旅行类型"{params.get('travel_type','性价比出行')}"，用户类型"{params.get('user_type','成人')}"。
交通：去程{params.get('transport_go','高铁')}，返程{params.get('transport_back','高铁')}。住宿：{params.get('accommodation','经济酒店')}。同行{params.get('companions_count',1)}人，{params.get('companion_type','独自出行')}。

请推荐{to_city}的 6-10 个热门景点，按以下格式输出（简洁为主，不要写太多）：

---
🏞️ **景点名**
🎫 门票：全价XX元 / {params.get('user_type','成人')}优惠价XX元
⏰ 游玩时长：X小时 | ⭐ 推荐指数：X/5
📝 一句话描述
---

按地理位置分组排列，方便后续规划不走回头路的路线。"""

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
        coords = geocode_spots(spots, to_city)
        yield f"data: {json.dumps({'type': 'done', 'spots': spots, 'coords': coords}, ensure_ascii=False)}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")


@app.post("/api/generate-plan")
async def generate_plan(req: PlanRequest, user_id: int = Depends(optional_user)):
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
async def modify(req: ModifyRequest, user_id: int = Depends(optional_user)):
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


@app.post("/api/geocode")
async def geocode(req: GeocodeRequest):
    """将景点名列表转换为经纬度，使用高德地理编码 API。"""
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


@app.get("/api/history")
async def api_list_history(user_id: int = Depends(get_current_user)):
    plans = await list_plans(user_id)
    return {"status": "ok", "plans": plans}


@app.post("/api/history")
async def api_save_history(req: SavePlanRequest, user_id: int = Depends(get_current_user)):
    plan_id = await save_plan(user_id, req.model_dump())
    return {"status": "ok", "plan_id": plan_id}


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



if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
