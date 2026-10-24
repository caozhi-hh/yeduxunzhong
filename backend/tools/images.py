# tools/images.py - 景点真实照片搜索（Pixabay 优先 / Unsplash 回退）
import hashlib
import json
import re
import threading
import requests
import base64
import os
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

# 绕过环境里的代理变量（与 xiaozhiAI 的 core/llm.py 同一套做法）。
# 本机实测：Clash 退出后环境里仍残留 HTTPS_PROXY=127.0.0.1:7897，
# requests 会直接 ProxyError —— 与代码无关，但不处理就会表现为"图抓不到"。
# 本项目的部署目标（HF Spaces）与智谱/Unsplash 直连都不需要代理。
os.environ["NO_PROXY"] = "*"
os.environ["no_proxy"] = "*"

from config import UNSPLASH_ACCESS_KEY, PIXABAY_API_KEY

_image_cache = {}


def generate_spot_image(spot_name: str, city: str = "") -> dict:
    """从 Unsplash 搜索景点真实照片，返回 base64 图片。"""
    cache_key = f"{spot_name}_{city}"
    if cache_key in _image_cache:
        return _image_cache[cache_key]

    if not UNSPLASH_ACCESS_KEY:
        print("[images] 未配置 UNSPLASH_ACCESS_KEY")
        return _error_result(cache_key)

    # 搜索关键词：去掉 "travel landmark" 噪声词，提高中文景点匹配率
    query = f"{spot_name} {city}" if city else spot_name

    try:
        resp = requests.get(
            "https://api.unsplash.com/search/photos",
            params={"query": query, "per_page": 3, "orientation": "landscape"},
            headers={"Authorization": f"Client-ID {UNSPLASH_ACCESS_KEY}"},
            timeout=15,
        )
        resp.raise_for_status()
        results = resp.json().get("results", [])

        if not results:
            # 中文搜不到，用英文关键词兜底
            query2 = f"{spot_name} China"
            resp2 = requests.get(
                "https://api.unsplash.com/search/photos",
                params={"query": query2, "per_page": 3, "orientation": "landscape"},
                headers={"Authorization": f"Client-ID {UNSPLASH_ACCESS_KEY}"},
                timeout=15,
            )
            results = resp2.json().get("results", [])

        if results:
            img_url = results[0]["urls"]["regular"]
            result = {"status": "ok", "url": img_url, "base64": ""}
            _image_cache[cache_key] = result
            return result

        print(f"[images] Unsplash 无搜索结果: {query}")
        return _error_result(cache_key)

    except Exception as e:
        print(f"[images] 搜索 {spot_name} 照片失败: {e}")
        return _error_result(cache_key)


def _error_result(cache_key: str) -> dict:
    _image_cache[cache_key] = {"status": "error", "url": "", "base64": ""}
    return {"status": "error", "url": "", "base64": ""}


# ==================== 景点图片（按图源分策略） ====================
# 合规约束（2026-10-11 调研查到的原文级依据）：
#   Unsplash API Guidelines 强制三件事 —— ① hotlink（前端直连其 CDN，
#   **不得**下载到服务器再展示）② 署名摄影师并回链其主页 ③ 保留 urls 里的 ixid 参数。
# 所以 Unsplash 走 policy="hotlink"：后端只做"搜索"（key 留在服务端），
# 把 CDN URL 原样返回，由浏览器去加载。
# 等接入 Pixabay / 高德 POI 照片（条款相反：要求先下载到服务器）时，
# 走 policy="self_host" + GET /api/images/{file} 自托管 —— 通道已一并准备好。


def images_dir() -> str:
    """图片缓存目录。IMAGES_DIR 可覆盖（测试用，避免污染项目目录）。"""
    d = os.environ.get("IMAGES_DIR") or os.path.join(
        os.path.dirname(os.path.dirname(__file__)), "data", "images"
    )
    os.makedirs(d, exist_ok=True)
    return d


