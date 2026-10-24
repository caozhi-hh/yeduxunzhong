# database.py - SQLite 数据库
import aiosqlite
import os

# 允许用环境变量覆盖库路径：验收脚本据此用**临时库**跑，
# 不会污染你的真实数据（此前路径写死，测试只能动真库）。
DB_PATH = os.environ.get(
    "TRAVEL_DB_PATH",
    os.path.join(os.path.dirname(__file__), "data", "travel_planner.db"),
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    phone         TEXT UNIQUE,
    email         TEXT UNIQUE,
    password_hash TEXT NOT NULL,
    nickname      TEXT NOT NULL DEFAULT '',
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS plans (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id        INTEGER NOT NULL REFERENCES users(id),
    title          TEXT NOT NULL DEFAULT '',
    from_city      TEXT NOT NULL DEFAULT '',
    to_city        TEXT NOT NULL DEFAULT '',
    days           INTEGER NOT NULL DEFAULT 3,
    budget         INTEGER NOT NULL DEFAULT 3000,
    travel_type    TEXT NOT NULL DEFAULT '',
    user_type      TEXT NOT NULL DEFAULT '',
    dep_date       TEXT NOT NULL DEFAULT '',
    ret_date       TEXT NOT NULL DEFAULT '',
    spots          TEXT NOT NULL DEFAULT '[]',
    recommendation TEXT NOT NULL DEFAULT '',
    plan_text      TEXT NOT NULL DEFAULT '',
    params         TEXT NOT NULL DEFAULT '{}',
    created_at     TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ==================== 结构化行程（2026-10-12 新增）====================
-- 与 plans 的区别：plans 存的是「一整篇文章」；这里是「行程 → 每天 → 地点」的结构化实体，
-- 目的是让行程**可编辑**（拖拽换天、改时段、增删地点），而不是每次让模型重写一遍。
-- 地点来自真实 POI（/api/poi/search），带经纬度，所以能在地图上画出来、能算路线。

CREATE TABLE IF NOT EXISTS trips (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(id),
    title      TEXT NOT NULL DEFAULT '',
    city       TEXT NOT NULL DEFAULT '',
    start_date TEXT NOT NULL DEFAULT '',
    end_date   TEXT NOT NULL DEFAULT '',
    note       TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS trip_days (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    trip_id   INTEGER NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
    day_index INTEGER NOT NULL DEFAULT 0,
    date      TEXT NOT NULL DEFAULT '',
    note      TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS trip_places (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    day_id       INTEGER NOT NULL REFERENCES trip_days(id) ON DELETE CASCADE,
    name         TEXT NOT NULL,
    lat          REAL,
    lon          REAL,
    address      TEXT NOT NULL DEFAULT '',
    kind         TEXT NOT NULL DEFAULT '',
    source       TEXT NOT NULL DEFAULT '',
    source_url   TEXT NOT NULL DEFAULT '',
    sort_order   INTEGER NOT NULL DEFAULT 0,
    start_time   TEXT NOT NULL DEFAULT '',
    duration_min INTEGER NOT NULL DEFAULT 0,
    note         TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_trips_user   ON trips(user_id);
CREATE INDEX IF NOT EXISTS idx_days_trip    ON trip_days(trip_id);
CREATE INDEX IF NOT EXISTS idx_places_day   ON trip_places(day_id);

-- ==================== 旅行预算 / 费用明细（T1-D1 新增）====================
-- 为什么单独一张表而不是塞进 trip_places：一条费用可以不属于任何景点
-- （如高铁票、住宿、整体餐饮），塞进地点表会造出大量"没有地点的假地点"。
--
-- 金额单位：**分**（INTEGER）。货币运算不能用浮点，SQLite 也没有 DECIMAL 类型，
--   所以统一按整数分存储，所有加减都在整数域完成（见 trips.py 的金额工具函数）。
--
-- amount_cent 的语义（第一版明确约定）：**该条费用的总金额**，不是人均金额。
--   住宿/交通等由用户输入整项预计支出；每人、每间、每晚等计价模式留待后续版本。
--
-- status 三态：estimated（估算，默认）/ confirmed（已确认）/ pending（待确认）。
--   汇总时"已确认"与"估算"分开呈现，待确认不得混入已确认支出。
CREATE TABLE IF NOT EXISTS trip_costs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    trip_id      INTEGER NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
    category     TEXT NOT NULL DEFAULT 'other',
    title        TEXT NOT NULL DEFAULT '',
    amount_cent  INTEGER NOT NULL DEFAULT 0,
    status       TEXT NOT NULL DEFAULT 'estimated',
    note         TEXT NOT NULL DEFAULT '',
    day_id       INTEGER REFERENCES trip_days(id) ON DELETE SET NULL,
    place_id     INTEGER REFERENCES trip_places(id) ON DELETE SET NULL,
    client_token TEXT,
    created_at   TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_costs_trip ON trip_costs(trip_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_costs_idem
    ON trip_costs(trip_id, client_token) WHERE client_token IS NOT NULL;
"""

# trips 表在 T1-D1 之前没有任何预算相关列（实测：只有 user_id/title/city/日期/note）。
# 这里用幂等迁移补上，**不改动已有行的语义**（旧行程 budget_total 为 NULL = 未设预算，
# travelers 默认 1，且不会被"悄悄当成人均预算"）。
#
# 为什么需要它：CREATE TABLE IF NOT EXISTS 对**已存在**的表不会补列，
# 所以老库（本机真实库有 7 条行程）必须靠 ALTER 升级；重复执行必须安全。
TRIP_COLUMN_MIGRATIONS = (
    ("travelers", "ALTER TABLE trips ADD COLUMN travelers INTEGER NOT NULL DEFAULT 1"),
    ("budget_total_cent", "ALTER TABLE trips ADD COLUMN budget_total_cent INTEGER"),
)


async def _migrate_add_columns(db) -> list[str]:
    """幂等地为已存在的表补列；返回本次实际新增的列名（便于测试断言）。"""
    added: list[str] = []
    rows = await db.execute_fetchall("PRAGMA table_info(trips)")
    existing = {r["name"] for r in rows}
    for column, ddl in TRIP_COLUMN_MIGRATIONS:
        if column not in existing:
            await db.execute(ddl)
            added.append(column)
    return added


async def get_db() -> aiosqlite.Connection:
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA foreign_keys = ON")
    return db


async def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    db = await get_db()
    try:
        await db.executescript(SCHEMA)
        # 建表之后再补列：新库由 SCHEMA 一次建全，旧库走 ALTER。
        # 两步都幂等，重复调用 init_db() 不会报错、也不会重复加列。
        await _migrate_add_columns(db)
        await db.commit()
    finally:
        await db.close()
