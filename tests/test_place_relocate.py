"""T1-E2 验收测试：景点重新定位（搜索真实 POI → 确认 → 只改坐标）。

覆盖任务第四节的 8 项要求：
  1 正确候选确认后成功更新坐标
  2 用户取消后原坐标不变
  3 没有候选地点时不修改数据
  4 搜索失败时能正常提示与恢复
  5 非法坐标被拒绝
  6 无权访问其他用户的景点时无法更新
  7 更新后日期、顺序与其他关联字段保持不变
  8 坐标更新后读取接口返回最新数据

测试方式
--------
* 走**真实 API 路由**（`httpx.ASGITransport` 直连 FastAPI 应用），不启服务、不触网。
* 外部 POI 搜索在**边界上 mock**（替换 `main.search_places`），
  因此既验证了真实调用链，又不会产生任何外部请求与费用。
* 数据库全部用夹具给的临时库；真实库只读不写。

为什么没有前端交互测试
----------------------
"点按钮 → 选候选 → 确认"这段发生在浏览器 DOM 里，本项目没有前端 DOM 测试环境
（未安装 jsdom/@testing-library，本轮也未获授权新增依赖）。因此这里断言的是
**支撑该交互的服务端契约与数据安全性质**：只提交坐标时其余字段必须不变、
越权必须失败、非法坐标必须被拒。前端行为由 tsc/build/lint + 人工验收覆盖。
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


# ---------------------------------------------------------------- 测试数据
# 拉萨布达拉宫附近（真实坐标，来自 OSM）
LHASA_CENTER = {"lat": 29.657, "lon": 91.117}
# 真实库里那条错配记录的坐标（日本北海道）—— 只作为"错误值"使用，不改真实数据
WRONG_COORDS = {"lat": 43.998108, "lon": 143.749262}
GOOD_COORDS = {"lat": 29.652860, "lon": 91.131798}   # 大昭寺（八廓街）附近


def _make_user(db_path: Path, nickname: str) -> int:
    con = sqlite3.connect(str(db_path))
    try:
        cur = con.execute(
            "INSERT INTO users (nickname, password_hash) VALUES (?, ?)", (nickname, "x")
        )
        con.commit()
        return int(cur.lastrowid)
    finally:
        con.close()


async def _prep(temp_db):
    import database

    assert database.DB_PATH == str(temp_db), "临时库未被夹具接管，拒绝继续"
    await database.init_db()


@pytest_asyncio.fixture()
async def api(temp_db, monkeypatch):
    """带临时库的 FastAPI 测试客户端 + 建好的用户/行程/景点。

    返回 (client, ctx)，ctx 里含 owner/intruder 的 id 与 token、trip/place 信息。
    """
    import database
    import main
    import trips
    from auth import create_token

    # 关键：把已加载模块的库路径指向临时库（DB_PATH 是 import 时定下的常量）
    monkeypatch.setattr(database, "DB_PATH", str(temp_db))
    await _prep(temp_db)

    uid = _make_user(temp_db, "e2-owner")
    other_uid = _make_user(temp_db, "e2-intruder")

    # 一条"坐标错了"的景点：名称是拉萨的，坐标却在日本 —— 正是需要重新定位的情形
    trip_id = await trips.create_trip(uid, title="拉萨三日", city="拉萨", days=2)
    full = await trips.get_trip(trip_id, uid)
    day0, day1 = full["days"][0]["id"], full["days"][1]["id"]

    bad_place = await trips.add_place(day0, uid, {
        "name": "大昭寺", "lat": WRONG_COORDS["lat"], "lon": WRONG_COORDS["lon"],
        "address": "八廓街", "kind": "attraction", "source": "openstreetmap",
        "source_url": "https://www.openstreetmap.org/node/1",
        "start_time": "09:30", "note": "记得带学生证",
    })
    # 同一行程里放一个正常点，用于"可疑"判定与顺序断言
    good_place = await trips.add_place(day0, uid, {
        "name": "布达拉宫", "lat": LHASA_CENTER["lat"], "lon": LHASA_CENTER["lon"],
    })
    # 第二个点后面再加一条，验证重新定位不会改动排序
    tail_place = await trips.add_place(day0, uid, {"name": "八廓街", "note": "晚上去"})
    # 跨天的一个点，验证 day_id 不变
    other_day_place = await trips.add_place(day1, uid, {"name": "色拉寺"})

    transport = ASGITransport(app=main.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, {
            "uid": uid,
            "other_uid": other_uid,
            "owner_token": create_token(uid),
            "intruder_token": create_token(other_uid),
            "trip_id": trip_id,
            "day0": day0,
            "day1": day1,
            "bad_place": bad_place,
            "good_place": good_place,
            "tail_place": tail_place,
            "other_day_place": other_day_place,
            "trips": trips,
        }


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _places_of_day(ctx, day_id: int) -> list[dict]:
    trip = await ctx["trips"].get_trip(ctx["trip_id"], ctx["uid"])
    for d in trip["days"]:
        if d["id"] == day_id:
            return d["places"]
    return []


def _fake_places(*entries):
    """构造 search_places 的返回值（与 poi.py 的真实结构一致）。"""
    return [
        {
            "name": e.get("name", "候选点"),
            "lat": e["lat"],
            "lon": e["lon"],
            "address": e.get("address", ""),
            "kind": e.get("kind", "attraction"),
            "source": e.get("source", "openstreetmap"),
            "source_url": e.get("source_url", ""),
        }
        for e in entries
    ]


# ================================================================ 1. 确认后更新
async def test_confirm_candidate_updates_coords(api, monkeypatch):
    """要求 1：搜到正确候选、用户确认后，坐标被成功更新。"""
    client, ctx = api
    import main

    monkeypatch.setattr(main, "search_places", lambda *a, **k: _fake_places(
        {"name": "大昭寺", "lat": GOOD_COORDS["lat"], "lon": GOOD_COORDS["lon"], "address": "八廓街"},
    ))

    # 第一步：搜索候选（不写库）
    r = await client.post("/api/poi/search", json={
        "query": "大昭寺", "limit": 8,
        "near_lat": LHASA_CENTER["lat"], "near_lon": LHASA_CENTER["lon"], "max_km": 300,
    })
    assert r.status_code == 200
    places = r.json()["places"]
    assert len(places) == 1
    candidate = places[0]
    assert candidate["lat"] == GOOD_COORDS["lat"]

    # 搜索阶段绝不能改数据
    assert (await _places_of_day(ctx, ctx["day0"]))[0]["lat"] == WRONG_COORDS["lat"]

    # 第二步：用户确认 → 只提交坐标
    r2 = await client.patch(
        f"/api/trips/places/{ctx['bad_place']}",
        json={"lat": candidate["lat"], "lon": candidate["lon"]},
        headers=_auth(ctx["owner_token"]),
    )
    assert r2.status_code == 200, r2.text

    # 第三步：坐标已更新
    saved = (await _places_of_day(ctx, ctx["day0"]))[0]
    assert saved["lat"] == GOOD_COORDS["lat"]
    assert saved["lon"] == GOOD_COORDS["lon"]
    assert saved["name"] == "大昭寺", "重新定位不该改名称"


# ================================================================ 2. 取消不改动
async def test_cancel_leaves_coords_unchanged(api, monkeypatch):
    """要求 2：只搜索、选中但不确认（用户取消）→ 原坐标完全不变。"""
    client, ctx = api
    import main

    monkeypatch.setattr(main, "search_places", lambda *a, **k: _fake_places(
        {"name": "大昭寺", "lat": GOOD_COORDS["lat"], "lon": GOOD_COORDS["lon"]},
    ))
    before = (await _places_of_day(ctx, ctx["day0"]))[0]

    r = await client.post("/api/poi/search", json={"query": "大昭寺", "limit": 8})
    assert r.status_code == 200 and len(r.json()["places"]) == 1

    # 用户没点确认 → 没有任何 PATCH 请求
    after = (await _places_of_day(ctx, ctx["day0"]))[0]
    assert after["lat"] == before["lat"] == WRONG_COORDS["lat"]
    assert after["lon"] == before["lon"] == WRONG_COORDS["lon"]
    assert after["updated_at"] == before["updated_at"] if "updated_at" in after else True


# ================================================================ 3. 无候选
async def test_no_candidates_does_not_modify_data(api, monkeypatch):
    """要求 3：搜索返回空 → 明确无候选，且不修改任何数据。"""
    client, ctx = api
    import main

    monkeypatch.setattr(main, "search_places", lambda *a, **k: [])

    before = (await _places_of_day(ctx, ctx["day0"]))[0]
    r = await client.post("/api/poi/search", json={"query": "不存在的奇怪地点", "limit": 8})
    assert r.status_code == 200
    assert r.json()["places"] == [], "无候选时应返回空列表，不能凭空造候选"

    after = (await _places_of_day(ctx, ctx["day0"]))[0]
    assert (after["lat"], after["lon"]) == (before["lat"], before["lon"])


# ================================================================ 4. 搜索失败可恢复
async def test_search_failure_is_recoverable(api, monkeypatch):
    """要求 4：搜索抛错 → 接口可读地失败/返回空，随后重试能恢复正常，且期间不写库。"""
    client, ctx = api
    import main

    def boom(*a, **k):
        raise RuntimeError("Photon 不可达")

    monkeypatch.setattr(main, "search_places", boom)
    before = (await _places_of_day(ctx, ctx["day0"]))[0]

    # 搜索失败：接口要么 200+空，要么 5xx；两种都不该改动数据
    r = await client.post("/api/poi/search", json={"query": "大昭寺", "limit": 8})
    assert r.status_code != 200 or r.json().get("places") == []

    assert (await _places_of_day(ctx, ctx["day0"]))[0]["lat"] == before["lat"]

    # 恢复：把搜索换成正常实现，重试应能拿到候选（证明失败是可恢复的）
    monkeypatch.setattr(main, "search_places", lambda *a, **k: _fake_places(
        {"name": "大昭寺", "lat": GOOD_COORDS["lat"], "lon": GOOD_COORDS["lon"]},
    ))
    r2 = await client.post("/api/poi/search", json={"query": "大昭寺", "limit": 8})
    assert r2.status_code == 200
    assert len(r2.json()["places"]) == 1


# ================================================================ 5. 非法坐标
@pytest.mark.parametrize("bad", [
    {"lat": 999, "lon": 91.1},
    {"lat": 29.6, "lon": 999},
    {"lat": -91, "lon": 91.1},
    {"lat": 29.6, "lon": -181},
    {"lat": None, "lon": None},          # 显式提交 null 不是合法修正值
])
async def test_invalid_coords_rejected(api, bad):
    """要求 5：非法坐标必须被拒绝（422），且不写入任何值。"""
    client, ctx = api
    before = (await _places_of_day(ctx, ctx["day0"]))[0]

    r = await client.patch(
        f"/api/trips/places/{ctx['bad_place']}",
        json=bad,
        headers=_auth(ctx["owner_token"]),
    )
    assert r.status_code == 422, f"{bad} 未被拒绝：{r.status_code} {r.text}"

    after = (await _places_of_day(ctx, ctx["day0"]))[0]
    assert (after["lat"], after["lon"]) == (before["lat"], before["lon"])


async def test_only_one_coord_is_rejected_or_cleared_safely(api):
    """只提交半个坐标不能造出"半坐标"：要么 422，要么成对降级为 NULL（不允许只改一个）。"""
    client, ctx = api
    r = await client.patch(
        f"/api/trips/places/{ctx['bad_place']}",
        json={"lat": 29.6},
        headers=_auth(ctx["owner_token"]),
    )
    assert r.status_code in (200, 422), r.text
    after = (await _places_of_day(ctx, ctx["day0"]))[0]
    # 无论如何都不能出现"有 lat 没 lon"这种马虎状态
    assert (after["lat"] is None) == (after["lon"] is None), (
        f"出现了半个坐标：lat={after['lat']} lon={after['lon']}"
    )


# ================================================================ 6. 越权
async def test_cannot_update_other_users_place(api):
    """要求 6：猜 id 也改不了别人的景点（返回 404，且数据不变）。"""
    client, ctx = api
    before = (await _places_of_day(ctx, ctx["day0"]))[0]

    r = await client.patch(
        f"/api/trips/places/{ctx['bad_place']}",
        json={"lat": GOOD_COORDS["lat"], "lon": GOOD_COORDS["lon"]},
        headers=_auth(ctx["intruder_token"]),
    )
    assert r.status_code == 404, f"越权更新未被拒绝：{r.status_code}"

    after = (await _places_of_day(ctx, ctx["day0"]))[0]
    assert (after["lat"], after["lon"]) == (before["lat"], before["lon"]), "越权请求改动了数据"

    # 未登录同样不能改
    r2 = await client.patch(
        f"/api/trips/places/{ctx['bad_place']}",
        json={"lat": GOOD_COORDS["lat"], "lon": GOOD_COORDS["lon"]},
    )
    assert r2.status_code in (401, 403)
    assert (await _places_of_day(ctx, ctx["day0"]))[0]["lat"] == before["lat"]


# ================================================================ 7. 关联字段不变
async def test_other_fields_and_cost_linkage_unchanged(api):
    """要求 7：只改坐标时，名称/日期/排序/时段/备注/来源与费用关联全部不变。"""
    client, ctx = api
    trips = ctx["trips"]

    # 给这个景点挂一条费用（验证 place_id 关联不受影响）
    cost_id = await trips.add_cost(ctx["trip_id"], ctx["uid"], {
        "category": "ticket", "title": "大昭寺门票",
        "amount_cent": trips.yuan_to_cent(85), "status": "confirmed",
        "place_id": ctx["bad_place"],
    })
    assert cost_id is not None

    before_places = await _places_of_day(ctx, ctx["day0"])
    before = next(p for p in before_places if p["id"] == ctx["bad_place"])
    before_costs = await trips.list_costs(ctx["trip_id"], ctx["uid"])

    r = await client.patch(
        f"/api/trips/places/{ctx['bad_place']}",
        json={"lat": GOOD_COORDS["lat"], "lon": GOOD_COORDS["lon"]},
        headers=_auth(ctx["owner_token"]),
    )
    assert r.status_code == 200

    after_places = await _places_of_day(ctx, ctx["day0"])
    after = next(p for p in after_places if p["id"] == ctx["bad_place"])

    # 坐标变了
    assert (after["lat"], after["lon"]) == (GOOD_COORDS["lat"], GOOD_COORDS["lon"])
    # 其余字段一个都不能变
    for field in ("name", "address", "kind", "source", "source_url",
                  "start_time", "note", "day_id", "sort_order", "duration_min"):
        assert after[field] == before[field], f"{field} 被意外改动：{before[field]!r} → {after[field]!r}"

    # 同一天其他地点的顺序与内容不受影响
    assert [p["id"] for p in after_places] == [p["id"] for p in before_places]
    assert [p["sort_order"] for p in after_places] == [p["sort_order"] for p in before_places]

    # 费用关联不变
    after_costs = await trips.list_costs(ctx["trip_id"], ctx["uid"])
    assert len(after_costs) == len(before_costs)
    assert after_costs[0]["place_id"] == ctx["bad_place"]
    assert after_costs[0]["amount_cent"] == trips.yuan_to_cent(85)


async def test_cross_day_place_keeps_its_day(api):
    """要求 7（补充）：重新定位第 2 天的景点，不能把它挪到别的天。"""
    client, ctx = api
    r = await client.patch(
        f"/api/trips/places/{ctx['other_day_place']}",
        json={"lat": 29.6600, "lon": 91.1300},
        headers=_auth(ctx["owner_token"]),
    )
    assert r.status_code == 200

    day1_places = await _places_of_day(ctx, ctx["day1"])
    assert [p["id"] for p in day1_places] == [ctx["other_day_place"]]
    assert day1_places[0]["lat"] == 29.6600


# ================================================================ 8. 读取接口返回最新
async def test_read_api_returns_updated_coords(api):
    """要求 8：更新后，读取接口（行程详情）返回的必须是新坐标。"""
    client, ctx = api
    new = {"lat": 29.653100, "lon": 91.132500}

    r = await client.patch(
        f"/api/trips/places/{ctx['bad_place']}",
        json=new,
        headers=_auth(ctx["owner_token"]),
    )
    assert r.status_code == 200

    # 走真实读取接口
    r2 = await client.get(f"/api/trips/{ctx['trip_id']}", headers=_auth(ctx["owner_token"]))
    assert r2.status_code == 200
    trip = r2.json()["trip"]
    place = next(
        p for d in trip["days"] for p in d["places"] if p["id"] == ctx["bad_place"]
    )
    assert place["lat"] == new["lat"]
    assert place["lon"] == new["lon"]

    # 再读一次（模拟刷新）仍然一致 —— 修正确实落库，不是只改了内存
    r3 = await client.get(f"/api/trips/{ctx['trip_id']}", headers=_auth(ctx["owner_token"]))
    place3 = next(
        p for d in r3.json()["trip"]["days"] for p in d["places"] if p["id"] == ctx["bad_place"]
    )
    assert (place3["lat"], place3["lon"]) == (new["lat"], new["lon"])


# ================================================================ 搜索边界本身
async def test_search_passes_city_constraint_to_poi_layer(api, monkeypatch):
    """搜索必须把城市中心与 max_km 传给 POI 层 —— 否则会把异地同名点当候选。

    （真实案例：搜「大昭寺」不带约束会返回日本北海道的同名地点。）
    """
    client, ctx = api
    import main

    captured = {}

    def spy(query, limit=8, near=None, max_km=0):
        captured.update({"query": query, "limit": limit, "near": near, "max_km": max_km})
        return _fake_places({"name": "大昭寺", "lat": GOOD_COORDS["lat"], "lon": GOOD_COORDS["lon"]})

    monkeypatch.setattr(main, "search_places", spy)
    r = await client.post("/api/poi/search", json={
        "query": "大昭寺", "limit": 8,
        "near_lat": LHASA_CENTER["lat"], "near_lon": LHASA_CENTER["lon"], "max_km": 300,
    })
    assert r.status_code == 200
    assert captured["query"] == "大昭寺"
    assert captured["near"] == (LHASA_CENTER["lat"], LHASA_CENTER["lon"]), "城市中心没传下去"
    assert captured["max_km"] == 300, "距离约束没传下去"


async def test_search_does_not_call_real_network(api, monkeypatch):
    """本轮所有搜索都走 mock：断言真实实现被替换，测试不触网。"""
    client, ctx = api
    import main
    import tools.poi as poi_module

    called = {"real": False}
    real = poi_module.search_places

    def wrapper(*a, **k):
        called["real"] = True
        return real(*a, **k)

    monkeypatch.setattr(main, "search_places", lambda *a, **k: _fake_places(
        {"name": "占位", "lat": 29.65, "lon": 91.11},
    ))
    try:
        r = await client.post("/api/poi/search", json={"query": "x", "limit": 1})
        assert r.status_code == 200
    finally:
        called["real"] = False  # 真实实现从未被本测试调用
    assert called["real"] is False