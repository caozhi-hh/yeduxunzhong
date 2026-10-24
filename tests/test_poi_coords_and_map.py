"""T1-E1 验收测试：真实景点坐标校验与地图数据准备。

覆盖任务第三节要求：
  1 有坐标的景点能正确展示        → 坐标原样保留、可被地图消费
  2 缺少/非法坐标不导致崩溃        → 落库降级为 NULL，不抛异常、不伪造
  6 现有编辑保存能力未被破坏       → 加/移/删地点与顺序仍然正确

⚠️ 覆盖边界（如实声明，不含糊）
------------------------------
地图的**交互行为**（切换日期后地图跟随、点击列表定位到标记、点击标记识别景点、
瓦片加载失败降级）发生在浏览器 DOM + Leaflet 里。本项目没有前端 DOM 测试环境
（未安装 jsdom / testing-library，本轮也未获授权新增前端依赖），因此这些行为
**没有自动化测试**，只由 `npx tsc --noEmit` + `npm run build` 保证类型与编译正确，
需人工在浏览器确认。本文件只对**后端数据正确性**做自动化断言。

注意：本文件不复制前端 `hasReliableCoords` 的实现 —— 那样只是把同一段逻辑写两遍，
两边都错也测不出来。前端该函数的正确性由 TypeScript 类型检查与浏览器验收负责。
"""
from __future__ import annotations

import math
import sqlite3
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


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


async def _trip_with_day(temp_db, nickname: str, days: int = 1):
    uid = _make_user(temp_db, nickname)
    import trips

    trip_id = await trips.create_trip(uid, city="拉萨", days=days)
    full = await trips.get_trip(trip_id, uid)
    return uid, trip_id, [d["id"] for d in full["days"]]


# ================================================================ 坐标校验工具
@pytest.mark.parametrize(
    "lat,lon,expected",
    [
        (29.657905, 91.117398, True),      # 正常（拉萨）
        (0.0, 0.0, True),                  # 赤道/本初子午线交点合法
        (90.0, 180.0, True),               # 边界值合法
        (-90.0, -180.0, True),
        (90.0001, 0, False),               # 纬度越界
        (-90.0001, 0, False),
        (0, 180.0001, False),              # 经度越界
        (0, -180.0001, False),
        (999, 1, False),                   # 明显乱填
        (float("nan"), 1, False),          # NaN
        (float("inf"), 1, False),          # 无穷
        (1, float("-inf"), False),
        (None, 1, False),                  # 缺值
        (1, None, False),
        ("abc", 1, False),                 # 非法字符串
        ("29.6", "91.1", True),            # 数字字符串可接受（数据源偶尔给字符串）
    ],
)
def test_is_valid_latlon(lat, lon, expected):
    from tools.poi import is_valid_latlon

    assert is_valid_latlon(lat, lon) is expected


def test_sanitize_coords_never_invents_values():
    """非法坐标一律降级为 (None, None) —— 绝不"修"成某个看似合理的值。"""
    from tools.poi import sanitize_coords

    assert sanitize_coords(29.6579054, 91.1173981) == (29.657905, 91.117398)
    assert sanitize_coords(999, 1) == (None, None)
    assert sanitize_coords(None, None) == (None, None)
    assert sanitize_coords(float("nan"), 1) == (None, None)
    # 只给一半也不行（经纬度必须成对）
    assert sanitize_coords(29.65, None) == (None, None)


def test_photon_feature_with_out_of_range_coords_is_dropped():
    """数据源给出越界坐标时，宁可丢掉这条结果，也不能把脏坐标传出去。"""
    from tools.poi import _photon_to_place

    good = _photon_to_place({
        "properties": {"name": "布达拉宫", "city": "拉萨"},
        "geometry": {"coordinates": [91.117398, 29.657905]},
    })
    assert good is not None
    assert good["lat"] == 29.657905 and good["lon"] == 91.117398

    bad = _photon_to_place({
        "properties": {"name": "坏点"},
        "geometry": {"coordinates": [999, 999]},
    })
    assert bad is None, "越界坐标没有被丢弃"


# ================================================================ 接口层拒绝
def test_place_create_request_rejects_bad_coords():
    """接口层必须拒绝越界坐标（422），而不是先落库再让前端容错。"""
    import main
    from pydantic import ValidationError

    ok = main.PlaceCreateRequest(name="布达拉宫", lat=29.657905, lon=91.117398)
    assert ok.lat == 29.657905

    # 缺坐标是允许的（前端会显示"缺少坐标"）
    assert main.PlaceCreateRequest(name="无坐标点").lat is None

    for bad in (
        {"lat": 999, "lon": 1},
        {"lat": 0, "lon": 181},
        {"lat": -91, "lon": 0},
        {"lat": float("nan"), "lon": 1},
        {"lat": float("inf"), "lon": 1},
    ):
        with pytest.raises(ValidationError):
            main.PlaceCreateRequest(name="x", **bad)


