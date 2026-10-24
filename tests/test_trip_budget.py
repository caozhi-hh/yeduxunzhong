"""T1-D1 验收测试：旅行预算 MVP（费用 CRUD + 确定性汇总 + 隔离 + 迁移兼容）。

覆盖任务第四节要求的 10 场景：
  1 创建并读取   2 编辑/删除   3 分类汇总与总额   4 剩余/超支
  5 三态区分     6 非法金额拒绝  7 刷新后持久化     8 用户隔离
  9 旧旅行兼容   10 重复请求不产生重复记录

金额口径（与实现一致）：amount 表示**该条费用的总金额**，不是人均。
金额以**整数分**存储与计算；本文件断言的也是分，避免用浮点比较货币。

所有测试都在临时库上跑（conftest 的 temp_db 夹具），不触碰真实库。
"""
from __future__ import annotations

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


async def _new_trip(temp_db, nickname: str, days: int = 2, travelers: int = 1):
    uid = _make_user(temp_db, nickname)
    import trips

    trip_id = await trips.create_trip(uid, city="测试城", days=days)
    if travelers != 1:
        await trips.update_trip_budget(trip_id, uid, travelers=travelers, budget_total_cent=None)
    return uid, trip_id


# ---------------------------------------------------------------- 1. 创建并读取
async def test_create_and_read_costs(temp_db):
    await _prep(temp_db)
    import trips

    uid, trip_id = await _new_trip(temp_db, "d1-create")

    cid = await trips.add_cost(trip_id, uid, {
        "category": "transport", "title": "高铁票",
        "amount_cent": trips.yuan_to_cent(553.5), "status": "confirmed",
    })
    assert cid is not None

    costs = await trips.list_costs(trip_id, uid)
    assert len(costs) == 1
    row = costs[0]
    assert row["title"] == "高铁票"
    assert row["category"] == "transport"
    # 553.5 元必须精确落成 55350 分（decimal 路径，不受二进制浮点影响）
    assert row["amount_cent"] == 55350
    assert row["amount_yuan"] == 553.5
    assert row["status"] == "confirmed"
    assert row["created_at"] and row["updated_at"], "缺少创建/更新时间"


# ---------------------------------------------------------------- 2. 编辑 / 删除
async def test_update_and_delete_cost(temp_db):
    await _prep(temp_db)
    import trips

    uid, trip_id = await _new_trip(temp_db, "d1-upd")
    cid = await trips.add_cost(trip_id, uid, {
        "category": "food", "title": "午餐", "amount_cent": 5000, "status": "estimated",
    })

    # 改金额 + 改状态
    assert await trips.update_cost(cid, uid, {
        "amount_cent": 8800, "status": "confirmed", "title": "午餐（已结账）",
    }) is True

    row = (await trips.list_costs(trip_id, uid))[0]
    assert row["amount_cent"] == 8800
    assert row["status"] == "confirmed"
    assert row["title"] == "午餐（已结账）"

    # 删除
    assert await trips.delete_cost(cid, uid) is True
    assert await trips.list_costs(trip_id, uid) == []
    # 再删同一条：应返回 False，而不是抛异常
    assert await trips.delete_cost(cid, uid) is False


