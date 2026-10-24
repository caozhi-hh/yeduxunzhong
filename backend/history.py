# history.py - 攻略历史 CRUD
import json
from database import get_db


async def save_plan(user_id: int, data: dict) -> int:
    db = await get_db()
    try:
        cursor = await db.execute(
            """INSERT INTO plans
            (user_id, title, from_city, to_city, days, budget, travel_type, user_type,
             dep_date, ret_date, spots, recommendation, plan_text, params)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                user_id,
                data.get("title", ""),
                data.get("from_city", ""),
                data.get("to_city", ""),
                data.get("days", 3),
                data.get("budget", 3000),
                data.get("travel_type", ""),
                data.get("user_type", ""),
                data.get("dep_date", ""),
                data.get("ret_date", ""),
                json.dumps(data.get("spots", []), ensure_ascii=False),
                data.get("recommendation", ""),
                data.get("plan_text", ""),
                json.dumps(data.get("params", {}), ensure_ascii=False),
            ),
        )
        await db.commit()
        return cursor.lastrowid
    finally:
        await db.close()


async def list_plans(user_id: int) -> list[dict]:
    db = await get_db()
    try:
        rows = await db.execute_fetchall(
            """SELECT id, title, from_city, to_city, days, budget, travel_type,
                      dep_date, ret_date, spots, created_at, updated_at
               FROM plans WHERE user_id=? ORDER BY updated_at DESC""",
            (user_id,),
        )
        result = []
        for row in rows:
            item = dict(row)
            try:
                item["spots"] = json.loads(item.get("spots", "[]"))
            except Exception:
                item["spots"] = []
            result.append(item)
        return result
    finally:
        await db.close()


async def get_plan(plan_id: int, user_id: int) -> dict | None:
    db = await get_db()
    try:
        rows = await db.execute_fetchall(
            "SELECT * FROM plans WHERE id=? AND user_id=?",
            (plan_id, user_id),
        )
        if not rows:
            return None
        item = dict(rows[0])
        try:
            item["spots"] = json.loads(item.get("spots", "[]"))
        except Exception:
            item["spots"] = []
        try:
            item["params"] = json.loads(item.get("params", "{}"))
        except Exception:
            item["params"] = {}
        return item
    finally:
        await db.close()


async def update_plan_text(plan_id: int, user_id: int, plan_text: str) -> bool:
    db = await get_db()
    try:
        cursor = await db.execute(
            "UPDATE plans SET plan_text=?, updated_at=datetime('now') WHERE id=? AND user_id=?",
            (plan_text, plan_id, user_id),
        )
        await db.commit()
        return cursor.rowcount > 0
    finally:
        await db.close()


async def update_plan(user_id: int, plan_id: int, data: dict) -> bool:
    """就地更新一条已有攻略。

    2026-10-10 修复：对话里每改一版攻略，前端都会回存一次；旧实现无条件 INSERT，
    于是同一份攻略在历史列表里刷出一长串重复条目。带 plan_id 时改为更新同一条。

    只刷新会随修改变化的字段（plan_text / spots / recommendation）与 updated_at，
    其余字段（出发地、天数、预算等）保留首次生成时的值。
    """
    db = await get_db()
    try:
        cursor = await db.execute(
            """UPDATE plans
               SET plan_text=?, spots=?, recommendation=?, updated_at=datetime('now')
               WHERE id=? AND user_id=?""",
            (
                data.get("plan_text", ""),
                json.dumps(data.get("spots", []), ensure_ascii=False),
                data.get("recommendation", ""),
                plan_id,
                user_id,
            ),
        )
        await db.commit()
        return cursor.rowcount > 0
    finally:
        await db.close()


async def delete_plan(plan_id: int, user_id: int) -> bool:
    db = await get_db()
    try:
        cursor = await db.execute(
            "DELETE FROM plans WHERE id=? AND user_id=?",
            (plan_id, user_id),
        )
        await db.commit()
        return cursor.rowcount > 0
    finally:
        await db.close()
