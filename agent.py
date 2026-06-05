# agent.py - LangGraph Agent 定义
from langchain_openai import ChatOpenAI
from langchain_core.tools import tool
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, ToolMessage
from typing import TypedDict, Annotated
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.checkpoint.memory import MemorySaver
import json
import requests
import os
from config import ARK_API_KEY, ARK_BASE_URL, CHAT_MODEL

# ==================== 1. 连接 AI（豆包1.8） ====================
llm = ChatOpenAI(
    model=CHAT_MODEL,
    openai_api_key=ARK_API_KEY,
    openai_api_base=ARK_BASE_URL
)

# ==================== 2. 定义工具 ====================

@tool
def get_weather(city: str) -> str:
    """查询目的地未来3天天气预报，用于给出穿衣建议和雨天备选方案。

    当用户提到旅行目的地时，主动调用此工具获取天气信息，
    以便在攻略中加入穿衣建议、雨天备选方案等实用信息。

    Args:
        city: 中文城市名，如"北京"、"成都"、"西安"
    """
    try:
        url = f"https://wttr.in/{city}?format=j1&lang=zh"
        resp = requests.get(url, timeout=8)
        resp.raise_for_status()
        data = resp.json()

        days = data.get("weather", [])
        lines = []
        for day in days:
            date = day.get("date", "")
            hourly = day.get("hourly", [])
            # 取中午时段（index 4 ≈ 12:00）作为代表
            mid = hourly[4] if len(hourly) > 4 else (hourly[0] if hourly else {})
            max_temp = day.get("maxtempC", "?")
            min_temp = day.get("mintempC", "?")
            desc = mid.get("lang_zh", [{}])[0].get("value",
                    mid.get("weatherDesc", [{}])[0].get("value", "?"))
            wind = mid.get("windspeedKmph", "?")
            humidity = mid.get("humidity", "?")
            lines.append(
                f"{date}: {desc}, {min_temp}~{max_temp}°C, "
                f"风速{wind}km/h, 湿度{humidity}%"
            )

        return f"📍 {city}未来天气：\n" + "\n".join(lines)
    except Exception as e:
        return f"天气查询失败（{e}），请根据季节和常识给出穿衣建议。"


tools = [get_weather]
llm_with_tools = llm.bind_tools(tools)

# ==================== 3. 定义 State ====================
class PlannerState(TypedDict):
    messages: Annotated[list, add_messages]  # add_messages = 追加模式，保护历史消息
    user_input: dict   # 用户参数（城市、天数、预算等）

