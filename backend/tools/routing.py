"""真实道路路线适配层（T1-F1）—— 供应商逻辑集中在这里，不写进地图组件。

为什么要独立一层
----------------
地图组件只该负责"把几何画出来"。路线怎么取、用哪家服务、坐标系怎么换算，
全部收在这个模块里 —— 这样换成微信小程序时可以直接复用（小程序没有 Leaflet，
但一样能调同一批后端接口）。

目前支持的供应商
----------------
1) **OSRM**（默认，无需密钥）
   `poi.py` 顶部备注过它在大陆直连可用；本轮**实测确认**（拉萨 布达拉宫→大昭寺）：
   直连 1.51s / 1479m / 125.1s / 19 个几何点，返回的是真实 OSM 道路几何。
   坐标系与项目一致：**WGS-84**（无需换算）。

   ⚠️ 公共演示服务的一个坑（本轮实测发现，必须记住）：
   它对 `driving / foot / walking / bike / cycling` **返回完全相同的结果**
   （同一次请求五种 profile 都是 1479m / 125.1s）—— 说明它只加载了驾车 profile，
   却对任何 profile 名都照常返回驾车数据。
   所以默认 `OSRM_MODES=driving`：其它模式一律返回 `mode_unsupported`，
   **绝不把驾车数据当成步行/骑行数据展示**。自建 OSRM 可以加载 foot/bike profile，
   那时用环境变量把支持的模型列出来即可。

2) **高德 AMAP**（可选，需服务端密钥）
   国内道路数据与限行信息更贴合中国境内出行。要求服务端环境变量
   `AMAP_ROUTE_KEY`（**不读前端 NEXT_PUBLIC_* 的 key**，避免复用一个已经暴露的密钥）。
   高德使用 **GCJ-02**，因此：入参 WGS-84→GCJ-02，出参 GCJ-02→WGS-84，
   保证存库/返回的几何仍是项目统一的 WGS-84（否则在 Carto 底图上会整体偏移几百米）。

状态语义（前端据此区分"没路线"和"服务坏了"）
---------------------------------------------
OK / NOT_CONFIGURED / UNAVAILABLE / NO_ROUTE / MODE_UNSUPPORTED / INCOMPLETE
"""
from __future__ import annotations

import json
import math
import os
import time
import urllib.error
import urllib.parse
import urllib.request

# ---------------------------------------------------------------- 状态常量
STATUS_OK = "ok"
STATUS_NOT_CONFIGURED = "not_configured"
STATUS_UNAVAILABLE = "unavailable"
STATUS_NO_ROUTE = "no_route"
STATUS_MODE_UNSUPPORTED = "mode_unsupported"
STATUS_INCOMPLETE = "incomplete"
STATUS_INVALID_COORDS = "invalid_coords"

# ---------------------------------------------------------------- 配置（调用时读环境变量）
# 为什么**不在 import 时快照**：快照会让运行时改环境变量失效，
# 也让"未配置路线服务"这一状态没法在测试里可靠构造（import 一次就定死了）。
# 这里统一用函数在调用时读取，测试因此可以直接 monkeypatch.setenv。

def osrm_base_url() -> str:
    """OSRM 服务地址。默认公共演示服务；设为空字符串表示"不启用 OSRM"。"""
    return os.environ.get("OSRM_BASE_URL", "https://router.project-osrm.org").rstrip("/")


def osrm_modes() -> set[str]:
    """该 OSRM 服务**实际支持**的出行方式。

    默认只有 driving —— 原因见模块顶部：公共演示服务对任何 profile 名都返回
    驾车结果（实测 driving/foot/walking/bike/cycling 完全同值），
    所以不能凭 profile 名就声称支持步行/骑行。自建服务加载了 foot/bike profile 时，
    用 `OSRM_MODES=driving,walking,cycling` 显式声明。
    """
    return {m.strip() for m in os.environ.get("OSRM_MODES", "driving").split(",") if m.strip()}


def amap_route_key() -> str:
    """高德路线服务密钥：**只读服务端环境变量**，不设默认值、不读前端 NEXT_PUBLIC_*。"""
    return os.environ.get("AMAP_ROUTE_KEY", "").strip()