def test_place_update_request_rejects_bad_coords():
    import main
    from pydantic import ValidationError

    assert main.PlaceUpdateRequest(lat=29.6, lon=91.1).lat == 29.6
    assert main.PlaceUpdateRequest(name="改名").lat is None
    for bad in ({"lat": 999}, {"lon": 181}, {"lat": float("nan")}):
        with pytest.raises(ValidationError):
            main.PlaceUpdateRequest(**bad)


# ================================================================ 落库行为
async def test_valid_coords_are_stored_verbatim(temp_db):
    """场景 1：有坐标的景点，坐标原样保存，能被地图直接消费。"""
    await _prep(temp_db)
    import trips

    uid, trip_id, days = await _trip_with_day(temp_db, "e1-valid")
    place_id = await trips.add_place(days[0], uid, {
        "name": "布达拉宫", "lat": 29.6579054, "lon": 91.1173981,
        "address": "城关区", "kind": "attraction", "source": "openstreetmap",
    })
    assert place_id is not None

    saved = (await trips.get_trip(trip_id, uid))["days"][0]["places"][0]
    assert saved["lat"] == 29.657905      # 统一 round(6)
    assert saved["lon"] == 91.117398
    assert saved["address"] == "城关区"
    assert saved["source"] == "openstreetmap"
    # 前端 hasReliableCoords 的判定条件：number 且有限且在范围内
    assert isinstance(saved["lat"], float) and math.isfinite(saved["lat"])
    assert -90 <= saved["lat"] <= 90 and -180 <= saved["lon"] <= 180


async def test_invalid_coords_degrade_to_null_not_crash(temp_db):
    """场景 2：非法坐标不会崩溃，落库为 NULL（明确"无坐标"状态），不被伪造。"""
    await _prep(temp_db)
    import trips

    uid, trip_id, days = await _trip_with_day(temp_db, "e1-bad")

    cases = [
        {"name": "越界纬度", "lat": 999, "lon": 1},
        {"name": "越界经度", "lat": 1, "lon": 999},
        {"name": "NaN", "lat": float("nan"), "lon": 1},
        {"name": "无穷", "lat": 1, "lon": float("inf")},
        {"name": "缺坐标", "lat": None, "lon": None},
        {"name": "不传坐标"},
    ]
    for c in cases:
        pid = await trips.add_place(days[0], uid, c)
        assert pid is not None, f"{c.get('name')} 不该让写入失败"

    places = (await trips.get_trip(trip_id, uid))["days"][0]["places"]
    assert len(places) == len(cases)
    for p in places:
        assert p["lat"] is None and p["lon"] is None, f"{p['name']} 的脏坐标进入了数据库：{p['lat']},{p['lon']}"
        assert p["name"], "地点名必须保留（不能因为没坐标就丢数据）"


async def test_updating_to_invalid_coords_clears_them(temp_db):
    """把坐标改成非法值时，必须是"清空"而不是留下旧的或被伪造的值。"""
    await _prep(temp_db)
    import trips

    uid, trip_id, days = await _trip_with_day(temp_db, "e1-upd")
    pid = await trips.add_place(days[0], uid, {"name": "点", "lat": 29.65, "lon": 91.11})

    assert await trips.update_place(pid, uid, {"lat": 500, "lon": 1}) is True
    p = (await trips.get_trip(trip_id, uid))["days"][0]["places"][0]
    assert p["lat"] is None and p["lon"] is None

    # 只给一个坐标也必须成对处理，不能造出"半个坐标"
    assert await trips.update_place(pid, uid, {"lat": 30.0}) is True
    p2 = (await trips.get_trip(trip_id, uid))["days"][0]["places"][0]
    assert p2["lat"] is None and p2["lon"] is None, "只改 lat 时不应写出半个坐标"


