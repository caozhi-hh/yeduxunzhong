"""结构化行程 CRUD —— 行程 → 每天 → 地点

为什么要有它：现有 `plans` 表存的是一整篇「攻略文章」，生成完就只能看、不能改。
成熟项目（TREK / 浮光）都是「结构化行程 + 可编辑」：地点是实体、能拖到别的天、
能改时段、能加备注。这里就是那层数据。

地点带经纬度（来自 /api/poi/search 的真实 POI），所以地图能画、路线能算。

所有函数都做**归属校验**（通过 JOIN 确认这条记录属于当前用户），
避免"猜一个 id 就能改别人行程"这类越权 —— 与 plans 的处理保持一致。
"""
from __future__ import annotations

import decimal
import math

from database import get_db
# 坐标合理性校验与"非法即降级为 None"的策略统一放在 poi 层，避免两处各写一套
from tools.poi import sanitize_coords, is_valid_latlon

# 允许通过接口修改的地点字段（白名单，避免把 id/day_id 之类也改了）
PLACE_FIELDS = ("name", "lat", "lon", "address", "kind", "source", "source_url",
                "start_time", "duration_min", "note")
# 行程可改字段：T1-D1 起增加"人数"与"总预算"
TRIP_FIELDS = ("title", "city", "start_date", "end_date", "note",
               "travelers", "budget_total_cent")

# ---------------------------------------------------------------- 预算：约定与校验
# 费用分类（第一版固定五类，前端下拉与后端校验共用同一份定义）
COST_CATEGORIES = ("transport", "stay", "food", "ticket", "other")
CATEGORY_LABELS = {
    "transport": "交通",
    "stay": "住宿",
    "food": "餐饮",
    "ticket": "景点门票",
    "other": "其他",
}

# 价格状态三态。estimated 可计入"预计总支出"，confirmed 才是真正已花的钱，
# pending 只单独展示、不混入已确认支出。
COST_STATUSES = ("estimated", "confirmed", "pending")
STATUS_LABELS = {"estimated": "估算", "confirmed": "已确认", "pending": "待确认"}

# 金额单位统一为**分**。上限取 1 亿元：既能拦住明显误输入/溢出，又不妨碍真实场景。
MAX_AMOUNT_CENT = 10_000_000_000      # 1 亿元
_CENT = decimal.Decimal(100)
_CENT_INT = 100


def amount_cent_to_yuan(cent: int | None) -> float | None:
    """分 → 元（仅用于返回给前端展示；计算一律在整数分域完成）。"""
    if cent is None:
        return None
    return float(decimal.Decimal(int(cent)) / _CENT)


def yuan_to_cent(value, *, allow_none: bool = False) -> int | None:
    """元 → 分，拒绝负数/NaN/无穷/非法输入。

    走 decimal 而不是 round(v * 100)：后者在 19.99 这类值上会受二进制浮点影响
    （19.99 * 100 == 1998.9999...，直接取整会少一分）。decimal 解析字符串后
    ROUND_HALF_UP，得到与用户输入一致的整数分。

    抛出的 ValueError 由接口层转成 422 —— 金额校验必须在服务端做，
    前端校验只是体验优化。
    """
    if value is None:
        if allow_none:
            return None
        raise ValueError("金额不能为空")
    if isinstance(value, bool):          # bool 是 int 的子类，这里必须显式挡掉
        raise ValueError("金额非法：布尔值不是有效金额")
    if isinstance(value, int):
        cent = value * _CENT_INT
    elif isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            raise ValueError("金额非法：NaN 或无穷大")
        cent = int((decimal.Decimal(repr(value)) * _CENT).to_integral_value(decimal.ROUND_HALF_UP))
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            raise ValueError("金额不能为空")
        try:
            d = decimal.Decimal(text)
        except decimal.InvalidOperation as exc:
            raise ValueError(f"金额非法：{value!r} 不是有效数字") from exc
        if not d.is_finite():
            raise ValueError("金额非法：NaN 或无穷大")
        cent = int((d * _CENT).to_integral_value(decimal.ROUND_HALF_UP))
    else:
        raise ValueError(f"金额非法：不支持的输入类型 {type(value).__name__}")

    if cent < 0:
        raise ValueError("金额不能为负数")
    if cent > MAX_AMOUNT_CENT:
        raise ValueError(f"金额超出上限（最大 {MAX_AMOUNT_CENT // _CENT_INT} 元）")
    return cent