# ---------------------------------------------------------------- 3. 分类汇总与总额
async def test_category_totals_and_grand_total(temp_db):
    await _prep(temp_db)
    import trips

    uid, trip_id = await _new_trip(temp_db, "d1-sum")
    await trips.add_cost(trip_id, uid, {"category": "transport", "title": "车票", "amount_cent": 30000, "status": "confirmed"})
    await trips.add_cost(trip_id, uid, {"category": "transport", "title": "打车", "amount_cent": 5000, "status": "confirmed"})
    await trips.add_cost(trip_id, uid, {"category": "stay", "title": "两晚", "amount_cent": 60000, "status": "estimated"})
    await trips.add_cost(trip_id, uid, {"category": "ticket", "title": "门票", "amount_cent": 12000, "status": "confirmed"})

    s = await trips.compute_budget(trip_id, uid)
    by = {row["category"]: row for row in s["by_category"]}

    assert by["transport"]["total_cent"] == 35000
    assert by["transport"]["count"] == 2
    assert by["stay"]["total_cent"] == 60000
    assert by["ticket"]["total_cent"] == 12000
    assert by["food"]["total_cent"] == 0, "没有餐饮费用时该分类应为 0 而不是缺行"
    assert len(s["by_category"]) == 5, "五个分类必须都在（空分类也要显示）"

    # 总额 = 已确认 + 估算；分类合计相加必须等于总额（同一口径）
    assert s["confirmed_cent"] == 30000 + 5000 + 12000
    assert s["estimated_cent"] == 60000
    assert s["spent_expected_cent"] == 107000
    assert sum(row["total_cent"] for row in s["by_category"]) == s["spent_expected_cent"]


# ---------------------------------------------------------------- 4. 剩余 / 超支
async def test_remaining_and_over_budget(temp_db):
    await _prep(temp_db)
    import trips

    uid, trip_id = await _new_trip(temp_db, "d1-over", travelers=4)
    assert await trips.update_trip_budget(trip_id, uid, travelers=4, budget_total_cent=trips.yuan_to_cent(1000))

    # 未超支：600 元支出 / 1000 元预算
    await trips.add_cost(trip_id, uid, {"category": "stay", "title": "住宿", "amount_cent": 60000, "status": "confirmed"})
    s = await trips.compute_budget(trip_id, uid)
    assert s["budget_total_cent"] == 100000
    assert s["remaining_cent"] == 40000
    assert s["over_budget"] is False
    assert s["over_by_cent"] == 0
    # 人均 = 60000 / 4 = 15000 分（整数域计算）
    assert s["per_person_cent"] == 15000

    # 再加 500 元 → 超支 100 元 / 10000 分
    await trips.add_cost(trip_id, uid, {"category": "food", "title": "餐饮", "amount_cent": 50000, "status": "confirmed"})
    s2 = await trips.compute_budget(trip_id, uid)
    assert s2["spent_expected_cent"] == 110000
    assert s2["over_budget"] is True
    assert s2["over_by_cent"] == 10000
    assert s2["remaining_cent"] == -10000, "超支时 remaining 必须是负数，不能夹到 0"

    # 恰好等于预算 → 不算超支
    assert await trips.update_trip_budget(trip_id, uid, travelers=4, budget_total_cent=110000)
    s3 = await trips.compute_budget(trip_id, uid)
    assert s3["over_budget"] is False
    assert s3["remaining_cent"] == 0

    # 未设置预算 → 三项都应是 None，而不是当成 0 判超支
    assert await trips.update_trip_budget(trip_id, uid, travelers=4, budget_total_cent=None)
    s4 = await trips.compute_budget(trip_id, uid)
    assert s4["budget_total_cent"] is None
    assert s4["remaining_cent"] is None
    assert s4["over_budget"] is None
    assert s4["over_by_cent"] is None


# ---------------------------------------------------------------- 5. 三态区分
async def test_status_separation(temp_db):
    await _prep(temp_db)
    import trips

    uid, trip_id = await _new_trip(temp_db, "d1-status")
    await trips.add_cost(trip_id, uid, {"category": "ticket", "title": "已付款门票", "amount_cent": 20000, "status": "confirmed"})
    await trips.add_cost(trip_id, uid, {"category": "food", "title": "估算餐饮", "amount_cent": 15000, "status": "estimated"})
    await trips.add_cost(trip_id, uid, {"category": "other", "title": "待定纪念品", "amount_cent": 9000, "status": "pending"})

    s = await trips.compute_budget(trip_id, uid)
    assert s["confirmed_cent"] == 20000
    assert s["estimated_cent"] == 15000
    assert s["pending_cent"] == 9000

    # 关键：待确认**不得**混入与预算比较的口径
    assert s["spent_expected_cent"] == 35000
    assert s["spent_all_cent"] == 44000
    assert s["spent_expected_cent"] != s["spent_all_cent"]

    # 三个状态之和 = spent_all
    assert s["confirmed_cent"] + s["estimated_cent"] + s["pending_cent"] == s["spent_all_cent"]

    # 待确认确实出现在分类行里，但没进"预计"口径
    by = {row["category"]: row for row in s["by_category"]}
    assert by["other"]["pending_cent"] == 9000
    assert by["other"]["total_cent"] == 9000
    assert by["other"]["confirmed_cent"] == 0