# 搜索结果的缓存：缓存**「查询 → 结果」**而不是最终记录。
# 这样第二次批量请求零外部调用，而"挑哪一张"的去重逻辑每次照常执行。
# 必须**落盘**：Unsplash 免费（Demo）档实测只有 50 次/小时（响应头 x-ratelimit-limit: 50），
# 进程一重启就丢缓存 = 白白烧掉配额。
_search_cache: dict = {}
_search_lock = threading.Lock()
_cache_loaded = False
# 限流状态：命中后本次进程不再无脑重试（403 Rate Limit Exceeded 时响应体就是这四个字）
_RATE_LIMITED = {"hit": False, "remaining": None}


def _cache_file() -> str:
    return os.path.join(os.path.dirname(images_dir()), "image_search_cache.json")


def _load_cache() -> None:
    global _cache_loaded
    if _cache_loaded:
        return
    _cache_loaded = True
    try:
        with open(_cache_file(), encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            _search_cache.update({k: v for k, v in data.items() if isinstance(v, list)})
        print(f"[images] 已载入搜索缓存 {len(_search_cache)} 条（省配额）")
    except FileNotFoundError:
        pass
    except Exception as e:
        print(f"[images] 载入搜索缓存失败: {e}")


def _save_cache() -> None:
    try:
        path = _cache_file()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(_search_cache, f, ensure_ascii=False)
    except Exception as e:
        print(f"[images] 保存搜索缓存失败: {e}")


def _empty_spot_image(spot_name: str, note: str = "") -> dict:
    """抓不到图时的占位结构。

    image_url 为空 → 前端显示占位，绝不显示破图。
    `note` **必须写清原因**（配额用尽 / 未匹配 / 未配置 key）——
    "静默空白"会让用户和排查者都不知道发生了什么。
    """
    return {
        "name": spot_name, "image_url": "", "thumb_url": "", "large_url": "",
        "source": "", "author": "", "author_url": "", "source_url": "",
        "policy": "hotlink", "license": "", "match": "none", "note": note,
        "width": None, "height": None,
    }


def _search_unsplash(query: str, count: int = 5) -> list:
    """搜一次 Unsplash。命中缓存则**零网络请求**（配额只有 50 次/小时，必须省）。"""
    with _search_lock:
        if query in _search_cache:
            return _search_cache[query]

    try:
        resp = requests.get(
            "https://api.unsplash.com/search/photos",
            params={"query": query, "per_page": count, "orientation": "landscape"},
            headers={"Authorization": f"Client-ID {UNSPLASH_ACCESS_KEY}"},
            timeout=15,
        )
        remaining = resp.headers.get("x-ratelimit-remaining")
        if remaining is not None:
            _RATE_LIMITED["remaining"] = remaining
        resp.raise_for_status()
        results = resp.json().get("results") or []
    except requests.HTTPError as e:
        resp = getattr(e, "response", None)
        status = getattr(resp, "status_code", None)
        body = (getattr(resp, "text", "") or "").strip()
        if status == 403 and "rate limit" in body.lower():
            # 配额用尽：**故意不写缓存** —— 否则这一小时的空结果会被永久记住。
            _RATE_LIMITED["hit"] = True
            print("[images][警告] Unsplash 配额已用尽（403 Rate Limit Exceeded），本轮改用占位并标注原因")
            return []
        print(f"[images] 搜索「{query}」失败: HTTP {status} {body[:80]}")
        return []
    except Exception as e:
        print(f"[images] 搜索「{query}」失败: {e}")
        return []

    with _search_lock:
        _search_cache[query] = results
    return results


# ==================== Pixabay（推荐图源） ====================
# 与 Unsplash 的条款方向**正好相反**：
#   Unsplash → 必须 hotlink（前端直连其 CDN），不得下载到服务器
#   Pixabay  → 禁止永久 hotlink，**要求先把图片下载到服务器**再展示
# 所以 Pixabay 走 policy="self_host"：下载到本机 images_dir()，由 /api/images/{file} 自托管。
# 好处不止合规：图片落在自己服务器上 → 国内加载快、浏览器能正常缓存、不受对方 CDN 波动影响。


def _download_to_cache(url: str, timeout: int = 20) -> tuple:
    """把图片下载到本机缓存目录。返回 (文件名, 失败原因)；成功时原因为空串。

    `timeout` 可调：地点图选的来源是各家旅行博客，在大陆往往很慢（实测有源站要 30s+），
    那种场景要主动放弃慢的那张，别让整批被一张图拖住。

    ⚠️ 429 必须单独识别：Pixabay 返回的图片地址是 `pixabay.com/get/...`，
    **与搜索 API 同主机、共用限额**（实测 100 次/60 秒），所以"服务端下载图片"
    同样会吃配额。限流是**瞬时的**（实测 65 秒后即恢复），因此这里短暂重试一次，
    并把原因如实写出来 —— 不要含糊成"网络失败"，否则排查时完全看不出真相。
    """
    if not url:
        return "", "图片地址为空"

    name = hashlib.sha1(url.encode()).hexdigest()[:20] + ".jpg"
    path = os.path.join(images_dir(), name)
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return name, ""  # 已缓存，零网络（这也是省配额的关键：每张图一辈子只下一次）

    for attempt in (1, 2):
        try:
            r = requests.get(url, timeout=timeout, headers={"User-Agent": "Mozilla/5.0"})
            if r.status_code == 429:
                if attempt == 1:
                    time.sleep(1.5)  # 限额窗口可能刚好滚动，短暂重试一次
                    continue
                return "", "图源限流中（HTTP 429），约 1 分钟后自动恢复"
            r.raise_for_status()
            blob = r.content
            if not blob:
                return "", "图源返回空内容"
            if len(blob) > 3 * 1024 * 1024:
                return "", f"图片超过 3MB（{len(blob) // 1024}KB），已跳过缓存"
            with open(path, "wb") as f:
                f.write(blob)
            return name, ""
        except requests.HTTPError as e:
            status = getattr(getattr(e, "response", None), "status_code", None)
            if status == 429 and attempt == 1:
                time.sleep(1.5)
                continue
            if status == 429:
                return "", "图源限流中（HTTP 429），约 1 分钟后自动恢复"
            return "", f"图源返回 HTTP {status}"
        except Exception as e:
            return "", f"下载失败：{type(e).__name__}"
    return "", "下载失败（未知原因）"


def _search_pixabay(query: str, count: int = 5) -> list:
    ck = "pixabay:" + query
    with _search_lock:
        if ck in _search_cache:
            return _search_cache[ck]
    try:
        resp = requests.get(
            "https://pixabay.com/api/",
            params={"key": PIXABAY_API_KEY, "q": query, "image_type": "photo",
                    "orientation": "horizontal", "per_page": count, "safesearch": "true"},
            timeout=15,
        )
        resp.raise_for_status()
        hits = resp.json().get("hits") or []
    except requests.HTTPError as e:
        resp = getattr(e, "response", None)
        status = getattr(resp, "status_code", None)
        body = (getattr(resp, "text", "") or "")[:100]
        if status == 429:
            _RATE_LIMITED["hit"] = True
            print("[images][警告] Pixabay 触发限流（429），本轮改用占位并标注原因")
        else:
            print(f"[images] Pixabay 搜索「{query}」失败: HTTP {status} {body}")
        return []
    except Exception as e:
        print(f"[images] Pixabay 搜索「{query}」失败: {e}")
        return []
    with _search_lock:
        _search_cache[ck] = hits
    return hits


def _pixabay_record(spot_name: str, hit: dict, match: str) -> dict:
    """把一条 Pixabay 命中转成记录：**先下载到本机再自托管**。

    卡片图**立即下载**（列表要马上显示，且下载后本地即秒开）；
    放大图**不预下载** —— 返回本站 /api/image-proxy 的地址，用户真正点开时才由
    服务端去取并缓存。理由：实测 8 张放大图共约 3MB，预下载会白白拖慢首屏，
    而实际上没人会把 8 个景点全点开一遍。
    """
    src = hit.get("webformatURL", "")
    card, why = _download_to_cache(src)
    if not card:
        return _empty_spot_image(spot_name, why or "图片下载失败")
    user = hit.get("user", "")
    uid = hit.get("user_id", "")
    large_src = hit.get("largeImageURL", "")
    if large_src:
        # 懒加载：真正的下载发生在 /api/image-proxy 被请求时（服务端下载，符合 Pixabay 条款）
        large_url = "/api/image-proxy?src=" + urllib.parse.quote(large_src, safe="")
    else:
        large_url = f"/api/images/{card}"
    rec = {
        "name": spot_name,
        "image_url": f"/api/images/{card}",
        "thumb_url": f"/api/images/{card}",
        "large_url": large_url,
        "source": "pixabay",
        "author": user,
        "author_url": f"https://pixabay.com/users/{user}-{uid}/" if user else "",
        "source_url": hit.get("pageURL", ""),
        "policy": "self_host",
        "license": "Pixabay Content License",
        "match": match,
        "note": "",
        "width": hit.get("webformatWidth"),
        "height": hit.get("webformatHeight"),
    }
    rec["_src"] = src  # 去重用的"源图"标识（本地路径不能当去重键）
    return rec


def _queries_for(spot_name: str, city: str) -> list:
    """降级链：`景点 城市`(exact) → `景点 China`(approx) → `景点`(approx)。

    ⚠️ **故意不降级到裸城市名**：那会让所有"专名搜不到"的景点都拿到同一张城市风景照
    —— 多个景点显示同一张图（串图），用户一眼能看出是错的。
    按调研的最佳实践「宁可无图不可错图」，搜不到就返回空 image_url，由前端显示占位。
    """
    pairs = [
        (f"{spot_name} {city}".strip(), "exact"),
        (f"{spot_name} China", "approx"),
        (spot_name, "approx"),
    ]
    return [(q, m) for q, m in pairs if q]


def _to_record(spot_name: str, photo: dict, match: str) -> dict:
    """把 Unsplash 的一张照片转成记录。

    三个尺寸各司其职（实测字节数：thumb 6.6KB / small 20.3KB / regular 112.8KB）：
      - image_url  卡片用     → small(400w)，比 regular 小 5.6 倍，112px 缩略图足够清晰
      - thumb_url  低带宽备用 → thumb(200w)
      - large_url  点击放大用 → regular(1080w)，**只在用户点开时才下载**
    原样透传（含 ixid），不改写 URL —— Unsplash 条款要求，也因为它带签名，
    手工加 &w= 参数实测会 HTTPError。
    """
    user = photo.get("user") or {}
    urls = photo.get("urls") or {}
    return {
        "name": spot_name,
        "image_url": urls.get("small", ""),
        "thumb_url": urls.get("thumb", ""),
        "large_url": urls.get("regular", ""),
        "source": "unsplash",
        "author": user.get("name", ""),
        "author_url": (user.get("links") or {}).get("html", ""),
        "source_url": (photo.get("links") or {}).get("html", ""),
        "policy": "hotlink",
        "license": "Unsplash License",
        "match": match,
        "width": photo.get("width"),
        "height": photo.get("height"),
    }


_PHOTO_ID_RE = re.compile(r"photo-([0-9a-zA-Z\-]+)")


def _photo_key(url: str) -> str:
    """去重键用**照片 ID**，而不是整条 URL。

    ⚠️ 这是实测踩出来的：Unsplash 对**同一张照片**在不同响应里返回的查询参数可能不同
    （URL 字符串不同、`photo-<id>` 部分恒定）。只比整条 URL 会漏掉"同一张图被多个景点复用"
    —— 实测漏掉过 3 处（布达拉宫 / 扎什伦布寺 / 羊卓雍错 共用同一张，
    罗布林卡 / 八廓街 共用另一张），而按 URL 判定时显示"重复 0"，把断言骗过去了。
    """
    m = _PHOTO_ID_RE.search(url or "")
    return m.group(1) if m else (url or "")


def _active_provider() -> str:
    """当前生效的图源：填了 Pixabay key 就用它，否则回退 Unsplash。"""
    return "pixabay" if PIXABAY_API_KEY else "unsplash"


def _pick_photo(spot_name: str, city: str, taken: set, provider: str):
    """**只挑选、不下载**。返回 (命中对象, match, 源图标识)。

    挑选必须串行（依赖"前面已经选了哪些"以保证同批不重复）；
    耗时的下载放到调用侧并发做 —— 这是"下载串行导致 32 秒"的修法。
    """
    for query, match in _queries_for(spot_name, city):
        if provider == "pixabay":
            for hit in _search_pixabay(query):
                src = hit.get("webformatURL", "")
                if src and src not in taken:
                    return hit, match, src
        else:
            for photo in _search_unsplash(query):
                url = (photo.get("urls") or {}).get("small", "")
                if url and _photo_key(url) not in taken:
                    return photo, match, _photo_key(url)
    return None, "none", ""


def _build_record(pick, provider: str) -> dict:
    spot_name, hit, match = pick
    if hit is None:
        if _RATE_LIMITED["hit"]:
            return _empty_spot_image(spot_name, "图源配额已用尽，约 1 小时后自动恢复")
        return _empty_spot_image(spot_name, "图源中没有匹配这个景点的照片")
    if provider == "pixabay":
        return _pixabay_record(spot_name, hit, match)
    rec = _to_record(spot_name, hit, match)
    rec["_src"] = _photo_key((hit.get("urls") or {}).get("small", ""))
    return rec


def fetch_spot_image(spot_name: str, city: str = "", used: set | None = None) -> dict:
    """单个景点（不并发）：挑选 + 立刻下载。批量请用 fetch_spot_images。"""
    provider = _active_provider()
    if provider == "unsplash" and not UNSPLASH_ACCESS_KEY:
        return _empty_spot_image(spot_name, "后端未配置任何图源 key（PIXABAY_API_KEY / UNSPLASH_ACCESS_KEY）")
    if _RATE_LIMITED["hit"]:
        return _empty_spot_image(spot_name, "图源配额已用尽，约 1 小时后自动恢复")
    hit, match, src = _pick_photo(spot_name, city, used or set(), provider)
    return _build_record((spot_name, hit, match), provider)


def fetch_spot_images(city: str, spots: list, workers: int = 8) -> list:
    """批量抓图，并保证**同一批景点不复用同一张照片**。

    两段式（依据是实测，不是猜）：瓶颈在**搜索 API** 而不在图片下载 ——
    实测串行 8 个景点要 **29.8 秒**（每次搜索 ~4.3 秒），而一张 6.6KB 的图只要 0.16 秒。

      ① **并发只预取每个景点的第一级查询**（`景点 城市`）
      ② **串行**挑选并去重；只有第一级没命中时才**按需**降级查第二/三级

    ⚠️ ① 为什么只预取第一级：一次事故换来的教训 ——
    原先预取整条降级链（8 景点 × 3 级 = **24 次请求**），而 Unsplash 免费档
    实测只有 **50 次/小时**（响应头 x-ratelimit-limit: 50），两批就把配额烧光，
    之后全部 403。省配额比多省几秒更重要。

    ⚠️ ② 调用侧仍必须放进线程里跑（`anyio.to_thread.run_sync`）——
    HF 免费档只有 1 个 worker，同步 requests 写在 async 路由里会把事件循环堵死。
    """
    names = [str(s) for s in (spots or [])[:12]]
    if not names:
        return []

    _load_cache()  # 落盘缓存：重启不丢，直接省下配额
    provider = _active_provider()
    if provider == "unsplash" and not UNSPLASH_ACCESS_KEY:
        return [_empty_spot_image(n, "后端未配置任何图源 key") for n in names]

    search = _search_pixabay if provider == "pixabay" else _search_unsplash

    # ① 并发预取**第一级查询**（同一 query 只搜一次）
    if not _RATE_LIMITED["hit"]:
        firsts: list = []
        for n in names:
            chain = _queries_for(n, city)
            if chain and chain[0][0] not in firsts:
                firsts.append(chain[0][0])
        if firsts:
            with ThreadPoolExecutor(max_workers=max(1, min(workers, len(firsts)))) as pool:
                list(pool.map(search, firsts))

    # ② 串行挑选（**只挑不下载**；选择顺序决定去重结果，必须串行）
    taken: set = set()
    picks: list = []
    for n in names:
        hit, match, src = _pick_photo(n, city, taken, provider)
        if hit is not None:
            taken.add(src)
        picks.append((n, hit, match))

    # ③ **并发组装 + 下载**：Pixabay 需要下载卡片图（串行做的话 8 张就要 30 秒，实测踩过），
    #    Unsplash 只是拼 URL。这一步并发后，总耗时 ≈ 一次搜索 + 一次下载。
    max_w = max(1, min(workers, len(picks)))
    if provider == "pixabay":
        with ThreadPoolExecutor(max_workers=max_w) as pool:
            records = list(pool.map(lambda p: _build_record(p, provider), picks))
    else:
        records = [_build_record(p, provider) for p in picks]

    out = []
    for rec in records:
        rec.pop("_src", None)
        out.append(rec)

    _save_cache()
    return out


def extract_spots_from_text(text: str) -> list:
    """从 AI 推荐文本中提取景点名称。"""
    spots = []
    seen = set()

    bold_pattern = r'\*\*([^*]{2,20})\*\*'
    skip_words = [
        "门票", "时长", "推荐", "价格", "费用", "交通", "住宿", "餐饮",
        "预算", "行程", "描述", "备注", "总计", "合计", "Day", "天", "第",
        "小时", "元", "攻略", "参考", "其他", "注意", "提示", "建议",
        "到达", "离开", "早", "中", "晚", "餐", "住宿建议", "费用明细",
        "实用贴士", "详细攻略", "大景点", "推荐景点", "顺路", "位置",
        "美食", "特产", "小吃", "景点推荐", "安排", "路线",
        "全天", "半天", "上午", "下午", "傍晚", "晚上", "夜景",
        "早上", "出发", "回程", "自由", "休息", "返程",
        "预约", "放票", "抢票", "旅行", "类型", "出行",
    ]
    for match in re.finditer(bold_pattern, text):
        name = match.group(1).strip()
        if name not in seen and len(name) >= 2 and not any(w in name for w in skip_words):
            spots.append(name)
            seen.add(name)

    if not spots:
        emoji_pattern = r'[🏞️🏯🏔️🛕🏛️🕌🏰⛩️⛪🌉🌃🏖️🌋🏕️]\s*(.+?)(?:\n|$)'
        for match in re.finditer(emoji_pattern, text):
            name = match.group(1).strip()
            if name not in seen and len(name) >= 2:
                spots.append(name)
                seen.add(name)

    # 兜底：按 --- 或 \n\n 分段，找含 emoji 的行
    if len(spots) < 3:
        segments = re.split(r'(?:---|\n{2,})', text)
        for seg in segments:
            lines = seg.strip().split('\n')
            if not lines:
                continue
            first = lines[0].strip()
            # 从第一行提取名字（去掉 emoji 和 markdown 符号）
            clean = re.sub(r'[🏞️🏯🏔️🛕🏛️🕌🏰⛩️⛪🌉🌃🏖️🌋🏕️📄🎫⏰📍📝🔀💡⭐*\s]', '', first).strip()
            if clean and clean not in seen and len(clean) >= 2 and not any(w in clean for w in skip_words):
                spots.append(clean)
                seen.add(clean)

    return spots[:12]


def extract_spot_details(text: str) -> list:
    """从 AI 推荐文本中提取景点详细信息（名称、评分、时长、描述）。"""
    spots = []
    seen = set()

    skip_words = [
        "门票", "时长", "推荐", "价格", "费用", "交通", "住宿", "餐饮",
        "预算", "行程", "描述", "备注", "总计", "合计", "Day", "天", "第",
        "小时", "元", "攻略", "参考", "其他", "注意", "提示", "建议",
        "到达", "离开", "早", "中", "晚", "餐", "住宿建议", "费用明细",
        "实用贴士", "详细攻略", "大景点", "推荐景点", "顺路", "位置",
        "美食", "特产", "小吃", "景点推荐", "安排", "路线",
        "全天", "半天", "上午", "下午", "傍晚", "晚上", "夜景",
        "早上", "出发", "回程", "自由", "休息", "返程",
        "预约", "放票", "抢票", "旅行", "类型", "出行",
    ]

    # 按 --- 分段，每段是一个景点
    segments = re.split(r'---+', text)

    for seg in segments:
        seg = seg.strip()
        if not seg:
            continue

        lines = seg.split('\n')
        name = ""
        rating = ""
        duration = ""
        desc = ""
        ticket = ""

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # 提取名字：从 bold 标记或第一行含 emoji 的行
            bold_match = re.search(r'\*\*([^*]{2,20})\*\*', line)
            if bold_match:
                candidate = bold_match.group(1).strip()
                if not name and not any(w in candidate for w in skip_words):
                    name = candidate

            # 提取评分
            rating_match = re.search(r'⭐\s*推荐指数[：:]\s*(\S+)', line)
            if rating_match:
                rating = rating_match.group(1).strip()
            else:
                rating_match = re.search(r'⭐\s*(\d\.?\d*\s*[/／]\s*\d)', line)
                if rating_match:
                    rating = rating_match.group(1).strip()

            # 提取时长
            duration_match = re.search(r'游玩时长[：:]\s*(\S+)', line)
            if duration_match:
                duration = duration_match.group(1).strip()
            else:
                duration_match = re.search(r'⏰\s*(\d+[~\-到]\d*\s*小时)', line)
                if duration_match:
                    duration = duration_match.group(1).strip()

            # 提取门票
            ticket_match = re.search(r'门票[：:]\s*(.+?)(?:\||\n|$)', line)
            if ticket_match:
                ticket = ticket_match.group(1).strip()

            # 提取描述（📝 开头或一句话描述）
            if '📝' in line or '一句话描述' in line:
                desc_clean = re.sub(r'[📝\s]', ' ', line).strip()
                desc = re.sub(r'一句话描述[：:]?\s*', '', desc_clean).strip()

        # 如果没有通过 bold 提取到名字，尝试从第一行提取
        if not name and lines:
            first = lines[0].strip()
            clean = re.sub(r'[🏞️🏯🏔️🛕🏛️🕌🏰⛩️⛪🌉🌃🏖️🌋🏕️*\s]', '', first).strip()
            if clean and len(clean) >= 2 and not any(w in clean for w in skip_words):
                name = clean

        if name and name not in seen and len(name) >= 2:
            seen.add(name)
            spots.append({
                "name": name,
                "rating": rating or "",
                "duration": duration or "",
                "ticket": ticket or "",
                "desc": desc or "",
            })

    return spots[:12]


def geocode_spots(spots: list, city: str) -> list:
    """用 LLM 生成景点的大致经纬度坐标。"""
    if not spots:
        return []

    try:
        from config import ZHIPU_API_KEY, ZHIPU_BASE_URL, CHAT_MODEL
        from langchain_anthropic import ChatAnthropic
        import json

        geo_llm = ChatAnthropic(
            model=CHAT_MODEL, api_key=ZHIPU_API_KEY, base_url=ZHIPU_BASE_URL,
        )

        spot_list = "、".join(spots)
        prompt = f"""请给出{city}以下景点的大致经纬度坐标（GCJ-02坐标系，用于高德地图）。
只返回JSON数组，不要其他内容。格式：
[{{"name":"景点名","lng":120.xxx,"lat":30.xxx}}]

景点：{spot_list}"""

        resp = geo_llm.invoke(prompt)
        text = resp.content.strip()
        # 提取 JSON 部分
        if "```" in text:
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        start = text.find("[")
        end = text.rfind("]") + 1
        if start >= 0 and end > start:
            result = json.loads(text[start:end])
            return [{"name": r["name"], "lng": float(r["lng"]), "lat": float(r["lat"])} for r in result if "lng" in r and "lat" in r]
    except Exception as e:
        print(f"[geocode_spots] LLM 地理编码失败: {e}")

    return []
