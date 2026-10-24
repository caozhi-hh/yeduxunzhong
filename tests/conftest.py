"""T1-0 测试夹具（骨架）—— 预算系统 v2 TDD 的地基。

这个文件存在的唯一目的：保证**任何**测试都不可能碰到真实数据。

三层保护：
  1. 顶部（模块级、import 之前）就把 TRAVEL_DB_PATH 指向临时库，
     并把 JWT_SECRET 设成测试专用假值。
     ⚠️ 顺序至关重要：业务模块 `database.py` 在 **import 时** 读取
     TRAVEL_DB_PATH（见 backend/database.py:7-10）；`config.py` 在 import 时
     会尝试生成/读取 `.jwt_secret`（backend/config.py:61-86）。若先把
     `database` 或 `main` import 进来再设环境变量，临时库设置就已经失效了，
     测试会静默操作真实库。所以这里**只设环境变量、不 import 业务模块**。
  2. `sys.path` 加入 backend/：后端用的是平铺 import（`from database import get_db`、
     `from trips import ...`），不是包结构，因此必须让 backend/ 可被直接导入。
  3. `temp_db` 夹具为**每个测试**建一个独立临时库并清理，测试之间互不干扰。

pytest 在收集到第一个测试模块之前会先 import conftest.py，
所以这里设的环境变量一定早于任何测试模块的顶层 import。
"""
from __future__ import annotations

import os
import shutil
import sys
from itertools import count
from pathlib import Path

# ---------------------------------------------------------------- 路径
TESTS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = TESTS_DIR.parent
BACKEND_DIR = PROJECT_ROOT / "backend"
REAL_DB = BACKEND_DIR / "data" / "travel_planner.db"

# ---------------------------------------------------------------- 临时目录根
# 放在项目 .venv 下：一来 .venv 已被 .gitignore 覆盖，不会污染 git status；
# 二来工具沙箱只允许写工作区内路径，系统 %TEMP% 会被拒绝。
#
# ⚠️ 本文件刻意不使用 tempfile.mkdtemp / pytest 的 tmp_path（实测结论，非推测）：
#   在受限环境下，`tempfile.mkdtemp()` 创建的目录**不可写入**——
#   在其内部写文件稳定报 PermissionError [Errno 13]，在 pytest 进程内与
#   普通 python 进程内均可复现；而 `pathlib.Path.mkdir()` 创建的目录完全正常。
#   同一现象也影响 pytest 的 tmp_path/--basetemp（它会 PermissionError [WinError 5]
#   使测试在 setup 阶段 error）。
#   → 属环境限制，不是代码缺陷；故统一改用 os.makedirs/mkdir 自建临时目录。
TMP_ROOT = PROJECT_ROOT / ".venv" / ".tmptest"
TMP_ROOT.mkdir(parents=True, exist_ok=True)

# 每个测试会话一个唯一子目录（用 pid 区分进程，避免跨进程复用旧目录）
_SESSION_ID = f"s{os.getpid()}"
_SESSION_TMP = TMP_ROOT / _SESSION_ID
_SESSION_TMP.mkdir(parents=True, exist_ok=True)

os.environ["TMPDIR"] = str(_SESSION_TMP)
os.environ["TEMP"] = str(_SESSION_TMP)
os.environ["TMP"] = str(_SESSION_TMP)

# pytest 缓存目录在本沙箱下也会报 "could not create cache path"；缓存只影响重复运行速度，
# 禁用比每次刷一堆告警更干净。
os.environ["PYTEST_ADDOPTS"] = (
    os.environ.get("PYTEST_ADDOPTS", "") + " -p no:cacheprovider"
).strip()

# ---------------------------------------------------------------- 关键：先设环境变量
# 一个进程级默认值，覆盖"测试模块在夹具生效前就 import 业务模块"的情况。
# 真正的隔离靠下面的 temp_db 夹具（每个测试一个库）。
_PROCESS_TMP_DB = TMP_ROOT / "process_default.db"
os.environ["TRAVEL_DB_PATH"] = str(_PROCESS_TMP_DB)

# JWT 用测试专用假值：这样 config.py 走"环境变量优先"分支，
# 既不会读也不会写真实的 backend/.jwt_secret（backend/config.py:63-65）。
os.environ.setdefault("JWT_SECRET", "t1-test-secret-not-a-real-key-0123456789abcdef")

# 后端代码在 backend/ 下平铺导入，必须把它加入 sys.path
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import pytest  # noqa: E402  （必须在设完环境变量后导入）


_case_counter = count(1)


@pytest.fixture()
def temp_dir():
    """每个测试一个独立临时目录（用 mkdir 自建，不依赖 pytest 的 tmp_path）。

    为什么自建：见文件顶部说明 —— 本沙箱下 mkdtemp 产物不可写入、
    pytest 的 tmp_path 会直接 error。本夹具在同一进程内创建、使用、清理。
    """
    d = _SESSION_TMP / f"case-{next(_case_counter):03d}"
    d.mkdir(parents=True, exist_ok=True)
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture()
def temp_db(monkeypatch, temp_dir):
    """每个测试一个独立的临时 SQLite 库，并**同时**把 database.DB_PATH 指过去。

    用法（无需再手工 patch）：
        async def test_xxx(temp_db):
            import database
            await database.init_db()      # 已经作用在临时库上

    为什么必须同时 patch 模块常量：
    `database.DB_PATH` 是在 import 时读一次环境变量定下来的模块级常量
    （backend/database.py:7-10），之后只改 TRAVEL_DB_PATH 环境变量**不会**
    改变它的值。若只改环境变量，测试会继续向真实库写入 —— 这正是本项目
    最不能接受的失败模式。所以这里做"双保险"：
      1. monkeypatch.setenv("TRAVEL_DB_PATH")  —— 管住"之后才 import"的模块
      2. monkeypatch.setattr(database, "DB_PATH") —— 管住"已经 import 过"的模块
    """
    db_file = temp_dir / "test_travel_planner.db"

    if db_file.resolve() == REAL_DB.resolve():  # 极端情况下的自检，宁可报错也不写真实库
        raise RuntimeError(f"拒绝使用真实数据库作为测试库：{REAL_DB}")

    # 保险 1：环境变量层
    monkeypatch.setenv("TRAVEL_DB_PATH", str(db_file))

    # 保险 2：已导入模块的常量层
    import database  # noqa: PLC0415  （此处 import 安全：环境变量已在文件顶部设好）

    monkeypatch.setattr(database, "DB_PATH", str(db_file))
    assert database.DB_PATH == str(db_file), "临时库路径未被成功接管"
    assert database.DB_PATH != str(REAL_DB), "拒绝在真实库上运行测试"

    yield db_file

    # 清理：库文件、WAL、SHM 一起删，避免残留影响下次
    for suffix in ("", "-wal", "-shm"):
        p = Path(str(db_file) + suffix)
        if p.exists():
            p.unlink()


@pytest.fixture()
def backend_dir() -> Path:
    """后端目录路径，供需要直接读文件/拼接路径的测试使用。"""
    return BACKEND_DIR


@pytest.fixture(scope="session", autouse=True)
def _cleanup_session_tmp():
    """整个测试会话结束后清掉本会话的临时目录，保持工作区干净。"""
    yield
    shutil.rmtree(_SESSION_TMP, ignore_errors=True)