# ==================== 4. 定义节点 ====================
SYSTEM_PROMPT = """你是"野渡寻踪"的 AI 助手，专门为预算有限的旅行者生成个性化攻略。

**用户类型票价优惠**（user_type 字段）：学生=门票半价/火车硬座半价/高铁7.5折 | 老人(60+)=门票免/半价 | 军人=多景区免票 | 儿童(1.2m以下)=免票 | 成人=全价。所有价格同时标注全价和优惠价。

**天气查询**：推荐景点或生成攻略时，主动调用 get_weather 工具查天气，加入穿衣建议和雨天备选。

**工作流程（按顺序执行）：**

**第 1 步：收集信息**
你已有：出发城市、目的地、天数、预算、旅行类型、用户类型、出发/返程日期。
一次追问：到达/离开时间、交通偏好、住宿偏好、同行人数、必去/不去的地方、每日步行量。

**第 2 步：推荐景点 + 门票预约表**
推荐 6-10 个大景点，按地理位置分组。每个景点含：门票（全价/优惠价）、时长、推荐指数、位置、一句话描述、顺路景点（3-5个）、tips。
同时生成「门票预约总览表」：景点、游玩日期、预约开放时间、预约渠道、价格、是否必须预约。来不及预约的要⚠️警告并推荐替代。

**第 3 步：逐天分配景点**
根据旅行类型主动建议分配方案，等用户确认后进入下一步。

**核心原则：不走回头路！** 同天景点在同一区域/方向，住宿在当天终点和明天起点之间，到达日从车站方向开始，离开日最后景点靠近车站。

**第 4 步：生成详细攻略**
用户确认分配后，生成每天的详细攻略。每天必须包含：
- 交通概览（具体线路：地铁几号线/公交几路/打车价格）
- 时间轴（精确到 10-30 分钟节点，含具体店名/菜名/人均价格的早中晚餐）
- 景点内部路线（从哪个门进、必看亮点、拍照机位）
- 住宿建议（推荐区域+类型+参考价格）
- 今日花费明细表
- 实用贴士（避坑提醒、穿衣建议、雨天备选方案）

**第 5 步：修改调整**
只输出修改的部分，不重新生成未修改的天。支持：减景点/调预算/加景点/换天/天气调整。

**第 6 步：路线验证**
生成后自查：不走回头路、住宿位置合理、时间不赶不闲。在攻略末尾加「✅ 路线检查」说明合理性。

**预算分配参考**（交通/住宿/餐饮/门票/其他）：
- 特种兵 30/20/15/30/5 | 性价比 25/30/20/20/5 | 享受 25/35/25/10/5
- City Walk 15/35/30/15/5 | 慢旅行 20/40/25/10/5 | 窝囊旅游 10/45/30/10/5
- 美食之旅 20/25/40/10/5 | 打卡出片 20/30/20/20/10 | 探索冒险 30/25/20/15/10 | 主题深度 20/30/20/25/5

**通用规则**：价格用人民币、预算不足要提醒、优先推荐当地特色、用中文和 Markdown 格式、不要提图片（系统自动展示）。"""

def supervisor_node(state: PlannerState) -> dict:
    """主管节点：调用 LLM 处理对话。

    不再每次重新构造 [SystemMessage(SYSTEM_PROMPT)] + history。
    System Prompt 由 app.py 在首次调用时注入 messages 列表，
    add_messages reducer 会保留历史，后续轮次自动携带，不会重复。
    """
    user_input = state.get("user_input", {})
    context = f"用户参数：{json.dumps(user_input, ensure_ascii=False)}"

    response = llm_with_tools.invoke(
        state["messages"] + [SystemMessage(content=context)]
    )
    return {"messages": [response]}

def tool_node(state: PlannerState) -> dict:
    """工具执行节点：真正执行 LLM 选择的工具。

    LangGraph 模式：接收 AIMessage（含 tool_calls），
    执行每个工具，返回 ToolMessage。图会路由回 supervisor。
    """
    last_message = state["messages"][-1]
    tool_map = {t.name: t for t in tools}
    tool_messages = []

    for tool_call in last_message.tool_calls:
        tool_name = tool_call["name"]
        tool_args = tool_call["args"]

        fn = tool_map.get(tool_name)
        if fn:
            try:
                result = str(fn.invoke(tool_args))
            except Exception as e:
                result = f"工具 {tool_name} 执行出错：{e}"
        else:
            result = f"未知工具：{tool_name}"

        tool_messages.append(ToolMessage(
            content=result,
            tool_call_id=tool_call["id"]
        ))
    return {"messages": tool_messages}

def should_use_tool(state: PlannerState) -> str:
    """条件边：AI 需要用工具吗？"""
    last_message = state["messages"][-1]
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        return "use_tool"
    return "end"

# ==================== 5. 组装图 ====================
graph = StateGraph(PlannerState)
graph.add_node("supervisor", supervisor_node)
graph.add_node("tools", tool_node)
graph.set_entry_point("supervisor")
graph.add_conditional_edges("supervisor", should_use_tool, {
    "use_tool": "tools",
    "end": END
})
graph.add_edge("tools", "supervisor")

# 编译（带记忆）
checkpointer = MemorySaver()
app = graph.compile(checkpointer=checkpointer)