def validate_travelers(value) -> int:
    """人数校验：1–99 的整数。"""
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("人数必须是整数")
    if value < 1 or value > 99:
        raise ValueError("人数需在 1–99 之间")
    return value


# ---------------------------------------------------------------- 行程
async def create_trip(user_id: int, title: str = "", city: str = "",
                      days: int = 3, start_date: str = "", end_date: str = "") -> int:
    """新建行程，并**预建空的每一天**（前端一进去就有 Day1..N 可以放地点）。"""
    days = max(1, min(int(days or 3), 30))
    db = await get_db()
    try:
        cur = await db.execute(
            """INSERT INTO trips (user_id, title, city, start_date, end_date)
               VALUES (?, ?, ?, ?, ?)""",
            (user_id, title or f"{city}行程" if city else "新行程", city, start_date, end_date),
        )
        trip_id = cur.lastrowid
        for i in range(days):
            await db.execute(
                "INSERT INTO trip_days (trip_id, day_index, date) VALUES (?, ?, ?)",
                (trip_id, i, ""),
            )
        await db.commit()
        return trip_id
    finally:
        await db.close()


async def list_trips(user_id: int) -> list[dict]:
    db = await get_db()
    try:
        rows = await db.execute_fetchall(
            """SELECT t.id, t.title, t.city, t.start_date, t.end_date, t.created_at, t.updated_at,
                      t.travelers, t.budget_total_cent,
                      (SELECT COUNT(*) FROM trip_places p
                        JOIN trip_days d ON p.day_id = d.id
                       WHERE d.trip_id = t.id) AS place_count
                 FROM trips t WHERE t.user_id = ? ORDER BY t.updated_at DESC""",
            (user_id,),
        )
        out = []
        for r in rows:
            item = dict(r)
            item["travelers"] = int(item.get("travelers") or 1)
            item["budget_total_yuan"] = amount_cent_to_yuan(item.get("budget_total_cent"))
            out.append(item)
        return out
    finally:
        await db.close()


async def get_trip(trip_id: int, user_id: int) -> dict | None:
    """取一条完整行程：含每天与每天里的地点（按 sort_order 排好）。"""
    db = await get_db()
    try:
        rows = await db.execute_fetchall(
            "SELECT * FROM trips WHERE id = ? AND user_id = ?", (trip_id, user_id)
        )
        if not rows:
            return None
        trip = dict(rows[0])
        # 预算字段以"分"入库，这里补一份"元"视图给前端展示（T1-D1）
        trip["budget_total_yuan"] = amount_cent_to_yuan(trip.get("budget_total_cent"))
        if not trip.get("travelers"):
            trip["travelers"] = 1

        day_rows = await db.execute_fetchall(
            "SELECT * FROM trip_days WHERE trip_id = ? ORDER BY day_index, id", (trip_id,)
        )
        days = [dict(d) for d in day_rows]
        place_rows = await db.execute_fetchall(
            """SELECT p.* FROM trip_places p
                 JOIN trip_days d ON p.day_id = d.id
                WHERE d.trip_id = ?
                ORDER BY p.day_id, p.sort_order, p.id""",
            (trip_id,),
        )
        by_day: dict[int, list] = {}
        for p in place_rows:
            by_day.setdefault(p["day_id"], []).append(dict(p))
        for d in days:
            d["places"] = by_day.get(d["id"], [])
        trip["days"] = days
        return trip
    finally:
        await db.close()


async def update_trip(trip_id: int, user_id: int, data: dict) -> bool:
    fields = {k: v for k, v in data.items() if k in TRIP_FIELDS and v is not None}
    if not fields:
        return bool(await get_trip(trip_id, user_id))
    db = await get_db()
    try:
        sets = ", ".join(f"{k} = ?" for k in fields)
        cur = await db.execute(
            f"UPDATE trips SET {sets}, updated_at = datetime('now') WHERE id = ? AND user_id = ?",
            (*fields.values(), trip_id, user_id),
        )
        await db.commit()
        return cur.rowcount > 0
    finally:
        await db.close()