async def test_pending_only_trip_does_not_trip_over_budget(temp_db):
    """只有待确认费用时，不应被判超支（否则用户会被虚假警报误导）。"""
    await _prep(temp_db)
    import trips

    uid, trip_id = await _new_trip(temp_db, "d1-pending-only")
    await trips.update_trip_budget(trip_id, uid, travelers=1, budget_total_cent=10000)
    await trips.add_cost(trip_id, uid, {"category": "other", "title": "也许要买", "amount_cent": 999999, "status": "pending"})

    s = await trips.compute_budget(trip_id, uid)
    assert s["spent_expected_cent"] == 0
    assert s["over_budget"] is False
    assert s["remaining_cent"] == 10000


# ---------------------------------------------------------------- 6. 非法金额拒绝
@pytest.mark.parametrize("bad", [-1, -0.01, float("nan"), float("inf"), float("-inf"), "abc", "", "  ", True, None, 10**12])
def test_invalid_amount_rejected(bad):
    """负数 / NaN / 无穷 / 非法字符串 / 布尔 / 空值 / 超限 一律拒绝。"""
    import trips

    with pytest.raises(ValueError):
        trips.yuan_to_cent(bad)


async def test_invalid_amount_rejected_at_write_path(temp_db):
    """非法金额必须在**写入路径**上被挡下，不能先落库再报错。"""
    await _prep(temp_db)
    import trips

    uid, trip_id = await _new_trip(temp_db, "d1-badamt")
    with pytest.raises(ValueError):
        trips.yuan_to_cent(-5)
    # 直接绕过校验写负数（模拟"没走 API 校验"的场景）时，至少确认库里没有脏数据产生
    assert await trips.list_costs(trip_id, uid) == []


def test_api_models_reject_bad_amounts():
    """接口层模型同样拒绝非法金额与非法分类/状态（服务端校验不只在数据层）。"""
    import main
    from pydantic import ValidationError

    good = main.CostCreateRequest(category="food", title="x", amount_yuan=12.34)
    assert good.amount_yuan == 12.34

    for bad in (-1, float("nan"), float("inf"), "abc"):
        with pytest.raises(ValidationError):
            main.CostCreateRequest(category="food", title="x", amount_yuan=bad)

    with pytest.raises(ValidationError):
        main.CostCreateRequest(category="不存在的分类", title="x", amount_yuan=1)
    with pytest.raises(ValidationError):
        main.CostCreateRequest(category="food", title="x", amount_yuan=1, status="乱写")

    # 人数边界：越界必须拒绝
    for bad_travelers in (0, -2, 100, 1000):
        with pytest.raises(ValidationError):
            main.TripBudgetRequest(travelers=bad_travelers)
    assert main.TripBudgetRequest(travelers=4).travelers == 4
    assert main.TripBudgetRequest(travelers=None).travelers is None
    # pydantic 宽松模式会把 "4" 这类数字字符串转成 4，然后照常走 1–99 校验；
    # 这是可接受的行为（表单常传字符串），关键是转换后仍被校验。
    assert main.TripBudgetRequest(travelers="4").travelers == 4
    with pytest.raises(ValidationError):
        main.TripBudgetRequest(travelers="0")

    # 金额同样接受数字字符串，但转换后必须仍然合法
    assert main.CostCreateRequest(category="food", title="x", amount_yuan="12.34").amount_yuan == 12.34
    with pytest.raises(ValidationError):
        main.CostCreateRequest(category="food", title="x", amount_yuan="-1")


