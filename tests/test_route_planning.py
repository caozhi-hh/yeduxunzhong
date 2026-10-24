"""T1-F1 验收测试：真实道路路线、分段距离与耗时。

覆盖任务第四节要求：
  · 正常路线结果的解析与展示数据结构
  · 分段距离与耗时汇总
  · 缺少坐标 / 非法坐标的处理
  · 无权访问其他用户的行程
  · 路线服务未配置 / 上游失败 / 两点无路线
  · 切换日期只计算对应日期的景点
  · 修改景点顺序后不会返回旧顺序的路线
  · 既有行程编辑、重新定位与预算功能没有被破坏
另加：接口无数据库副作用、参数校验、高德坐标系换算。

测试方式与"不触网"证据
----------------------
走**真实 API 路由**（httpx.ASGITransport 直连 FastAPI 应用），
在 `routing._get_json` 这一边界替换成假响应 —— 也就是**真实解析逻辑被完整执行**，
只有最后一跳 HTTP 被替换。因此自动化测试里不会发出任何外部请求。

（`routing._osrm_leg` 只在少数需要构造"异常"的用例里被替换。）

前端交互（地图画线、日期切换、降级提示）没有 DOM 测试环境，
由 `npx tsc --noEmit` + `npm run build` + 人工验收覆盖，本文件不伪造那部分。
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# 拉萨真实坐标（与项目数据同城）
P1 = (29.657905, 91.117398)   # 布达拉宫
P2 = (29.652860, 91.131798)   # 大昭寺
P3 = (29.651687, 91.131348)   # 八廓街


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


def _osrm_payload(distance: float, duration: float, a, b) -> dict:
    """构造与 OSRM 真实返回同形状的响应（coordinates 是 [lon, lat]）。"""
    return {
        "code": "Ok",
        "routes": [{
            "distance": distance,
            "duration": duration,
            "geometry": {"coordinates": [[a[1], a[0]], [(a[1] + b[1]) / 2, (a[0] + b[0]) / 2], [b[1], b[0]]]},
        }],
    }


@pytest.fixture(autouse=True)
def _clear_route_cache():
    """路线适配层有进程内缓存：每个测试前后都清，避免相互影响。"""
    from tools import routing

    routing.clear_cache()
    yield
    routing.clear_cache()


@pytest.fixture(autouse=True)
def _default_provider(monkeypatch):
    """默认让 OSRM 生效且只支持 driving，并保证高德密钥不存在。

    各用例可按需覆盖（未配置、高德等）。
    """
    monkeypatch.delenv("AMAP_ROUTE_KEY", raising=False)
    monkeypatch.setenv("OSRM_BASE_URL", "https://router.example.test")
    monkeypatch.setenv("OSRM_MODES", "driving")


async def _prep(temp_db):
    import database

    assert database.DB_PATH == str(temp_db), "临时库未被夹具接管，拒绝继续"
    await database.init_db()


@pytest_asyncio.fixture()
async def api(temp_db, monkeypatch):
    """临时库上的 FastAPI 客户端 + 一条两天的拉萨行程。"""
    import database
    import main
    import trips
    from auth import create_token

    monkeypatch.setattr(database, "DB_PATH", str(temp_db))
    await _prep(temp_db)

    uid = _make_user(temp_db, "f1-owner")
    other_uid = _make_user(temp_db, "f1-intruder")

    trip_id = await trips.create_trip(uid, title="拉萨两日", city="拉萨", days=2)
    full = await trips.get_trip(trip_id, uid)
    day0, day1 = full["days"][0]["id"], full["days"][1]["id"]

    # 第 1 天：三个点，但中间插一个缺坐标的（用于验证"跳过并报告"）
    a = await trips.add_place(day0, uid, {"name": "布达拉宫", "lat": P1[0], "lon": P1[1]})
    nocoord = await trips.add_place(day0, uid, {"name": "没坐标的茶馆"})
    b = await trips.add_place(day0, uid, {"name": "大昭寺", "lat": P2[0], "lon": P2[1]})
    c = await trips.add_place(day0, uid, {"name": "八廓街", "lat": P3[0], "lon": P3[1]})
    # 第 2 天：两个点（验证切换日期只算当天）
    d1a = await trips.add_place(day1, uid, {"name": "色拉寺", "lat": 29.700000, "lon": 91.130000})
    d1b = await trips.add_place(day1, uid, {"name": "哲蚌寺", "lat": 29.673000, "lon": 91.050000})

    transport = ASGITransport(app=main.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, {
            "uid": uid,
            "other_uid": other_uid,
            "token": create_token(uid),
            "other_token": create_token(other_uid),
            "trip_id": trip_id,
            "day0": day0,
            "day1": day1,
            "a": a, "b": b, "c": c, "nocoord": nocoord,
            "d1a": d1a, "d1b": d1b,
            "db": temp_db,
            "trips": trips,
        }


def _auth(ctx) -> dict:
    return {"Authorization": f"Bearer {ctx['token']}"}


def _db_snapshot(db_path: Path) -> dict:
    """数据库快照：行数 + 顺序 + updated_at。用于证明路线查询**没有副作用**。"""
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    try:
        snap = {
            "places": [dict(r) for r in con.execute(
                "SELECT id, day_id, sort_order, name, lat, lon FROM trip_places ORDER BY id"
            )],
            "trips_updated": [dict(r) for r in con.execute(
                "SELECT id, updated_at FROM trips ORDER BY id"
            )],
            "costs": con.execute("SELECT COUNT(*) FROM trip_costs").fetchone()[0],
        }
    finally:
        con.close()
    return snap


# ================================================================ 1. 正常解析
async def test_route_parses_real_geometry(api, monkeypatch):
    """要求：正常路线结果的解析与展示数据结构（几何/距离/耗时/来源/方式）。"""
    client, ctx = api
    from tools import routing

    monkeypatch.setattr(routing, "_get_json", lambda url, params, timeout=15: _osrm_payload(
        1479.0, 125.1, P1, P2,
    ))

    r = await client.get(
        f"/api/trips/{ctx['trip_id']}/route?day_index=0&mode=driving", headers=_auth(ctx)
    )
    assert r.status_code == 200, r.text
    body = r.json()
    route = body["route"]

    assert body["day_index"] == 0
    assert body["day_id"] == ctx["day0"]
    assert route["status"] == "ok"
    assert route["provider"] == "osrm"
    assert route["mode"] == "driving"

    # 缺坐标的景点被跳过，其余保持用户顺序
    assert route["ordered_place_ids"] == [ctx["a"], ctx["b"], ctx["c"]]
    assert [s["place_id"] for s in route["skipped"]] == [ctx["nocoord"]]
    assert route["skipped"][0]["reason"] == "invalid_coords"

    # 3 个可用点 → 2 段
    assert route["legs_total"] == 2
    assert route["legs_ok"] == 2

    leg = route["legs"][0]
    assert leg["from_place_id"] == ctx["a"]
    assert leg["to_place_id"] == ctx["b"]
    assert leg["from_name"] == "布达拉宫"
    assert leg["to_name"] == "大昭寺"
    assert leg["distance_m"] == 1479.0          # 米
    assert leg["duration_s"] == 125.1           # 秒
    assert leg["source"] == "osrm"
    # 几何统一为 [lat, lon]，便于前端直接喂地图
    assert leg["geometry"][0] == [P1[0], P1[1]]
    assert leg["geometry"][-1] == [P2[0], P2[1]]
    assert len(leg["geometry"]) == 3


# ================================================================ 2. 分段汇总
async def test_leg_distances_and_durations_sum(api, monkeypatch):
    """要求：分段距离与耗时汇总 = 各成功段之和（整数米/秒，不做任何估算）。"""
    client, ctx = api
    from tools import routing

    calls = []

    def fake_get(url, params, timeout=15):
        calls.append(url)
        # 第一段 1000m/100s，第二段 2000m/300s → 合计 3000m/400s
        if len(calls) == 1:
            return _osrm_payload(1000.0, 100.0, P1, P2)
        return _osrm_payload(2000.0, 300.0, P2, P3)

    monkeypatch.setattr(routing, "_get_json", fake_get)

    r = await client.get(f"/api/trips/{ctx['trip_id']}/route?day_index=0", headers=_auth(ctx))
    route = r.json()["route"]

    assert [l["distance_m"] for l in route["legs"]] == [1000.0, 2000.0]
    assert [l["duration_s"] for l in route["legs"]] == [100.0, 300.0]
    assert route["total_distance_m"] == 3000.0
    assert route["total_duration_s"] == 400.0
    # 逐段相加必须等于汇总（同一口径）
    assert sum(l["distance_m"] for l in route["legs"]) == route["total_distance_m"]


# ================================================================ 3. 缺坐标 / 非法坐标
async def test_missing_and_invalid_coords_are_skipped_not_faked(api, monkeypatch, temp_db):
    """要求：缺坐标与非法坐标被跳过并逐个报告，不参与计算，也不伪造坐标。"""
    client, ctx = api
    from tools import routing

    monkeypatch.setattr(routing, "_get_json", lambda *a, **k: _osrm_payload(500.0, 60.0, P1, P2))

    # 直接往库里塞一个"越界坐标"（模拟历史脏数据；API 层会拒，所以绕过它）
    con = sqlite3.connect(str(temp_db))
    con.execute(
        "INSERT INTO trip_places (day_id, name, lat, lon) VALUES (?, ?, ?, ?)",
        (ctx["day0"], "错配点", 43.998108, 143.749262),  # 北海道坐标，范围合法但明显异地
    )
    con.execute(
        "INSERT INTO trip_places (day_id, name, lat, lon) VALUES (?, ?, ?, ?)",
        (ctx["day0"], "越界点", 999.0, 1.0),             # 越界：必须被判为不可用
    )
    con.commit()
    con.close()

    r = await client.get(f"/api/trips/{ctx['trip_id']}/route?day_index=0", headers=_auth(ctx))
    assert r.status_code == 200
    route = r.json()["route"]

    # 越界点必须被跳过（缺坐标的茶馆也跳过）
    skipped_ids = {s["place_id"] for s in route["skipped"]}
    assert ctx["nocoord"] in skipped_ids
    assert all(s["reason"] == "invalid_coords" for s in route["skipped"])
    # 没有任何被跳过的点混进计算序列
    assert not (skipped_ids & set(route["ordered_place_ids"]))
    # 被跳过的项里**不得**出现被"修好"的坐标字段
    for s in route["skipped"]:
        assert "lat" not in s and "lon" not in s


async def test_all_places_missing_coords_yields_no_legs(api, monkeypatch, temp_db):
    """一天里的点全都没坐标 → 没有可算的段，但不报错也不编造路线。"""
    client, ctx = api
    from tools import routing

    called = {"n": 0}

    def should_not_call(*a, **k):
        called["n"] += 1
        return _osrm_payload(1.0, 1.0, P1, P2)

    monkeypatch.setattr(routing, "_get_json", should_not_call)

    # 把第 2 天两个点的坐标清空（走 API 会 422，所以直接用 SQL 造状态）
    con = sqlite3.connect(str(temp_db))
    con.execute("UPDATE trip_places SET lat=NULL, lon=NULL WHERE id IN (?, ?)", (ctx["d1a"], ctx["d1b"]))
    con.commit()
    con.close()

    r = await client.get(f"/api/trips/{ctx['trip_id']}/route?day_index=1", headers=_auth(ctx))
    assert r.status_code == 200
    route = r.json()["route"]
    assert route["legs"] == []
    assert route["legs_total"] == 0
    assert route["total_distance_m"] is None
    assert len(route["skipped"]) == 2
    assert called["n"] == 0, "没有可算的段时不该调用上游"


# ================================================================ 4. 越权
async def test_route_requires_trip_ownership(api):
    """要求：无权访问其他用户的行程 → 404（猜 id 也拿不到路线）。"""
    client, ctx = api

    r = await client.get(
        f"/api/trips/{ctx['trip_id']}/route?day_index=0", headers={"Authorization": f"Bearer {ctx['other_token']}"}
    )
    assert r.status_code == 404

    # 未登录
    r2 = await client.get(f"/api/trips/{ctx['trip_id']}/route?day_index=0")
    assert r2.status_code in (401, 403)

    # 不存在的行程
    r3 = await client.get("/api/trips/999999/route?day_index=0", headers=_auth(ctx))
    assert r3.status_code == 404


# ================================================================ 5. 失败状态
async def test_not_configured_reported_honestly(api, monkeypatch):
    """要求：路线服务未配置 → not_configured，并说明需要哪个环境变量。"""
    client, ctx = api
    monkeypatch.setenv("OSRM_BASE_URL", "")
    monkeypatch.delenv("AMAP_ROUTE_KEY", raising=False)

    r = await client.get(f"/api/trips/{ctx['trip_id']}/route?day_index=0", headers=_auth(ctx))
    assert r.status_code == 200
    route = r.json()["route"]
    assert route["status"] == "not_configured"
    assert route["provider"] is None
    assert route["provider_info"]["requires_env"], "必须告诉调用方还缺什么配置"
    assert route["legs"] == []
    assert route["total_distance_m"] is None


async def test_upstream_failure_reported_as_unavailable(api, monkeypatch):
    """要求：上游超时/失败 → unavailable，且不返回任何伪造的距离或几何。"""
    client, ctx = api
    from tools import routing

    def boom(url, params, timeout=15):
        raise OSError("connection timed out")

    monkeypatch.setattr(routing, "_get_json", boom)

    r = await client.get(f"/api/trips/{ctx['trip_id']}/route?day_index=0", headers=_auth(ctx))
    route = r.json()["route"]
    assert route["status"] == "unavailable"
    for leg in route["legs"]:
        assert leg["status"] == "unavailable"
        assert "distance_m" not in leg
        assert "geometry" not in leg
    assert route["total_distance_m"] is None


async def test_no_route_between_points(api, monkeypatch):
    """要求：两点之间没有可用路线 → no_route（不是 unavailable，也不是 0 米）。"""
    client, ctx = api
    from tools import routing

    monkeypatch.setattr(
        routing, "_get_json",
        lambda url, params, timeout=15: {"code": "NoRoute", "routes": []},
    )

    r = await client.get(f"/api/trips/{ctx['trip_id']}/route?day_index=0", headers=_auth(ctx))
    route = r.json()["route"]
    assert route["status"] == "no_route"
    assert all(l["status"] == "no_route" for l in route["legs"])
    assert route["total_distance_m"] is None


async def test_partial_success_keeps_successful_legs(api, monkeypatch):
    """要求：一段失败不应毁掉整天 → partial，成功的段照常带真实数据。"""
    client, ctx = api
    from tools import routing

    calls = {"n": 0}

    def flaky(url, params, timeout=15):
        calls["n"] += 1
        if calls["n"] == 1:
            return _osrm_payload(800.0, 90.0, P1, P2)
        raise OSError("second leg failed")

    monkeypatch.setattr(routing, "_get_json", flaky)

    r = await client.get(f"/api/trips/{ctx['trip_id']}/route?day_index=0", headers=_auth(ctx))
    route = r.json()["route"]
    assert route["status"] == "partial"
    assert route["legs_ok"] == 1 and route["legs_total"] == 2
    assert route["legs"][0]["status"] == "ok" and route["legs"][0]["distance_m"] == 800.0
    assert route["legs"][1]["status"] == "unavailable"
    # 汇总只统计成功的段，不含失败的（不把缺数据当 0 米）
    assert route["total_distance_m"] == 800.0


async def test_incomplete_upstream_not_backfilled(api, monkeypatch):
    """要求：上游几何/距离/耗时不完整 → 如实报告 incomplete，不自行补造。"""
    client, ctx = api
    from tools import routing

    monkeypatch.setattr(
        routing, "_get_json",
        lambda url, params, timeout=15: {"code": "Ok", "routes": [{"distance": 1200.0}]},  # 缺 duration 与 geometry
    )

    r = await client.get(f"/api/trips/{ctx['trip_id']}/route?day_index=0", headers=_auth(ctx))
    route = r.json()["route"]
    assert route["status"] == "incomplete"
    for leg in route["legs"]:
        assert leg["status"] == "incomplete"
        assert "distance_m" not in leg and "geometry" not in leg


async def test_unsupported_mode_is_honest(api, monkeypatch):
    """要求：不支持的模式如实报告 —— 公共 OSRM 演示服务对任何 profile 都回驾车数据，
    因此默认只认 driving，绝不把驾车结果当步行结果展示。"""
    client, ctx = api
    from tools import routing

    called = {"n": 0}

    def spy(*a, **k):
        called["n"] += 1
        return _osrm_payload(1479.0, 125.1, P1, P2)

    monkeypatch.setattr(routing, "_get_json", spy)

    r = await client.get(f"/api/trips/{ctx['trip_id']}/route?day_index=0&mode=walking", headers=_auth(ctx))
    assert r.status_code == 200
    route = r.json()["route"]
    assert route["status"] == "mode_unsupported"
    assert route["legs"] == []
    assert called["n"] == 0, "不支持的模式不该去调上游（否则就是拿驾车数据冒充步行）"


# ================================================================ 6. 参数校验
async def test_param_validation(api, monkeypatch):
    """要求：对经纬度、交通方式和请求参数进行校验。"""
    client, ctx = api
    from tools import routing

    monkeypatch.setattr(routing, "_get_json", lambda *a, **k: _osrm_payload(1.0, 1.0, P1, P2))

    # mode 非法
    r = await client.get(f"/api/trips/{ctx['trip_id']}/route?day_index=0&mode=flying", headers=_auth(ctx))
    assert r.status_code == 422

    # day_index 越界（该行程只有 2 天）
    r2 = await client.get(f"/api/trips/{ctx['trip_id']}/route?day_index=5", headers=_auth(ctx))
    assert r2.status_code == 422

    # day_index 负数
    r3 = await client.get(f"/api/trips/{ctx['trip_id']}/route?day_index=-1", headers=_auth(ctx))
    assert r3.status_code == 422

    # 合法请求仍正常
    r4 = await client.get(f"/api/trips/{ctx['trip_id']}/route?day_index=0&mode=driving", headers=_auth(ctx))
    assert r4.status_code == 200


# ================================================================ 7. 无副作用
async def test_route_query_has_no_db_side_effects(api, monkeypatch):
    """要求：不修改原有行程顺序、不产生任何数据库副作用。"""
    client, ctx = api
    from tools import routing

    monkeypatch.setattr(routing, "_get_json", lambda *a, **k: _osrm_payload(700.0, 80.0, P1, P2))

    before = _db_snapshot(ctx["db"])
    for _ in range(2):                      # 连查两次（含命中缓存的那次）
        r = await client.get(f"/api/trips/{ctx['trip_id']}/route?day_index=0", headers=_auth(ctx))
        assert r.status_code == 200
    after = _db_snapshot(ctx["db"])

    assert before == after, "路线查询改动了数据库（行数/顺序/updated_at 有变化）"


# ================================================================ 8. 按日期
async def test_day_switch_only_uses_that_day(api, monkeypatch):
    """要求：切换日期时只计算对应日期的景点。"""
    client, ctx = api
    from tools import routing

    monkeypatch.setattr(routing, "_get_json", lambda *a, **k: _osrm_payload(1000.0, 100.0, P1, P2))

    r0 = await client.get(f"/api/trips/{ctx['trip_id']}/route?day_index=0", headers=_auth(ctx))
    r1 = await client.get(f"/api/trips/{ctx['trip_id']}/route?day_index=1", headers=_auth(ctx))

    b0, b1 = r0.json(), r1.json()
    d0, d1 = b0["route"], b1["route"]

    # day_index 在响应体顶层（handler 补的日程上下文）
    assert b0["day_index"] == 0 and b1["day_index"] == 1
    # 各段的归属日也正确
    assert b0["day_id"] == ctx["day0"] and b1["day_id"] == ctx["day1"]
    assert set(d0["ordered_place_ids"]) == {ctx["a"], ctx["b"], ctx["c"]}
    assert set(d1["ordered_place_ids"]) == {ctx["d1a"], ctx["d1b"]}
    # 两天之间没有任何交叉
    assert not (set(d0["ordered_place_ids"]) & set(d1["ordered_place_ids"]))
    assert d0["legs_total"] == 2 and d1["legs_total"] == 1


# ================================================================ 9. 顺序变化
async def test_reorder_does_not_return_stale_route(api, monkeypatch):
    """要求：调整景点顺序后不会返回旧顺序的路线（缓存键必须含顺序与坐标）。"""
    client, ctx = api
    from tools import routing

    # 让上游把"请求的起终点"回显进几何，便于判断返回的是哪一对
    def echo(url, params, timeout=15):
        # url 形如 .../driving/lon,lat;lon,lat
        seg = url.rsplit("/", 1)[-1]
        (a_lon, a_lat), (b_lon, b_lat) = [p.split(",") for p in seg.split(";")[:2]]
        a = (float(a_lat), float(a_lon))
        b = (float(b_lat), float(b_lon))
        return _osrm_payload(111.0, 11.0, a, b)

    monkeypatch.setattr(routing, "_get_json", echo)

    first = (await client.get(
        f"/api/trips/{ctx['trip_id']}/route?day_index=0", headers=_auth(ctx)
    )).json()["route"]
    assert first["ordered_place_ids"] == [ctx["a"], ctx["b"], ctx["c"]]
    assert first["legs"][0]["from_place_id"] == ctx["a"]
    assert first["legs"][0]["to_place_id"] == ctx["b"]

    # 把 C 移到最前面（真实顺序变更，走生产接口）
    assert await ctx["trips"].move_place(ctx["c"], ctx["uid"], ctx["day0"], 0) is True

    second = (await client.get(
        f"/api/trips/{ctx['trip_id']}/route?day_index=0", headers=_auth(ctx)
    )).json()["route"]

    assert second["ordered_place_ids"] == [ctx["c"], ctx["a"], ctx["b"]], (
        "顺序变了但路线仍按旧顺序返回（缓存键未包含顺序）"
    )
    assert second["legs"][0]["from_place_id"] == ctx["c"]
    assert second["legs"][0]["to_place_id"] == ctx["a"]
    # 几何首点应等于新的起点坐标（证明不是把旧结果端回来）
    assert second["legs"][0]["geometry"][0] == [P3[0], P3[1]]


async def test_coord_change_invalidates_cached_route(api, monkeypatch):
    """要求：坐标变化后必须重新取路线（缓存键含坐标）。"""
    client, ctx = api
    from tools import routing

    calls = {"n": 0}

    def echo(url, params, timeout=15):
        calls["n"] += 1
        seg = url.rsplit("/", 1)[-1]
        (a_lon, a_lat), (b_lon, b_lat) = [p.split(",") for p in seg.split(";")[:2]]
        return _osrm_payload(1000.0, 100.0, (float(a_lat), float(a_lon)), (float(b_lat), float(b_lon)))

    monkeypatch.setattr(routing, "_get_json", echo)

    url = f"/api/trips/{ctx['trip_id']}/route?day_index=0"
    await client.get(url, headers=_auth(ctx))
    n_first = calls["n"]

    # 同样请求再来一次：应命中缓存，不再打上游
    await client.get(url, headers=_auth(ctx))
    assert calls["n"] == n_first, "重复请求没有命中缓存，会造成请求风暴"

    # 修改一个景点的坐标（走生产接口）→ 缓存键变化 → 必须重新取
    ok = await client.patch(
        f"/api/trips/places/{ctx['b']}",
        json={"lat": 29.6600, "lon": 91.1400},
        headers=_auth(ctx),
    )
    assert ok.status_code == 200
    await client.get(url, headers=_auth(ctx))
    assert calls["n"] > n_first, "坐标变了却仍返回缓存的旧路线"


# ================================================================ 10. 高德适配（可选供应商）
def test_amap_polyline_is_converted_back_to_wgs84():
    """高德返回 GCJ-02：几何必须换算回 WGS-84，否则在 Carto 底图上整体偏移。"""
    from tools import routing

    # 高德给出的坐标是 GCJ-02（这里用正变换造一对"高德会返回的点"）
    gcj = routing.wgs84_to_gcj02(*P1)
    polyline = f"{gcj[1]:.6f},{gcj[0]:.6f};{gcj[1] + 0.001:.6f},{gcj[0] + 0.001:.6f}"

    pts = routing._amap_parse_polyline(polyline)
    assert len(pts) == 2
    # 换算回来应贴近原始 WGS-84（误差远小于 1 米量级）
    assert abs(pts[0][0] - P1[0]) < 1e-5
    assert abs(pts[0][1] - P1[1]) < 1e-5


def test_gcj_conversion_roundtrip_is_metric_accurate():
    """WGS84→GCJ02→WGS84 往返误差应在米级以下（否则高德路线会飘）。"""
    from tools import routing

    for lat, lon in ((29.657905, 91.117398), (39.907359, 116.391263), (31.230416, 121.473701)):
        g = routing.wgs84_to_gcj02(lat, lon)
        back = routing.gcj02_to_wgs84(*g)
        err_m = max(abs(back[0] - lat), abs(back[1] - lon)) * 111_000
        assert err_m < 1.0, f"往返误差 {err_m:.3f} m 过大"


def test_gcj_offset_is_not_applied_outside_china():
    """境外坐标不做 GCJ 偏移（否则会凭空挪动日本/欧洲的点）。"""
    from tools import routing

    # 北海道（真实库里那条错配坐标所在区域）
    lat, lon = 43.998108, 143.749262
    assert routing.wgs84_to_gcj02(lat, lon) == (lat, lon)


async def test_amap_provider_parses_v3_response(api, monkeypatch):
    """高德适配器（可选供应商）：用与官方同形状的假响应验证解析与换算。

    ⚠️ 诚实声明：本用例只验证**解析逻辑**。高德需要服务端密钥
    （`AMAP_ROUTE_KEY`），当前环境未配置，因此**未经真实服务验证**。
    """
    client, ctx = api
    from tools import routing

    monkeypatch.setenv("AMAP_ROUTE_KEY", "test-key-not-real")
    gcj_a = routing.wgs84_to_gcj02(*P1)
    gcj_b = routing.wgs84_to_gcj02(*P2)
    payload = {
        "status": "1",
        "info": "OK",
        "route": {
            "paths": [{
                "distance": "1479",       # 高德用字符串
                "duration": "125",
                "steps": [{
                    "polyline": f"{gcj_a[1]:.6f},{gcj_a[0]:.6f};{gcj_b[1]:.6f},{gcj_b[0]:.6f}",
                }],
            }],
        },
    }
    monkeypatch.setattr(routing, "_get_json", lambda url, params, timeout=15: payload)

    r = await client.get(f"/api/trips/{ctx['trip_id']}/route?day_index=0&mode=driving", headers=_auth(ctx))
    route = r.json()["route"]
    assert route["provider"] == "amap"
    assert route["status"] == "ok"
    leg = route["legs"][0]
    assert leg["distance_m"] == 1479.0
    assert leg["duration_s"] == 125.0
    assert leg["source"] == "amap"
    # 几何已换算回 WGS-84
    assert abs(leg["geometry"][0][0] - P1[0]) < 1e-4
    assert abs(leg["geometry"][0][1] - P1[1]) < 1e-4


# ================================================================ 11. 既有功能未被破坏
async def test_existing_features_still_work(api):
    """要求：既有行程编辑、重新定位与预算功能没有被破坏。"""
    client, ctx = api
    trips = ctx["trips"]

    # 行程编辑：加地点
    new_id = await trips.add_place(ctx["day1"], ctx["uid"], {
        "name": "新加的点", "lat": 29.65, "lon": 91.12,
    })
    assert new_id is not None

    # 重新定位：改坐标（T1-E2）
    r = await client.patch(
        f"/api/trips/places/{ctx['b']}",
        json={"lat": 29.6580, "lon": 91.1350},
        headers=_auth(ctx),
    )
    assert r.status_code == 200

    # 预算（T1-D1）
    rb = await client.patch(
        f"/api/trips/{ctx['trip_id']}/budget",
        json={"travelers": 3, "budget_total_yuan": 2000},
        headers=_auth(ctx),
    )
    assert rb.status_code == 200
    r_cost = await client.post(
        f"/api/trips/{ctx['trip_id']}/costs",
        json={"category": "ticket", "title": "门票", "amount_yuan": 120, "status": "confirmed"},
        headers=_auth(ctx),
    )
    assert r_cost.status_code == 200
    budget = (await client.get(f"/api/trips/{ctx['trip_id']}/budget", headers=_auth(ctx))).json()
    assert budget["budget"]["travelers"] == 3
    assert budget["budget"]["spent_expected_cent"] == 12000

    # 跨天拖拽
    assert await trips.move_place(new_id, ctx["uid"], ctx["day0"], 0) is True

    # 行程仍可读且顺序正确
    trip = await trips.get_trip(ctx["trip_id"], ctx["uid"])
    assert trip is not None
    assert len(trip["days"]) == 2
    assert trip["days"][0]["places"][0]["id"] == new_id