async def delete_trip(trip_id: int, user_id: int) -> bool:
    db = await get_db()
    try:
        cur = await db.execute("DELETE FROM trips WHERE id = ? AND user_id = ?", (trip_id, user_id))
        await db.commit()
        return cur.rowcount > 0
    finally:
        await db.close()


# ---------------------------------------------------------------- 天
async def add_day(trip_id: int, user_id: int, date: str = "") -> int | None:
    """在行程末尾加一天。"""
    db = await get_db()
    try:
        own = await db.execute_fetchall(
            "SELECT id FROM trips WHERE id = ? AND user_id = ?", (trip_id, user_id))
        if not own:
            return None
        rows = await db.execute_fetchall(
            "SELECT COALESCE(MAX(day_index), -1) AS m FROM trip_days WHERE trip_id = ?", (trip_id,))
        nxt = int(rows[0]["m"]) + 1
        cur = await db.execute(
            "INSERT INTO trip_days (trip_id, day_index, date) VALUES (?, ?, ?)",
            (trip_id, nxt, date),
        )
        await db.execute("UPDATE trips SET updated_at = datetime('now') WHERE id = ?", (trip_id,))
        await db.commit()
        return cur.lastrowid
    finally:
        await db.close()


async def delete_day(day_id: int, user_id: int) -> bool:
    """删一天（连带那天里的地点，靠外键 CASCADE）。"""
    db = await get_db()
    try:
        # 先取所属行程（删完该行就查不到了），与 add_place / delete_place 一致地刷新 updated_at
        rows = await db.execute_fetchall(
            """SELECT d.trip_id FROM trip_days d JOIN trips t ON d.trip_id = t.id
                WHERE d.id = ? AND t.user_id = ?""",
            (day_id, user_id),
        )
        if not rows:
            return False
        trip_id = rows[0]["trip_id"]

        cur = await db.execute(
            """DELETE FROM trip_days WHERE id = ?
                 AND trip_id IN (SELECT id FROM trips WHERE user_id = ?)""",
            (day_id, user_id),
        )
        await db.execute(
            "UPDATE trips SET updated_at = datetime('now') WHERE id = ?", (trip_id,)
        )
        await db.commit()
        return cur.rowcount > 0
    finally:
        await db.close()


