"""真实地点（POI）层 —— 全部免费、无需任何 API key

为什么要这一层：现在项目里的景点是**模型编的**（名字、门票、时长、描述全靠生成），
所以会出现"编出个不存在的地方""配不到图""路线不合理"。成熟项目（TREK / 浮光 / 见好）
共同做法是：**真实数据提供事实，模型只负责组织与建议**。

数据源与实测结论（注意「从哪台机器」这个前提，同一服务换个出口结论会反）：

  ✅ Photon (komoot)      地点搜索 / 地理编码    大陆直连 3.2s 通
  ✅ OpenFreeMap          矢量地图瓦片（前端用）  大陆直连 0.9s 通
  ✅ OSRM                 路线规划               大陆直连 1.0s 通
  ✅ Overpass             按范围查 POI           大陆能连，偶发 504 → 做重试 + 换镜像
  ❌ Nominatim            地理编码               大陆直连超时；经代理也不通
  ❌ OpenStreetMap 官方瓦片                       大陆直连超时
  ⚠️ 高德                 瓦片 + 地理编码        都需 key；现有 key 已失效（USER_KEY_RECYCLED）

对外只返回**规整后的字典列表**，绝不抛异常 —— 上层接口和 Agent 都按"有结果/没结果"处理。
"""
from __future__ import annotations

import json
import math
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

os.environ.setdefault("NO_PROXY", "*")
os.environ.setdefault("no_proxy", "*")

# Photon 要求可识别的 UA；带上项目标识是使用礼仪
UA = "yedu-xunzong/0.1 (personal travel planner)"

PHOTON = "https://photon.komoot.io/api/"
# Overpass 有多个镜像。注意：不同镜像的**数据覆盖不一致**（实测主站给出 8 个 POI 时
# overpass.osm.ch 返回 0 个），所以遇到"连上了但为空"不能立刻放弃，要把镜像都试完。
OVERPASS_MIRRORS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.osm.ch/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]