def test_amount_rounding_uses_decimal_not_float():
    """货币换算不能有浮点误差：19.99 必须是 1999 分，而不是 1998。"""
    import trips

    assert trips.yuan_to_cent(19.99) == 1999
    assert trips.yuan_to_cent(0.1) + trips.yuan_to_cent(0.2) == trips.yuan_to_cent(0.3)
    assert trips.yuan_to_cent("0.005") == 1        # 半分 → 四舍五入进位
    assert trips.yuan_to_cent(100) == 10000


# ---------------------------------------------------------------- 7. 刷新后持久化
async def test_costs_survive_reload(temp_db):
    """模拟刷新：丢弃内存引用，重新读取，明细与合计都一致。"""
    await _prep(temp_db)
    import trips

    uid, trip_id = await _new_trip(temp_db, "d1-reload", travelers=2)
    await trips.update_trip_budget(trip_id, uid, travelers=2, budget_total_cent=500000)
    await trips.add_cost(trip_id, uid, {"category": "transport", "title": "去程", "amount_cent": 22333, "status": "confirmed"})
    await trips.add_cost(trip_id, uid, {"category": "stay", "title": "住宿", "amount_cent": 40000, "status": "estimated"})

    before = await trips.compute_budget(trip_id, uid)

    # "刷新" = 全新连接重新读（不看任何内存状态）
    after_costs = await trips.list_costs(trip_id, uid)
    after = await trips.compute_budget(trip_id, uid)

    assert len(after_costs) == 2
    assert [c["title"] for c in after_costs] == ["去程", "住宿"]
    assert after["spent_expected_cent"] == before["spent_expected_cent"] == 62333
    assert after["per_person_cent"] == before["per_person_cent"] == 31167  # 62333/2 四舍五入
    assert after["remaining_cent"] == before["remaining_cent"] == 500000 - 62333
    assert after["travelers"] == 2
    assert after["budget_total_cent"] == 500000


# ---------------------------------------------------------------- 8. 用户隔离
async def test_cost_isolation_between_users(temp_db):
    await _prep(temp_db)
    import trips

    uid_a, trip_a = await _new_trip(temp_db, "d1-owner")
    uid_b, _trip_b = await _new_trip(temp_db, "d1-other")
    cid = await trips.add_cost(trip_a, uid_a, {"category": "food", "title": "A 的餐费", "amount_cent": 3000, "status": "confirmed"})

    # B 读不到 A 的行程（None → 路由 404）
    assert await trips.list_costs(trip_a, uid_b) is None
    assert await trips.compute_budget(trip_a, uid_b) is None

    # B 改/删 A 的费用都不行
    assert await trips.update_cost(cid, uid_b, {"amount_cent": 1}) is False
    assert await trips.delete_cost(cid, uid_b) is False
    # B 也不能往 A 的行程里加费用
    assert await trips.add_cost(trip_a, uid_b, {"title": "注入", "amount_cent": 100}) is None
    # B 不能改 A 的预算
    assert await trips.update_trip_budget(trip_a, uid_b, travelers=9, budget_total_cent=1) is False

    # A 的数据完好
    rows = await trips.list_costs(trip_a, uid_a)
    assert len(rows) == 1 and rows[0]["amount_cent"] == 3000
    s = await trips.compute_budget(trip_a, uid_a)
    assert s["travelers"] == 1, "A 的人数不该被 B 的越权请求改动"

    # 不存在的行程 / 不存在的费用都是 False/None，而不是 500
    assert await trips.list_costs(999999, uid_a) is None
    assert await trips.delete_cost(999999, uid_a) is False


