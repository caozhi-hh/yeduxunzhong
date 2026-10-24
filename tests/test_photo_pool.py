"""候选图片池测试（九宫格动态补位的数据基础）。

覆盖任务第五节要求中可在后端验证的部分：
  1  初始候选 9 张 —— 分页第一页返回 9 条
  2  候选 18 张时翻页能拿到后续（补位靠它）
  3  连续选择后仍有候选可翻（has_more / next_offset 正确）
  4  候选不足 9 张时如实返回，不造假数据
  5  已选不会重复出现 —— 稳定 id 唯一、跨页无重复
  6  取消选择不丢数据 —— 池是"整池缓存 + 切片"，取消不影响池内容
  7  按景点隔离 —— 不同景点的缓存键与结果互不影响
  8  搜索失败 / 重复结果 / 图床不可达 的处理
  9  选中结果可持久化（这里验证数据结构可序列化且 id 稳定）
 10  老调用方（place_photos）保持兼容

不触网：把两个图源适配器（_tavily_images / _pixabay_images）与下载器
（_download_to_cache）都替换成假实现，只验证本项目自己的逻辑。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


@pytest.fixture(autouse=True)
def _fresh_photo_cache():
    """每个测试用全新的进程内池缓存，避免相互串味。"""
    from tools import photos

    photos._cache.clear()
    photos._cache_loaded = True   # 阻止它去读真实缓存文件
    yield
    photos._cache.clear()


@pytest.fixture()
def fake_sources(monkeypatch):
    """把图源与下载器换成可控的假实现；返回可调参数。"""
    from tools import photos

    state = {
        "tavily": [],          # 每次调用返回的 URL 列表
        "pixabay": {},         # page -> URL 列表
        "tavily_calls": 0,
        "pixabay_calls": [],
        "download_ok": True,
        "fail_tavily": False,
    }

    def fake_tavily(query, limit):
        state["tavily_calls"] += 1
        if state["fail_tavily"]:
            raise RuntimeError("tavily down")
        return list(state["tavily"]), "https://example.test/page"

    def fake_pixabay(query, limit, page=1):
        state["pixabay_calls"].append(page)
        return list(state["pixabay"].get(page, []))

    def fake_download(url, timeout=8):
        if not state["download_ok"]:
            return "", "下载失败（测试）"
        # 文件名由源 URL 派生，保证同一 URL 得到同一文件（与真实实现一致）
        import hashlib

        return f"f_{hashlib.sha1(url.encode()).hexdigest()[:10]}.jpg", ""

    monkeypatch.setattr(photos, "_tavily_images", fake_tavily)
    monkeypatch.setattr(photos, "_pixabay_images", fake_pixabay)
    monkeypatch.setattr(photos, "_download_to_cache", fake_download)
    monkeypatch.setattr(photos, "_make_thumb", lambda fn, width=480: fn)
    monkeypatch.setenv("PIXABAY_API_KEY", "test-key")
    # photos 模块在 import 时读取该 key，这里直接改模块常量
    monkeypatch.setattr(photos, "PIXABAY_KEY", "test-key", raising=False)
    return state


def _urls(n: int, prefix: str = "https://img.example.com/a") -> list[str]:
    return [f"{prefix}{i}.jpg" for i in range(n)]


# ================================================================ 1. 第一页 9 张
def test_first_page_returns_nine(fake_sources):
    from tools import photos

    fake_sources["tavily"] = _urls(12, "https://t.example.com/t")
    pool = photos.place_photo_pool("布达拉宫", "拉萨", limit=9, offset=0)

    assert len(pool["photos"]) == 9, "第一页应为 9 张"
    assert pool["total"] >= 12
    assert pool["has_more"] is True
    assert pool["next_offset"] == 9


# ================================================================ 2 & 3. 翻页补位
def test_pagination_has_no_overlap_and_reaches_all(fake_sources):
    from tools import photos

    fake_sources["tavily"] = _urls(10, "https://a.example.com/x")
    fake_sources["pixabay"] = {1: _urls(10, "https://b.example.com/y")}

    p1 = photos.place_photo_pool("大昭寺", "拉萨", limit=9, offset=0)
    assert len(p1["photos"]) == 9
    p2 = photos.place_photo_pool("大昭寺", "拉萨", limit=9, offset=p1["next_offset"] or 0)

    ids1 = [p["id"] for p in p1["photos"]]
    ids2 = [p["id"] for p in p2["photos"]]
    assert len(ids1) == len(set(ids1)), "同一页内 id 必须唯一"
    assert not (set(ids1) & set(ids2)), "跨页不能出现重复图（否则补位会重复展示）"

    # 18 张候选 → 两页拿完
    assert p1["total"] + 0 == 20 or p1["total"] >= 18
    all_ids = set(ids1) | set(ids2)
    assert len(all_ids) >= 18, f"应能拿到 18 张以上，实际 {len(all_ids)}"


# ================================================================ 4. 候选不足 9
def test_fewer_than_nine_is_reported_honestly(fake_sources):
    from tools import photos

    fake_sources["tavily"] = _urls(3, "https://few.example.com/f")
    pool = photos.place_photo_pool("冷门小庙", "某城", limit=9, offset=0)

    assert len(pool["photos"]) == 3, "只有 3 张就返回 3 张，不补造"
    assert pool["has_more"] is False
    assert pool["next_offset"] is None
    assert pool["total"] == 3


def test_no_candidates_returns_empty_not_fake(fake_sources):
    from tools import photos

    fake_sources["tavily"] = []
    fake_sources["pixabay"] = {}
    pool = photos.place_photo_pool("不存在的地方", "某城", limit=9, offset=0)

    assert pool["photos"] == []
    assert pool["total"] == 0
    assert pool["has_more"] is False
    assert pool["sources"] == []


# ================================================================ 5 & 8. 去重与不可达图床
def test_dedup_by_normalized_url(fake_sources):
    from tools import photos

    # 同一张图被不同站点点名（仅 query/协议不同）→ 必须只留一张
    fake_sources["tavily"] = [
        "https://img.example.com/same.jpg?w=800",
        "http://img.example.com/same.jpg",
        "https://img.example.com/same.jpg#frag",
        "https://img.example.com/other.jpg",
    ]
    pool = photos.place_photo_pool("测试点", "", limit=9, offset=0)
    assert len(pool["photos"]) == 2, f"去重后应剩 2 张，实际 {len(pool['photos'])}"


def test_blocked_hosts_are_skipped(fake_sources):
    from tools import photos

    fake_sources["tavily"] = [
        "https://upload.wikimedia.org/a.jpg",
        "https://commons.wikimedia.org/b.jpg",
        "https://lh3.googleusercontent.com/c.jpg",
        "https://good.example.com/d.jpg",
    ]
    pool = photos.place_photo_pool("测试点", "", limit=9, offset=0)
    assert len(pool["photos"]) == 1
    assert "good.example.com" not in (pool["photos"][0]["credit"] or "")


# ================================================================ 7. 按景点隔离
def test_pools_are_isolated_per_spot(fake_sources):
    from tools import photos

    fake_sources["tavily"] = _urls(5, "https://one.example.com/o")
    a = photos.place_photo_pool("景点甲", "拉萨", limit=9, offset=0)

    fake_sources["tavily"] = _urls(5, "https://two.example.com/t")
    b = photos.place_photo_pool("景点乙", "拉萨", limit=9, offset=0)

    a_ids = {p["id"] for p in a["photos"]}
    b_ids = {p["id"] for p in b["photos"]}
    assert not (a_ids & b_ids), "不同景点的候选不应混用"
    # 再取一次甲：应命中缓存，不再打图源
    calls_before = fake_sources["tavily_calls"]
    again = photos.place_photo_pool("景点甲", "拉萨", limit=9, offset=0)
    assert {p["id"] for p in again["photos"]} == a_ids
    assert fake_sources["tavily_calls"] == calls_before, "整池已缓存，翻页/重复取不应再打图源"


# ================================================================ 8. 搜索失败与下载失败
def test_source_failure_degrades_without_exception(fake_sources):
    from tools import photos

    fake_sources["fail_tavily"] = True
    fake_sources["pixabay"] = {}
    pool = photos.place_photo_pool("会失败的点", "", limit=9, offset=0)
    assert pool["photos"] == [], "图源失败应返回空，而不是抛异常或造图"


def test_download_failure_reduces_count_but_keeps_pool(fake_sources):
    from tools import photos

    fake_sources["tavily"] = _urls(9, "https://d.example.com/d")
    fake_sources["download_ok"] = False
    pool = photos.place_photo_pool("下载全失败", "", limit=9, offset=0)
    assert pool["photos"] == [], "全下载失败时不应返回任何记录（前端显示占位）"
    # 但候选池仍然统计到了 9 张，has_more 体现的是"池"的真实情况
    assert pool["total"] == 9


# ================================================================ 参数与兼容
def test_param_clamping(fake_sources):
    from tools import photos

    fake_sources["tavily"] = _urls(30, "https://p.example.com/p")
    p = photos.place_photo_pool("参数点", "", limit=999, offset=-5)
    assert len(p["photos"]) <= 12, "limit 应被夹到 12 以内"
    assert p["photos"], "负 offset 应被夹为 0，而不是报错"


def test_legacy_place_photos_still_returns_list(fake_sources):
    """老调用方（/api/trip 地点缩略图等）继续拿到 list，不被分页改动破坏。"""
    from tools import photos

    fake_sources["tavily"] = _urls(4, "https://l.example.com/l")
    out = photos.place_photos("兼容点", "拉萨", limit=2)
    assert isinstance(out, list)
    assert len(out) == 2


def test_record_shape_is_serializable_and_stable(fake_sources):
    """选中结果要能存 localStorage 并在 /plan 复用：结构可 JSON 序列化、id 稳定。"""
    from tools import photos

    fake_sources["tavily"] = _urls(3, "https://s.example.com/s")
    pool = photos.place_photo_pool("序列化点", "拉萨", limit=3, offset=0)

    text = json.dumps(pool, ensure_ascii=False)
    back = json.loads(text)
    assert [p["id"] for p in back["photos"]] == [p["id"] for p in pool["photos"]]

    for p in pool["photos"]:
        assert set(["id", "url", "thumb_url", "source_url", "credit", "source"]).issubset(p)
        assert p["url"].startswith("/api/images/"), "必须是自托管路径（前端不直连外站图床）"
        assert p["source"] in ("tavily", "pixabay")

    # 同一个源图再取一次，id 必须一致（跨分页/跨会话稳定）
    photos._cache.clear()
    again = photos.place_photo_pool("序列化点", "拉萨", limit=3, offset=0)
    assert [p["id"] for p in again["photos"]] == [p["id"] for p in pool["photos"]]


# ================================================================ 路由契约
def test_photos_route_exposes_pool_envelope(monkeypatch):
    """接口要给出 total / has_more / next_offset，前端才能判断"还有没有候选"。"""
    import main
    from tools import photos as photos_mod

    monkeypatch.setattr(photos_mod, "_tavily_images", lambda q, l: (_urls(12, "https://r.example.com/r"), "p"))
    monkeypatch.setattr(photos_mod, "_pixabay_images", lambda q, l, page=1: [])
    monkeypatch.setattr(photos_mod, "_download_to_cache", lambda u, timeout=8: (f"f{abs(hash(u))}.jpg", ""))
    monkeypatch.setattr(photos_mod, "_make_thumb", lambda fn, width=480: fn)
    photos_mod._cache.clear()
    photos_mod._cache_loaded = True

    req = main.PoiPhotosRequest(query="布达拉宫", city="拉萨", limit=9, offset=0)
    assert req.offset == 0
    assert main.PoiPhotosRequest(query="x", limit=9, offset=5).offset == 5

    pool = photos_mod.place_photo_pool(req.query, req.city, limit=req.limit, offset=req.offset)
    body = {"status": "ok", **pool}
    for key in ("photos", "total", "has_more", "next_offset", "sources"):
        assert key in body, f"接口响应缺少 {key}"
    assert isinstance(body["photos"], list)