"""T1-C1 验收测试：行程编辑后的保存与恢复（在临时库上跑，不碰真实数据）。

覆盖任务要求的验收场景（1–8），并直接证据化"刷新后能否恢复"。

为什么这样测"刷新"
------------------
刷新对后端而言等价于：**丢弃前端内存状态，重新调一次读取接口**。
本项目两端的接口一一对应：
    frontend/src/lib/api.ts   fetchTrip(id)  ->  GET /api/trips/{id}
    frontend/src/lib/api.ts   fetchTrips()   ->  GET /api/trips
因此"模拟刷新"= 丢掉本地引用，重新调用 `trips.get_trip()` / `trips.list_trips()`
（两条路由只是这两层函数的薄封装，见 backend/main.py:866-882）。

前端侧本轮的真实缺陷（无"当前行程"标识）无法用 pytest 覆盖，
由 `npm run build` 做类型/编译验证，并需人工在浏览器按验收步骤确认；
本文件负责证明**后端确实保存了全部编辑内容且能原样取回**——
即"刷新后丢数据"不是后端的锅，前端修复后有据可依。
"""
from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def _make_user(db_path: Path, nickname: str) -> int:
    """在临时库里造一个测试用户（trips.user_id 有外键约束，必须先建用户）。"""
    con = sqlite3.connect(str(db_path))
    try:
        cur = con.execute(
            "INSERT INTO users (nickname, password_hash) VALUES (?, ?)",
            (nickname, "x"),
        )
        con.commit()
        return int(cur.lastrowid)
    finally:
        con.close()


async def _prep_db(temp_db):
    """建表：init_db() 读的是环境变量 TRAVEL_DB_PATH，夹具已把它指向临时库。"""
    import database

    assert database.DB_PATH == str(temp_db), "临时库未被夹具接管，拒绝继续"
    await database.init_db()


async def test_trip_edits_survive_reload(temp_db):
    """场景 1–4：加多个景点 → 跨天调整 + 同日改序 → "刷新"后完全一致。"""
    await _prep_db(temp_db)
    import trips

    uid = _make_user(temp_db, "t1c1-user-a")

    trip_id = await trips.create_trip(uid, title="西安三日", city="西安", days=3)
    full = await trips.get_trip(trip_id, uid)
    assert full is not None
    day_ids = [d["id"] for d in full["days"]]
    assert len(day_ids) == 3, "create_trip 应预建 3 个空天"

    # --- 场景 1：添加多个景点 ---
    p1 = await trips.add_place(day_ids[0], uid, {"name": "兵马俑", "lat": 34.38, "lon": 109.27})
    p2 = await trips.add_place(day_ids[0], uid, {"name": "华清宫", "lat": 34.36, "lon": 109.21})
    p3 = await trips.add_place(day_ids[1], uid, {"name": "大雁塔", "lat": 34.21, "lon": 108.96})
    p4 = await trips.add_place(day_ids[1], uid, {"name": "陕西历史博物馆", "lat": 34.22, "lon": 108.95})
    assert all(x is not None for x in (p1, p2, p3, p4)), "添加地点失败"

    # --- 场景 2a：把「华清宫」挪到第 2 天 ---
    assert await trips.move_place(p2, uid, day_ids[1], 0) is True
    # --- 场景 2b：在第 1 天内部把「兵马俑」改到末尾（同日改序）---
    assert await trips.move_place(p1, uid, day_ids[0], 5) is True  # 越界索引会被夹到末尾

    # ================= 模拟"刷新页面"：丢弃本地引用，重新读取 =================
    reread = await trips.get_trip(trip_id, uid)
    assert reread is not None, "刷新后读取不到行程"
    assert reread["id"] == trip_id
    assert reread["title"] == "西安三日"
    assert reread["city"] == "西安"
    assert len(reread["days"]) == 3

    first_day_names = [p["name"] for p in reread["days"][0]["places"]]
    second_day_names = [p["name"] for p in reread["days"][1]["places"]]

    # --- 场景 3–4：景点、所属日期、顺序与刷新前一致 ---
    assert first_day_names == ["兵马俑"], f"第 1 天内容不符：{first_day_names}"
    assert second_day_names == ["华清宫", "大雁塔", "陕西历史博物馆"], (
        f"第 2 天内容/顺序不符：{second_day_names}"
    )

    # 排序字段确实被持久化（不是靠返回顺序碰巧对上）
    orders = [(p["name"], p["sort_order"]) for p in reread["days"][1]["places"]]
    assert orders == [("华清宫", 0), ("大雁塔", 1), ("陕西历史博物馆", 2)], orders