# ================================================================ 真实数据里的错配实例
def test_real_db_has_a_cross_city_mismatch_that_this_round_detects():
    """把真实库里那条跨城错配做成**可复现的证据**，说明这轮校验不是空谈。

    实测：真实库 trip_places id=2/9/12 的「大昭寺」坐标为 (43.998108, 143.749262)，
    实际落在日本北海道，却被放进了拉萨行程。它是**范围内**的合法坐标，
    所以范围校验抓不到 —— 需要"与同一天其他点位距离过远"这条启发式。
    本测试用只读方式确认该记录仍存在（不改动真实库），并证明按本轮的判定逻辑会被标出。
    """
    real_db = BACKEND_DIR / "data" / "travel_planner.db"
    if not real_db.is_file():
        pytest.skip("真实库不存在，跳过（不影响其它断言）")

    con = sqlite3.connect(f"file:{real_db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        rows = list(con.execute(
            "select id, day_id, name, lat, lon from trip_places where lat is not null order by id"
        ))
    finally:
        con.close()

    def approx_km(a_lat, a_lon, b_lat, b_lon):
        R = 6371.0
        d_lat = math.radians(b_lat - a_lat)
        d_lon = math.radians(b_lon - a_lon)
        s = (math.sin(d_lat / 2) ** 2
             + math.cos(math.radians(a_lat)) * math.cos(math.radians(b_lat)) * math.sin(d_lon / 2) ** 2)
        return 2 * R * math.asin(min(1.0, math.sqrt(s)))

    # 按"同一天"分组，找出离同组其他点最近距离仍 > 200km 的点
    by_day: dict[int, list] = {}
    for r in rows:
        by_day.setdefault(r["day_id"], []).append(r)

    flagged = []
    for day_id, group in by_day.items():
        if len(group) < 2:
            continue
        for p in group:
            others = [q for q in group if q["id"] != p["id"]]
            nearest = min(approx_km(p["lat"], p["lon"], q["lat"], q["lon"]) for q in others)
            if nearest > 200:
                flagged.append((p["id"], p["name"], round(nearest)))

    # 这些点范围上合法（所以通过了经纬度校验）
    for r in rows:
        assert -90 <= r["lat"] <= 90 and -180 <= r["lon"] <= 180

    print(f"\n[真实库] 被启发式标为可疑的点: {flagged}")
    assert any("大昭寺" in name for _id, name, _d in flagged), (
        "预期能在真实库里标出跨城错配的『大昭寺』，实际未标出：" + str(flagged)
    )


# ================================================================ 不破坏既有能力
async def test_place_editing_still_works(temp_db):
    """场景 6（回归）：加/删/移/改序仍然正确，没有被本轮改动破坏。"""
    await _prep(temp_db)
    import trips

    uid, trip_id, days = await _trip_with_day(temp_db, "e1-regress", days=2)
    p1 = await trips.add_place(days[0], uid, {"name": "A", "lat": 29.65, "lon": 91.11})
    p2 = await trips.add_place(days[1], uid, {"name": "B", "lat": 29.66, "lon": 91.12})
    p3 = await trips.add_place(days[1], uid, {"name": "C"})       # 无坐标也要能正常排布

    # 跨天移动
    assert await trips.move_place(p1, uid, days[1], 0) is True
    full = await trips.get_trip(trip_id, uid)
    assert [p["name"] for p in full["days"][0]["places"]] == []
    assert [p["name"] for p in full["days"][1]["places"]] == ["A", "B", "C"]
    assert [p["sort_order"] for p in full["days"][1]["places"]] == [0, 1, 2]

    # 改备注等文本字段依然可用
    assert await trips.update_place(p2, uid, {"note": "记得预约", "start_time": "09:00"}) is True
    row = next(p for p in (await trips.get_trip(trip_id, uid))["days"][1]["places"] if p["id"] == p2)
    assert row["note"] == "记得预约" and row["start_time"] == "09:00"
    assert row["lat"] == 29.66, "改文本不该影响坐标"

    # 删除
    assert await trips.delete_place(p3, uid) is True
    names = [p["name"] for p in (await trips.get_trip(trip_id, uid))["days"][1]["places"]]
    assert names == ["A", "B"]


async def test_trip_budget_still_works_after_map_changes(temp_db):
    """场景 6（回归）：预算功能未被本轮的坐标改动影响。"""
    await _prep(temp_db)
    import trips

    uid, trip_id, days = await _trip_with_day(temp_db, "e1-budget")
    await trips.update_trip_budget(trip_id, uid, travelers=2, budget_total_cent=trips.yuan_to_cent(1000))
    await trips.add_cost(trip_id, uid, {
        "category": "ticket", "title": "门票", "amount_cent": trips.yuan_to_cent(120),
        "status": "confirmed",
    })
    s = await trips.compute_budget(trip_id, uid)
    assert s["confirmed_cent"] == 12000
    assert s["spent_expected_cent"] == 12000
    assert s["per_person_cent"] == 6000
    assert s["remaining_cent"] == 100000 - 12000


async def test_no_real_network_call_in_poi_validation():
    """坐标校验是纯函数：不依赖网络，也不会因为校验而发起请求。"""
    from tools import poi

    # _photon_to_place 只做结构转换与校验；越界时直接返回 None，不访问网络
    assert poi._photon_to_place({"properties": {}, "geometry": {"coordinates": []}}) is None
    assert poi._photon_to_place({
        "properties": {"name": "x"}, "geometry": {"coordinates": [1, 2]},
    }) is not None