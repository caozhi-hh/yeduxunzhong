"""T1-B-1 首条回归测试：从历史恢复行程时，同行人数不得被重置为 1。

被固化的缺陷（P0-2，见 T1-A 审计报告 D 节）
-------------------------------------------
前端把参数写进 localStorage 时用的键名是 `companions`
（frontend/src/app/recommend/page.tsx:234），这份 params 会**原样**落到
history 表（frontend/src/app/plan/page.tsx:148 → POST /api/history），
从历史页打开时又原样写回 localStorage（frontend/src/app/history/page.tsx:48）。

但后端读取时只认 `companions_count`：
    backend/main.py:484   companions = params.get('companions_count', 1)
→ 键名不匹配时**静默退回默认值 1**，于是"4 人同行"的行程被按 1 人生成。

本测试覆盖的就是这条**历史恢复路径**：请求体形状与真实历史数据一致
（只有 `companions`，没有 `companions_count`），断言后端在拼行程 prompt 时
实际使用的是 4 人。

测试入口与 mock 边界（全部离线，不触网、不产生费用）
--------------------------------------------------
入口：真实 ASGI 应用 `backend/main.py` 的**两步生产链路**（不复制任何解析逻辑）：

    ① POST /api/recommend      带着历史数据的 params → 生产代码把它存进
                               session["params"]（backend/main.py:453）
    ② POST /api/generate-plan  平台期只传 session_id + spots；同行人数**只能**
                               来自 session["params"]（backend/main.py:472, 484）

    这一步很关键：`/api/recommend` 自己拼的 prompt 是**景点推荐**用的，不含同行人数；
    真正生成行程、使用 `同行：N人` 的是 `/api/generate-plan`（backend/main.py:495）。
    因此只打 /api/recommend 无法观察到该缺陷 —— 必须走完这两步。

mock：① `main.get_weather`  → 固定返回失败文案，跳过天气查询（避免 requests 外呼）
      ② `main.stream_llm`    → 路由真正调用的模块级函数，固定产出并**捕获收到的
                              messages**。它在"行程 prompt 已拼好之后"才被调用，
                              因此不影响被测的参数解析逻辑。
                              ⚠️ 不能去 patch `main.llm.stream`：llm 是 pydantic 模型
                              （ChatAnthropic），赋值不存在的字段会抛 ValueError，
                              那属于 mock 失效，会制造"假红灯"。
断言：从捕获到的**行程 prompt**（/api/generate-plan 那次）里取出
      `同行：N人` 中的 N —— 该片段由生产模板 backend/main.py:495 生成，
      因此 N 就是生产代码实际使用的同行人数。

为什么用子进程
--------------
`database.DB_PATH` 是 import 时定下的模块级常量（backend/database.py:7-10）。
pytest 进程里可能已经 import 过 `main`（例如基础设施自检会导入它以取路由表），
那样临时库设置对已加载模块就失效了。子进程能保证：
    "先设 TRAVEL_DB_PATH → 再 import main" 这个生产等价的顺序**必然成立**，
且完全不复用父进程的模块状态。子进程返回码即断言结果（0=通过，非 0=该断言失败）。

⚠️ 隔离盲区（本轮实测发现，已在测试内修好）
------------------------------------------
`TRAVEL_DB_PATH` **只**管 SQLite 库路径，**管不住会话落盘**：
`backend/main.py:36` 把 `SESSION_DIR` 硬编码为 `backend/data/sessions`。
第一版测试因此把会话文件写进了**真实**的 `backend/data/sessions/`（已取证并清理）。
现在测试会显式把 `main.SESSION_DIR` 重定向到临时目录，
并断言"临时目录里有会话文件 + 真实目录里没有该会话"，防止此类污染再次发生。
（`_session_path()` 在调用时读取该全局变量，见 backend/main.py:281-283，故运行时改写有效。）
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = PROJECT_ROOT / "backend"
REAL_DB = BACKEND_DIR / "data" / "travel_planner.db"
# 真实会话落盘目录（backend/main.py:36 硬编码）——测试绝不能写这里
REAL_SESSIONS_DIR = BACKEND_DIR / "data" / "sessions"

# ---------------------------------------------------------------- 确定性输入
# 与真实历史数据同形状：只有 companions，没有 companions_count。
HISTORY_RESTORED_PARAMS = {
    "from_city": "西安",
    "to_city": "西安",
    "days": 3,
    "budget": 3000,
    "travel_type": "性价比出行",
    "user_type": "学生",
    "dep_date": "2026-11-01",
    "ret_date": "2026-11-03",
    "transport_go": "高铁",
    "transport_back": "高铁",
    "accommodation": "经济酒店",
    "companions": 4,              # ← 前端历史数据的真实键名
    "companion_type": "同学",
}
EXPECTED_TRAVELERS = 4
SESSION_ID = "t1b1-history-restore"
# /api/generate-plan 需要的景点清单（固定输入，与人数解析无关）
SELECTED_SPOTS = ["秦始皇兵马俑博物馆", "西安城墙"]

# 从生产 prompt 模板中取"同行：N人"的 N（模板见 backend/main.py:495）
_TRAVELERS_RE = re.compile(r"同行：(\d+)人")

# 子进程脚本：只做"调真实接口 + 离线 mock + 把结果打成一行 JSON"，不含任何重做的解析逻辑。
_CHILD_SCRIPT = r'''
import asyncio, json, re, sys

import httpx
import main

CAPTURED = {"calls": []}

def _fake_stream_llm(messages, max_retries=2):
    """替代 main.stream_llm：完全不联网，逐次捕获真正传给模型的 messages。"""
    CAPTURED["calls"].append(messages)
    yield "data: " + json.dumps({"type": "chunk", "content": "【离线桩输出】"}, ensure_ascii=False) + "\n\n"
    return "【离线桩输出】不调用真实模型"

def _fake_weather(city):
    """替代 main.get_weather：固定返回失败文案 → 路由跳过天气注入（不触网）。"""
    CAPTURED["weather_called_with"] = city
    return "天气查询失败：离线测试桩"

def _pick_prompt(calls):
    """在所有被捕获的 prompt 里找『同行：N人』那一份（即 /api/generate-plan 的行程 prompt）。"""
    for messages in calls:
        for m in messages:
            content = getattr(m, "content", "")
            if isinstance(content, str) and "同行：" in content:
                return content
    return ""

async def run():
    # 注意：llm 是 pydantic 模型，不能改 main.llm.stream（会 ValueError）。
    # 真正该替换的边界是模块级的 stream_llm —— 路由调的就是它。
    main.stream_llm = _fake_stream_llm
    main.get_weather = _fake_weather

    # ⚠️ 会话落盘目录必须一起重定向：
    # main.SESSION_DIR 是硬编码常量（backend/main.py:36），不受 TRAVEL_DB_PATH 影响，
    # 不重定向就会把测试会话写进**真实**的 backend/data/sessions/。
    # _session_path() 在调用时读该全局变量（backend/main.py:281-283），因此运行时改写有效。
    import os as _os
    sess_dir = sys.argv[4]
    _os.makedirs(sess_dir, exist_ok=True)
    main.SESSION_DIR = sess_dir

    session_id = sys.argv[2]
    params = json.loads(sys.argv[1])
    spots = json.loads(sys.argv[3])

    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # ---- 第 1 步：与真实前端一致，把历史数据形状的 params 交给 /api/recommend
        resp_recommend = await client.post(
            "/api/recommend", json={"params": params, "session_id": session_id}
        )
        # ---- 第 2 步：只传 session_id + spots，人数只能来自 session["params"]
        resp_plan = await client.post(
            "/api/generate-plan", json={"session_id": session_id, "spots": spots}
        )

    prompt = _pick_prompt(CAPTURED["calls"])
    match = re.search(r"同行：(\d+)人", prompt)
    seen = int(match.group(1)) if match else None

    result = {
        "recommend_status": resp_recommend.status_code,
        "plan_status": resp_plan.status_code,
        "stream_llm_calls": len(CAPTURED["calls"]),
        "weather_called_with": CAPTURED.get("weather_called_with"),
        "companions_seen": seen,
        "has_companions_line": "同行：" in prompt,
        "session_params_in_module": main.sessions.get(session_id, {}).get("params"),
        "plan_body_head": resp_plan.text[:160],
        "session_dir_in_module": main.SESSION_DIR,
        "session_file_written": _os.path.isfile(_os.path.join(sess_dir, session_id + ".json")),
    }
    print("OFFLINE_CHECK " + json.dumps(result, ensure_ascii=False))

asyncio.run(run())
'''


def _run_child(tmp_db: Path, params: dict) -> tuple[subprocess.CompletedProcess, dict | None, str]:
    """在新进程里跑真实 ASGI 入口，返回 (进程结果, 解析出的结果字典, 原始输出)。"""
    env = dict(os.environ)
    # 生产等价的顺序：这两个变量必须在 import main 之前生效
    env["TRAVEL_DB_PATH"] = str(tmp_db)
    env["JWT_SECRET"] = "t1b1-test-secret-not-a-real-key-0123456789abcdef"
    env["PYTHONPATH"] = str(BACKEND_DIR)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"

    # 会话落盘也要隔离：SESSION_DIR 是硬编码常量（backend/main.py:36），
    # 不受 TRAVEL_DB_PATH 影响 —— 不重定向就会写进真实 backend/data/sessions/。
    tmp_sessions = Path(tmp_db).parent / "sessions"
    tmp_sessions.mkdir(parents=True, exist_ok=True)

    proc = subprocess.run(
        [sys.executable, "-c", _CHILD_SCRIPT,
         json.dumps(params, ensure_ascii=False),
         SESSION_ID,
         json.dumps(SELECTED_SPOTS, ensure_ascii=False),
         str(tmp_sessions)],
        cwd=str(BACKEND_DIR),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
    )

    parsed = None
    for line in (proc.stdout or "").splitlines():
        if line.startswith("OFFLINE_CHECK "):
            parsed = json.loads(line[len("OFFLINE_CHECK "):])
            break
    raw = (proc.stdout or "") + ("\n--- stderr ---\n" + (proc.stderr or "") if proc.stderr else "")
    return proc, parsed, raw


def _skip_if_invalid(proc, result, raw) -> dict:
    """把"环境/夹具/抓取边界失效"与"业务缺陷"分开：前者一律判为无效信号。"""
    assert result is not None, (
        "子进程未产出结果行 → 属环境或导入问题，不是有效的测试信号。\n"
        f"returncode={proc.returncode}\n{raw}"
    )
    assert result["recommend_status"] == 200, f"/api/recommend 未返回 200：{raw}"
    assert result["plan_status"] == 200, f"/api/generate-plan 未返回 200：{raw}"
    assert result["stream_llm_calls"] >= 2, (
        "两步链路的 stream_llm 未被各调用一次 → 请求没走到拼行程 prompt 的位置，测试无效。\n"
        f"returncode={proc.returncode}\n{raw}"
    )
    assert result["has_companions_line"] is True, (
        "捕获到的 prompt 里没有『同行：』片段 → 抓取边界失效，测试无效。\n"
        f"returncode={proc.returncode}\n{raw}"
    )
    assert result["companions_seen"] is not None, f"未能从 prompt 解析出人数：{raw}"
    # 不触网证据：天气桩确实被调用（真查询路径被替换）
    assert result["weather_called_with"] == HISTORY_RESTORED_PARAMS["to_city"], (
        f"天气桩未被按预期调用：{result['weather_called_with']}"
    )
    # 隔离证据：会话落盘被重定向到临时目录，且确实写成功
    assert Path(result["session_dir_in_module"]).resolve() != REAL_SESSIONS_DIR.resolve(), (
        f"SESSION_DIR 未被重定向，测试会污染真实 sessions：{result['session_dir_in_module']}"
    )
    assert result["session_file_written"] is True, (
        "临时 sessions 目录里没有生成会话文件 → 落盘隔离未真正生效。\n"
        f"returncode={proc.returncode}\n{raw}"
    )
    # 防回归：真实 sessions 目录里绝不能出现测试会话
    assert not (REAL_SESSIONS_DIR / f"{SESSION_ID}.json").exists(), (
        f"测试会话被写进了真实 sessions 目录：{REAL_SESSIONS_DIR / (SESSION_ID + '.json')}"
    )
    return result


def test_history_restore_keeps_travelers_count(temp_db):
    """【回归 · 当前应为红灯】历史恢复的参数形状（只有 `companions`）必须仍被识别为 4 人。

    这是真实缺陷所在路径：
        请求参数键名 = companions（前端 localStorage 的真实键名）
        后端读取键名 = companions_count（backend/main.py:484）
        → 不匹配 → 静默退回默认值 1
    """
    assert Path(temp_db).resolve() != REAL_DB.resolve(), "夹具给出了真实库路径"
    real_db_before = (REAL_DB.stat().st_size, REAL_DB.stat().st_mtime_ns)

    proc, result, raw = _run_child(Path(temp_db), HISTORY_RESTORED_PARAMS)
    result = _skip_if_invalid(proc, result, raw)

    # 前置事实：历史数据里的 companions=4 确实进入了 session（不是"参数没传进去"）
    assert result["session_params_in_module"]["companions"] == EXPECTED_TRAVELERS, (
        f"参数未按预期进入 session：{result['session_params_in_module']}"
    )

    # -------- 被测断言：后端实际使用的同行人数 --------
    assert result["companions_seen"] == EXPECTED_TRAVELERS, (
        "历史恢复后同行人数被错误处理：\n"
        f"  请求参数（历史数据形状）= {HISTORY_RESTORED_PARAMS}\n"
        f"  后端拼行程 prompt 时实际使用 = {result['companions_seen']} 人\n"
        f"  期望                     = {EXPECTED_TRAVELERS} 人\n"
        "  根因位置：backend/main.py:484 只读 params.get('companions_count', 1)，"
        "而历史数据里的键名是 'companions'。\n"
        f"  子进程 returncode={proc.returncode}\n{raw}"
    )

    # -------- 事后：真实库未被触碰 --------
    real_db_after = (REAL_DB.stat().st_size, REAL_DB.stat().st_mtime_ns)
    assert real_db_after == real_db_before, "测试过程中真实库被改动了"


def test_control_companions_count_key_is_honored(temp_db):
    """【对照 · 当前应为绿灯】用 `companions_count` 时人数必须被正确识别为 4。

    这条对照测试的作用是**排除"测试本身测错了东西"**，而不是重复覆盖：
    若本对照也失败，说明问题出在测试/环境而非 P0-2 键名分歧；
    只有当"对照绿 + 回归红"同时成立，红灯才真正指向该缺陷。

    它也解释了为什么 P0-2 危险：`/api/recommend` 直接调用时键名是对的
    （frontend/src/app/recommend/page.tsx:161），
    但只要参数来自 localStorage（历史恢复路径），键名就变成 `companions`。
    """
    assert Path(temp_db).resolve() != REAL_DB.resolve(), "夹具给出了真实库路径"

    control_params = dict(HISTORY_RESTORED_PARAMS)
    del control_params["companions"]
    control_params["companions_count"] = EXPECTED_TRAVELERS

    proc, result, raw = _run_child(Path(temp_db), control_params)
    result = _skip_if_invalid(proc, result, raw)

    assert result["session_params_in_module"].get("companions") is None, (
        "对照输入不应包含 companions 键"
    )
    assert result["companions_seen"] == EXPECTED_TRAVELERS, (
        "对照测试失败 → 说明测试或环境有问题，回归红灯不能算作有效业务证据：\n"
        f"  control params = {control_params}\n"
        f"  实际使用 = {result['companions_seen']} 人，期望 {EXPECTED_TRAVELERS} 人\n"
        f"  returncode={proc.returncode}\n{raw}"
    )