async def test_latest_edit_is_not_overwritten_by_stale_data(temp_db):
    """场景 6：再次修改后"刷新"，取到的是**最新**修改，不会被旧数据覆盖。"""
    await _prep_db(temp_db)
    import trips

    uid = _make_user(temp_db, "t1c1-user-b")
    trip_id = await trips.create_trip(uid, title="二次修改", city="成都", days=2)
    full = await trips.get_trip(trip_id, uid)
    day_ids = [d["id"] for d in full["days"]]

    pid = await trips.add_place(day_ids[0], uid, {"name": "宽窄巷子"})
    # 第一次修改：挪到第 2 天
    await trips.move_place(pid, uid, day_ids[1], 0)
    first_read = await trips.get_trip(trip_id, uid)
    assert [p["name"] for p in first_read["days"][0]["places"]] == []
    assert [p["name"] for p in first_read["days"][1]["places"]] == ["宽窄巷子"]

    # 第二次修改：挪回第 1 天
    await trips.move_place(pid, uid, day_ids[0], 0)
    second_read = await trips.get_trip(trip_id, uid)
    assert [p["name"] for p in second_read["days"][0]["places"]] == ["宽窄巷子"], (
        "刷新后拿到的是旧数据（第二次修改被覆盖）"
    )
    assert [p["name"] for p in second_read["days"][1]["places"]] == []


async def test_removed_place_stays_removed_after_reload(temp_db):
    """删除同样要持久化：刷新后不能"复活"。"""
    await _prep_db(temp_db)
    import trips

    uid = _make_user(temp_db, "t1c1-user-c")
    trip_id = await trips.create_trip(uid, city="重庆", days=1)
    full = await trips.get_trip(trip_id, uid)
    day_id = full["days"][0]["id"]

    keep = await trips.add_place(day_id, uid, {"name": "洪崖洞"})
    drop = await trips.add_place(day_id, uid, {"name": "磁器口"})
    assert await trips.delete_place(drop, uid) is True

    reread = await trips.get_trip(trip_id, uid)
    names = [p["name"] for p in reread["days"][0]["places"]]
    assert names == ["洪崖洞"], f"删除未持久化：{names}"
    assert keep is not None


async def test_empty_state_initialises_cleanly(temp_db):
    """场景 7：全新用户 / 没有任何行程时，读取接口正常返回空，不报错。"""
    await _prep_db(temp_db)
    import trips

    uid = _make_user(temp_db, "t1c1-empty-user")
    assert await trips.list_trips(uid) == [], "空用户应返回空列表"
    assert await trips.get_trip(123456, uid) is None, "不存在的行程应返回 None（路由层转 404）"


async def test_user_and_trip_isolation(temp_db):
    """场景 8：不同用户之间、以及猜 id 都不能互相读写。"""
    await _prep_db(temp_db)
    import trips

    uid_a = _make_user(temp_db, "t1c1-owner")
    uid_b = _make_user(temp_db, "t1c1-intruder")

    trip_a = await trips.create_trip(uid_a, title="A 的行程", city="杭州", days=1)
    full_a = await trips.get_trip(trip_a, uid_a)
    day_a = full_a["days"][0]["id"]
    place_a = await trips.add_place(day_a, uid_a, {"name": "西湖"})

    # A 自己看得到
    assert (await trips.get_trip(trip_a, uid_a)) is not None
    assert len(await trips.list_trips(uid_a)) == 1

    # B 猜 id 看不到 A 的行程 / 列表里也没有
    assert await trips.get_trip(trip_a, uid_b) is None, "越权读到了别人的行程"
    assert await trips.list_trips(uid_b) == [], "越权看到了别人的行程列表"

    # B 不能改 / 删 A 的东西
    assert await trips.update_trip(trip_a, uid_b, {"title": "篡改"}) is False
    assert await trips.move_place(place_a, uid_b, day_a, 0) is False
    assert await trips.delete_place(place_a, uid_b) is False
    assert await trips.delete_day(day_a, uid_b) is False

    # A 的数据完好无损
    after = await trips.get_trip(trip_a, uid_a)
    assert after["title"] == "A 的行程"
    assert [p["name"] for p in after["days"][0]["places"]] == ["西湖"]