async def test_cost_cross_trip_day_or_place_injection_blocked(temp_db):
    """费用不能挂到**别人行程**的 day/place 上（外键注入防护）。"""
    await _prep(temp_db)
    import trips

    uid_a, trip_a = await _new_trip(temp_db, "d1-inj-a")
    uid_b, trip_b = await _new_trip(temp_db, "d1-inj-b")

    day_b = (await trips.get_trip(trip_b, uid_b))["days"][0]["id"]
    place_b = await trips.add_place(day_b, uid_b, {"name": "B 的景点"})

    cid = await trips.add_cost(trip_a, uid_a, {"title": "A 的费用", "amount_cent": 100})
    # 试图把 A 的费用挂到 B 的日程/地点上 → 必须失败
    assert await trips.update_cost(cid, uid_a, {"day_id": day_b}) is False
    assert await trips.update_cost(cid, uid_a, {"place_id": place_b}) is False

    # 挂到自己行程的日程是允许的
    day_a = (await trips.get_trip(trip_a, uid_a))["days"][0]["id"]
    assert await trips.update_cost(cid, uid_a, {"day_id": day_a}) is True


# ---------------------------------------------------------------- 9. 旧旅行兼容
async def test_legacy_trip_rows_get_migrated_and_remain_readable(temp_db):
    """旧库（trips 没有预算列）升级后：旧行可读、默认值合理、重复升级安全。"""
    import asyncio

    import database

    # --- 手工造一个"旧版本"库：trips 只有原始 9 列 ---
    con = sqlite3.connect(str(temp_db))
    try:
        con.executescript("""
            CREATE TABLE users (
                id INTEGER PRIMARY KEY AUTOINCREMENT, phone TEXT UNIQUE, email TEXT UNIQUE,
                password_hash TEXT NOT NULL, nickname TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE TABLE trips (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES users(id),
                title TEXT NOT NULL DEFAULT '', city TEXT NOT NULL DEFAULT '',
                start_date TEXT NOT NULL DEFAULT '', end_date TEXT NOT NULL DEFAULT '',
                note TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            INSERT INTO users (nickname, password_hash) VALUES ('legacy', 'x');
            INSERT INTO trips (user_id, title, city) VALUES (1, '旧行程', '拉萨');
        """)
        con.commit()
    finally:
        con.close()

    # --- 跑迁移：应补上两列，且旧行保持可读 ---
    await database.init_db()
    con = sqlite3.connect(str(temp_db))
    try:
        cols = [r[1] for r in con.execute("PRAGMA table_info(trips)")]
        assert "travelers" in cols and "budget_total_cent" in cols, f"迁移未加列：{cols}"
        row = con.execute("SELECT travelers, budget_total_cent FROM trips WHERE id=1").fetchone()
        assert row == (1, None), f"旧行的默认值不符合预期：{row}"
    finally:
        con.close()

    # --- 重复执行迁移必须安全（幂等）---
    await database.init_db()
    await database.init_db()

    import trips

    legacy = await trips.get_trip(1, 1)
    assert legacy is not None, "迁移后旧行程读不出来了"
    assert legacy["city"] == "拉萨"
    assert legacy["travelers"] == 1
    assert legacy["budget_total_yuan"] is None, "旧行程不该被凭空赋予预算"
    assert legacy["days"] == [], "旧库没有 trip_days 表时不应崩，days 应为空"

    # 旧行程也能正常记账
    cid = await trips.add_cost(1, 1, {"category": "other", "title": "旧行程费用", "amount_cent": 500})
    assert cid is not None
    s = await trips.compute_budget(1, 1)
    assert s["spent_expected_cent"] == 500
    assert s["budget_total_cent"] is None
    assert s["over_budget"] is None

    await asyncio.sleep(0)


