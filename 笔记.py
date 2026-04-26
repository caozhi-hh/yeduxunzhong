# ============================================
# 野渡寻踪 — AI 旅行攻略规划师 项目笔记
# ============================================
# 项目周期：2026.04 - 2026.04
# 技术栈：Next.js 16 + FastAPI + LangChain + Qwen + 通义万相
# 在线地址：https://41229068.yeduxunzhong.pages.dev
# ============================================

# ============================================
# 一、项目概述
# ============================================
# "野渡寻踪"是一个 AI 旅行攻略生成器，用户输入出发城市、目的地、
# 预算、时间等参数后，AI 自动推荐景点、规划详细行程、生成攻略。
# 支持景点图片生成、Word 导出、预约抢票提醒等功能。

# ============================================
# 二、架构设计（前后端分离）
# ============================================
# 前端：Next.js 16（App Router）+ React 19 + Tailwind CSS + Framer Motion
#   - 静态导出部署到 Cloudflare Pages
#   - 三页面：首页 / 推荐页 / 攻略页
#
# 后端：FastAPI + Python 3.11
#   - Docker 部署到 HuggingFace Spaces
#   - SSE 流式输出
#   - LangChain + Qwen 模型（通义千问）
#
# 通信：REST API + SSE（Server-Sent Events）
#
# 目录结构：
#   frontend/          → Next.js 前端
#     app/page.tsx           → 首页（品牌展示）
#     app/recommend/page.tsx → 推荐页（参数填写 + 景点勾选）
#     app/plan/page.tsx      → 攻略页（AI 对话修改）
#     lib/api.ts             → API 请求封装
#   backend/           → FastAPI 后端
#     main.py                → API 路由（5个接口）
#     config.py              → 模型配置（Qwen API）
#     tools/images.py        → 图片生成（通义万相）
#     tools/export.py        → Word 导出（绿色主题排版）
#     Dockerfile             → Docker 构建
#     requirements.txt       → Python 依赖

# ============================================
# 三、核心知识点
# ============================================

# --- 1. SSE 流式输出 ---
# 前后端通过 SSE 实现流式对话，用户看到 AI 逐字输出效果
#
# 后端（FastAPI）：
#   from fastapi.responses import StreamingResponse
#
#   def stream():
#       yield from stream_llm(messages)  # yield from 传递生成器
#       yield f'data: {json.dumps({"type": "done"})}\n\n'
#
#   return StreamingResponse(stream(), media_type="text/event-stream")
#
# 前端（fetch + ReadableStream）：
#   const res = await fetch(url, { method: "POST", body: ... })
#   const reader = res.body.getReader()
#   while (true) {
#       const { done, value } = await reader.read()
#       if (done) break
#       // 解析 SSE data: 行
#   }
#
# ⚠️ 关键点：data 行必须以 \n\n 结尾，否则浏览器不会触发

# --- 2. LangChain + OpenAI 兼容 API ---
# Qwen 通过 DashScope 提供 OpenAI 兼容接口
# langchain_openai 1.2.1 的参数名变了：
#
#   # ❌ 旧版写法（会报错）
#   ChatOpenAI(openai_api_key=..., openai_api_base=...)
#
#   # ✅ 新版写法
#   ChatOpenAI(api_key=..., base_url=...)
#
#   # config.py 配置
#   ARK_API_KEY = "sk-xxx"
#   ARK_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
#   CHAT_MODEL = "qwen-max"

# --- 3. Base64 图片传输 ---
# 图片不保存文件系统，直接 Base64 编码传输
#
# 后端：response_format: "b64_json" → 直接拿到 base64
# 前端：<img src="data:image/png;base64,..." />
#
# ⚠️ 浏览器安全策略禁止 file:// 协议显示图片

# --- 4. Word 导出（python-docx）---
# 绿色主题排版，emoji 清除防乱码
#
# from docx import Document
# from docx.shared import Pt, Cm, RGBColor
# import emoji
#
# _strip_emoji(text)  # 清除 emoji，防止 Word 乱码
# # 主题色：深绿 #1B5E20、主绿 #2E7D32、浅绿 #4CAF50
# # 表头：白字绿底、交替行浅绿背景

# --- 5. Next.js 静态导出 ---
# 部署到 Cloudflare Pages 需要静态导出
#
# next.config.ts:
#   const nextConfig = {
#     output: "export",       // 静态导出
#     images: { unoptimized: true },  // 禁用图片优化
#   }
#
# 构建后生成 out/ 目录，直接部署为静态文件
# ⚠️ 环境变量 NEXT_PUBLIC_* 在构建时嵌入，部署后改不了

# ============================================
# 四、部署方案
# ============================================
# 前端：Cloudflare Pages（国内可访问）
#   - Root Directory: frontend
#   - Build command: npm run build
#   - Output: out
#   - 环境变量：NEXT_PUBLIC_API_BASE = https://powercz-yeduxunzhong-api.hf.space
#
# 后端：HuggingFace Spaces（Docker）
#   - Space: PowerCZ/yeduxunzhong-api
#   - 端口：7860
#   - CMD: uvicorn main:app --host 0.0.0.0 --port 7860
#
# ⚠️ 踩坑记录：
#   - Vercel（vercel.app）在国内被墙，手机打不开
#   - HF Spaces 环境变量会覆盖 config.py 默认值
#   - HF Spaces 文件上传要保持目录结构（tools/ 前缀）
#   - Dockerfile 的 EXPOSE 端口要和 CMD 一致

# ============================================
# 五、API 接口设计
# ============================================
# POST /api/recommend       → 景点推荐（SSE 流式）
#   请求：{ params: { from_city, to_city, days, budget, ... }, session_id }
#   响应：SSE data: {"type": "chunk", "content": "..."}
#         SSE data: {"type": "done", "spots": ["景点1", "景点2"]}
#
# POST /api/generate-plan   → 生成详细攻略（SSE 流式）
#   请求：{ session_id, spots: ["景点1", "景点2"] }
#
# POST /api/modify          → 修改攻略（SSE 流式）
#   请求：{ session_id, message: "太累了，减少景点" }
#
# POST /api/generate-image  → 生成景点图片
#   请求：{ spot_name, city }
#   响应：{ status: "ok", base64: "data:image/png;base64,..." }
#
# GET  /api/export-word     → 导出 Word 文档
#   参数：session_id, title

# ============================================
# 六、学到的经验
# ============================================
# 1. SSE 流式输出比 WebSocket 更适合单向推送（AI 生成）
# 2. langchain_openai 新版参数名变了，注意版本兼容
# 3. 图片在浏览器中必须用 Base64 或 URL，不能用 file://
# 4. python-docx 导出中文文档要处理 emoji（会乱码）
# 5. 部署时注意：Vercel 国内被墙、HF Spaces 环境变量优先级
# 6. Docker 部署时 EXPOSE 端口要和 uvicorn 端口一致
# 7. NEXT_PUBLIC_ 环境变量是构建时嵌入的，改了要重新构建
# 8. 前后端分离部署时注意 CORS 配置（allow_origins=["*"]）
# 9. yield from 可以把子生成器的值传递给外层生成器
# 10. 预约抢票提醒需要根据出发日期计算具体抢票日期和时间


# ============================================
# 七、课后作业
# ============================================
# 1. 给攻略页添加"分享"功能，生成分享链接或海报图片
# 2. 实现用户登录，保存历史攻略到数据库
# 3. 添加地图可视化，在地图上展示景点位置和路线
# 4. 实现多语言支持（中文/英文）
# 5. 尝试把后端也部署到国内云平台（如阿里云函数计算），提升访问速度
