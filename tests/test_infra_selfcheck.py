"""T1-0 基础设施自检 —— 验证测试地基真的可用、且绝不可能碰到真实数据。

这是 T1-0（建立可复现测试环境）的**交付自检**，不是业务测试。
它固化本轮踩过的四个环境坑，使后续任何人（或 T1-B 的第一条回归测试）
都能用一条命令确认"地基还在"：

    .venv\\Scripts\\python.exe -m pytest

它断言的四件事：
  1. pytest 能收集并执行 tests/ 下的测试
  2. async def 测试真的被 await 执行（而非被静默跳过）→ asyncio_mode=auto 生效
  3. temp_db 夹具给出的库路径既不是真实库、也真的可读写
  4. 后端模块能在临时库上 init_db()，且真实库与 JWT 密钥文件不受影响
"""
from __future__ import annotations

import asyncio
import os
import sqlite3
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REAL_DB = PROJECT_ROOT / "backend" / "data" / "travel_planner.db"
JWT_SECRET_FILE = PROJECT_ROOT / "backend" / ".jwt_secret"


def _fingerprint(path: Path):
    """只读指纹：大小 + mtime，用于证明文件未被改动。"""
    if not path.exists():
        return None
    st = path.stat()
    return (st.st_size, st.st_mtime_ns)


# ---------------------------------------------------------------- 1. 真实库基线
def test_real_db_exists_and_is_not_touched_yet():
    """前置事实：真实库存在且非空（仅用于对比，绝不写入）。"""
    assert REAL_DB.is_file(), f"真实库不存在：{REAL_DB}"
    assert REAL_DB.stat().st_size > 0


# ---------------------------------------------------------------- 2. 夹具可用
def test_temp_dir_fixture_works(temp_dir):
    """自建临时目录可写可读，且不在真实库所在目录下。"""
    f = temp_dir / "hello.txt"
    f.write_text("ok", encoding="utf-8")
    assert f.read_text(encoding="utf-8") == "ok"
    assert temp_dir.is_dir()
    assert REAL_DB.parent not in temp_dir.parents


def test_temp_db_fixture_isolates_database_path(temp_db):
    """temp_db 必须同时改掉环境变量与已导入模块的常量。"""
    import database  # noqa: PLC0415

    # 环境变量层
    assert Path(os.environ["TRAVEL_DB_PATH"]).resolve() != REAL_DB.resolve()
    # 模块常量层（关键：否则测试会写真实库）
    assert database.DB_PATH == str(temp_db)
    assert Path(database.DB_PATH).resolve() != REAL_DB.resolve()
    # 文件尚未创建（夹具只给路径，不建库）
    assert not Path(temp_db).exists()


# ---------------------------------------------------------------- 3. 异步真执行
async def test_async_execution_is_real():
    """证明 async 测试真的被 await 执行，而不是被静默跳过。

    若 asyncio_mode 配置失效，pytest 会跳过或只告警；下面这行一旦执行到，
    就说明异步测试体确实跑过了。
    """
    await asyncio.sleep(0)
    assert True, "异步测试体未被执行"


# ---------------------------------------------------------------- 4. 临时库上的后端
async def test_backend_init_db_runs_on_temp_db(temp_db):
    """在临时库上导入后端并建表，表结构与真实库一致。"""
    import database  # noqa: PLC0415

    await database.init_db()
    assert Path(temp_db).is_file(), "init_db() 没有在临时路径建库"

    db = await database.get_db()
    try:
        rows = await db.execute_fetchall(
            "select name from sqlite_master where type='table' order by name"
        )
    finally:
        await db.close()

    tables = {r["name"] for r in rows}
    for expected in ("users", "plans", "trips", "trip_days", "trip_places"):
        assert expected in tables, f"临时库缺少表：{expected}"

    # 临时库必须是空库（真实库 plans 有 78 行）——同时证明没连上真实库
    con = sqlite3.connect(str(temp_db))
    try:
        count = con.execute("select count(*) from plans").fetchone()[0]
    finally:
        con.close()
    assert count == 0, f"临时库 plans 有 {count} 行，极可能连到了真实库"


async def test_backend_main_imports_without_touching_real_files(temp_db):
    """导入 FastAPI 应用（含路由）后，真实库与 JWT 密钥文件指纹不变。"""
    before_db = _fingerprint(REAL_DB)
    before_jwt = _fingerprint(JWT_SECRET_FILE)

    import main  # noqa: PLC0415

    paths = [r.path for r in main.app.routes if hasattr(r, "path")]
    assert len(paths) >= 1, "应用没有任何路由"

    assert _fingerprint(REAL_DB) == before_db, "导入后端后真实库被改动了"
    assert _fingerprint(JWT_SECRET_FILE) == before_jwt, "导入后端后 JWT 密钥文件被改动了"


def test_jwt_secret_is_test_value_not_real_one():
    """conftest 必须在 import config 之前把 JWT_SECRET 设为测试专用假值。"""
    assert os.environ.get("JWT_SECRET", "").startswith("t1-test-secret")
    from config import JWT_SECRET  # noqa: PLC0415

    assert JWT_SECRET.startswith("t1-test-secret"), "JWT 未使用测试假值，可能读了真实密钥"