_CACHE_FILE = os.environ.get(
    "POI_CACHE_FILE",
    os.path.join(os.environ.get("DATA_DIR", "/data"), "poi_cache.json"),
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
        print(f"[poi] 载入缓存失败: {exc}")


def _save_cache() -> None:
    try:
        os.makedirs(os.path.dirname(_CACHE_FILE), exist_ok=True)
        with open(_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(dict(list(_cache.items())[-300:]), f, ensure_ascii=False)
    except Exception as exc:  # noqa: BLE001
        print(f"[poi] 保存缓存失败: {exc}")


def _get_json(url: str, params: dict | None = None, timeout: int = 25):
    """GET 一个 JSON。失败抛异常，由调用侧决定重试与兜底。"""
    if params:
        url = url + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    raw = urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8", "replace")
    return json.loads(raw)


def _post_json(url: str, data: dict, timeout: int = 30):
    """POST 表单并解析 JSON。

    Overpass 把查询塞在 GET 的 data= 参数里容易被拒（实测 406 / 504），
    改用 POST 表单才是官方推荐姿势。
    """
    req = urllib.request.Request(
        url, data=urllib.parse.urlencode(data).encode(), method="POST",
        headers={"User-Agent": UA, "Content-Type": "application/x-www-form-urlencoded"},
    )
    raw = urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8", "replace")
    return json.loads(raw)


def _clean(s) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip()


def is_valid_latlon(lat, lon) -> bool:
    """经纬度合理性校验（T1-E1）。

    为什么必须校验：地图上任何"看起来正常"的点都可能来自错配的数据。
    实测真实库里就存在一条：拉萨行程里的「大昭寺」坐标为 (43.998, 143.749)，
    实际落在日本北海道 —— 数据源本身会给出这种跨城结果。
    超范围的值（如 lat=999）会让 Leaflet 直接抛错或把视野拉爆，必须先挡掉。
    """
    try:
        if lat is None or lon is None:
            return False
        lat_f, lon_f = float(lat), float(lon)
    except (TypeError, ValueError):
        return False
    if math.isnan(lat_f) or math.isnan(lon_f) or math.isinf(lat_f) or math.isinf(lon_f):
        return False
    return -90.0 <= lat_f <= 90.0 and -180.0 <= lon_f <= 180.0


def sanitize_coords(lat, lon) -> tuple[float | None, float | None]:
    """返回可安全落库的坐标：非法一律降级为 (None, None)，绝不伪造。"""
    if not is_valid_latlon(lat, lon):
        return None, None
    return round(float(lat), 6), round(float(lon), 6)


def _photon_to_place(feat: dict) -> dict | None:
    """把 Photon 的一条 GeoJSON feature 规整成统一的地点结构。"""
    props = feat.get("properties") or {}
    geom = feat.get("geometry") or {}
    coords = geom.get("coordinates") or []
    if len(coords) < 2:
        return None
    lon, lat = float(coords[0]), float(coords[1])
    name = _clean(props.get("name")) or _clean(props.get("street"))
    if not name:
        return None
    # 坐标合理性校验：Photon/Overpass 偶尔会给出越界值，宁可不返回也不能传出脏坐标
    if not is_valid_latlon(lat, lon):
        return None
    # 地址拼装：城市/州/国家，去掉与名称重复的部分
    parts = [_clean(props.get(k)) for k in ("city", "district", "state", "country")]
    address = " · ".join(dict.fromkeys(p for p in parts if p and p != name))
    return {
        "name": name,
        "lat": round(lat, 6),
        "lon": round(lon, 6),
        "address": address,
        "kind": _clean(props.get("osm_value")) or _clean(props.get("type")),
        "source": "openstreetmap",
        "source_url": (f"https://www.openstreetmap.org/{props.get('osm_type')}/{props.get('osm_id')}"
                       if props.get("osm_type") and props.get("osm_id") else ""),
    }


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """两点球面距离（公里）。"""
    import math
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def search_places(query: str, limit: int = 8, near: tuple | None = None,
                  max_km: float = 0) -> list:
    """按名字搜真实地点（Photon）。

    Args:
        query: 地点名，中文可直接用（如「布达拉宫」）
        limit: 最多返回几条
        near: (lat, lon)，给了就按距离优先，用于「XX 附近的 YY」
        max_km: >0 时**丢弃离 near 超过这个距离的结果**。

    ⚠️ `max_km` 为什么必要：实测搜「大昭寺」时，不带任何地理上下文会匹配到
    **日本北海道**的一个同名地点（43.99, 143.74）。一个坐标飞到国外的点，
    会让地图的视野自适应把范围拉到覆盖中日，其余点全挤成一团 ——
    用户看到的就是"只加了一个点"。所以有城市中心时必须做离群过滤。
    """
    query = _clean(query)
    if not query:
        return []
    limit = max(1, min(int(limit or 8), 20))
    ck = f"search:{query}|{limit}|{near}|{max_km}"
    _load_cache()
    if ck in _cache:
        return _cache[ck]

    # ⚠️ 不要传 lang=zh：实测 Photon 只支持 default/de/en/fr，传 zh 直接 HTTP 400，
    # 表现为「搜索返回 0 条」—— 很容易被误判成"这个地方不存在"。默认就返回中文名。
    params = {"q": query, "limit": limit}
    if near:
        params["lat"], params["lon"] = near[0], near[1]
    try:
        data = _get_json(PHOTON, params)
    except Exception as exc:  # noqa: BLE001
        print(f"[poi] Photon 搜索失败: {type(exc).__name__}: {exc}")
        return []

    out, seen = [], set()
    dropped = 0
    for feat in (data.get("features") or []):
        p = _photon_to_place(feat)
        if not p:
            continue
        if near and max_km and _haversine_km(near[0], near[1], p["lat"], p["lon"]) > max_km:
            dropped += 1
            continue
        key = (p["name"], p["lat"], p["lon"])
        if key in seen:
            continue
        seen.add(key)
        out.append(p)

    if dropped:
        print(f"[poi] 丢弃 {dropped} 个离群结果（>{max_km}km）：{query}")
    if out:
        _cache[ck] = out
        _save_cache()
    return out


def nearby_places(lat: float, lon: float, radius: int = 3000, limit: int = 20,
                  kinds: str = "attraction|museum|viewpoint|artwork|zoo|theme_park") -> list:
    """查某个坐标附近的景点类 POI（Overpass）。

    Overpass 主站偶发 504，所以逐个镜像重试；全失败就返回空列表（不抛异常）。
    """
    radius = max(100, min(int(radius or 3000), 20000))
    limit = max(1, min(int(limit or 20), 60))
    ck = f"near:{round(lat, 3)},{round(lon, 3)}|{radius}|{limit}"
    _load_cache()
    if ck in _cache:
        return _cache[ck]

    # 以 (lat,lon) 为中心的 bbox：纬度 1 度 ≈ 111km
    d = radius / 111000.0
    bbox = f"{lat - d:.5f},{lon - d:.5f},{lat + d:.5f},{lon + d:.5f}"
    q = (f"[out:json][timeout:25];"
         f'(node[tourism~"{kinds}"]({bbox});way[tourism~"{kinds}"]({bbox}););'
         f"out center {limit};")

    for url in OVERPASS_MIRRORS:
        try:
            data = _post_json(url, {"data": q}, timeout=30)
        except Exception as exc:  # noqa: BLE001
            print(f"[poi] Overpass {url.split('/')[2]} 失败: {type(exc).__name__}")
            continue

        found = []
        for el in (data.get("elements") or []):
            tags = el.get("tags") or {}
            name = _clean(tags.get("name:zh")) or _clean(tags.get("name"))
            if not name:
                continue
            elat = el.get("lat") or (el.get("center") or {}).get("lat")
            elon = el.get("lon") or (el.get("center") or {}).get("lon")
            if elat is None or elon is None:
                continue
            # 同 _photon_to_place：越界坐标宁可丢弃，也不让脏数据进入地图链路
            alat, alon = sanitize_coords(elat, elon)
            if alat is None or alon is None:
                continue
            found.append({
                "name": name,
                "lat": alat,
                "lon": alon,
                "address": _clean(tags.get("addr:city")) or _clean(tags.get("addr:street")),
                "kind": _clean(tags.get("tourism")),
                "source": "openstreetmap",
                "source_url": f"https://www.openstreetmap.org/{el.get('type')}/{el.get('id')}",
            })
        if found:
            _cache[ck] = found
            _save_cache()
            return found
        # 连上了但为空 → 继续试下一个镜像（不同镜像数据覆盖不同），全都为空才返回空
    return []


# ---------------------------------------------------------------- 行程自检
def looks_like_real_place(name: str, city: str = "") -> dict:
    """判断一个「景点名」在真实数据里存不存在。

    用途：拿来做**机械校验** —— 模型给出的景点如果查不到，就该标出来而不是直接展示。
    这是"联网实查"思路的最小实现（见好 / Migo 都强调了这一步）。
    """
    hits = search_places(f"{name} {city}".strip(), limit=3)
    if hits:
        return {"exists": True, "matched": hits[0]}
    hits = search_places(name, limit=3)
    if hits:
        return {"exists": True, "matched": hits[0]}
    return {"exists": False, "matched": None}