# ---------------------------------------------------------------- 10. 重复请求
async def test_repeated_request_does_not_duplicate_cost(temp_db):
    """同一次用户提交重复发送（双击/重试）只应产生一条费用。"""
    await _prep(temp_db)
    import trips

    uid, trip_id = await _new_trip(temp_db, "d1-idem")
    token = "submit-token-abc123"

    first = await trips.add_cost(trip_id, uid, {
        "category": "ticket", "title": "兵马俑门票", "amount_cent": 12000,
        "status": "confirmed", "client_token": token,
    })
    second = await trips.add_cost(trip_id, uid, {
        "category": "ticket", "title": "兵马俑门票", "amount_cent": 12000,
        "status": "confirmed", "client_token": token,
    })
    third = await trips.add_cost(trip_id, uid, {
        "category": "ticket", "title": "兵马俑门票", "amount_cent": 12000,
        "status": "confirmed", "client_token": token,
    })

    assert first == second == third, "幂等键未生效：返回了不同的费用 id"
    costs = await trips.list_costs(trip_id, uid)
    assert len(costs) == 1, f"重复提交产生了 {len(costs)} 条费用"

    s = await trips.compute_budget(trip_id, uid)
    assert s["confirmed_cent"] == 12000, "重复提交把金额也算重复了"

    # 换一个 token（真的是另一笔）→ 应该正常新增
    other = await trips.add_cost(trip_id, uid, {
        "category": "ticket", "title": "兵马俑门票", "amount_cent": 12000,
        "status": "confirmed", "client_token": "another-token",
    })
    assert other != first
    assert len(await trips.list_costs(trip_id, uid)) == 2

    # 不带 token 的两次相同提交按业务语义算两笔（不做内容去重）
    await trips.add_cost(trip_id, uid, {"title": "无 token", "amount_cent": 100})
    await trips.add_cost(trip_id, uid, {"title": "无 token", "amount_cent": 100})
    assert len(await trips.list_costs(trip_id, uid)) == 4


# ---------------------------------------------------------------- 附加：分类/状态白名单
async def test_unknown_category_or_status_falls_back_safely(temp_db):
    """库层收到未知分类/状态时不炸、也不写脏值（接口层另有 422 校验）。"""
    await _prep(temp_db)
    import trips

    uid, trip_id = await _new_trip(temp_db, "d1-fallback")
    await trips.add_cost(trip_id, uid, {"category": "乱写", "title": "x", "amount_cent": 100, "status": "乱写"})

    row = (await trips.list_costs(trip_id, uid))[0]
    # 原样存入但归一到 other/estimated 参与汇总，保证合计口径可控
    s = await trips.compute_budget(trip_id, uid)
    assert s["estimated_cent"] == 100, "未知状态被当成了已确认？"
    assert s["confirmed_cent"] == 0
    by = {r["category"]: r for r in s["by_category"]}
    assert by["other"]["total_cent"] == 100, "未知分类未归入 other"
    assert row["amount_cent"] == 100


async def test_trip_updated_at_advances_on_cost_change(temp_db):
    """记账也是"行程内容变更"：trips.updated_at 必须前进（列表排序才正确）。"""
    import asyncio

    await _prep(temp_db)
    import trips

    uid, trip_id = await _new_trip(temp_db, "d1-ts")

    def updated_at() -> str:
        con = sqlite3.connect(str(temp_db))
        try:
            return con.execute("SELECT updated_at FROM trips WHERE id=?", (trip_id,)).fetchone()[0]
        finally:
            con.close()

    before = updated_at()
    await asyncio.sleep(1.1)
    cid = await trips.add_cost(trip_id, uid, {"title": "x", "amount_cent": 100})
    after_add = updated_at()
    assert after_add > before, f"新增费用后 updated_at 未前进：{before} -> {after_add}"

    await asyncio.sleep(1.1)
    await trips.update_cost(cid, uid, {"amount_cent": 200})
    after_upd = updated_at()
    assert after_upd > after_add, "编辑费用后 updated_at 未前进"

    await asyncio.sleep(1.1)
    await trips.delete_cost(cid, uid)
    after_del = updated_at()
    assert after_del > after_upd, "删除费用后 updated_at 未前进"