"""网络搜索层 —— 攻略 / 小红书 内容的情报来源

用途：让用户"搜一个地方 → 看到真实攻略与照片 → 再决定去不去"。

合规说明（重要）：**不抓取小红书**（其 robots.txt 是 Disallow: /）。
这里走的是**正规搜索 API 拿公开结果** —— Tavily 会自然带出小红书、携程、马蜂窝、
去哪儿等公开页面，我们只展示标题、链接与摘要，不绕过任何反爬、不抓评论。

实测（大陆直连）：
  ✅ Tavily  search 2.0s，返回结果 + include_images 给的真实照片地址
  ✅ 普通搜索会自然包含 xiaohongshu.com 等站点的公开页面
  ⚠️ 定向 site:xiaohongshu.com 效果差（小红书本身不被索引），所以不做那种"定向抓取"，
     而是正常搜索后按来源分类展示
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
TAVILY_KEY = os.environ.get("TAVILY_API_KEY", "").strip()

# 来源分类：让前端能把"小红书/携程/马蜂窝"这类内容单独标出来
SOURCE_RULES = [
    ("小红书", ("xiaohongshu.com", "xhslink.com")),
    ("携程", ("ctrip.com", "trip.com")),
    ("马蜂窝", ("mafengwo.cn",)),
    ("去哪儿", ("qunar.com",)),
    ("知乎", ("zhihu.com",)),
    ("B站", ("bilibili.com",)),
    ("抖音", ("douyin.com",)),
    ("穷游", ("qyer.com",)),
]

_CACHE_FILE = os.environ.get(
    "WEBSEARCH_CACHE_FILE",
    os.path.join(os.environ.get("DATA_DIR", "/data"), "websearch_cache.json"),
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
        print(f"[websearch] 载入缓存失败: {exc}")


def _save_cache() -> None:
    try:
        os.makedirs(os.path.dirname(_CACHE_FILE), exist_ok=True)
        with open(_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(dict(list(_cache.items())[-200:]), f, ensure_ascii=False)
    except Exception as exc:  # noqa: BLE001
        print(f"[websearch] 保存缓存失败: {exc}")


def classify(url: str) -> str:
    host = (urllib.parse.urlparse(url).hostname or "").lower()
    for label, keys in SOURCE_RULES:
        if any(k in host for k in keys):
            return label
    return "其他"


def web_search(query: str, limit: int = 8) -> dict:
    """搜公开攻略内容。返回 {"results": [...], "images": [...]}。

    结果只含标题/链接/摘要/来源分类 —— 不搬运正文，用户点链接去原站看。
    """
    query = re.sub(r"\s+", " ", str(query or "")).strip()
    if not query:
        return {"results": [], "images": []}
    limit = max(1, min(int(limit or 8), 16))
    ck = f"{query}|{limit}"
    _load_cache()
    if ck in _cache:
        return _cache[ck]

    if not TAVILY_KEY:
        return {"results": [], "images": [], "error": "未配置 TAVILY_API_KEY"}

    payload = {"query": query, "max_results": limit, "include_images": True,
               "include_image_descriptions": True, "search_depth": "basic"}
    data = None
    for attempt in (1, 2):
        try:
            req = urllib.request.Request(
                "https://api.tavily.com/search",
                data=json.dumps(payload).encode(), method="POST",
                headers={"Content-Type": "application/json",
                         "Authorization": f"Bearer {TAVILY_KEY}"},
            )
            data = json.loads(urllib.request.urlopen(req, timeout=40)
                              .read().decode("utf-8", "replace"))
            break
        except Exception as exc:  # noqa: BLE001
            print(f"[websearch] 第{attempt}次失败: {type(exc).__name__}")
            if attempt == 1:
                time.sleep(1.5)

    if not data:
        return {"results": [], "images": []}

    results = []
    for r in (data.get("results") or []):
        url = str(r.get("url") or "")
        if not url:
            continue
        results.append({
            "title": re.sub(r"\s+", " ", str(r.get("title") or ""))[:120],
            "url": url,
            "snippet": re.sub(r"\s+", " ", str(r.get("content") or ""))[:280],
            "source": classify(url),
        })

    images = []
    for im in (data.get("images") or [])[:8]:
        if isinstance(im, dict) and im.get("url"):
            images.append({"url": str(im["url"]),
                           "description": str(im.get("description") or "")[:80]})

    out = {"results": results, "images": images}
    _cache[ck] = out
    _save_cache()
    return out