# ---------------------------------------------------------------- 地点
async def add_place(day_id: int, user_id: int, place: dict) -> int | None:
    """往某一天加一个地点（通常来自 /api/poi/search）。"""
    db = await get_db()
    try:
        own = await db.execute_fetchall(
            """SELECT d.id FROM trip_days d JOIN trips t ON d.trip_id = t.id
                WHERE d.id = ? AND t.user_id = ?""",
            (day_id, user_id),
        )
        if not own:
            return None
        # T1-E1：坐标先过合理性校验。非法（越界/NaN/非法类型）一律存 NULL，
        # **绝不伪造、也绝不把脏坐标写进库**；前端据此显示"缺少坐标"状态。
        safe_lat, safe_lon = sanitize_coords(place.get("lat"), place.get("lon"))
        rows = await db.execute_fetchall(
            "SELECT COALESCE(MAX(sort_order), -1) AS m FROM trip_places WHERE day_id = ?", (day_id,))
        nxt = int(rows[0]["m"]) + 1
        cur = await db.execute(
            """INSERT INTO trip_places
               (day_id, name, lat, lon, address, kind, source, source_url,
                sort_order, start_time, duration_min, note)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (day_id, str(place.get("name") or "").strip()[:80],
             safe_lat, safe_lon,
             str(place.get("address") or "")[:200], str(place.get("kind") or "")[:30],
             str(place.get("source") or "openstreetmap")[:20],
             str(place.get("source_url") or "")[:300],
             nxt, str(place.get("start_time") or "")[:10],
             int(place.get("duration_min") or 0), str(place.get("note") or "")[:300]),
        )
        await db.execute(
            """UPDATE trips SET updated_at = datetime('now')
                WHERE id = (SELECT trip_id FROM trip_days WHERE id = ?)""", (day_id,))
        await db.commit()
        return cur.lastrowid
    finally:
        await db.close()


async def update_place(place_id: int, user_id: int, data: dict) -> bool:
    fields = {k: v for k, v in data.items() if k in PLACE_FIELDS and v is not None}
    if not fields:
        return False

    # T1-E1：只要这次要改坐标，就必须两个一起给且都合法；否则坐标整体降级为 NULL。
    # 为什么不能只改一个：经纬度成对才有意义，单独写 lat 会造出"半个坐标"的马虎数据。
    if "lat" in fields or "lon" in fields:
        safe_lat, safe_lon = sanitize_coords(fields.get("lat"), fields.get("lon"))
        fields["lat"], fields["lon"] = safe_lat, safe_lon

    db = await get_db()
    try:
        sets = ", ".join(f"{k} = ?" for k in fields)
        cur = await db.execute(
            f"""UPDATE trip_places SET {sets} WHERE id = ?
                  AND day_id IN (SELECT d.id FROM trip_days d JOIN trips t ON d.trip_id = t.id
                                  WHERE t.user_id = ?)""",
            (*fields.values(), place_id, user_id),
        )
        await db.commit()
        return cur.rowcount > 0
    finally:
        await db.close()


async def delete_place(place_id: int, user_id: int) -> bool:
    db = await get_db()
    try:
        # 先取所属行程，删完要同步刷新 trips.updated_at（T1-C1 修复）
        rows = await db.execute_fetchall(
            """SELECT d.trip_id FROM trip_places p
                 JOIN trip_days d ON p.day_id = d.id
                 JOIN trips t ON d.trip_id = t.id
                WHERE p.id = ? AND t.user_id = ?""",
            (place_id, user_id),
        )
        if not rows:
            return False
        trip_id = rows[0]["trip_id"]

        cur = await db.execute(
            """DELETE FROM trip_places WHERE id = ?
                 AND day_id IN (SELECT d.id FROM trip_days d JOIN trips t ON d.trip_id = t.id
                                 WHERE t.user_id = ?)""",
            (place_id, user_id),
        )
        # 与 add_place 保持一致：行程内容变了就刷新 updated_at，
        # 否则左侧列表的排序与时间戳会停在旧值（"改了却没变新"）。
        await db.execute(
            "UPDATE trips SET updated_at = datetime('now') WHERE id = ?", (trip_id,)
        )
        await db.commit()
        return cur.rowcount > 0
    finally:
        await db.close()


async def move_place(place_id: int, user_id: int, to_day_id: int, to_index: int = 0) -> bool:
    """把地点移到另一天（或同一天内换位置）—— 拖拽落地的后端。

    做法：先把它从原处摘掉、重排原天的 sort_order，再插入目标天并重排。
    全部在一个事务里，避免中途失败留下"序号空洞"。
    """
    db = await get_db()
    try:
        rows = await db.execute_fetchall(
            """SELECT p.id, p.day_id FROM trip_places p
                 JOIN trip_days d ON p.day_id = d.id
                 JOIN trips t ON d.trip_id = t.id
                WHERE p.id = ? AND t.user_id = ?""",
            (place_id, user_id),
        )
        if not rows:
            return False
        from_day_id = rows[0]["day_id"]

        # 目标天也必须属于同一用户
        target = await db.execute_fetchall(
            """SELECT d.id FROM trip_days d JOIN trips t ON d.trip_id = t.id
                WHERE d.id = ? AND t.user_id = ?""",
            (to_day_id, user_id),
        )
        if not target:
            return False

        await db.execute("UPDATE trip_places SET day_id = ? WHERE id = ?", (to_day_id, place_id))

        # 目标天重排：把要移动的这条插到 to_index 位置
        ids = [r["id"] for r in await db.execute_fetchall(
            "SELECT id FROM trip_places WHERE day_id = ? ORDER BY sort_order, id", (to_day_id,))]
        ids.remove(place_id)
        idx = max(0, min(int(to_index or 0), len(ids)))
        ids.insert(idx, place_id)
        for i, pid in enumerate(ids):
            await db.execute("UPDATE trip_places SET sort_order = ? WHERE id = ?", (i, pid))

        # 原天重排（如果换了天）
        if from_day_id != to_day_id:
            src = [r["id"] for r in await db.execute_fetchall(
                "SELECT id FROM trip_places WHERE day_id = ? ORDER BY sort_order, id", (from_day_id,))]
            for i, pid in enumerate(src):
                await db.execute("UPDATE trip_places SET sort_order = ? WHERE id = ?", (i, pid))

        await db.execute("UPDATE trips SET updated_at = datetime('now') WHERE id = "
                         "(SELECT trip_id FROM trip_days WHERE id = ?)", (to_day_id,))
        await db.commit()
        return True
    finally:
        await db.close()


# ================================================================ 费用明细（T1-D1）
# 归属校验一律通过 trips.user_id，与地点那套保持一致：
# 猜一个 cost id 也改不了别人的数据。
COST_TEXT_LIMITS = {"title": 80, "note": 300}

# 允许通过接口修改的费用字段（白名单）
COST_FIELDS = ("category", "title", "amount_cent", "status", "note",
               "day_id", "place_id")


def _clean_cost_fields(data: dict) -> dict:
    """白名单 + 长度截断，避免把 id/trip_id/created_at 之类也写进去。"""
    out: dict = {}
    for key in COST_FIELDS:
        if key not in data:
            continue
        value = data[key]
        if value is None:
            # day_id/place_id 允许置空；其余字段忽略 None（保持原值）
            if key in ("day_id", "place_id"):
                out[key] = None
            continue
        if key in COST_TEXT_LIMITS:
            out[key] = str(value)[: COST_TEXT_LIMITS[key]]
        else:
            out[key] = value
    return out


def _row_to_cost(row) -> dict:
    """DB 行 → 前端友好结构：金额同时给出「分」（计算用）与「元」（展示用）。"""
    item = dict(row)
    item["amount_yuan"] = amount_cent_to_yuan(item.get("amount_cent"))
    item["category_label"] = CATEGORY_LABELS.get(item.get("category"), item.get("category"))
    item["status_label"] = STATUS_LABELS.get(item.get("status"), item.get("status"))
    return item


async def _assert_trip_owned(db, trip_id: int, user_id: int) -> bool:
    """确认这条行程属于该用户 —— 所有费用操作的前置门槛。"""
    rows = await db.execute_fetchall(
        "SELECT id FROM trips WHERE id = ? AND user_id = ?", (trip_id, user_id)
    )
    return bool(rows)


async def list_costs(trip_id: int, user_id: int) -> list[dict] | None:
    """取一条行程的全部费用；行程不存在或不属于该用户时返回 None（路由转 404）。"""
    db = await get_db()
    try:
        if not await _assert_trip_owned(db, trip_id, user_id):
            return None
        rows = await db.execute_fetchall(
            """SELECT * FROM trip_costs WHERE trip_id = ?
                ORDER BY created_at, id""",
            (trip_id,),
        )
        return [_row_to_cost(r) for r in rows]
    finally:
        await db.close()


async def add_cost(trip_id: int, user_id: int, data: dict) -> int | None:
    """新增一条费用。

    client_token：幂等键。前端为"一次用户提交"生成一个 token，
    重复请求（双击 / 网络重试）命中同一个 token 时**返回已存在的那条**，
    不再新增 —— 避免非预期的重复费用。token 为空则按普通新增处理。
    """
    fields = _clean_cost_fields(data)
    db = await get_db()
    try:
        if not await _assert_trip_owned(db, trip_id, user_id):
            return None

        token = data.get("client_token")
        token = str(token)[:64] if token else None
        if token:
            existing = await db.execute_fetchall(
                "SELECT id FROM trip_costs WHERE trip_id = ? AND client_token = ?",
                (trip_id, token),
            )
            if existing:
                return int(existing[0]["id"])

        cur = await db.execute(
            """INSERT INTO trip_costs
               (trip_id, category, title, amount_cent, status, note,
                day_id, place_id, client_token, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))""",
            (
                trip_id,
                str(fields.get("category") or "other")[:20],
                str(fields.get("title") or "")[: COST_TEXT_LIMITS["title"]],
                int(fields.get("amount_cent") or 0),
                str(fields.get("status") or "estimated")[:20],
                str(fields.get("note") or "")[: COST_TEXT_LIMITS["note"]],
                fields.get("day_id"),
                fields.get("place_id"),
                token,
            ),
        )
        await db.execute("UPDATE trips SET updated_at = datetime('now') WHERE id = ?", (trip_id,))
        await db.commit()
        return int(cur.lastrowid)
    finally:
        await db.close()


async def update_cost(cost_id: int, user_id: int, data: dict) -> bool:
    """改一条费用（只有它所属行程的 owner 能改）。

    除白名单外还显式防御两个**外键注入**点：day_id / place_id 可以被任意数字提交，
    必须确认它们确实属于同一趟行程，否则会把费用挂到别人的日程/地点上。
    """
    fields = _clean_cost_fields(data)
    if not fields:
        return False
    db = await get_db()
    try:
        rows = await db.execute_fetchall(
            """SELECT c.id, c.trip_id FROM trip_costs c
                 JOIN trips t ON c.trip_id = t.id
                WHERE c.id = ? AND t.user_id = ?""",
            (cost_id, user_id),
        )
        if not rows:
            return False
        trip_id = int(rows[0]["trip_id"])

        if "day_id" in fields and fields["day_id"] is not None:
            own = await db.execute_fetchall(
                "SELECT id FROM trip_days WHERE id = ? AND trip_id = ?",
                (fields["day_id"], trip_id),
            )
            if not own:
                return False
        if "place_id" in fields and fields["place_id"] is not None:
            own = await db.execute_fetchall(
                """SELECT p.id FROM trip_places p
                     JOIN trip_days d ON p.day_id = d.id
                    WHERE p.id = ? AND d.trip_id = ?""",
                (fields["place_id"], trip_id),
            )
            if not own:
                return False

        sets = ", ".join(f"{k} = ?" for k in fields)
        cur = await db.execute(
            f"""UPDATE trip_costs SET {sets}, updated_at = datetime('now')
                 WHERE id = ?
                   AND trip_id IN (SELECT id FROM trips WHERE user_id = ?)""",
            (*fields.values(), cost_id, user_id),
        )
        await db.execute("UPDATE trips SET updated_at = datetime('now') WHERE id = ?", (trip_id,))
        await db.commit()
        return cur.rowcount > 0
    finally:
        await db.close()


async def delete_cost(cost_id: int, user_id: int) -> bool:
    db = await get_db()
    try:
        rows = await db.execute_fetchall(
            """SELECT c.trip_id FROM trip_costs c
                 JOIN trips t ON c.trip_id = t.id
                WHERE c.id = ? AND t.user_id = ?""",
            (cost_id, user_id),
        )
        if not rows:
            return False
        trip_id = int(rows[0]["trip_id"])

        cur = await db.execute(
            """DELETE FROM trip_costs WHERE id = ?
                 AND trip_id IN (SELECT id FROM trips WHERE user_id = ?)""",
            (cost_id, user_id),
        )
        await db.execute("UPDATE trips SET updated_at = datetime('now') WHERE id = ?", (trip_id,))
        await db.commit()
        return cur.rowcount > 0
    finally:
        await db.close()


async def update_trip_budget(trip_id: int, user_id: int,
                            travelers: int | None, budget_total_cent: int | None) -> bool:
    """设置人数 / 总预算。budget_total_cent 传 None 表示"清空预算上限"。"""
    db = await get_db()
    try:
        if not await _assert_trip_owned(db, trip_id, user_id):
            return False
        # 这里显式写 NULL：不能用 update_trip()，因为它会滤掉 None 值（那正是"清空"的语义）
        await db.execute(
            """UPDATE trips SET travelers = COALESCE(?, travelers),
                                budget_total_cent = ?,
                                updated_at = datetime('now')
                WHERE id = ? AND user_id = ?""",
            (travelers, budget_total_cent, trip_id, user_id),
        )
        await db.commit()
        return True
    finally:
        await db.close()


def _round_half_up_div(numerator: int, denominator: int) -> int:
    """整数域的四舍五入除法（远离零方向）。全整数，无浮点误差。"""
    if denominator <= 0:
        return 0
    return (numerator + denominator // 2) // denominator


async def compute_budget(trip_id: int, user_id: int) -> dict | None:
    """确定性的预算汇总 —— 所有合计都由这段程序算，不依赖任何模型输出。

    金额全程用**整数分**运算，最后才换算成元返回，避免浮点误差累积。

    口径（第一版明确约定，接口里也会标注）：
      * confirmed  = 已确认支出（真正花掉/已付款）
      * estimated  = 估算支出（预计会发生）
      * pending    = 待确认（**不计入**任何合计，只单独展示）
      * spent_expected = confirmed + estimated      → 用于与预算比较、算人均
      * spent_all      = confirmed + estimated + pending（仅供"含待确认"视图）
    剩余与超支都以 spent_expected 为基准；超支时 remaining 为负数（不夹到 0）。
    """
    db = await get_db()
    try:
        # 一次查询同时完成：归属校验 + 取预算/人数（不属于该用户时直接返回 None）
        rows = await db.execute_fetchall(
            "SELECT travelers, budget_total_cent FROM trips WHERE id = ? AND user_id = ?",
            (trip_id, user_id),
        )
        if not rows:
            return None
        trip = dict(rows[0])
        cost_rows = await db.execute_fetchall(
            "SELECT category, status, amount_cent FROM trip_costs WHERE trip_id = ?",
            (trip_id,),
        )
    finally:
        await db.close()

    travelers = int(trip.get("travelers") or 1)
    budget_cent = trip.get("budget_total_cent")
    budget_cent = int(budget_cent) if budget_cent is not None else None

    by_status = {"confirmed": 0, "estimated": 0, "pending": 0}
    by_category: dict[str, dict] = {
        c: {"category": c, "label": CATEGORY_LABELS[c],
            "confirmed_cent": 0, "estimated_cent": 0, "pending_cent": 0,
            "total_cent": 0, "count": 0}
        for c in COST_CATEGORIES
    }

    for r in cost_rows:
        amount = int(r["amount_cent"] or 0)
        status = r["status"] if r["status"] in COST_STATUSES else "estimated"
        category = r["category"] if r["category"] in COST_CATEGORIES else "other"

        by_status[status] += amount
        bucket = by_category[category]
        bucket[f"{status}_cent"] += amount
        bucket["total_cent"] += amount
        bucket["count"] += 1

    spent_expected = by_status["confirmed"] + by_status["estimated"]
    spent_all = spent_expected + by_status["pending"]

    summary = {
        "trip_id": trip_id,
        "travelers": travelers,
        "currency": "CNY",
        "amount_unit": "cent",           # 所有 *_cent 字段的单位声明
        # ---- 预算 ----
        "budget_total_cent": budget_cent,
        "budget_total_yuan": amount_cent_to_yuan(budget_cent),
        # ---- 三类支出（分）----
        "confirmed_cent": by_status["confirmed"],
        "estimated_cent": by_status["estimated"],
        "pending_cent": by_status["pending"],
        # ---- 关键合计 ----
        "spent_expected_cent": spent_expected,
        "spent_all_cent": spent_all,
        # ---- 对应的"元"视图，供前端直接展示 ----
        "confirmed_yuan": amount_cent_to_yuan(by_status["confirmed"]),
        "estimated_yuan": amount_cent_to_yuan(by_status["estimated"]),
        "pending_yuan": amount_cent_to_yuan(by_status["pending"]),
        "spent_expected_yuan": amount_cent_to_yuan(spent_expected),
        "spent_all_yuan": amount_cent_to_yuan(spent_all),
        # ---- 人均（整数分四舍五入）----
        "per_person_cent": _round_half_up_div(spent_expected, travelers),
        "per_person_yuan": amount_cent_to_yuan(_round_half_up_div(spent_expected, travelers)),
        # ---- 剩余 / 超支 ----
        "remaining_cent": None if budget_cent is None else budget_cent - spent_expected,
        "remaining_yuan": None if budget_cent is None else amount_cent_to_yuan(budget_cent - spent_expected),
        "over_budget": None if budget_cent is None else spent_expected > budget_cent,
        "over_by_cent": None if budget_cent is None else max(0, spent_expected - budget_cent),
        "over_by_yuan": None if budget_cent is None else amount_cent_to_yuan(max(0, spent_expected - budget_cent)),
        "cost_count": len(cost_rows),
        "by_category": [by_category[c] for c in COST_CATEGORIES],
    }
    return summary