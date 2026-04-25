# backend/main.py - FastAPI 后端
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse
from pydantic import BaseModel
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from tools.images import generate_spot_image, extract_spots_from_text
from tools.export import export_to_word
from config import ARK_API_KEY, ARK_BASE_URL, CHAT_MODEL
import json
import os

app = FastAPI(title="野渡寻踪 API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 直接用 LLM 流式输出（绕过 LangGraph graph 的 tool call 问题）
llm = ChatOpenAI(
    model=CHAT_MODEL,
    openai_api_key=ARK_API_KEY,
    openai_api_base=ARK_BASE_URL,
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


def get_session(session_id: str):
    if session_id not in sessions:
        sessions[session_id] = {"messages": [], "plan": ""}
    return sessions[session_id]


class RecommendRequest(BaseModel):
    params: dict
    session_id: str = "default"


class PlanRequest(BaseModel):
    session_id: str
    spots: list


class ModifyRequest(BaseModel):
    session_id: str
    message: str


class ImageRequest(BaseModel):
    spot_name: str
    city: str = ""


def stream_llm(messages: list):
    """统一的 LLM 流式输出"""
    full_response = ""
    for chunk in llm.stream(messages):
        if chunk.content:
            full_response += chunk.content
            yield f"data: {json.dumps({'type': 'chunk', 'content': chunk.content}, ensure_ascii=False)}\n\n"
    return full_response


@app.post("/api/recommend")
async def recommend(req: RecommendRequest):
    params = req.params
    session = get_session(req.session_id)

    prompt = f"""我想从{params.get('from_city','')}去{params.get('to_city','')}旅行{params.get('days',3)}天（{params.get('dep_datetime','')}到达，{params.get('ret_datetime','')}返程），预算{params.get('budget',3000)}元，旅行类型是"{params.get('travel_type','性价比出行')}"，用户类型是"{params.get('user_type','成人')}"。
交通方式：去程{params.get('transport_go','高铁')}，返程{params.get('transport_back','高铁')}。
住宿偏好：{params.get('accommodation','经济酒店')}。
同行{params.get('companions_count',1)}人，关系：{params.get('companion_type','独自出行')}。

请帮我推荐{params.get('to_city','')}的热门景点。**输出格式要求**：

## 门票预约抢票提醒
在最前面放一张门票预约总览表，包含：景点名、游玩日期、放票时间（精确到几点几分）、最晚预约时间、预约渠道、门票价格、是否必须预约、紧急程度（需立即抢/建议提前/可选）。用表格展示，紧急程度用加粗标红。

## 推荐景点
然后推荐 6-10 个大景点，每个景点用 **景点名** 加粗，包含门票价格（全价和优惠价）、游玩时长、推荐指数、一句话描述，按地理位置分组。"""

    messages = [SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=prompt)]
    session["messages"] = messages

    def stream():
        full_response = yield from stream_llm(messages)
        session["messages"].append(AIMessage(content=full_response))
        session["plan"] = full_response
        spots = extract_spots_from_text(full_response)
        yield f"data: {json.dumps({'type': 'done', 'spots': spots}, ensure_ascii=False)}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")


@app.post("/api/generate-plan")
async def generate_plan(req: PlanRequest):
    session = get_session(req.session_id)

    prompt = f"我选好了，要去这些景点：{', '.join(req.spots)}。请根据这些景点帮我安排详细行程攻略。注意路线不要走回头路，并且再次确认路线是否合理。"

    # 只发系统提示 + 新请求，不带历史推荐内容（减少上下文长度）
    messages = [SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=prompt)]
    session["messages"] = messages

    def stream():
        full_response = yield from stream_llm(messages)
        session["plan"] = full_response
        session["messages"].append(AIMessage(content=full_response))
        yield f"data: {json.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")


@app.post("/api/modify")
async def modify(req: ModifyRequest):
    session = get_session(req.session_id)

    # 带上当前攻略作为上下文 + 用户新要求
    context = f"当前攻略内容：\n{session.get('plan', '')[:3000]}\n\n用户修改要求：{req.message}\n\n请根据用户要求修改攻略，输出完整的修改后攻略。"
    messages = [SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=context)]
    session["messages"] = messages

    def stream():
        full_response = yield from stream_llm(messages)
        session["plan"] = full_response
        session["messages"].append(AIMessage(content=full_response))
        yield f"data: {json.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")


@app.post("/api/generate-image")
async def generate_image(req: ImageRequest):
    result = generate_spot_image(req.spot_name, req.city)
    return result


@app.get("/api/export-word")
async def export_word(session_id: str, title: str = "旅行攻略"):
    session = get_session(session_id)
    itinerary = {
        "title": title,
        "overview": session.get("plan", ""),
        "spot_images": {},
    }
    filepath = export_to_word(itinerary)
    return FileResponse(filepath, filename=os.path.basename(filepath))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