async def test_two_tabs_each_open_their_own_trip(temp_db):
    """多标签页不变量：两趟行程可各自独立读取，互不干扰。

    为什么需要这条测试：
    "当前行程"从 localStorage（整个浏览器一个值）改成 URL 查询参数 ?trip=<id>
    （每个标签页各自一份）之后，前端能保证"A 标签开 1、B 标签开 2"互不覆盖。
    前端这一层没有 DOM 测试环境，所以这里断言**支撑该能力的数据层不变量**：
    按 id 读取任意一趟行程，取回的永远是它自己的完整内容，且交替读取不会串数据。

    注意：本测试**不**验证 URL 行为本身（那是浏览器交互，需人工验收）；
    它验证的是"URL 里的 id 一旦指向某行程，就一定拿得到它自己的数据"。
    """
    import asyncio

    await _prep_db(temp_db)
    import trips

    uid = _make_user(temp_db, "t1c1-multitab")

    trip_a = await trips.create_trip(uid, title="行程A", city="拉萨", days=1)
    trip_b = await trips.create_trip(uid, title="行程B", city="北京", days=2)
    day_a = (await trips.get_trip(trip_a, uid))["days"][0]["id"]
    day_b = (await trips.get_trip(trip_b, uid))["days"][0]["id"]

    await trips.add_place(day_a, uid, {"name": "布达拉宫", "lat": 29.657905, "lon": 91.117398})
    await trips.add_place(day_a, uid, {"name": "八廓街", "lat": 29.65286, "lon": 91.131798})
    await trips.add_place(day_b, uid, {"name": "天安门", "lat": 39.907359, "lon": 116.391263})

    # 交替读取（模拟两个标签页各自刷新），每次都必须是"自己那一趟"
    for _ in range(3):
        a = await trips.get_trip(trip_a, uid)
        assert a["title"] == "行程A" and a["city"] == "拉萨"
        assert len(a["days"]) == 1
        assert [p["name"] for p in a["days"][0]["places"]] == ["布达拉宫", "八廓街"]

        b = await trips.get_trip(trip_b, uid)
        assert b["title"] == "行程B" and b["city"] == "北京"
        assert len(b["days"]) == 2
        assert [p["name"] for p in b["days"][0]["places"]] == ["天安门"]

        assert day_a != day_b, "两趟行程的 day id 不能相同，否则 URL 传错会串数据"
        await asyncio.sleep(0)

    # 改 B 不能影响 A
    await trips.add_place(day_b, uid, {"name": "故宫", "lat": 39.916345, "lon": 116.397155})
    a_after = await trips.get_trip(trip_a, uid)
    assert [p["name"] for p in a_after["days"][0]["places"]] == ["布达拉宫", "八廓街"], (
        "改动 B 影响到了 A —— 两趟行程的数据串了"
    )

    # URL 参数指向别人的行程时，数据层必须取不到（前端会退化为空态，不伪造内容）
    other_uid = _make_user(temp_db, "t1c1-multitab-other")
    assert await trips.get_trip(trip_a, other_uid) is None
    assert await trips.get_trip(trip_b, other_uid) is None


async def test_day_and_place_edits_refresh_trip_updated_at(temp_db):
    """行程内容变了，trips.updated_at 必须跟着变（否则列表排序/时间戳停在旧值）。"""
    await _prep_db(temp_db)
    import trips

    uid = _make_user(temp_db, "t1c1-ts-user")
    trip_id = await trips.create_trip(uid, city="苏州", days=2)
    full = await trips.get_trip(trip_id, uid)
    day_ids = [d["id"] for d in full["days"]]

    def updated_at() -> str:
        con = sqlite3.connect(str(temp_db))
        try:
            return con.execute(
                "SELECT updated_at FROM trips WHERE id = ?", (trip_id,)
            ).fetchone()[0]
        finally:
            con.close()

    before = updated_at()

    # 让时间戳有区分度：SQLite 的 datetime('now') 精度是秒
    import asyncio

    await asyncio.sleep(1.1)
    pid = await trips.add_place(day_ids[0], uid, {"name": "拙政园"})
    after_add = updated_at()
    assert after_add > before, f"新增地点后 trips.updated_at 未前进：{before} -> {after_add}"

    await asyncio.sleep(1.1)
    # 删一天也是"行程内容变更"，必须刷新 updated_at（本轮修复点之一）
    assert await trips.delete_day(day_ids[1], uid) is True
    after_delete_day = updated_at()
    assert after_delete_day > after_add, (
        f"删除天后 trips.updated_at 未前进：{after_add} -> {after_delete_day}"
    )

    await asyncio.sleep(1.1)
    # 删地点同样必须刷新（本轮修复点之二）
    assert await trips.delete_place(pid, uid) is True
    after_delete_place = updated_at()
    assert after_delete_place > after_delete_day, (
        f"删除地点后 trips.updated_at 未前进：{after_delete_day} -> {after_delete_place}"
    )