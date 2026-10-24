"""地点照片层 —— 给真实地点配真实照片

为什么需要它：现在地图上只有"点"，用户没法凭名字判断要不要去。
参考项目都是"看图选"（TREK 显示候选照片、浮光有景点图、见好"每天有实拍图"）。

照片来源与实测（注意"从哪台机器"这个前提）：

  ✅ Tavily include_images   大陆直连 2.0s，搜「布达拉宫」返回 **5 张该景点真实照片**
  ⚠️ Pixabay                中文名匹配**完全失效**（搜「布达拉宫」返回拉面/丝绸），
                            必须用英文名（「Potala Palace」才准）→ 作为兜底
  ❌ Wikipedia / Wikimedia  大陆全部连不上（Google/Wikipedia 系不可达）
  ❌ Wikimedia Commons      同上

做法：拿到图片地址后**下载到本机缓存**，由 /api/images/{file} 自托管 ——
与 Pixabay 通道同一套机制，好处是热链不会失效、不受跨域限制、二次访问零网络。

⚠️ 版权说明：这些是第三方站点上的照片，非 CC0 图库。因此每条都**保留来源页链接**，
前端展示时给出"图片来源"入口；仅作参考用途，不要二次分发。
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.parse
import urllib.request

os.environ.setdefault("NO_PROXY", "*")
os.environ.setdefault("no_proxy", "*")

UA = "yedu-xunzong/0.1 (personal travel planner)"

# 复用图片通道的下载器（同一个缓存目录，因此 /api/images/ 能直接服务这些文件）
from tools.images import _download_to_cache  # noqa: E402

TAVILY_KEY = os.environ.get("TAVILY_API_KEY", "").strip()
PIXABAY_KEY = os.environ.get("PIXABAY_API_KEY", "").strip()

# 已知在大陆取不到的图床：直接跳过，不浪费并发位与时间。
# - Wikimedia 系：实测全部超时（Tavily 候选里第一张常是它，正是它拖慢整批）
# - blogger.googleusercontent：Google 系，大陆不通
_BLOCKED_HOSTS = ("upload.wikimedia.org", "wikimedia.org", "wikipedia.org",
                  "googleusercontent.com", "ggpht.com")

_CACHE_FILE = os.environ.get(
    "PHOTO_CACHE_FILE",
    os.path.join(os.environ.get("DATA_DIR", "/data"), "photo_cache.json"),
)
_cache: dict = {}
_cache_loaded = False


def _load_cache() -> None:
    global _cache_loaded
    if _cache_loaded:
        return
    _cache_loaded = True
    try:
        with open(_CACHE_FILE, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            _cache.update(data)
    except FileNotFoundError:
        pass
    except Exception as exc:  # noqa: BLE001
        print(f"[photos] 载入缓存失败: {exc}")


def _save_cache() -> None:
    try:
        os.makedirs(os.path.dirname(_CACHE_FILE), exist_ok=True)
        with open(_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(dict(list(_cache.items())[-200:]), f, ensure_ascii=False)
    except Exception as exc:  # noqa: BLE001
        print(f"[photos] 保存缓存失败: {exc}")


def _tavily_images(query: str, limit: int) -> tuple:
    """用 Tavily 搜该地点的照片。返回 (图片地址列表, 来源页地址)。"""
    if not TAVILY_KEY:
        return [], ""
    payload = {"query": query, "max_results": 3, "include_images": True,
               "include_image_descriptions": True, "search_depth": "basic"}
    req = urllib.request.Request(
        "https://api.tavily.com/search",
        data=json.dumps(payload).encode(), method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {TAVILY_KEY}"},
    )
    data = json.loads(urllib.request.urlopen(req, timeout=40).read().decode("utf-8", "replace"))
    urls = []
    for im in (data.get("images") or [])[:limit]:
        u = im.get("url") if isinstance(im, dict) else im
        if u:
            urls.append(str(u))
    results = data.get("results") or []
    source = str((results[0] or {}).get("url") or "") if results else ""
    return urls, source


def _pixabay_images(query: str, limit: int, page: int = 1) -> list:
    """Pixabay 图搜（支持翻页）。

    ⚠️ 更正一条过时注释：原代码写着"中文名基本没用，调用方应传英文名"。
    R2/本轮实测**中文名完全可用**：`大昭寺` → totalHits=500、单页可返回 20 张。
    因此这里是拿到"≥9 张候选"的**主要来源**（Tavily 每次固定只给约 5 张，
    max_results 调到 12 也一样，实测确认）。

    page 从 1 开始（Pixabay 的约定）。
    """
    if not PIXABAY_KEY:
        return []
    url = "https://pixabay.com/api/?" + urllib.parse.urlencode(
        {"key": PIXABAY_KEY, "q": query, "image_type": "photo",
         "orientation": "horizontal", "per_page": max(3, min(int(limit), 20)),
         "page": max(1, int(page)), "safesearch": "true"})
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    data = json.loads(urllib.request.urlopen(req, timeout=25).read().decode("utf-8", "replace"))
    return [h.get("largeImageURL") or h.get("webformatURL") for h in (data.get("hits") or [])
            if h.get("webformatURL")]


def _make_thumb(fn: str, width: int = 480) -> str:
    """把已下载的图压成卡片用的小图，返回新文件名（失败就返回原文件名）。

    为什么必须压：图选来源的图动辄 170~480KB，而卡片只需要 300px 宽。
    实测压到 480px / JPEG q78 后通常 25~50KB，**展示速度快一个数量级**，
    这对"等很久才看到图"是最直接的改善。Pillow 不可用时静默退回原图。
    """
    try:
        from PIL import Image
    except Exception:  # noqa: BLE001
        return fn
    src = os.path.join(_images_dir(), fn)
    dst_name = "t_" + fn.rsplit(".", 1)[0] + ".jpg"
    dst = os.path.join(_images_dir(), dst_name)
    if os.path.exists(dst) and os.path.getsize(dst) > 0:
        return dst_name
    try:
        with Image.open(src) as im:
            im = im.convert("RGB")
            if im.width > width:
                im = im.resize((width, max(1, round(im.height * width / im.width))), Image.LANCZOS)
            im.save(dst, "JPEG", quality=78, optimize=True)
        return dst_name if os.path.getsize(dst) > 0 else fn
    except Exception as exc:  # noqa: BLE001
        print(f"[photos] 压图失败({type(exc).__name__})，退回原图")
        return fn


def _images_dir() -> str:
    from tools.images import images_dir
    return images_dir()


# ==================== 候选池（本轮新增：支持九宫格"动态补位"）====================
# 为什么需要它：九宫格要"初始 9 张 + 选中后从候选池补下一张"，
# 而原来的 place_photos 每次最多只给 6 张、且没有翻页能力 —— 只改前端展示数量
# 是拿不到 9 张以上的。这里把**同一条链路**（Tavily + Pixabay）扩成可分页的候选池。
#
# 实测依据（不要凭印象改）：
#   · Tavily 的 include_images 每次固定返回约 5 张，max_results 设 3/8/12 都是 5 张；
#     去掉大陆不可达图床后只剩约 4 张 → 单靠它永远到不了 9 张。
#   · Pixabay 中文名可用（「大昭寺」totalHits=500），且支持翻页 → 主来源。
MAX_CANDIDATES = 24          # 单个地点的候选池上限（防止无限翻页打爆配额）
_PIXABAY_PAGE_SIZE = 20


def _norm_url(u: str) -> str:
    """去重用的稳定归一化：忽略协议与查询串差异，只比较 host+path。

    为什么不直接比原始 URL：同一张图常被不同站点带不同的 query（?w=800 等），
    按原串去重会留下重复图。
    """
    try:
        p = urllib.parse.urlparse(u)
    except Exception:  # noqa: BLE001
        return u
    return f"{(p.netloc or '').lower()}{p.path}".rstrip("/")


def _is_blocked(u: str) -> bool:
    host = (urllib.parse.urlparse(u).hostname or "").lower()
    return any(h in host for h in _BLOCKED_HOSTS)


def _candidate_pool(name: str, city: str) -> list[dict]:
    """收集一个地点的候选图（**带缓存**，按 name|city 缓存整池而不是按 limit/offset）。

    为什么按整池缓存：翻页时若按 (name|city|limit|offset) 缓存，每翻一页都要重新
    搜索一遍（Tavily/Pixabay 都要花配额）。缓存整池后翻页只是切片，零额外搜索。
    """
    ck = f"pool|{name}|{city}"
    _load_cache()
    if ck in _cache:
        return _cache[ck]

    items: list[dict] = []
    seen: set[str] = set()

    def _add(url: str, credit: str, source_page: str = "") -> None:
        if not url or _is_blocked(url):
            return
        key = _norm_url(url)
        if not key or key in seen:
            return
        seen.add(key)
        items.append({"src": url, "credit": credit, "source_page": source_page})

    # ① Tavily（每次约 5 张；多查询链提高覆盖）
    queries = []
    for q in (f"{name} {city}".strip(), f"{name} {city} 景点".strip(), name):
        if q and q not in queries:
            queries.append(q)
    for query in queries:
        if len(items) >= MAX_CANDIDATES:
            break
        try:
            cand, page_url = _tavily_images(query, 8)
        except Exception as exc:  # noqa: BLE001
            print(f"[photos] Tavily 取图失败({query}): {type(exc).__name__}")
            continue
        for u in cand:
            _add(u, "Tavily 搜索", page_url)
        if items:
            break   # 第一条查询有结果就不再换链，省配额

    # ② Pixabay 翻页补足（中文名可用，是达到 9+ 的主要来源）
    page = 1
    while PIXABAY_KEY and len(items) < MAX_CANDIDATES and page <= 2:
        try:
            hits = _pixabay_images(name, _PIXABAY_PAGE_SIZE, page=page)
        except Exception as exc:  # noqa: BLE001
            print(f"[photos] Pixabay 第{page}页失败: {type(exc).__name__}")
            break
        if not hits:
            break
        before = len(items)
        for u in hits:
            _add(u, "Pixabay")
        if len(items) == before:   # 这一页全是重复 → 没必要继续翻
            break
        page += 1

    print(f"[photos] {name} 候选池 = {len(items)} 张")
    _cache[ck] = items
    _save_cache()
    return items


def place_photo_pool(name: str, city: str = "", limit: int = 9, offset: int = 0) -> dict:
    """取一个地点的**候选图片池**（可分页），供九宫格动态补位使用。

    返回：
      photos       本次这一页的图片记录（每条含稳定 id，便于前端去重与做 key）
      total        候选总数（本页之前已统计到的真实数量，不是估算）
      has_more     是否还有更多候选可翻
      next_offset  下一页偏移；没有更多时为 None
      sources      本页涉及的来源名称（如 ["Tavily 搜索", "Pixabay"]）

    抓不到就返回空 photos —— **绝不伪造图片或来源**。
    """
    name = re.sub(r"\s+", " ", str(name or "")).strip()
    limit = max(1, min(int(limit or 9), 12))
    offset = max(0, int(offset or 0))
    empty = {"photos": [], "total": 0, "has_more": False, "next_offset": None, "sources": []}
    if not name:
        return empty

    cats = _candidate_pool(name, city)
    total = len(cats)
    if total == 0:
        print(f"[photos] {name}：所有来源都没给出可用候选")
        return empty

    window = cats[offset: offset + limit]
    photos = _materialize(window)

    next_offset = offset + limit
    has_more = next_offset < total
    return {
        "photos": photos,
        "total": total,
        "has_more": has_more,
        "next_offset": next_offset if has_more else None,
        "sources": sorted({p.get("source") or "" for p in photos if p.get("source")}),
        # 注意：本页可能因下载失败少于 limit 张，但 has_more 仍以**候选池**为准，
        # 这样前端可以继续翻页拿到后面真正能下载的图，而不是提前判定耗尽。
    }


def _materialize(window: list[dict]) -> list[dict]:
    """把候选源 URL 下载成可自托管的记录（并发 + 整批 10s 截止）。

    ⚠️ 产出**必须按 window 的原始顺序**，不能按下载完成顺序：
    as_completed 是"谁先下完谁先出"，会让同一批候选在不同请求里顺序不同 ——
    九宫格会因此抖动，分页切片与展示顺序也会对不上。这里按下标回填再顺序输出。
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import hashlib

    out: list[dict] = []
    if not window:
        return out

    def _fetch(u: str):
        return _download_to_cache(u, timeout=8)

    by_index: dict[int, dict] = {}
    pool = ThreadPoolExecutor(max_workers=max(1, min(6, len(window))))
    futures = {pool.submit(_fetch, it["src"]): (i, it) for i, it in enumerate(window)}
    deadline = time.time() + 10
    try:
        for fut in as_completed(futures, timeout=10):
            idx, it = futures[fut]
            u = it["src"]
            try:
                fn, why = fut.result()
            except Exception as exc:  # noqa: BLE001
                print(f"[photos] 下载异常({type(exc).__name__}): {u[:50]}")
                continue
            if not fn:
                print(f"[photos] 下载失败({why}): {u[:60]}")
                continue
            thumb = _make_thumb(fn)
            by_index[idx] = {
                # 稳定 id：同一张源图在任何分页/任何会话里都得到同一个 id
                "id": hashlib.sha1(_norm_url(u).encode()).hexdigest()[:12],
                "url": f"/api/images/{fn}",
                "thumb_url": f"/api/images/{thumb}",
                "source_url": it.get("source_page") or "",
                "credit": it.get("credit") or "",
                "source": "pixabay" if it.get("credit") == "Pixabay" else "tavily",
            }
            if time.time() > deadline:
                break
    except Exception:  # noqa: BLE001  TimeoutError：到点就用已完成的
        print(f"[photos] 到 10s 截止，已拿到 {len(by_index)} 张")
    finally:
        pool.shutdown(wait=False, cancel_futures=True)

    # 按候选池原顺序输出（跳过没下成功的）
    out = [by_index[i] for i in sorted(by_index)]
    return out


def place_photos(name: str, city: str = "", limit: int = 4, offset: int = 0) -> list:
    """兼容入口：只返回图片列表（老调用方继续可用）。

    新代码请用 place_photo_pool()，它能拿到 total/has_more 用于分页。
    """
    return place_photo_pool(name, city, limit=limit, offset=offset)["photos"]
