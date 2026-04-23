# app.py - 野渡寻踪 Streamlit 前端
import streamlit as st
from agent import app as langgraph_app, PlannerState
from tools.export import export_to_word
from tools.images import generate_spot_image, extract_spots_from_text
from langchain_core.messages import HumanMessage, AIMessage
import json
import os
import re

# ==================== 页面配置 ====================
st.set_page_config(
    page_title="野渡寻踪 — AI 旅行攻略",
    page_icon="🌿",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ==================== 全局样式 ====================
st.markdown("""
<style>
/* ===== 侧边栏 ===== */
[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #1B2A1B 0%, #0F1F0F 100%);
}
[data-testid="stSidebar"] label {
    color: #C8E6C9 !important;
    font-weight: 500;
    font-size: 0.9rem;
}
[data-testid="stSidebar"] .stMarkdown {
    color: #E8F5E9 !important;
}
[data-testid="stSidebar"] input,
[data-testid="stSidebar"] .stTextInput > div > div > input,
[data-testid="stSidebar"] .stNumberInput > div > div > input {
    color: #222222 !important;
    background-color: rgba(255,255,255,0.92) !important;
    border-radius: 8px;
}
[data-testid="stSidebar"] .stSelectbox div[data-baseweb="select"] > div {
    color: #222222 !important;
    background-color: rgba(255,255,255,0.92) !important;
    border-radius: 8px;
}
[data-testid="stSidebar"] .stSelectbox div[data-baseweb="select"] span {
    color: #222222 !important;
}
[data-testid="stSidebar"] .stDateInput input,
[data-testid="stSidebar"] .stTimeInput input {
    color: #222222 !important;
    background-color: rgba(255,255,255,0.92) !important;
    border-radius: 8px;
}
[data-testid="stSidebar"] .stButton > button {
    background: linear-gradient(135deg, #2E7D32, #43A047);
    color: white !important;
    border: none;
    font-weight: bold;
    width: 100%;
    border-radius: 8px;
}
[data-testid="stSidebar"] .stButton > button:hover {
    background: linear-gradient(135deg, #388E3C, #4CAF50);
    box-shadow: 0 4px 12px rgba(46,125,50,0.4);
}
/* 侧边栏表格 */
[data-testid="stSidebar"] table {
    font-size: 0.8rem;
}
[data-testid="stSidebar"] thead th {
    background-color: #2E7D32 !important;
    color: white !important;
}

/* ===== 主区域 ===== */
.stApp {
    background: #FAFAF5;
}
h1, h2, h3 {
    color: #2E7D32 !important;
}
h1 { font-weight: 700; }

/* ===== 聊天气泡 ===== */
.stChatMessage {
    border-radius: 16px;
    padding: 12px 16px;
    margin: 8px 0;
    box-shadow: 0 2px 8px rgba(0,0,0,0.06);
}
[data-testid="stChatMessageAvatarUser"] {
    background: #E8F5E9;
}
[data-testid="stChatMessageAvatarAssistant"] {
    background: #FFF8E1;
}

/* ===== 特色卡片 ===== */
.feature-card {
    background: white;
    border-radius: 16px;
    padding: 24px 20px;
    text-align: center;
    box-shadow: 0 4px 16px rgba(0,0,0,0.06);
    transition: transform 0.2s, box-shadow 0.2s;
    border: 1px solid #E8F5E9;
    height: 100%;
}
.feature-card:hover {
    transform: translateY(-4px);
    box-shadow: 0 8px 24px rgba(46,125,50,0.12);
}
.feature-icon {
    font-size: 2.5rem;
    margin-bottom: 8px;
}
.feature-title {
    font-size: 1.1rem;
    font-weight: 700;
    color: #2E7D32;
    margin-bottom: 6px;
}
.feature-desc {
    font-size: 0.88rem;
    color: #666;
    line-height: 1.5;
}

/* ===== 流程步骤 ===== */
.step-container {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
    margin: 32px 0;
}
.step-item {
    display: flex;
    align-items: center;
    gap: 8px;
}
.step-num {
    width: 36px;
    height: 36px;
    border-radius: 50%;
    background: #2E7D32;
    color: white;
    display: flex;
    align-items: center;
    justify-content: center;
    font-weight: 700;
    font-size: 1rem;
}
.step-text {
    font-size: 0.95rem;
    color: #555;
    font-weight: 500;
}
.step-arrow {
    color: #A5D6A7;
    font-size: 1.3rem;
    margin: 0 4px;
}

/* ===== 景点卡片 ===== */
.spot-card-wrapper {
    background: white;
    border-radius: 14px;
    overflow: hidden;
    box-shadow: 0 2px 12px rgba(0,0,0,0.06);
    border: 2px solid transparent;
    transition: all 0.25s;
    margin-bottom: 12px;
}
.spot-card-wrapper:hover {
    border-color: #66BB6A;
    box-shadow: 0 6px 20px rgba(46,125,50,0.15);
}
.spot-card-info {
    padding: 10px 14px;
}
.spot-card-name {
    font-weight: 700;
    font-size: 1rem;
    color: #2E7D32;
}
.spot-card-desc {
    font-size: 0.82rem;
    color: #777;
    margin-top: 2px;
}
.spot-card-price {
    font-size: 0.85rem;
    color: #E65100;
    font-weight: 600;
    margin-top: 4px;
}

/* ===== CTA 按钮 ===== */
.cta-button {
    display: inline-block;
    background: linear-gradient(135deg, #2E7D32, #43A047);
    color: white;
    padding: 16px 48px;
    border-radius: 50px;
    font-size: 1.2rem;
    font-weight: 700;
    text-align: center;
    cursor: pointer;
    box-shadow: 0 4px 16px rgba(46,125,50,0.3);
    transition: all 0.3s;
    border: none;
}
.cta-button:hover {
    transform: translateY(-2px);
    box-shadow: 0 8px 24px rgba(46,125,50,0.4);
}

/* ===== 快捷按钮 ===== */
.quick-btn {
    background: white;
    border: 1px solid #C8E6C9;
    border-radius: 20px;
    padding: 8px 16px;
    font-size: 0.85rem;
    color: #2E7D32;
    cursor: pointer;
    transition: all 0.2s;
    margin: 4px;
    display: inline-block;
}
.quick-btn:hover {
    background: #E8F5E9;
    border-color: #66BB6A;
}

/* ===== 进度条 ===== */
.stProgress > div > div > div {
    background: linear-gradient(90deg, #66BB6A, #2E7D32);
}
</style>
""", unsafe_allow_html=True)

# ==================== 辅助函数 ====================
def parse_spot_details(text: str, spot_name: str) -> dict:
    """从 AI 推荐文本中提取单个景点的描述和价格"""
    result = {"desc": "", "price": ""}
    pattern = rf'\*\*{re.escape(spot_name)}\*\*.*?(?=\n---|\n🏞️|\n\*\*$|$)'
    match = re.search(pattern, text, re.DOTALL)
    if match:
        block = match.group()
        # 提取价格
        price_match = re.search(r'🎫\s*门票[：:]\s*(.+?)(?:\n|$)', block)
        if price_match:
            result["price"] = price_match.group(1).strip()
        # 提取描述
        desc_match = re.search(r'📝\s*(.+?)(?:\n|$)', block)
        if desc_match:
            result["desc"] = desc_match.group(1).strip()
    return result


# ==================== 初始化 Session State ====================
if "messages" not in st.session_state:
    st.session_state.messages = []
if "user_params" not in st.session_state:
    st.session_state.user_params = {}
if "current_plan" not in st.session_state:
    st.session_state.current_plan = ""
if "phase" not in st.session_state:
    st.session_state.phase = "recommend"
if "thread_id" not in st.session_state:
    st.session_state.thread_id = "travel_planner_001"
if "recommended_spots" not in st.session_state:
    st.session_state.recommended_spots = []
if "spot_images" not in st.session_state:
    st.session_state.spot_images = {}
if "ai_recommendation" not in st.session_state:
    st.session_state.ai_recommendation = ""

# ==================== 侧边栏：参数设置 ====================
with st.sidebar:
    st.markdown("## 🌿 野渡寻踪")
    st.markdown("---")

    # ── 基本信息 ──
    st.markdown("### 📍 基本信息")
    from_city = st.text_input("出发城市", value="苏州", placeholder="你从哪出发？")
    to_city = st.text_input("目的地", value="", placeholder="你想去哪？")

    # ── 时间安排 ──
    st.markdown("### 🕐 时间安排")
    dep_datetime_raw = st.datetime_input("到达时间", value=None)
    ret_datetime_raw = st.datetime_input("返程时间", value=None)
    dep_datetime = f"{dep_datetime_raw.year}年{dep_datetime_raw.month}月{dep_datetime_raw.day}日 {dep_datetime_raw.hour:02d}:{dep_datetime_raw.minute:02d}" if dep_datetime_raw else "未定"
    ret_datetime = f"{ret_datetime_raw.year}年{ret_datetime_raw.month}月{ret_datetime_raw.day}日 {ret_datetime_raw.hour:02d}:{ret_datetime_raw.minute:02d}" if ret_datetime_raw else "未定"
    try:
        days = (ret_datetime_raw.date() - dep_datetime_raw.date()).days + 1
    except:
        days = 3

    # ── 预算与身份 ──
    st.markdown("### 💰 预算与身份")
    budget = st.number_input("预算上限（元）", min_value=100, max_value=50000, value=3000, step=100)
    user_type = st.selectbox(
        "用户类型",
        ["🎒 学生", "👤 成人", "👴 老人(60+)", "🎖️ 军人/退役军人", "👶 儿童(1.2m以下)"],
        index=0
    )
    user_type_key = user_type.split(" ", 1)[1] if " " in user_type else user_type

    # ── 旅行风格 ──
    st.markdown("### 🎯 旅行风格")
    travel_type = st.selectbox(
        "旅行类型",
        [
            "🎒 特种兵旅行 — 高效打卡，一天跑8个景点",
            "💰 性价比出行 — 该省省该花花，精明消费",
            "👑 享受出行 — 吃好住好，深度体验",
            "🚶 City Walk — 逛吃逛吃，漫步城市",
            "🧘 慢旅行 — 不赶路，在一个地方深度感受",
            "😴 窝囊旅游 — 能躺着绝不站着，轻松躺平",
            "🍜 美食之旅 — 为了一顿饭去一座城",
            "📸 打卡出片 — 网红景点，拍好看的照片",
            "🏔️ 探索冒险 — 徒步/自驾/挑战极限",
            "🎯 主题深度游 — 历史文化/自然生态/剧本杀等",
        ],
        index=0
    )
    travel_type_key = travel_type.split(" — ")[0].split(" ", 1)[1] if " — " in travel_type else travel_type

    # ── 交通偏好 ──
    st.markdown("### 🚄 交通偏好")
    transport_go = st.selectbox("去程交通", ["🚄 高铁", "🚂 火车", "✈️ 飞机", "🚗 自驾"], index=0)
    transport_back = st.selectbox("返程交通", ["🚄 高铁", "🚂 火车", "✈️ 飞机", "🚗 自驾"], index=0)

    # ── 住宿偏好 ──
    st.markdown("### 🏨 住宿偏好")
    accommodation = st.selectbox(
        "住宿类型",
        ["🛏️ 青旅（50-100元/晚）", "🏢 经济酒店（150-300元/晚）", "🏡 民宿（200-400元/晚）", "⭐ 星级酒店（400+元/晚）"],
        index=1
    )

    # ── 同行人员 ──
    st.markdown("### 👥 同行人员")
    companions_count = st.number_input("同行人数（含自己）", min_value=1, max_value=20, value=1, step=1)
    companion_type = st.selectbox(
        "同行关系",
        ["🧑 独自出行", "💑 情侣", "👫 朋友", "👨‍👩‍👧 家庭", "🏢 团建/集体"],
        index=0
    )

    st.markdown("---")
    st.markdown("### 📊 预算分配参考")
    budget_table = {
        "特种兵旅行": {"交通": "30%", "住宿": "20%", "餐饮": "15%", "门票": "30%", "其他": "5%"},
        "性价比出行": {"交通": "25%", "住宿": "30%", "餐饮": "20%", "门票": "20%", "其他": "5%"},
        "享受出行": {"交通": "25%", "住宿": "35%", "餐饮": "25%", "门票": "10%", "其他": "5%"},
        "City Walk": {"交通": "15%", "住宿": "35%", "餐饮": "30%", "门票": "15%", "其他": "5%"},
        "慢旅行": {"交通": "20%", "住宿": "40%", "餐饮": "25%", "门票": "10%", "其他": "5%"},
        "窝囊旅游": {"交通": "10%", "住宿": "45%", "餐饮": "30%", "门票": "10%", "其他": "5%"},
        "美食之旅": {"交通": "20%", "住宿": "25%", "餐饮": "40%", "门票": "10%", "其他": "5%"},
        "打卡出片": {"交通": "20%", "住宿": "30%", "餐饮": "20%", "门票": "20%", "其他": "10%"},
        "探索冒险": {"交通": "30%", "住宿": "25%", "餐饮": "20%", "门票": "15%", "其他": "10%"},
        "主题深度游": {"交通": "20%", "住宿": "30%", "餐饮": "20%", "门票": "25%", "其他": "5%"},
    }
    st.table(budget_table.get(travel_type_key, budget_table["性价比出行"]))

    st.markdown("---")
    if st.button("🔄 开始新的攻略", use_container_width=True):
        for key in ["messages", "current_plan", "recommended_spots", "spot_images", "ai_recommendation"]:
            if key == "messages":
                st.session_state[key] = []
            elif key == "recommended_spots":
                st.session_state[key] = []
            elif key == "spot_images":
                st.session_state[key] = {}
            elif key in ("ai_recommendation", "current_plan"):
                st.session_state[key] = ""
        st.session_state.phase = "recommend"
        st.rerun()

    st.markdown("---")
    st.caption("Powered by LangGraph + 豆包")

# ==================== 主区域 ====================

# 显示历史消息
for msg in st.session_state.messages:
    role = "user" if isinstance(msg, HumanMessage) else "assistant"
    avatar = "🧑" if role == "user" else "🌿"
    with st.chat_message(role, avatar=avatar):
        st.markdown(msg.content)

# ==================== 首页（欢迎页） ====================
if not st.session_state.messages and not st.session_state.ai_recommendation:
    # 品牌标题
    st.markdown("<div style='text-align:center; padding: 30px 0 10px;'>", unsafe_allow_html=True)
    st.markdown("# 🌿 野渡寻踪")
    st.markdown("<p style='font-size:1.15rem; color:#666; text-align:center;'>AI 智能旅行攻略规划师 — 从景点推荐到详细行程，一站搞定</p>", unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)

    # 特色卡片
    cols = st.columns(4)
    features = [
        ("🎯", "AI 智能推荐", "根据你的预算和风格\n精准推荐必去景点"),
        ("🎨", "AI 生成景点图", "每个景点自动生成\n沉浸式预览图片"),
        ("🗺️", "智能路线规划", "不走回头路\n每天行程最优安排"),
        ("📄", "一键导出攻略", "详细攻略导出 Word\n离线也能随时查看"),
    ]
    for i, (icon, title, desc) in enumerate(features):
        with cols[i]:
            st.markdown(f"""
            <div class="feature-card">
                <div class="feature-icon">{icon}</div>
                <div class="feature-title">{title}</div>
                <div class="feature-desc">{desc.replace(chr(10), '<br>')}</div>
            </div>
            """, unsafe_allow_html=True)

    # 流程步骤
    st.markdown("""
    <div class="step-container">
        <div class="step-item">
            <div class="step-num">1</div>
            <div class="step-text">填写旅行参数</div>
        </div>
        <div class="step-arrow">→</div>
        <div class="step-item">
            <div class="step-num">2</div>
            <div class="step-text">勾选心仪景点</div>
        </div>
        <div class="step-arrow">→</div>
        <div class="step-item">
            <div class="step-num">3</div>
            <div class="step-text">获取详细攻略</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # CTA 按钮
    if st.button("🚀 开始生成攻略", type="primary", use_container_width=True):
        if not to_city:
            st.warning("请先在左侧填写目的地！")
        else:
            st.session_state.user_params = {
                "from_city": from_city,
                "to_city": to_city,
                "days": days,
                "budget": budget,
                "travel_type": travel_type_key,
                "user_type": user_type_key,
                "dep_datetime": dep_datetime or "未定",
                "ret_datetime": ret_datetime or "未定",
                "transport_go": transport_go,
                "transport_back": transport_back,
                "accommodation": accommodation,
                "companions_count": companions_count,
                "companion_type": companion_type,
            }
            st.session_state.phase = "recommend"
            st.rerun()

# ==================== 推荐景点阶段 ====================
if st.session_state.phase == "recommend" and st.session_state.user_params and not st.session_state.ai_recommendation:
    params = st.session_state.user_params
    prompt = f"""我想从{params['from_city']}去{params['to_city']}旅行{params['days']}天（{params['dep_datetime']}到达，{params['ret_datetime']}返程），预算{params['budget']}元，旅行类型是"{params['travel_type']}"，用户类型是"{params['user_type']}"。
交通方式：去程{params['transport_go']}，返程{params['transport_back']}。
住宿偏好：{params['accommodation']}。
同行{params['companions_count']}人，关系：{params['companion_type']}。

请帮我推荐{params['to_city']}的热门景点。要求：
1. 推荐 6-10 个大景点
2. 每个景点用 **景点名** 加粗，包含门票价格（全价和优惠价）、游玩时长、推荐指数、一句话描述
3. 必须生成门票预约总览表（包含每个景点的预约开放时间、预约渠道、是否必须预约）
4. 按地理位置分组"""

    with st.chat_message("assistant", avatar="🌿"):
        with st.spinner("🌿 AI 正在推荐景点..."):
            config = {"configurable": {"thread_id": st.session_state.thread_id}}
            state_input = {
                "messages": [HumanMessage(content=prompt)],
                "user_input": st.session_state.user_params,
                "phase": "recommend",
                "plan": "",
            }

            full_response = ""
            placeholder = st.empty()
            for event in langgraph_app.stream(state_input, config=config, stream_mode="messages"):
                if isinstance(event, tuple) and len(event) == 2:
                    chunk, metadata = event
                    if isinstance(chunk, AIMessage) and isinstance(chunk.content, str) and chunk.content:
                        full_response += chunk.content
                        placeholder.markdown(full_response)

    if full_response:
        st.session_state.ai_recommendation = full_response
        st.session_state.messages.append(HumanMessage(content=prompt))
        st.session_state.messages.append(AIMessage(content=full_response))

        spots = extract_spots_from_text(full_response)
        st.session_state.recommended_spots = spots
        st.rerun()

# ==================== 显示推荐 + 勾选 + 图片 ====================
if st.session_state.phase == "recommend" and st.session_state.ai_recommendation:
    with st.chat_message("assistant", avatar="🌿"):
        st.markdown(st.session_state.ai_recommendation)

    spots = st.session_state.recommended_spots
    city = st.session_state.user_params.get("to_city", "")

    if spots:
        st.markdown("---")
        st.markdown("### 📸 景点一览")

        # 生成图片（只生成一次）
        if not st.session_state.spot_images:
            progress_text = st.empty()
            progress_bar = st.progress(0)
            total = len(spots)
            for idx, name in enumerate(spots):
                progress_text.text(f"🎨 AI 正在生成图片 ({idx+1}/{total})：{name}...")
                img_path = generate_spot_image(name, city)
                if img_path:
                    st.session_state.spot_images[name] = img_path
                progress_bar.progress((idx + 1) / total)
            progress_text.empty()
            progress_bar.empty()

        # 景点勾选卡片
        st.markdown("### ✅ 勾选你想去的景点")
        st.markdown("<p style='color:#888; font-size:0.9rem;'>点击景点卡片下方的复选框选择，然后点击确认</p>", unsafe_allow_html=True)

        selected = []
        spot_images = st.session_state.spot_images
        cols_per_row = 3
        for i in range(0, len(spots), cols_per_row):
            row_spots = spots[i:i+cols_per_row]
            cols = st.columns(len(row_spots))
            for j, name in enumerate(row_spots):
                with cols[j]:
                    details = parse_spot_details(st.session_state.ai_recommendation, name)
                    img_html = ""
                    img_path = spot_images.get(name, "")
                    if img_path:
                        try:
                            st.image(img_path, use_container_width=True)
                        except:
                            pass
                    else:
                        st.markdown("<div style='height:120px; background:#f0f0f0; border-radius:10px; display:flex; align-items:center; justify-content:center; color:#aaa;'>图片生成中...</div>", unsafe_allow_html=True)

                    desc = details.get("desc", "")
                    price = details.get("price", "")
                    if desc or price:
                        st.markdown(f"""
                        <div style='padding: 4px 8px;'>
                            <div style='font-size:0.8rem; color:#777;'>{desc}</div>
                            <div style='font-size:0.82rem; color:#E65100; font-weight:600;'>{price}</div>
                        </div>
                        """, unsafe_allow_html=True)

                    if st.checkbox(name, key=f"spot_{name}"):
                        selected.append(name)

        if selected:
            st.markdown(f"<div style='text-align:center; padding:10px; color:#2E7D32; font-weight:600;'>已选择 {len(selected)} 个景点：{', '.join(selected)}</div>", unsafe_allow_html=True)
            if st.button("✅ 确认选择，生成详细攻略", type="primary", use_container_width=True):
                st.session_state.phase = "plan"
                st.session_state.messages.append(HumanMessage(
                    content=f"我选好了，要去这些景点：{', '.join(selected)}。请根据这些景点帮我安排{st.session_state.user_params.get('days', 3)}天的详细行程攻略。注意路线不要走回头路，并且再次确认路线是否合理。"
                ))
                st.rerun()
        else:
            st.info("👆 请在上方勾选你想去的景点")

# ==================== 生成详细攻略阶段 ====================
if st.session_state.phase == "plan":
    with st.chat_message("assistant", avatar="🌿"):
        with st.spinner("🌿 AI 正在生成详细攻略（含路线合理性检查）..."):
            config = {"configurable": {"thread_id": st.session_state.thread_id}}
            state_input = {
                "messages": st.session_state.messages,
                "user_input": st.session_state.user_params,
                "phase": st.session_state.phase,
                "plan": st.session_state.current_plan,
            }

            full_response = ""
            placeholder = st.empty()
            for event in langgraph_app.stream(state_input, config=config, stream_mode="messages"):
                if isinstance(event, tuple) and len(event) == 2:
                    chunk, metadata = event
                    if isinstance(chunk, AIMessage) and isinstance(chunk.content, str) and chunk.content:
                        full_response += chunk.content
                        placeholder.markdown(full_response)

    if full_response:
        st.session_state.current_plan = full_response
        st.session_state.messages.append(AIMessage(content=full_response))
        st.session_state.phase = "modify"
        st.rerun()

# ==================== 后续对话（修改调整） ====================
if st.session_state.phase in ("modify", "done"):
    # 快捷按钮
    if st.session_state.current_plan:
        st.markdown("---")
        st.markdown("**💬 快捷调整：**")
        quick_cols = st.columns(4)
        quick_actions = ["太累了，减少景点", "预算超了", "加个景点", "换天安排"]
        for i, action in enumerate(quick_actions):
            with quick_cols[i]:
                if st.button(action, key=f"quick_{action}"):
                    st.session_state.messages.append(HumanMessage(content=action))
                    st.session_state.phase = "modify"

                    with st.chat_message("user", avatar="🧑"):
                        st.markdown(action)

                    with st.chat_message("assistant", avatar="🌿"):
                        with st.spinner("🌿 AI 正在调整攻略..."):
                            config = {"configurable": {"thread_id": st.session_state.thread_id}}
                            state_input = {
                                "messages": st.session_state.messages,
                                "user_input": st.session_state.user_params,
                                "phase": st.session_state.phase,
                                "plan": st.session_state.current_plan,
                            }

                            full_response = ""
                            placeholder = st.empty()
                            for event in langgraph_app.stream(state_input, config=config, stream_mode="messages"):
                                if isinstance(event, tuple) and len(event) == 2:
                                    chunk, metadata = event
                                    if isinstance(chunk, AIMessage) and isinstance(chunk.content, str) and chunk.content:
                                        full_response += chunk.content
                                        placeholder.markdown(full_response)

                    if full_response:
                        st.session_state.current_plan = full_response
                        st.session_state.messages.append(AIMessage(content=full_response))
                    st.rerun()

    # 聊天输入
    if prompt := st.chat_input("输入消息，比如：太累了减少景点 / 预算超了 / 加个景点..."):
        st.session_state.messages.append(HumanMessage(content=prompt))
        st.session_state.phase = "modify"

        with st.chat_message("user", avatar="🧑"):
            st.markdown(prompt)

        with st.chat_message("assistant", avatar="🌿"):
            with st.spinner("🌿 AI 正在调整攻略..."):
                config = {"configurable": {"thread_id": st.session_state.thread_id}}
                state_input = {
                    "messages": st.session_state.messages,
                    "user_input": st.session_state.user_params,
                    "phase": st.session_state.phase,
                    "plan": st.session_state.current_plan,
                }

                full_response = ""
                placeholder = st.empty()
                for event in langgraph_app.stream(state_input, config=config, stream_mode="messages"):
                    if isinstance(event, tuple) and len(event) == 2:
                        chunk, metadata = event
                        if isinstance(chunk, AIMessage) and isinstance(chunk.content, str) and chunk.content:
                            full_response += chunk.content
                            placeholder.markdown(full_response)

        if full_response:
            st.session_state.current_plan = full_response
            st.session_state.messages.append(AIMessage(content=full_response))

# ==================== 导出按钮 ====================
if st.session_state.current_plan:
    st.markdown("---")
    col1, col2 = st.columns([3, 1])
    with col2:
        if st.button("📄 导出 Word 攻略", type="primary", use_container_width=True):
            params = st.session_state.user_params
            itinerary = {
                "title": f"{params.get('to_city', '旅行')}{params.get('days', '')}日攻略",
                "overview": st.session_state.current_plan,
                "dep_datetime": params.get("dep_datetime", ""),
                "ret_datetime": params.get("ret_datetime", ""),
                "user_type": params.get("user_type", ""),
                "budget_total": params.get("budget", 0),
                "days": [],
                "budget": {},
                "spot_images": st.session_state.get("spot_images", {}),
            }
            try:
                filepath = export_to_word(itinerary)
                with open(filepath, "rb") as f:
                    st.download_button(
                        label="⬇️ 下载 Word 文件",
                        data=f.read(),
                        file_name=os.path.basename(filepath),
                        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                    )
                st.success("Word 文件生成成功！")
            except Exception as e:
                st.error(f"导出失败：{e}")