# 前端/接口可选的出行方式 → 各供应商的原生标识
SUPPORTED_MODES = ("driving", "walking", "cycling")
_OSRM_PROFILE = {"driving": "driving", "walking": "foot", "cycling": "bike"}
_AMAP_PATH = {
    "driving": "https://restapi.amap.com/v3/direction/driving",
    "walking": "https://restapi.amap.com/v3/direction/walking",
    "cycling": "https://restapi.amap.com/v4/direction/bicycling",
}

_UA = "yedu-xunzong/0.1 (personal travel planner)"

# ---------------------------------------------------------------- 小缓存
# 为什么需要：同一段路在一次会话里会被反复请求（切天、切模式、重渲染）。
# 键里带**坐标序列**，所以景点顺序或坐标一变键就变，天然失效 —— 不会返回旧顺序的路线。
_CACHE: dict = {}
_CACHE_MAX = 300


def _cache_get(key):
    hit = _CACHE.get(key)
    if hit is None:
        return None
    return hit


def _cache_put(key, value):
    if len(_CACHE) >= _CACHE_MAX:
        # 简单的先进先出淘汰：路线结果不贵，不需要 LRU 精确性
        for k in list(_CACHE.keys())[: max(1, _CACHE_MAX // 10)]:
            _CACHE.pop(k, None)
    _CACHE[key] = value


def clear_cache() -> None:
    """测试与排障用：清空进程内路线缓存。"""
    _CACHE.clear()


# ---------------------------------------------------------------- 坐标系换算
# 高德用 GCJ-02（对 WGS-84 做非线性偏移）。项目内部统一 WGS-84，
# 因此只在"调高德"这一处做换算，其它地方一律 WGS-84。
_GCJ_A = 6378245.0
_GCJ_EE = 0.00669342162296594323


def _out_of_china(lat: float, lon: float) -> bool:
    return not (0.8293 <= lat <= 55.8271 and 72.004 <= lon <= 137.8347)


def _transform_lat(x: float, y: float) -> float:
    ret = -100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * math.sqrt(abs(x))
    ret += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
    ret += (20.0 * math.sin(y * math.pi) + 40.0 * math.sin(y / 3.0 * math.pi)) * 2.0 / 3.0
    ret += (160.0 * math.sin(y / 12.0 * math.pi) + 320 * math.sin(y * math.pi / 30.0)) * 2.0 / 3.0
    return ret


def _transform_lon(x: float, y: float) -> float:
    ret = 300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * math.sqrt(abs(x))
    ret += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
    ret += (20.0 * math.sin(x * math.pi) + 40.0 * math.sin(x / 3.0 * math.pi)) * 2.0 / 3.0
    ret += (150.0 * math.sin(x / 12.0 * math.pi) + 300.0 * math.sin(x / 30.0 * math.pi)) * 2.0 / 3.0
    return ret


def wgs84_to_gcj02(lat: float, lon: float) -> tuple[float, float]:
    """WGS-84 → GCJ-02（中国境内）。境外不偏移。"""
    if _out_of_china(lat, lon):
        return lat, lon
    d_lat = _transform_lat(lon - 105.0, lat - 35.0)
    d_lon = _transform_lon(lon - 105.0, lat - 35.0)
    rad_lat = lat / 180.0 * math.pi
    magic = math.sin(rad_lat)
    magic = 1 - _GCJ_EE * magic * magic
    sqrt_magic = math.sqrt(magic)
    d_lat = (d_lat * 180.0) / ((_GCJ_A * (1 - _GCJ_EE)) / (magic * sqrt_magic) * math.pi)
    d_lon = (d_lon * 180.0) / (_GCJ_A / sqrt_magic * math.cos(rad_lat) * math.pi)
    return lat + d_lat, lon + d_lon


def gcj02_to_wgs84(lat: float, lon: float) -> tuple[float, float]:
    """GCJ-02 → WGS-84。用迭代逼近（正变换不可解析求逆）。

    为什么必须做：高德返回的几何是 GCJ-02，而项目与 Carto 底图都是 WGS-84。
    直接把 GCJ-02 当 WGS-84 用会让整条路线偏移 100~500 米。
    """
    if _out_of_china(lat, lon):
        return lat, lon
    # 迭代：不断把当前估计正向变换后与目标比较，逐步修正
    w_lat, w_lon = lat, lon
    for _ in range(8):
        g_lat, g_lon = wgs84_to_gcj02(w_lat, w_lon)
        d_lat, d_lon = g_lat - lat, g_lon - lon
        if abs(d_lat) < 1e-9 and abs(d_lon) < 1e-9:
            break
        w_lat -= d_lat
        w_lon -= d_lon
    return w_lat, w_lon


# ---------------------------------------------------------------- 坐标校验（与本项目其它层一致）
def is_valid_latlon(lat, lon) -> bool:
    try:
        if lat is None or lon is None:
            return False
        la, lo = float(lat), float(lon)
    except (TypeError, ValueError):
        return False
    if math.isnan(la) or math.isnan(lo) or math.isinf(la) or math.isinf(lo):
        return False
    return -90.0 <= la <= 90.0 and -180.0 <= lo <= 180.0


# ---------------------------------------------------------------- 供应商状态
def active_provider() -> str | None:
    """当前生效的供应商。高德配了服务端密钥就优先（国内数据更准），否则用 OSRM。"""
    if amap_route_key():
        return "amap"
    if osrm_base_url():
        return "osrm"
    return None


def provider_info() -> dict:
    """给接口/排障用的配置状态 —— 明确告诉调用方"接没接通、还缺什么"。"""
    provider = active_provider()
    return {
        "provider": provider,
        "amap_configured": bool(amap_route_key()),
        "osrm_base_url": osrm_base_url(),
        "osrm_modes": sorted(osrm_modes()),
        "supported_modes": list(SUPPORTED_MODES),
        "requires_env": ([] if provider else ["AMAP_ROUTE_KEY 或 OSRM_BASE_URL"]),
        # 高德未配置时，提醒需要用**服务端**变量而不是前端 NEXT_PUBLIC_*
        "note": (
            "未配置路线服务：请设置服务端环境变量 AMAP_ROUTE_KEY（高德，推荐国内）"
            "或 OSRM_BASE_URL（OSRM）。"
            if provider is None else ""
        ),
    }


def mode_supported(provider: str | None, mode: str) -> bool:
    if provider == "amap":
        return mode in _AMAP_PATH
    if provider == "osrm":
        return mode in osrm_modes()
    return False


# ---------------------------------------------------------------- HTTP
def _get_json(url: str, params: dict, timeout: int = 15):
    full = url + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(full, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def _leg_failed(reason: str, detail: str = "") -> dict:
    return {"status": reason, "detail": detail}


# ---------------------------------------------------------------- OSRM 适配
def _osrm_leg(a: tuple[float, float], b: tuple[float, float], mode: str, timeout: int) -> dict:
    """一段路：a → b（WGS-84 入参，WGS-84 出参）。"""
    profile = _OSRM_PROFILE[mode]
    url = f"{osrm_base_url()}/route/v1/{profile}/{a[1]},{a[0]};{b[1]},{b[0]}"
    data = _get_json(url, {"overview": "full", "geometries": "geojson", "steps": "false"}, timeout)

    if data.get("code") != "Ok":
        return _leg_failed(STATUS_NO_ROUTE, str(data.get("code") or "unknown"))

    routes = data.get("routes") or []
    if not routes:
        return _leg_failed(STATUS_NO_ROUTE, "上游未返回路线")

    route = routes[0]
    coords = (route.get("geometry") or {}).get("coordinates") or []
    distance = route.get("distance")
    duration = route.get("duration")

    # 缺几何或数值就如实报告 incomplete，**不自行补造**
    if not coords or distance is None or duration is None:
        return _leg_failed(
            STATUS_INCOMPLETE,
            "上游未返回完整几何或距离/耗时",
        )

    return {
        "status": STATUS_OK,
        "distance_m": float(distance),
        "duration_s": float(duration),
        # OSRM 给的是 [lon, lat]；统一转成 [lat, lon] 方便前端直接喂给地图
        "geometry": [[float(c[1]), float(c[0])] for c in coords if len(c) >= 2],
        "source": "osrm",
    }


# ---------------------------------------------------------------- 高德适配
def _amap_parse_polyline(polyline: str) -> list[list[float]]:
    """高德 polyline: "lon,lat;lon,lat;..." → [[lat, lon], ...]，并转回 WGS-84。"""
    out: list[list[float]] = []
    for chunk in (polyline or "").split(";"):
        piece = chunk.strip()
        if not piece:
            continue
        parts = piece.split(",")
        if len(parts) < 2:
            continue
        try:
            lon_g, lat_g = float(parts[0]), float(parts[1])
        except ValueError:
            continue
        lat_w, lon_w = gcj02_to_wgs84(lat_g, lon_g)
        out.append([round(lat_w, 6), round(lon_w, 6)])
    return out


def _amap_leg(a: tuple[float, float], b: tuple[float, float], mode: str, timeout: int) -> dict:
    """一段路：a → b（WGS-84 入参）。内部换算 GCJ-02，返回仍是 WGS-84。"""
    a_g = wgs84_to_gcj02(a[0], a[1])
    b_g = wgs84_to_gcj02(b[0], b[1])
    url = _AMAP_PATH[mode]
    params = {
        "origin": f"{a_g[1]:.6f},{a_g[0]:.6f}",
        "destination": f"{b_g[1]:.6f},{b_g[0]:.6f}",
        "key": amap_route_key(),
        "output": "JSON",
    }
    if mode in ("driving", "walking"):
        params["extensions"] = "base"

    data = _get_json(url, params, timeout)

    # 高德 v3 用 status/info（status=="1" 才算成功）；v4 用 errcode/errmsg（0 才算成功）
    if data.get("errcode") is not None:
        if str(data.get("errcode")) not in ("0",):
            return _leg_failed(STATUS_NO_ROUTE, str(data.get("errmsg") or data.get("errcode")))
    elif str(data.get("status")) != "1":
        return _leg_failed(STATUS_NO_ROUTE, str(data.get("info") or "未知"))

    if mode == "cycling":
        paths = ((data.get("data") or {}).get("paths")) or []
    else:
        paths = ((data.get("route") or {}).get("paths")) or []
    if not paths:
        return _leg_failed(STATUS_NO_ROUTE, "上游未返回路线")

    path = paths[0]
    distance = path.get("distance")
    duration = path.get("duration")
    if distance is None or duration is None:
        return _leg_failed(STATUS_INCOMPLETE, "上游未返回距离或耗时")

    # 几何由 steps[].polyline 拼起来（v3/v4 都是这个结构）
    geometry: list[list[float]] = []
    for step in path.get("steps") or []:
        geometry.extend(_amap_parse_polyline(step.get("polyline") or ""))
    if not geometry:
        return _leg_failed(STATUS_INCOMPLETE, "上游未返回可用的路线几何")

    return {
        "status": STATUS_OK,
        "distance_m": float(distance),
        "duration_s": float(duration),
        "geometry": geometry,
        "source": "amap",
    }


# ---------------------------------------------------------------- 对外入口
def route_leg(
    a: tuple[float, float],
    b: tuple[float, float],
    mode: str = "driving",
    timeout: int = 15,
) -> dict:
    """计算两点之间的**一段**真实道路路线。

    返回里一定有 `status`：
      ok / no_route / incomplete / unavailable / not_configured / mode_unsupported / invalid_coords
    调用方据此区分"没路线""服务坏了""没配置"，不要把失败当成成功。
    """
    if not is_valid_latlon(*a) or not is_valid_latlon(*b):
        return _leg_failed(STATUS_INVALID_COORDS, "经纬度缺失或非法")

    provider = active_provider()
    if provider is None:
        return _leg_failed(STATUS_NOT_CONFIGURED, provider_info()["note"])
    if not mode_supported(provider, mode):
        return _leg_failed(
            STATUS_MODE_UNSUPPORTED,
            f"{provider} 未启用 {mode}（可用：{sorted(osrm_modes()) if provider == 'osrm' else sorted(_AMAP_PATH)}）",
        )

    key = (
        provider, mode,
        round(a[0], 6), round(a[1], 6),
        round(b[0], 6), round(b[1], 6),
    )
    cached = _cache_get(key)
    if cached is not None:
        return cached

    impl = _amap_leg if provider == "amap" else _osrm_leg
    started = time.time()
    try:
        result = impl(a, b, mode, timeout)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
        result = _leg_failed(STATUS_UNAVAILABLE, f"{type(exc).__name__}: {exc}")
    except json.JSONDecodeError as exc:
        result = _leg_failed(STATUS_UNAVAILABLE, f"上游返回非 JSON: {exc}")
    except Exception as exc:  # noqa: BLE001  —— 适配层不把异常抛给路由
        result = _leg_failed(STATUS_UNAVAILABLE, f"{type(exc).__name__}: {exc}")

    result["elapsed_ms"] = int((time.time() - started) * 1000)
    result["provider"] = provider
    result["mode"] = mode
    _cache_put(key, result)
    return result


def plan_day(
    stops: list[dict],
    mode: str = "driving",
    timeout: int = 15,
) -> dict:
    """把当日景点串成路线。

    stops 需要按**用户编排顺序**传入，每项形如
    `{"place_id": int, "name": str, "lat": float|None, "lon": float|None}`。

    与"直线连线"的区别必须清楚：只有拿到上游几何的段才会带 geometry；
    没有几何的段 status 不是 ok，前端**不得**用直线顶替。
    """
    info = provider_info()
    usable = [
        s for s in stops
        if is_valid_latlon(s.get("lat"), s.get("lon"))
    ]
    skipped = [
        {
            "place_id": s.get("place_id"),
            "name": s.get("name") or "",
            "reason": STATUS_INVALID_COORDS,
            "detail": "缺少可靠的经纬度，无法参与路线计算",
        }
        for s in stops
        if not is_valid_latlon(s.get("lat"), s.get("lon"))
    ]

    legs: list[dict] = []
    ok_legs: list[dict] = []

    # ── 先判"全局阻塞"：这类失败跟具体哪一段无关，不该逐段产出噪声，
    #    也不该白白去调上游（少 N 次无用请求）。 ──
    if info["provider"] is None:
        return _day_result(
            STATUS_NOT_CONFIGURED, info, mode, usable, skipped, legs, None, None,
            message=info["note"],
        )
    if not mode_supported(info["provider"], mode):
        avail = sorted(osrm_modes()) if info["provider"] == "osrm" else sorted(_AMAP_PATH)
        return _day_result(
            STATUS_MODE_UNSUPPORTED, info, mode, usable, skipped, legs, None, None,
            message=f"当前路线服务（{info['provider']}）不支持 {mode}，可用：{avail}",
        )

    for i in range(len(usable) - 1):
        a, b = usable[i], usable[i + 1]
        leg = route_leg(
            (float(a["lat"]), float(a["lon"])),
            (float(b["lat"]), float(b["lon"])),
            mode, timeout,
        )
        legs.append({
            "from_place_id": a.get("place_id"),
            "from_name": a.get("name") or "",
            "to_place_id": b.get("place_id"),
            "to_name": b.get("name") or "",
            **leg,
        })

    ok_legs = [l for l in legs if l.get("status") == STATUS_OK]
    total_distance = sum(l["distance_m"] for l in ok_legs)
    total_duration = sum(l["duration_s"] for l in ok_legs)

    # ── 整体状态：把"没路线/部分成功/正常"区分开 ──
    if len(usable) < 2:
        # 少于两个可用点：没有"段"可算，这本身不是错误
        status = STATUS_OK
        message = "当天的地点不足两个，没有可计算的路线段"
    elif not legs or len(ok_legs) == len(legs):
        status = STATUS_OK
        message = ""
    elif ok_legs:
        status = "partial"
        message = f"{len(legs) - len(ok_legs)} 段路线获取失败，已成功的段照常展示"
    else:
        # 一段都没成功：用第一段的失败原因作为整体原因
        first = legs[0].get("status") if legs else STATUS_UNAVAILABLE
        status = first if first in (
            STATUS_UNAVAILABLE, STATUS_NO_ROUTE, STATUS_INCOMPLETE,
        ) else STATUS_UNAVAILABLE
        message = f"路线获取失败：{legs[0].get('detail', '')}" if legs else "路线获取失败"

    return _day_result(
        status, info, mode, usable, skipped, legs,
        total_distance if ok_legs else None,
        total_duration if ok_legs else None,
        message=message,
    )


def _day_result(status, info, mode, usable, skipped, legs,
                total_distance, total_duration, message="") -> dict:
    """统一组装返回值，避免两处分支把字段写歪。"""
    ok_legs = [l for l in legs if l.get("status") == STATUS_OK]
    return {
        "status": status,
        "message": message,
        "provider": info["provider"],
        "provider_info": info,
        "mode": mode,
        # 按用户编排顺序返回，便于前端核对"用的就是这个顺序"
        "ordered_place_ids": [s.get("place_id") for s in usable],
        "skipped": skipped,
        "legs": legs,
        "total_distance_m": total_distance,
        "total_duration_s": total_duration,
        "legs_ok": len(ok_legs),
        "legs_total": len(legs),
    }