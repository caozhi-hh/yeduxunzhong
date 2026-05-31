# database.py - SQLite 数据库
import aiosqlite
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "data", "travel_planner.db")

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
"""


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
        await db.commit()
    finally:
        await db.close()
