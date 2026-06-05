# agent.py - LangGraph Agent 定义
from langchain_openai import ChatOpenAI
from langchain_core.tools import tool
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, ToolMessage
from typing import TypedDict, Annotated
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.checkpoint.memory import MemorySaver
import json
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
def generate_attractions(city: str, travel_type: str) -> str:
    """根据城市和旅行类型推荐热门景点，包含门票价格、游玩时长、推荐指数。"""
    return f"请推荐{city}的热门景点，旅行类型：{travel_type}"

@tool
def generate_itinerary(
    city: str,
    days: int,
    budget: int,
    travel_type: str,
    selected_spots: str,
    from_city: str = ""
) -> str:
    """根据用户选择的景点和参数生成完整行程攻略。"""
    return f"生成{city}的{days}日行程，预算{budget}元，类型{travel_type}，必去景点：{selected_spots}"

@tool
def modify_itinerary(modification_request: str, current_plan: str) -> str:
    """根据用户反馈修改行程安排。"""
    return f"修改请求：{modification_request}，当前行程：{current_plan[:500]}"

tools = [generate_attractions, generate_itinerary, modify_itinerary]
llm_with_tools = llm.bind_tools(tools)

# ==================== 3. 定义 State ====================
class PlannerState(TypedDict):
    messages: Annotated[list, add_messages]  # add_messages = 追加模式，保护历史消息
    user_input: dict   # 用户参数（城市、天数、预算等）
    phase: str         # 当前阶段：recommend / plan / modify / done
    plan: str          # 当前攻略内容

# ==================== 4. 定义节点 ====================
SYSTEM_PROMPT = """你是"野渡寻踪"的 AI 助手，专门为预算有限的旅行者生成个性化攻略。

**用户类型票价优惠**（user_type 字段）：学生=门票半价/火车硬座半价/高铁7.5折 | 老人(60+)=门票免/半价 | 军人=多景区免票 | 儿童(1.2m以下)=免票 | 成人=全价。所有价格同时标注全价和优惠价。

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
    """主管节点：根据当前阶段决定下一步"""
    messages = [SystemMessage(content=SYSTEM_PROMPT)]

    # 添加历史消息
    for msg in state["messages"]:
        messages.append(msg)

    # 附加当前阶段和攻略信息
    phase = state.get("phase", "recommend")
    plan = state.get("plan", "")
    user_input = state.get("user_input", {})

    context = f"\n当前阶段：{phase}\n用户参数：{json.dumps(user_input, ensure_ascii=False)}"
    if plan:
        context += f"\n当前攻略摘要：{plan[:500]}"
    messages.append(SystemMessage(content=context))

    response = llm_with_tools.invoke(messages)
    return {"messages": [response]}

def tool_node(state: PlannerState) -> dict:
    """工具执行节点"""
    last_message = state["messages"][-1]
    tool_messages = []
    for tool_call in last_message.tool_calls:
        tool_name = tool_call["name"]
        tool_args = tool_call["args"]

        # 执行工具（这里工具主要是提示 AI 生成对应内容）
        result = f"已调用 {tool_name}，参数：{json.dumps(tool_args, ensure_ascii=False)}"

        tool_messages.append(ToolMessage(
            content=str(result),
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
