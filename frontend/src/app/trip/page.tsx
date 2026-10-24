"use client";

/**
 * 行程规划页（第二版：看图选 + 攻略情报）
 *
 * 第一版的问题（用户反馈）："只能看见点点，没有真实景点图片" —— 只有名字和坐标，
 * 用户没法判断要不要去。这一版的核心改动：
 *
 *   1. 搜索结果变成**照片卡片**：真实地点 + 该地点的真实照片，看图选
 *   2. 每天里的地点卡片带缩略图
 *   3. 地图上的点可点开看照片
 *   4. 新增「攻略」搜索：走正规搜索 API 拿公开结果（会自然带出小红书/携程/马蜂窝…），
 *      **不抓取小红书站内内容**（其 robots.txt 为 Disallow: /）；正文点链接去原站看
 *
 * 数据来源（全部大陆直连可用，且都不需要额外账号）：
 *   地点 = OpenStreetMap（Photon/Overpass）  地图 = OpenFreeMap
 *   照片 = Tavily 图选后下载到本机自托管      攻略 = Tavily 公开结果
 */

import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import type * as LeafletNS from "leaflet";
import "leaflet/dist/leaflet.css";

import { useAuth } from "@/lib/auth";
import UserNav from "@/components/UserNav";
import LanguageSwitcher from "@/components/LanguageSwitcher";
import {
  addDay,
  addPlaceToDay,
  addTripCost,
  createTrip,
  deletePlace,
  deleteTrip,
  deleteTripCost,
  fetchDayRoute,
  fetchPlacePhotos,
  fetchTrip,
  fetchTripBudget,
  fetchTrips,
  fetchWebSearch,
  movePlace,
  searchPlaces,
  setTripBudget,
  updatePlace,
  updateTripCost,
  resolveApiUrl,
  COST_CATEGORY_LABELS,
  COST_STATUS_LABELS,
  type BudgetSummary,
  type CostCategory,
  type CostStatus,
  type DayRoute,
  type PlacePhoto,
  type RealPlace,
  type RouteMode,
  type Trip,
  type TripCost,
  type TripPlace,
  type TripSummary,
  type WebImage,
  type WebResult,
} from "@/lib/api";

const DAY_COLORS = ["#2563eb", "#db2777", "#059669", "#d97706", "#7c3aed", "#0891b2"];
const dayColor = (i: number) => DAY_COLORS[i % DAY_COLORS.length];

/* ── 当前行程的标识：URL 查询参数 ?trip=<id> 是唯一事实来源 ──────────
 *
 * 为什么从 localStorage 改成 URL（本轮改动）：
 *   localStorage 是**整个浏览器一个值**，两个标签页各开一趟行程时会互相覆盖 ——
 *   在 A 标签看行程 1、B 标签看行程 2，回头刷新 A 会恢复成行程 2。
 *   URL 是**每个标签页各自一份**，天然解决这个问题，而且顺带带来：
 *     · 刷新 / 前进后退都能回到同一趟行程
 *     · 行程链接可以直接分享（/trip?trip=12）
 *     · 与后端"行程属于用户"的模型天然对齐（id 就是行程的身份）
 *
 * 数据隔离没有变化：URL 里的 id 只是"要打开哪一个"，能不能打开仍由后端
 * `WHERE user_id = ?` 决定（backend/trips.py:67），越权只会拿到 404。
 *
 * localStorage 仅保留**一次性向后兼容**：老用户上次的行程 id 还在本地时，
 * 首次进来自动用它跳一次并把 id 写进 URL，随后立即清除 —— 保证不长期存在两个来源。
 */
const LEGACY_CURRENT_TRIP_KEY_PREFIX = "yedu_trip_current";

const legacyTripKey = (userId: string) => `${LEGACY_CURRENT_TRIP_KEY_PREFIX}:${userId}`;

/** 从 URL 查询参数里解析行程 id；非法/缺失一律返回 null（不猜、不伪造） */
function parseTripIdParam(raw: string | null): number | null {
  if (!raw) return null;
  const id = Number(raw);
  return Number.isFinite(id) && Number.isInteger(id) && id > 0 ? id : null;
}

/** 读一次旧版 localStorage 标识（只为兼容；读完即弃） */
function readLegacyTripId(userId: string): number | null {
  if (typeof window === "undefined" || !userId) return null;
  try {
    return parseTripIdParam(localStorage.getItem(legacyTripKey(userId)));
  } catch {
    return null; // 隐私模式等 localStorage 不可用：直接退化为"没有可恢复的行程"
  }
}

function clearLegacyTripId(userId: string) {
  if (typeof window === "undefined" || !userId) return;
  try {
    localStorage.removeItem(legacyTripKey(userId));
  } catch {
    /* 清不掉也无妨：URL 已生效，localStorage 不会再被读取 */
  }
}

/** 照片缓存：同一个地点不重复请求（后端也有缓存，这里是省一次往返）
 *  ⚠️ 键要带上城市：实测裸名字「大昭寺」搜出的图大量 403 / Google 图床，
 *  而「大昭寺 拉萨」才拿得到能下的图。 */
const photoCache = new Map<string, PlacePhoto[]>();
const pkey = (city: string, name: string) => `${city || ""}|${name}`;

function usePlacePhotos(name: string, enabled: boolean, limit = 3, city = "") {
  const key = pkey(city, name);
  const [photos, setPhotos] = useState<PlacePhoto[]>(photoCache.get(key) ?? []);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!enabled || !name) return;
    if (photoCache.has(key)) {
      setPhotos(photoCache.get(key)!);
      return;
    }
    let cancelled = false;
    setLoading(true);
    void fetchPlacePhotos(name, limit, city).then((ps) => {
      if (cancelled) return;
      photoCache.set(key, ps);
      setPhotos(ps);
      setLoading(false);
    });
    return () => {
      cancelled = true;
    };
  }, [key, name, city, enabled, limit]);

  return { photos, loading };
}

function TripPageClient() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { isAuthenticated, loading: authLoading, user } = useAuth();
  /** 本地标识的命名空间，按登录用户区分（仅用于读旧版 localStorage，见下） */
  const userKey = user?.id ? String(user.id) : "guest";
  /** URL 里的 ?trip=<id>：当前行程的唯一事实来源 */
  const urlTripId = parseTripIdParam(searchParams.get("trip"));

  const [trips, setTrips] = useState<TripSummary[]>([]);
  const [current, setCurrent] = useState<Trip | null>(null);
  const [busy, setBusy] = useState(false);

  const [newCity, setNewCity] = useState("");
  const [newDays, setNewDays] = useState(3);

  const [mode, setMode] = useState<"place" | "guide">("place");
  const [query, setQuery] = useState("");
  const [places, setPlaces] = useState<RealPlace[]>([]);
  const [guides, setGuides] = useState<WebResult[]>([]);
  const [guideImgs, setGuideImgs] = useState<WebImage[]>([]);
  const [searching, setSearching] = useState(false);
  const [targetDay, setTargetDay] = useState<number | null>(null);
  const [activeDay, setActiveDay] = useState(0);
  const [withPhotos, setWithPhotos] = useState(true);
  /** T1-E1：待定位的地点 id（点击列表里的地点 → 地图定位到它的标记） */
  const [focusedPlaceId, setFocusedPlaceId] = useState<number | null>(null);
  /** 稳定引用：避免 MapPanel 的绘制 effect 因内联回调每次都重跑 */
  const clearFocus = useCallback(() => setFocusedPlaceId(null), []);

  /** T1-E2：正在重新定位的景点（null = 面板关闭）。只改坐标，不动名称/日期/排序。 */
  const [relocateTarget, setRelocateTarget] = useState<TripPlace | null>(null);
  /** 地点搜索结果区的错误提示（搜索服务不可用时显示，不冒充"没有结果"） */
  const [placeSearchError, setPlaceSearchError] = useState<string | null>(null);

  /** 打开重新定位面板：先切到它所在的那一天，保证保存后地图立刻能看到新位置 */
  const startRelocate = useCallback((dayIndex: number, place: TripPlace) => {
    setActiveDay(dayIndex);
    setRelocateTarget(place);
  }, []);

  const dragRef = useRef<TripPlace | null>(null);
  /** 城市中心缓存：城市名 → 坐标，用于搜索时的就近过滤（只定位一次） */
  const cityCenterRef = useRef<Map<string, { lat: number; lon: number }>>(new Map());

  const ensureCityCenter = useCallback(
    async (city: string): Promise<{ lat: number; lon: number } | undefined> => {
      const c = (city || "").trim();
      if (!c) return undefined;
      const hit = cityCenterRef.current.get(c);
      if (hit) return hit;
      try {
        const found = await searchPlaces(c, 1);
        const p = found[0];
        if (!p) return undefined;
        const v = { lat: p.lat, lon: p.lon };
        cityCenterRef.current.set(c, v);
        return v;
      } catch {
        // 城市定位失败只是少一层离群过滤，不影响主流程 —— 保持"容错"语义
        return undefined;
      }
    },
    [],
  );

  useEffect(() => {
    if (!authLoading && !isAuthenticated) router.replace("/login");
  }, [isAuthenticated, authLoading, router]);

  const loadTrips = useCallback(async () => setTrips(await fetchTrips()), []);

  useEffect(() => {
    if (isAuthenticated) void loadTrips();
  }, [isAuthenticated, loadTrips]);

  /**
   * 初始化时恢复"当前行程"（T1-C1 引入，本轮改为以 URL 为准）。
   *
   * 恢复顺序（优先级从高到低，且**只有一个长期来源**）：
   *   1) URL 的 ?trip=<id>  —— 每个标签页各自一份，刷新/分享/前进后退都靠它
   *   2) 旧版 localStorage 标识 —— 仅兼容老用户上次的行程，用一次就写进 URL 并清除
   *
   * 两个保留的关键设计（防"异步读取覆盖用户新编辑"）：
   *   · 用 ref 守卫保证"每次参数变化只恢复一次"，避免 effect 因 setCurrent 重跑
   *   · 恢复失败（取不到）**不改任何状态**，也不把 URL 参数清掉 —— 网络抽风不该
   *     被误判成"行程没了"；真正不存在/越权的 id 由后端 404 决定，前端只退化为空态
   */
  const restoreGuardRef = useRef<string | null>(null);

  useEffect(() => {
    if (authLoading || !isAuthenticated) return;
    // 守卫键包含行程 id：参数变了（点击别的行程 / 粘贴链接）才需要重新恢复
    const guardKey = `${userKey}|${urlTripId ?? "none"}`;
    if (restoreGuardRef.current === guardKey) return;
    restoreGuardRef.current = guardKey;

    // ① URL 有就用 URL
    let targetId = urlTripId;
    let fromLegacy = false;
    // ② URL 没有才看旧版 localStorage（并且只用一次）
    if (targetId === null) {
      targetId = readLegacyTripId(userKey);
      fromLegacy = targetId !== null;
    }
    if (targetId === null) return; // ③ 都没有 → 正常空态，不伪造行程

    let cancelled = false;
    void (async () => {
      const t = await fetchTrip(targetId);
      if (cancelled) return;
      if (!t) {
        // 取不到（不存在 / 不属于当前用户 / 网络问题）→ 保持空态；越权数据拿不到是正确行为
        // 兼容来源失败时顺手清掉，免得每次进来都白跑一次请求
        if (fromLegacy) clearLegacyTripId(userKey);
        return;
      }
      setCurrent(t);
      setActiveDay(0);
      setTargetDay(t.days?.[0]?.id ?? null);
      if (fromLegacy) {
        // 把旧标识升级成 URL，随后清除 —— 从此只剩一个来源
        router.replace(`/trip?trip=${targetId}`, { scroll: false });
        clearLegacyTripId(userKey);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [authLoading, isAuthenticated, userKey, urlTripId, router]);

  const openTripSeq = useRef(0);

  /** 只刷新当前行程对象（保留用户当前选中的天/目标天），用于预算保存后同步人数与总预算 */
  const refetchCurrentTrip = useCallback(async (id: number) => {
    const seq = ++openTripSeq.current;
    const t = await fetchTrip(id);
    if (seq !== openTripSeq.current || !t) return;
    setCurrent(t);
  }, []);

  const openTrip = useCallback(async (id: number) => {
    const seq = ++openTripSeq.current;
    setBusy(true);
    const t = await fetchTrip(id);
    // 只接受"最后一次请求"的结果：避免慢响应后到、把用户刚打开的另一条行程覆盖掉。
    if (seq !== openTripSeq.current) return;
    setCurrent(t);
    setActiveDay(0);
    setTargetDay(t?.days?.[0]?.id ?? null);
    setBusy(false);
    // 把"当前行程"写进 URL（每个标签页各自一份）：
    // 刷新、前进/后退、把链接发给别人（越权会被后端 404 挡住）都能落到同一趟行程。
    // 用 replace 而不是 push：切行程不该往浏览器历史里塞一堆记录。
    if (t) router.replace(`/trip?trip=${id}`, { scroll: false });
  }, [router]);

  const handleCreate = async () => {
    if (!newCity.trim()) return;
    setBusy(true);
    const id = await createTrip({ city: newCity.trim(), days: newDays });
    setNewCity("");
    await loadTrips();
    await openTrip(id);
    setBusy(false);
  };

  const handleSearch = async () => {
    const q = query.trim();
    if (!q) return;
    setSearching(true);
    setPlaceSearchError(null);   // 每次搜索先清掉上一次的错误提示
    if (mode === "place") {
      setGuides([]);
      setGuideImgs([]);
      // 城市中心：已有地点就用第一个，否则先给城市本身定位一次。
      // 有了中心才能做离群过滤 —— 实测搜「大昭寺」会匹配到日本北海道的同名地点，
      // 一个飞到国外的坐标会让地图视野拉到覆盖中日，其余点全挤成一团。
      const center = firstCoord(current) ?? (await ensureCityCenter(current?.city ?? ""));
      try {
        setPlaces(await searchPlaces(q, 8, center, center ? 300 : 0));
      } catch (err) {
        // 搜索服务不可用时给出可读提示并清空列表，而不是留下上一次的结果冒充本次搜索
        setPlaces([]);
        setPlaceSearchError(err instanceof Error ? err.message : "地点搜索失败");
      }
    } else {
      setPlaces([]);
      const { results, images } = await fetchWebSearch(q, 8);
      setGuides(results);
      setGuideImgs(images);
    }
    setSearching(false);
  };

  const handleAdd = async (place: RealPlace) => {
    const dayId = targetDay ?? current?.days?.[0]?.id;
    if (!dayId || !current) return;
    setBusy(true);
    if (await addPlaceToDay(dayId, place)) {
      await openTrip(current.id);
      setPlaces((r) => r.filter((x) => x.name !== place.name));
    }
    setBusy(false);
  };

  const handleDrop = async (toDayId: number, toIndex: number) => {
    const p = dragRef.current;
    dragRef.current = null;
    if (!p || !current) return;
    if (p.day_id === toDayId && p.sort_order === toIndex) return;
    setBusy(true);
    if (await movePlace(p.id, toDayId, toIndex)) await openTrip(current.id);
    setBusy(false);
  };

  const handleDeletePlace = async (placeId: number) => {
    if (!current) return;
    setBusy(true);
    if (await deletePlace(placeId)) await openTrip(current.id);
    setBusy(false);
  };

  if (authLoading || !isAuthenticated) return null;

  return (
    <div className="min-h-screen bg-paper-2">
      <header className="bg-surface border-b border-line sticky top-0 z-20">
        <div className="max-w-[1500px] mx-auto px-4 py-3 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <span className="text-xl">🧭</span>
            <h1 className="font-bold text-ink-900">野渡寻踪 · 行程规划</h1>
            <span className="text-xs text-ink-400 hidden sm:inline">
              真实地点 · 真实照片 · 可拖拽编辑
            </span>
          </div>
          <div className="flex items-center gap-3">
            <LanguageSwitcher />
            <UserNav />
          </div>
        </div>
      </header>

      <div className="max-w-[1500px] mx-auto px-4 py-5 grid grid-cols-1 lg:grid-cols-[290px_1fr] gap-5">
        {/* ── 左：行程 ── */}
        <aside className="space-y-4">
          <section className="bg-surface rounded-[var(--radius-card)] border border-line p-4">
            <h2 className="text-sm font-bold text-ink-700 mb-3">新建行程</h2>
            <input
              value={newCity}
              onChange={(e) => setNewCity(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleCreate()}
              placeholder="目的地，例如 拉萨"
              className="w-full px-3 py-2 rounded-xl border border-line text-sm focus:outline-none focus:ring-2 focus:ring-blue-400"
            />
            <div className="flex items-center gap-2 mt-2">
              <span className="text-xs text-ink-600">天数</span>
              <input
                type="number"
                min={1}
                max={30}
                value={newDays}
                onChange={(e) => setNewDays(Number(e.target.value) || 1)}
                className="w-16 px-2 py-1.5 rounded-lg border border-line text-sm"
              />
              <button
                onClick={handleCreate}
                disabled={busy || !newCity.trim()}
                className="ml-auto px-4 py-1.5 rounded-xl bg-brand-700 hover:bg-brand-600 disabled:bg-gray-300 text-white text-sm font-bold"
              >
                创建
              </button>
            </div>
          </section>

          <section className="bg-surface rounded-[var(--radius-card)] border border-line p-4">
            <h2 className="text-sm font-bold text-ink-700 mb-3">
              我的行程 <span className="text-ink-400 font-normal">({trips.length})</span>
            </h2>
            {trips.length === 0 ? (
              <p className="text-xs text-ink-400">还没有行程，先在上面建一个。</p>
            ) : (
              <ul className="space-y-2">
                {trips.map((t) => (
                  <li key={t.id}>
                    <button
                      onClick={() => openTrip(t.id)}
                      className={`w-full text-left px-3 py-2 rounded-xl border transition-colors ${
                        current?.id === t.id
                          ? "border-brand-400 bg-brand-50"
                          : "border-line hover:border-gray-300"
                      }`}
                    >
                      <div className="text-sm font-medium text-ink-900 truncate">
                        {t.title || t.city || "未命名"}
                      </div>
                      <div className="text-[11px] text-ink-400">
                        {t.place_count} 个地点 · {t.updated_at?.slice(0, 10)}
                      </div>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </aside>

        {/* ── 右：地图 + 搜索 + 每天 ── */}
        <main className="space-y-4 min-w-0">
          <MapPanel
            trip={current}
            activeDayIndex={activeDay}
            focusedPlaceId={focusedPlaceId}
            onFocusHandled={clearFocus}
          />

          {!current ? (
            <div className="bg-surface rounded-[var(--radius-card)] border border-line p-10 text-center text-ink-400 text-sm">
              左边建一个行程，或点开已有的行程，然后用下面的搜索框加地点。
            </div>
          ) : (
            <>
              {/* 搜索：地点 / 攻略 */}
              <section className="bg-surface rounded-[var(--radius-card)] border border-line p-4">
                <div className="flex items-center gap-2 flex-wrap">
                  <div className="flex rounded-xl border border-line overflow-hidden">
                    {(
                      [
                        ["place", "地点", "OpenStreetMap 真实地点，带照片"],
                        ["guide", "攻略", "公开攻略与小红书等公开页面"],
                      ] as const
                    ).map(([k, label, tip]) => (
                      <button
                        key={k}
                        title={tip}
                        onClick={() => setMode(k)}
                        className={`px-3.5 py-2 text-sm font-medium transition-colors ${
                          mode === k ? "bg-brand-700 text-white" : "bg-surface text-ink-600 hover:bg-paper-2"
                        }`}
                      >
                        {label}
                      </button>
                    ))}
                  </div>
                  <label className="flex items-center gap-1.5 text-xs text-ink-600 cursor-pointer select-none">
                    <input
                      type="checkbox"
                      checked={withPhotos}
                      onChange={(e) => setWithPhotos(e.target.checked)}
                    />
                    显示照片
                  </label>
                  <span className="text-[11px] text-ink-400">
                    {mode === "place" ? "免 key · 带经纬度" : "不抓取站内内容，只展示公开结果"}
                  </span>
                </div>

                <div className="flex gap-2 mt-3">
                  <input
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && handleSearch()}
                    placeholder={mode === "place" ? "例如：布达拉宫 / 八廓街" : "例如：拉萨三日游 攻略"}
                    className="flex-1 px-3 py-2 rounded-xl border border-line text-sm focus:outline-none focus:ring-2 focus:ring-blue-400"
                  />
                  <button
                    onClick={handleSearch}
                    disabled={searching || !query.trim()}
                    className="px-5 py-2 rounded-xl bg-brand-700 hover:bg-gray-700 disabled:bg-gray-300 text-white text-sm font-bold"
                  >
                    {searching ? "搜索中…" : "搜索"}
                  </button>
                </div>

                {/* 地点结果：照片卡片，看图选 */}
                {placeSearchError && mode === "place" && (
                  <p className="mt-3 text-[11px] text-amber-800 bg-amber-50 border border-amber-200 rounded-lg px-2 py-1.5">
                    {placeSearchError}（可重试；已有行程数据未受影响）
                  </p>
                )}
                {places.length > 0 && (
                  <div className="mt-3 grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-3">
                    {places.map((p) => (
                      <PlaceCard
                        key={`${p.name}-${p.lat}-${p.lon}`}
                        place={p}
                        days={current.days}
                        targetDay={targetDay}
                        setTargetDay={setTargetDay}
                        onAdd={handleAdd}
                        busy={busy}
                        withPhotos={withPhotos}
                        city={current.city}
                      />
                    ))}
                  </div>
                )}

                {/* 攻略结果 */}
                {(guides.length > 0 || guideImgs.length > 0) && (
                  <div className="mt-3 space-y-3">
                    {guideImgs.length > 0 && (
                      <div className="flex gap-2 overflow-x-auto pb-1">
                        {guideImgs.slice(0, 6).map((im, i) => (
                          <a
                            key={i}
                            href={im.url}
                            target="_blank"
                            rel="noreferrer"
                            className="shrink-0"
                            title={im.description}
                          >
                            {/* 图源为外部站点，直接热链展示（点开看原图） */}
                            {/* eslint-disable-next-line @next/next/no-img-element */}
                            <img
                              src={im.url}
                              alt={im.description || "攻略配图"}
                              className="h-24 w-36 object-cover rounded-xl border border-line"
                              loading="lazy"
                            />
                          </a>
                        ))}
                      </div>
                    )}
                    <ul className="divide-y divide-line border border-line rounded-xl">
                      {guides.map((g) => (
                        <li key={g.url} className="p-3">
                          <div className="flex items-center gap-2">
                            <span
                              className={`text-[10px] px-1.5 py-0.5 rounded ${
                                g.source === "小红书"
                                  ? "bg-rose-50 text-rose-600"
                                  : "bg-paper-2 text-ink-600"
                              }`}
                            >
                              {g.source}
                            </span>
                            <a
                              href={g.url}
                              target="_blank"
                              rel="noreferrer"
                              className="text-sm text-ink-900 hover:text-brand-700 font-medium line-clamp-2"
                            >
                              {g.title || g.url}
                            </a>
                          </div>
                          {g.snippet && (
                            <p className="text-xs text-ink-600 mt-1 line-clamp-2">{g.snippet}</p>
                          )}
                        </li>
                      ))}
                    </ul>
                    <p className="text-[11px] text-ink-400">
                      以上为搜索引擎返回的公开结果，正文与图片版权归原站，点击标题前往查看。
                    </p>
                  </div>
                )}
              </section>

              {/* 每天一列，可拖拽 */}
              <section className="flex gap-3 overflow-x-auto pb-2">
                {current.days.map((d) => {
                  // 启发式每天只算一次：缺坐标或坐标可疑的地点给「重新定位」入口
                  const daySuspicious = suspiciousPlaceIds(d.places);
                  return (
                  <div
                    key={d.id}
                    onDragOver={(e) => e.preventDefault()}
                    onDrop={() => handleDrop(d.id, d.places.length)}
                    onClick={() => setActiveDay(d.day_index)}
                    className={`w-[250px] shrink-0 bg-surface rounded-[var(--radius-card)] border p-3 cursor-pointer transition-colors ${
                      activeDay === d.day_index ? "border-brand-300" : "border-line"
                    }`}
                  >
                    <div className="flex items-center gap-2 mb-2">
                      <span
                        className="w-2.5 h-2.5 rounded-full"
                        style={{ background: dayColor(d.day_index) }}
                      />
                      <span className="text-sm font-bold text-ink-700">第 {d.day_index + 1} 天</span>
                      <span className="text-[11px] text-ink-400">{d.places.length} 个</span>
                    </div>

                    {d.places.length === 0 ? (
                      <p className="text-[11px] text-ink-300 py-6 text-center">把地点拖到这里</p>
                    ) : (
                      <ul className="space-y-2">
                        {d.places.map((p, i) => (
                          <li
                            key={p.id}
                            draggable
                            onDragStart={() => (dragRef.current = p)}
                            onDragOver={(e) => e.preventDefault()}
                            onDrop={(e) => {
                              e.stopPropagation();
                              handleDrop(d.id, i);
                            }}
                            className="group rounded-xl border border-line p-2 cursor-grab active:cursor-grabbing hover:border-gray-300 bg-surface"
                          >
                            <PlaceThumb name={p.name} withPhotos={withPhotos} city={current.city} />
                            <div className="flex items-start gap-1.5 mt-1">
                              <span className="text-[11px] text-ink-400 mt-0.5">{i + 1}</span>
                              <div className="min-w-0 flex-1">
                                <div className="text-[13px] text-ink-900 leading-snug break-words">
                                  {p.name}
                                </div>
                                {/* 无可靠坐标时给明确状态，而不是让它"消失在地图上"却不说原因 */}
                                {!hasReliableCoords(p) && (
                                  <div className="text-[10px] text-amber-700 mt-0.5">缺少可靠坐标，暂不上图</div>
                                )}
                                {hasReliableCoords(p) && daySuspicious.has(p.id) && (
                                  <div className="text-[10px] text-amber-700 mt-0.5">坐标可能不准，建议重新定位</div>
                                )}
                                {p.note && (
                                  <div className="text-[11px] text-ink-400 mt-0.5">{p.note}</div>
                                )}
                              </div>
                              {/* 点击 → 地图定位到该标记（T1-E1） */}
                              <button
                                onClick={(e) => {
                                  e.stopPropagation();
                                  setActiveDay(d.day_index);
                                  setFocusedPlaceId(p.id);
                                }}
                                className="opacity-0 group-hover:opacity-100 text-ink-300 hover:text-brand-600 text-xs transition-opacity shrink-0"
                                title="在地图上定位"
                              >
                                定位
                              </button>
                              {/* 缺坐标或坐标可疑时才出现：搜索真实地点并确认修正（T1-E2） */}
                              {(!hasReliableCoords(p) || daySuspicious.has(p.id)) && (
                                <button
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    startRelocate(d.day_index, p);
                                  }}
                                  className="text-amber-700 hover:text-amber-900 text-xs shrink-0 bg-amber-50 border border-amber-200 rounded-md px-1.5 py-0.5"
                                  title="搜索真实地点并修正坐标"
                                >
                                  重新定位
                                </button>
                              )}
                              <button
                                onClick={(e) => {
                                  e.stopPropagation();
                                  handleDeletePlace(p.id);
                                }}
                                className="opacity-0 group-hover:opacity-100 text-ink-300 hover:text-red-500 text-xs transition-opacity shrink-0"
                                title="移除"
                              >
                                ✕
                              </button>
                            </div>
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                  );
                })}

                <button
                  onClick={async () => {
                    if (!current) return;
                    await addDay(current.id);
                    await openTrip(current.id);
                  }}
                  className="w-[110px] shrink-0 rounded-[var(--radius-card)] border border-dashed border-line-strong text-ink-400 text-sm hover:border-gray-400 hover:text-gray-500"
                >
                  + 加一天
                </button>
              </section>

              {/* 重新定位（T1-E2）：搜索真实 POI → 选择候选 → 显式确认 → 只改坐标 */}
              {relocateTarget && (
                <RelocatePanel
                  key={relocateTarget.id}
                  place={relocateTarget}
                  city={current.city}
                  cityCenter={firstCoord(current)}
                  onClose={() => setRelocateTarget(null)}
                  onSaved={() => void refetchCurrentTrip(current.id)}
                />
              )}

              {/* 预算（T1-D1）：整趟总预算 / 预计总费用 / 人均 / 剩余或超支 + 费用明细
                  key={current.id}：换行程时重挂载，面板内的表单与明细自动重置为该行程的数据 */}
              <BudgetPanel
                key={current.id}
                trip={current}
                refreshSignal={() => void refetchCurrentTrip(current.id)}
              />

              <div className="flex items-center gap-3 text-xs text-ink-400">
                <span>{busy ? "保存中…" : "已保存"}</span>
                <button
                  onClick={async () => {
                    if (!current) return;
                    if (confirm("删除这个行程？")) {
                      await deleteTrip(current.id);
                      setCurrent(null);
                      // 行程已删除：把 URL 里的 ?trip= 清掉，
                      // 否则刷新会去恢复一个已不存在的 id（T1-C1 / 本轮 URL 化）
                      router.replace("/trip", { scroll: false });
                      clearLegacyTripId(userKey);
                      await loadTrips();
                    }
                  }}
                  className="hover:text-red-500"
                >
                  删除该行程
                </button>
              </div>
            </>
          )}
        </main>
      </div>
    </div>
  );
}

/**
 * 页面入口：为 TripPageClient 提供 Suspense 边界。
 *
 * 为什么必须有这一层（依据本仓库 next 自带的 16.x 文档，
 * node_modules/next/dist/docs/01-app/03-api-reference/04-functions/use-search-params.md:178-180）：
 *   「During production builds, a static page that calls useSearchParams from a
 *     Client Component must be wrapped in a Suspense boundary, otherwise the build
 *     fails with the Missing Suspense boundary with useSearchParams error.」
 * 也就是说开发模式下不加也能跑，只在 `next build` 时才炸 —— 所以这条边界不能省。
 * fallback 用与页面同色系的空白块，避免加载瞬间出现刺眼白屏。
 */
export default function TripPage() {
  return (
    <Suspense
      fallback={
        <div className="min-h-screen bg-paper-2">
          <div className="max-w-[1500px] mx-auto px-4 py-6 text-sm text-ink-400">
            行程工作台加载中…
          </div>
        </div>
      }
    >
      <TripPageClient />
    </Suspense>
  );
}

/* ══════════════════════════════════════════════════════════════════
 * 重新定位面板（T1-E2）
 *
 * 解决的问题：景点坐标可能错（真实案例：拉萨行程里的「大昭寺」坐标落在日本
 * 北海道），或者干脆没有坐标。用户需要能搜真实地点、确认后把坐标改正。
 *
 * 安全约定（本面板最重要的性质）：
 *   * **只有用户点「确认使用这个位置」才写库**。搜索、选中都不写。
 *   * 只提交 {lat, lon} —— 名称、日期、排序、时段、备注、费用关联一律不碰。
 *   * 搜索失败 / 无候选 / 取消 → 原数据完全不变，并给出可读提示。
 *   * 保存失败 → 就地报错、面板保留，**绝不**先把界面标成"已修正"。
 *
 * 为什么复用现有能力而不是新写一套：候选来自既有 `POST /api/poi/search`
 * （searchPlaces），带 cityCenter + max_km 约束，避免把异地同名点当候选；
 * 保存走既有 `PATCH /api/trips/places/{id}`（updatePlace）。
 * 业务逻辑留在 API 层，地图组件只负责画点 —— 便于后续迁移到小程序。
 * ══════════════════════════════════════════════════════════════════ */
function RelocatePanel({
  place,
  city,
  cityCenter,
  onClose,
  onSaved,
}: {
  place: TripPlace;
  city: string;
  cityCenter?: { lat: number; lon: number };
  onClose: () => void;
  onSaved: () => void;
}) {
  const [query, setQuery] = useState(place.name);
  const [candidates, setCandidates] = useState<RealPlace[]>([]);
  const [selected, setSelected] = useState<RealPlace | null>(null);
  const [searching, setSearching] = useState(false);
  const [saving, setSaving] = useState(false);
  const [searched, setSearched] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [savedOk, setSavedOk] = useState(false);

  // 保存成功后的收尾定时器：组件卸载前清掉，避免对已卸载组件 setState
  const timerRef = useRef<number | null>(null);
  useEffect(() => {
    return () => {
      if (timerRef.current !== null) window.clearTimeout(timerRef.current);
    };
  }, []);

  const runSearch = async () => {
    const q = query.trim();
    if (!q) {
      setError("请输入要搜索的地点名");
      return;
    }
    setSearching(true);
    setError(null);
    setSelected(null);
    setSavedOk(false);
    try {
      // 带城市中心 + 300km 约束：搜「大昭寺」时不要把日本北海道的同名点混进来
      const found = await searchPlaces(q, 8, cityCenter, cityCenter ? 300 : 0);
      setCandidates(found);
      setSearched(true);
      if (found.length === 0) {
        setError("没有找到匹配的真实地点，换个名称试试（原坐标保持不变）");
      }
    } catch (err) {
      setCandidates([]);
      setSearched(true);
      setError(
        `地点搜索失败：${err instanceof Error ? err.message : "未知错误"}（原坐标保持不变）`,
      );
    } finally {
      setSearching(false);
    }
  };

  const confirmSave = async () => {
    if (!selected) return;
    if (!Number.isFinite(selected.lat) || !Number.isFinite(selected.lon)) {
      setError("该候选缺少有效坐标，不能使用");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      // 只发坐标：名称/日期/排序/时段/备注与费用关联都不会被改动
      const ok = await updatePlace(place.id, { lat: selected.lat, lon: selected.lon });
      if (!ok) {
        setError("保存失败：该景点可能已被删除或不属于当前账号，原坐标保持不变");
        return;
      }
      setSavedOk(true);
      onSaved(); // 让行程对象与地图立即拿到新坐标
      timerRef.current = window.setTimeout(() => onClose(), 1200);
    } catch (err) {
      setError(`保存失败：${err instanceof Error ? err.message : "未知错误"}（原坐标保持不变）`);
    } finally {
      setSaving(false);
    }
  };

  const fmtCoord = (v: number) => v.toFixed(6);

  return (
    <section className="bg-surface rounded-[var(--radius-card)] border border-amber-300 p-4">
      <div className="flex items-center gap-2 mb-2">
        <h2 className="text-sm font-bold text-ink-700">重新定位景点</h2>
        <span className="text-[11px] text-ink-400">
          只修正坐标，不改名称、日期、排序与费用关联
        </span>
        <button onClick={onClose} className="ml-auto text-xs text-ink-400 hover:text-ink-700">
          关闭
        </button>
      </div>

      {/* 当前值：让用户清楚"改的是哪一条、原来在哪" */}
      <div className="text-[11px] text-ink-500 mb-2 p-2 rounded-lg bg-paper-2 border border-line">
        <div>
          待修正景点：<b className="text-ink-900">{place.name}</b>
          {city ? `（${city}）` : ""}
        </div>
        <div className="mt-0.5">
          当前坐标：
          {hasReliableCoords(place) ? (
            <span>
              {fmtCoord(place.lat as number)}, {fmtCoord(place.lon as number)}
            </span>
          ) : (
            <span className="text-amber-700">无（缺少可用坐标）</span>
          )}
        </div>
      </div>

      {/* 搜索 */}
      <div className="flex flex-wrap items-end gap-2 mb-2">
        <label className="text-[11px] text-ink-600">
          搜索关键词
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && void runSearch()}
            placeholder="景点名，可加区域，如 大昭寺 八廓街"
            className="block w-64 mt-0.5 px-2 py-1 rounded-lg border border-line text-sm"
          />
        </label>
        <button
          onClick={() => void runSearch()}
          disabled={searching}
          className="px-3 py-1.5 rounded-lg bg-brand-700 hover:bg-brand-600 disabled:bg-gray-300 text-white text-xs font-bold"
        >
          {searching ? "搜索中…" : "搜索候选地点"}
        </button>
        {!cityCenter && (
          <span className="text-[10px] text-amber-700">
            尚未取得城市中心坐标，本次搜索未做距离约束
          </span>
        )}
      </div>

      {error && (
        <div className="text-[11px] text-amber-800 bg-amber-50 border border-amber-200 rounded-lg px-2 py-1.5 mb-2">
          {error}
        </div>
      )}
      {savedOk && (
        <div className="text-[11px] text-emerald-700 bg-emerald-50 border border-emerald-200 rounded-lg px-2 py-1.5 mb-2">
          坐标已更新，地图标记会立即刷新（已保存到服务器）
        </div>
      )}

      {/* 候选列表：名称 / 地址 / 经纬度 / 小地图预览 */}
      {!searching && candidates.length > 0 && (
        <ul className="space-y-2 mb-2">
          {candidates.map((c, i) => {
            const isSelected = selected?.name === c.name && selected?.lat === c.lat;
            return (
              <li
                key={`${c.name}-${c.lat}-${c.lon}-${i}`}
                className={`rounded-xl border p-2 flex flex-wrap items-center gap-2 ${
                  isSelected ? "border-brand-400 bg-brand-50" : "border-line"
                }`}
              >
                {/* 地图预览：用 OpenStreetMap 静态瓦片直连渲染，不需要 key、不产生费用 */}
                <MiniMapPreview lat={c.lat} lon={c.lon} label={c.name} />
                <div className="min-w-0 flex-1">
                  <div className="text-[13px] text-ink-900 truncate">{c.name}</div>
                  <div className="text-[11px] text-ink-400 truncate">
                    {c.address || c.kind || "（无地址信息）"}
                  </div>
                  <div className="text-[10px] text-ink-400">
                    {fmtCoord(c.lat)}, {fmtCoord(c.lon)}
                    {c.source ? ` · 来源 ${c.source}` : ""}
                  </div>
                </div>
                <button
                  onClick={() => {
                    setSelected(c);
                    setError(null);
                  }}
                  className={`px-3 py-1.5 rounded-lg text-xs font-bold shrink-0 ${
                    isSelected
                      ? "bg-brand-700 text-white"
                      : "border border-line text-ink-700 hover:border-brand-400"
                  }`}
                >
                  {isSelected ? "已选中" : "选这个"}
                </button>
              </li>
            );
          })}
        </ul>
      )}

      {/* 候选为空：明确说明，并强调数据未被改动 */}
      {searched && !searching && candidates.length === 0 && (
        <p className="text-[11px] text-ink-500 mb-2">
          没有候选地点可确认 —— 原坐标保持不变，你可以换个关键词再搜。
        </p>
      )}

      {/* 确认区：必须先选中候选，确认后才写库 */}
      <div className="flex flex-wrap items-center gap-2 p-2 rounded-xl border border-line bg-paper-2">
        <span className="text-[11px] text-ink-600">
          {selected ? (
            <>
              将把坐标改为 <b>{fmtCoord(selected.lat)}, {fmtCoord(selected.lon)}</b>
            </>
          ) : (
            "先在上面的候选里选一个位置"
          )}
        </span>
        <button
          onClick={() => void confirmSave()}
          disabled={!selected || saving}
          className="ml-auto px-4 py-1.5 rounded-lg bg-brand-700 hover:bg-brand-600 disabled:bg-gray-300 text-white text-xs font-bold"
        >
          {saving ? "保存中…" : "确认使用这个位置"}
        </button>
        <button
          onClick={onClose}
          className="px-3 py-1.5 rounded-lg border border-line text-ink-600 text-xs"
        >
          取消
        </button>
      </div>
    </section>
  );
}

/** 候选位置的小地图预览：单张栅格瓦片，免 key、无 API 费用。
 *  为什么不用 Leaflet 再建实例：一页多开地图实例既慢，又容易在硬件加速受限时白屏；
 *  这里只是"看一眼大概在哪"，一张瓦片足够。
 *  图源与项目默认底图保持一致（Carto 标准图，`BASEMAPS` 里实测不偏移的那个）。 */
function MiniMapPreview({ lat, lon, label }: { lat: number; lon: number; label: string }) {
  const zoom = 13;
  const n = 2 ** zoom;
  const x = Math.floor(((lon + 180) / 360) * n);
  const latRad = (lat * Math.PI) / 180;
  const y = Math.floor(
    ((1 - Math.log(Math.tan(latRad) + 1 / Math.cos(latRad)) / Math.PI) / 2) * n,
  );
  const [tileFailed, setTileFailed] = useState(false);
  return (
    <div
      className="w-[104px] h-[76px] rounded-lg overflow-hidden border border-line bg-paper-2 relative shrink-0"
      title={`${label} 附近（Carto / OpenStreetMap 瓦片预览）`}
    >
      {!tileFailed && (
        // 外部静态瓦片：用 next/image 需要改 next.config.ts 的 images.remotePatterns
        // （超出本轮范围），而对单张地图瓦片做优化也没有收益。与本文件其它
        // 外部图源一致，逐处抑制该规则。
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={`https://basemaps.cartocdn.com/rastertiles/voyager/${zoom}/${x}/${y}.png`}
          alt={`${label} 地图预览`}
          className="w-full h-full object-cover"
          loading="lazy"
          onError={() => setTileFailed(true)}   // 拿不到就退化为坐标文字，不留破图
        />
      )}
      {tileFailed && (
        <span className="absolute inset-0 flex items-center justify-center text-[10px] text-ink-400">
          预览不可用
        </span>
      )}
      <span className="absolute inset-x-0 bottom-0 text-[9px] text-center bg-surface/85 text-ink-500">
        {lat.toFixed(3)}, {lon.toFixed(3)}
      </span>
    </div>
  );
}

/* ══════════════════════════════════════════════════════════════════
 * 预算面板（T1-D1）
 *
 * 设计原则：
 *   * 所有数字都来自服务端 compute_budget()，前端**不做任何加总** ——
 *     明细与合计出自同一处，永远不会互相矛盾。
 *   * 金额口径：明细里的"金额"是**整项总金额**，不是人均。
 *     人均 = 已确认+估算 的总额 ÷ 人数，由服务端算好。
 *   * 人数沿用行程数据（trip.travelers），不另建一套人数状态。
 *   * 三态分开呈现：待确认的费用单列，绝不被计进已确认支出。
 *   * 写入失败必须显式报错（不显示虚假的成功）。
 * ══════════════════════════════════════════════════════════════════ */

/** 一次用户提交对应一个幂等键：双击/重试不会产生重复费用 */
function makeIdempotencyKey(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `k${Date.now()}-${Math.random().toString(16).slice(2, 10)}`;
}

const yuan = (v: number | null | undefined) =>
  v === null || v === undefined ? "—" : `¥${v.toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

type CostDraft = {
  category: CostCategory;
  title: string;
  amount: string;
  status: CostStatus;
  note: string;
};

const EMPTY_DRAFT: CostDraft = {
  category: "ticket",
  title: "",
  amount: "",
  status: "estimated",
  note: "",
};

function BudgetPanel({ trip, refreshSignal }: { trip: Trip; refreshSignal?: () => void }) {
  const [costs, setCosts] = useState<TripCost[]>([]);
  const [summary, setSummary] = useState<BudgetSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const [draft, setDraft] = useState<CostDraft>(EMPTY_DRAFT);
  const [editingId, setEditingId] = useState<number | null>(null);
  // 表单初值直接由行程给出（人数/总预算的唯一来源就是行程）
  const [budgetInput, setBudgetInput] = useState(
    trip.budget_total_yuan === null || trip.budget_total_yuan === undefined
      ? ""
      : String(trip.budget_total_yuan),
  );
  const [travelersInput, setTravelersInput] = useState(String(trip.travelers ?? 1));

  const tripId = trip.id;

  /** 只负责取数；任何失败都落到 error，绝不静默。
   *
   * 刻意**不在这里**同步 setLoading —— 所有 setState 都发生在 await 之后。
   * 取数在 useEffect 里是内联的（见下），因为本仓库的 react-hooks 规则禁止
   * effect 内同步 setState，而经函数调用间接触发也会被它追踪到。
   */
  const load = useCallback(async () => {
    try {
      const data = await fetchTripBudget(tripId);
      setCosts(data.costs);
      setSummary(data.budget);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "预算加载失败");
    } finally {
      setLoading(false);
    }
  }, [tripId]);

  // 初次挂载 / 行程变化后取预算；setLoading(false) 在 await 之后，不违反规则。
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const data = await fetchTripBudget(tripId);
        if (cancelled) return;
        setCosts(data.costs);
        setSummary(data.budget);
        setError(null);
      } catch (err) {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : "预算加载失败");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [tripId, refreshSignal]);

  // 说明：切换行程时**不需要**任何"同步 props 到表单"的逻辑 ——
  // 调用方用 key={trip.id} 让本组件在换行程时整体重挂载，
  // 人数/预算输入框自然回到新行程的值（见 TripPage 里的 <BudgetPanel key=.../>）。
  // 这比在 useEffect 里同步 setState 更少一轮渲染，也避免本仓库 react-hooks 规则报错。

  const submitBudget = async () => {
    setSaving(true);
    setFormError(null);
    try {
      const travelers = Number(travelersInput);
      if (!Number.isInteger(travelers) || travelers < 1 || travelers > 99) {
        throw new Error("人数需为 1–99 的整数");
      }
      const raw = budgetInput.trim();
      const budgetYuan = raw === "" ? null : Number(raw);
      if (budgetYuan !== null && (!Number.isFinite(budgetYuan) || budgetYuan < 0)) {
        throw new Error("总预算需为不小于 0 的数字");
      }
      const next = await setTripBudget(tripId, {
        travelers,
        budget_total_yuan: budgetYuan,
      });
      setSummary(next);
      refreshSignal?.(); // 让行程对象也刷新（人数/预算跟着变）
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "保存失败");
    } finally {
      setSaving(false);
    }
  };

  const submitCost = async () => {
    setFormError(null);
    const title = draft.title.trim();
    if (!title) {
      setFormError("请填写费用名称");
      return;
    }
    const amountValue = Number(draft.amount);
    if (draft.amount.trim() === "" || !Number.isFinite(amountValue) || amountValue < 0) {
      setFormError("请填写不小于 0 的金额");
      return;
    }

    setSaving(true);
    try {
      if (editingId === null) {
        // 幂等键只在"新提交"时生成；重试同一份提交会复用（见下方 catch 里的重试逻辑）
        await addTripCost(tripId, {
          category: draft.category,
          title,
          amount_yuan: amountValue,
          status: draft.status,
          note: draft.note.trim(),
          client_token: makeIdempotencyKey(),
        });
      } else {
        await updateTripCost(editingId, {
          category: draft.category,
          title,
          amount_yuan: amountValue,
          status: draft.status,
          note: draft.note.trim(),
        });
      }
      // 写成功后才清空表单；失败的半成品输入保留给用户改
      setDraft(EMPTY_DRAFT);
      setEditingId(null);
      await load();
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "保存失败，请重试");
    } finally {
      setSaving(false);
    }
  };

  const removeCost = async (cost: TripCost) => {
    setFormError(null);
    setSaving(true);
    try {
      await deleteTripCost(cost.id);
      if (editingId === cost.id) {
        setEditingId(null);
        setDraft(EMPTY_DRAFT);
      }
      await load();
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "删除失败，请重试");
    } finally {
      setSaving(false);
    }
  };

  const startEdit = (cost: TripCost) => {
    setEditingId(cost.id);
    setFormError(null);
    setDraft({
      category: cost.category,
      title: cost.title,
      amount: String(cost.amount_yuan),
      status: cost.status,
      note: cost.note || "",
    });
  };

  const over = summary?.over_budget === true;

  return (
    <section className="bg-surface rounded-[var(--radius-card)] border border-line p-4">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-sm font-bold text-ink-700">预算</h2>
        <span className="text-[11px] text-ink-400">
          金额为该条费用总额 · 金额单位：元
        </span>
      </div>

      {/* ── 加载 / 错误：两种状态都必须可见，不能假装成功 ── */}
      {loading && <p className="text-xs text-ink-400 py-3">预算加载中…</p>}
      {error && (
        <div className="text-xs text-red-600 bg-red-50 border border-red-200 rounded-xl px-3 py-2 mb-3">
          预算加载失败：{error}
          <button onClick={() => void load()} className="ml-2 underline">
            重试
          </button>
        </div>
      )}

      {!loading && summary && (
        <>
          {/* ── 总览：总预算 / 总费用 / 人均 / 剩余（口径写清楚，避免歧义）── */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mb-3">
            <div className="rounded-xl border border-line p-2.5">
              <div className="text-[11px] text-ink-400">整趟总预算</div>
              <div className="text-base font-bold text-ink-900">
                {summary.budget_total_yuan === null ? "未设置" : yuan(summary.budget_total_yuan)}
              </div>
            </div>
            <div className="rounded-xl border border-line p-2.5">
              <div className="text-[11px] text-ink-400">预计总费用</div>
              <div className="text-base font-bold text-ink-900">{yuan(summary.spent_expected_yuan)}</div>
              <div className="text-[10px] text-ink-400 mt-0.5">
                已确认 {yuan(summary.confirmed_yuan)} · 估算 {yuan(summary.estimated_yuan)}
              </div>
            </div>
            <div className="rounded-xl border border-line p-2.5">
              <div className="text-[11px] text-ink-400">人均费用</div>
              <div className="text-base font-bold text-ink-900">{yuan(summary.per_person_yuan)}</div>
              <div className="text-[10px] text-ink-400 mt-0.5">{summary.travelers} 人</div>
            </div>
            <div
              className={`rounded-xl border p-2.5 ${
                over ? "border-red-300 bg-red-50" : "border-line"
              }`}
            >
              <div className="text-[11px] text-ink-400">{over ? "超支金额" : "剩余预算"}</div>
              <div className={`text-base font-bold ${over ? "text-red-600" : "text-ink-900"}`}>
                {summary.remaining_yuan === null
                  ? "—"
                  : over
                    ? yuan(summary.over_by_yuan)
                    : yuan(summary.remaining_yuan)}
              </div>
              {summary.remaining_yuan !== null && (
                <div className="text-[10px] text-ink-400 mt-0.5">
                  {over ? "已超出总预算" : "总预算 − 预计总费用"}
                </div>
              )}
            </div>
          </div>

          {/* ── 待确认费用单独提示：绝不混进已确认支出 ── */}
          {summary.pending_cent > 0 && (
            <p className="text-[11px] text-amber-700 bg-amber-50 border border-amber-200 rounded-xl px-3 py-1.5 mb-3">
              另有 <b>{yuan(summary.pending_yuan)}</b> 待确认费用，<b>未计入</b>上面的合计与超支判断。
            </p>
          )}

          {/* ── 分类合计（服务端算好，前端只渲染）── */}
          <div className="overflow-x-auto mb-3">
            <table className="w-full text-[12px]">
              <thead>
                <tr className="text-ink-400 text-left">
                  <th className="py-1 pr-2 font-medium">分类</th>
                  <th className="py-1 pr-2 font-medium text-right">已确认</th>
                  <th className="py-1 pr-2 font-medium text-right">估算</th>
                  <th className="py-1 pr-2 font-medium text-right">待确认</th>
                  <th className="py-1 pr-2 font-medium text-right">合计</th>
                  <th className="py-1 font-medium text-right">笔数</th>
                </tr>
              </thead>
              <tbody>
                {summary.by_category.map((row) => (
                  <tr key={row.category} className="border-t border-line">
                    <td className="py-1 pr-2 text-ink-700">{row.label}</td>
                    <td className="py-1 pr-2 text-right text-ink-600">
                      {yuan(row.confirmed_cent / 100)}
                    </td>
                    <td className="py-1 pr-2 text-right text-ink-600">
                      {yuan(row.estimated_cent / 100)}
                    </td>
                    <td className="py-1 pr-2 text-right text-ink-400">
                      {yuan(row.pending_cent / 100)}
                    </td>
                    <td className="py-1 pr-2 text-right font-medium text-ink-900">
                      {yuan(row.total_cent / 100)}
                    </td>
                    <td className="py-1 text-right text-ink-400">{row.count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* ── 人数 / 总预算设置 ── */}
          <div className="flex flex-wrap items-end gap-2 mb-3 p-2.5 rounded-xl border border-line bg-paper-2">
            <label className="text-[11px] text-ink-600">
              旅行人数
              <input
                type="number"
                min={1}
                max={99}
                value={travelersInput}
                onChange={(e) => setTravelersInput(e.target.value)}
                className="block w-20 mt-0.5 px-2 py-1 rounded-lg border border-line text-sm"
              />
            </label>
            <label className="text-[11px] text-ink-600">
              整趟总预算（元）
              <input
                type="number"
                min={0}
                step="0.01"
                placeholder="留空 = 不设上限"
                value={budgetInput}
                onChange={(e) => setBudgetInput(e.target.value)}
                className="block w-36 mt-0.5 px-2 py-1 rounded-lg border border-line text-sm"
              />
            </label>
            <button
              onClick={() => void submitBudget()}
              disabled={saving}
              className="px-3 py-1.5 rounded-lg bg-brand-700 hover:bg-brand-600 disabled:bg-gray-300 text-white text-xs font-bold"
            >
              保存预算设置
            </button>
          </div>

          {/* ── 费用明细 ── */}
          {costs.length === 0 ? (
            <p className="text-xs text-ink-400 py-3">
              还没有费用记录。用下面的表单添加第一笔（例如交通、住宿、门票）。
            </p>
          ) : (
            <ul className="space-y-1.5 mb-3">
              {costs.map((c) => (
                <li
                  key={c.id}
                  className="flex items-center gap-2 rounded-xl border border-line px-2.5 py-1.5"
                >
                  <span className="text-[10px] px-1.5 py-0.5 rounded-md bg-paper-2 text-ink-600 shrink-0">
                    {c.category_label}
                  </span>
                  <span className="text-[13px] text-ink-900 truncate flex-1">{c.title || "（未命名）"}</span>
                  <span
                    className={`text-[10px] px-1.5 py-0.5 rounded-md shrink-0 ${
                      c.status === "confirmed"
                        ? "bg-emerald-50 text-emerald-700"
                        : c.status === "pending"
                          ? "bg-amber-50 text-amber-700"
                          : "bg-paper-2 text-ink-600"
                    }`}
                  >
                    {c.status_label}
                  </span>
                  <span className="text-[13px] font-medium text-ink-900 shrink-0">
                    {yuan(c.amount_yuan)}
                  </span>
                  <button
                    onClick={() => startEdit(c)}
                    className="text-ink-300 hover:text-brand-600 text-xs shrink-0"
                    title="编辑"
                  >
                    编辑
                  </button>
                  <button
                    onClick={() => void removeCost(c)}
                    disabled={saving}
                    className="text-ink-300 hover:text-red-500 text-xs shrink-0"
                    title="删除"
                  >
                    删除
                  </button>
                </li>
              ))}
            </ul>
          )}

          {/* ── 新增 / 编辑表单 ── */}
          <div className="p-2.5 rounded-xl border border-line bg-paper-2">
            <div className="text-[11px] text-ink-600 mb-1.5">
              {editingId === null ? "新增费用" : `正在编辑第 ${editingId} 条`}
              {editingId !== null && (
                <button
                  onClick={() => {
                    setEditingId(null);
                    setDraft(EMPTY_DRAFT);
                    setFormError(null);
                  }}
                  className="ml-2 underline text-ink-400"
                >
                  取消编辑
                </button>
              )}
            </div>
            <div className="flex flex-wrap items-end gap-2">
              <label className="text-[11px] text-ink-600">
                名称
                <input
                  value={draft.title}
                  onChange={(e) => setDraft({ ...draft, title: e.target.value })}
                  placeholder="如：西安→华山高铁票"
                  className="block w-52 mt-0.5 px-2 py-1 rounded-lg border border-line text-sm"
                />
              </label>
              <label className="text-[11px] text-ink-600">
                分类
                <select
                  value={draft.category}
                  onChange={(e) => setDraft({ ...draft, category: e.target.value as CostCategory })}
                  className="block mt-0.5 px-2 py-1 rounded-lg border border-line text-sm"
                >
                  {(Object.keys(COST_CATEGORY_LABELS) as CostCategory[]).map((k) => (
                    <option key={k} value={k}>
                      {COST_CATEGORY_LABELS[k]}
                    </option>
                  ))}
                </select>
              </label>
              <label className="text-[11px] text-ink-600">
                金额（元·整项总额）
                <input
                  type="number"
                  min={0}
                  step="0.01"
                  value={draft.amount}
                  onChange={(e) => setDraft({ ...draft, amount: e.target.value })}
                  placeholder="0.00"
                  className="block w-32 mt-0.5 px-2 py-1 rounded-lg border border-line text-sm"
                />
              </label>
              <label className="text-[11px] text-ink-600">
                价格状态
                <select
                  value={draft.status}
                  onChange={(e) => setDraft({ ...draft, status: e.target.value as CostStatus })}
                  className="block mt-0.5 px-2 py-1 rounded-lg border border-line text-sm"
                >
                  {(Object.keys(COST_STATUS_LABELS) as CostStatus[]).map((k) => (
                    <option key={k} value={k}>
                      {COST_STATUS_LABELS[k]}
                    </option>
                  ))}
                </select>
              </label>
              <label className="text-[11px] text-ink-600 flex-1 min-w-[8rem]">
                备注（可选）
                <input
                  value={draft.note}
                  onChange={(e) => setDraft({ ...draft, note: e.target.value })}
                  className="block w-full mt-0.5 px-2 py-1 rounded-lg border border-line text-sm"
                />
              </label>
              <button
                onClick={() => void submitCost()}
                disabled={saving}
                className="px-4 py-1.5 rounded-lg bg-brand-700 hover:bg-brand-600 disabled:bg-gray-300 text-white text-xs font-bold"
              >
                {saving ? "保存中…" : editingId === null ? "添加费用" : "保存修改"}
              </button>
            </div>
            {formError && (
              <p className="text-[11px] text-red-600 mt-2">⚠️ {formError}</p>
            )}
          </div>
        </>
      )}
    </section>
  );
}

/** 搜索结果卡片：照片 + 名称 + 加入第 N 天 */
function PlaceCard({
  place,
  days,
  targetDay,
  setTargetDay,
  onAdd,
  busy,
  withPhotos,
  city,
}: {
  place: RealPlace;
  days: Trip["days"];
  targetDay: number | null;
  setTargetDay: (id: number) => void;
  onAdd: (p: RealPlace) => void;
  busy: boolean;
  withPhotos: boolean;
  city: string;
}) {
  const { photos, loading } = usePlacePhotos(place.name, withPhotos, 3, city);
  const [idx, setIdx] = useState(0);
  const cover = photos[Math.min(idx, photos.length - 1)];

  return (
    <div className="rounded-[var(--radius-card)] border border-line overflow-hidden bg-surface flex flex-col">
      <div className="relative h-36 bg-paper-2">
        {cover ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={resolveApiUrl(cover.thumb_url || cover.url)}
            alt={place.name}
            className="w-full h-full object-cover"
            loading="lazy"
          />
        ) : (
          <div className="w-full h-full flex items-center justify-center text-ink-300 text-2xl">
            {loading ? (
              <span className="text-xs text-ink-400">照片加载中…</span>
            ) : withPhotos ? (
              "🏞️"
            ) : (
              "—"
            )}
          </div>
        )}
        {photos.length > 1 && (
          <div className="absolute bottom-1.5 left-1.5 flex gap-1">
            {photos.map((_, i) => (
              <button
                key={i}
                onClick={() => setIdx(i)}
                className={`w-1.5 h-1.5 rounded-full ${
                  i === idx ? "bg-surface" : "bg-surface/50"
                }`}
                aria-label={`第 ${i + 1} 张`}
              />
            ))}
          </div>
        )}
      </div>

      <div className="p-2.5 flex-1 flex flex-col">
        <div className="text-[13px] font-medium text-ink-900 leading-snug line-clamp-2">
          {place.name}
        </div>
        <div className="text-[11px] text-ink-400 mt-0.5 truncate">
          {place.address || place.kind || "OpenStreetMap"}
        </div>
        <div className="flex items-center gap-1.5 mt-2">
          <select
            value={targetDay ?? ""}
            onChange={(e) => setTargetDay(Number(e.target.value))}
            className="flex-1 text-xs px-2 py-1.5 rounded-lg border border-line"
          >
            {days.map((d) => (
              <option key={d.id} value={d.id}>
                第 {d.day_index + 1} 天
              </option>
            ))}
          </select>
          <button
            onClick={() => onAdd(place)}
            disabled={busy}
            className="px-3 py-1.5 rounded-lg bg-brand-700 hover:bg-brand-600 disabled:bg-gray-300 text-white text-xs font-bold"
          >
            加入
          </button>
        </div>
        {cover?.source_url && (
          <a
            href={cover.source_url}
            target="_blank"
            rel="noreferrer"
            className="text-[10px] text-ink-300 hover:text-gray-500 mt-1.5"
          >
            图片来源
          </a>
        )}
      </div>
    </div>
  );
}

/** 底图选项。
 *
 * 全部用**栅格瓦片 + Leaflet**，不用 MapLibre/WebGL ——
 * 原因：用户实测"地图一片白"，而 MapLibre 强依赖 WebGL，硬件加速关闭时就是整片白且不报错。
 * Leaflet 用普通 <img> 贴图，没有这个风险。
 *
 * ⚠️ 高德瓦片是 **GCJ-02** 坐标系，而我们的地点坐标是 WGS-84（OSM 标准），
 * 直接用会整体偏移约 100~500 米。所以选高德时要**把 WGS-84 转成 GCJ-02** 再画点，
 * 否则点位会飘到马路对面（Migo 项目 README 专门记过这个坑）。
 */
const BASEMAPS = [
  {
    key: "carto",
    label: "Carto（标准·不偏移）",
    url: "https://basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}.png",
    subdomains: "abc",
    maxZoom: 19,
    gcj: false,
    note: "WGS-84 坐标，点位与底图一致",
  },
  {
    key: "amap",
    label: "高德（中文·更快）",
    url: "https://webrd0{s}.is.autonavi.com/appmaptile?lang=zh_cn&size=1&scale=1&style=8&x={x}&y={y}&z={z}",
    subdomains: "1234",
    maxZoom: 18,
    gcj: true,
    note: "GCJ-02 底图，已把点位自动纠偏，不会飘",
  },
  {
    key: "sat",
    label: "卫星影像（高德）",
    url: "https://webst0{s}.is.autonavi.com/appmaptile?style=6&x={x}&y={y}&z={z}",
    subdomains: "1234",
    maxZoom: 18,
    gcj: true,
    note: "GCJ-02 影像，已自动纠偏；实测 0.1s（Esri 时通时不通，故不用）",
  },
] as const;

/* ── WGS-84 → GCJ-02 纠偏（高德/腾讯底图用 GCJ-02，不做这步点会偏）── */
const GCJ_A = 6378245.0;
const GCJ_EE = 0.00669342162296594323;

function _outOfChina(lat: number, lon: number) {
  return lon < 72.004 || lon > 137.8347 || lat < 0.8293 || lat > 55.8271;
}
function _transformLat(x: number, y: number) {
  let r = -100 + 2 * x + 3 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * Math.sqrt(Math.abs(x));
  r += ((20 * Math.sin(6 * x * Math.PI) + 20 * Math.sin(2 * x * Math.PI)) * 2) / 3;
  r += ((20 * Math.sin(y * Math.PI) + 40 * Math.sin((y / 3) * Math.PI)) * 2) / 3;
  r += ((160 * Math.sin((y / 12) * Math.PI) + 320 * Math.sin((y * Math.PI) / 30)) * 2) / 3;
  return r;
}
function _transformLon(x: number, y: number) {
  let r = 300 + x + 2 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * Math.sqrt(Math.abs(x));
  r += ((20 * Math.sin(6 * x * Math.PI) + 20 * Math.sin(2 * x * Math.PI)) * 2) / 3;
  r += ((20 * Math.sin(x * Math.PI) + 40 * Math.sin((x / 3) * Math.PI)) * 2) / 3;
  r += ((150 * Math.sin((x / 12) * Math.PI) + 300 * Math.sin((x / 30) * Math.PI)) * 2) / 3;
  return r;
}
function wgs84ToGcj02(lat: number, lon: number): [number, number] {
  if (_outOfChina(lat, lon)) return [lat, lon];
  let dLat = _transformLat(lon - 105, lat - 35);
  let dLon = _transformLon(lon - 105, lat - 35);
  const radLat = (lat / 180) * Math.PI;
  let magic = Math.sin(radLat);
  magic = 1 - GCJ_EE * magic * magic;
  const sqrtMagic = Math.sqrt(magic);
  dLat = (dLat * 180) / (((GCJ_A * (1 - GCJ_EE)) / (magic * sqrtMagic)) * Math.PI);
  dLon = (dLon * 180) / ((GCJ_A / sqrtMagic) * Math.cos(radLat) * Math.PI);
  return [lat + dLat, lon + dLon];
}

/** 行程里地点卡片的小缩略图 */
function PlaceThumb({
  name,
  withPhotos,
  city,
}: {
  name: string;
  withPhotos: boolean;
  city: string;
}) {
  const { photos } = usePlacePhotos(name, withPhotos, 1, city);
  if (!withPhotos) return null;
  const p = photos[0];
  return (
    <div className="h-20 rounded-lg bg-paper-2 overflow-hidden">
      {p ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={resolveApiUrl(p.thumb_url || p.url)}
          alt={name}
          className="w-full h-full object-cover"
          loading="lazy"
        />
      ) : (
        <div className="w-full h-full flex items-center justify-center text-ink-300 text-lg">🏞️</div>
      )}
    </div>
  );
}

function firstCoord(trip: Trip | null): { lat: number; lon: number } | undefined {
  for (const d of trip?.days ?? []) {
    for (const p of d.places) {
      if (typeof p.lat === "number" && typeof p.lon === "number") {
        return { lat: p.lat, lon: p.lon };
      }
    }
  }
  return undefined;
}

/** 地图：Leaflet + 栅格瓦片（刻意不用 WebGL）。
 *
 * 为什么从 MapLibre 换成 Leaflet：用户实测"地图一片白"。
 * MapLibre 强依赖 WebGL，硬件加速关闭时整片白且不报错；Leaflet 用普通 <img> 贴图，
 * 没有这个风险，栅格瓦片也更容易换源（中文底图、影像都能直接切）。
 *
 * 同时修掉"只看到一个点"：绘制分两层（先点、后线），并在最后统一做**视野自适应**。
 * 之前把 addSource 和视野自适应放在同一段里，前者在样式未就绪时抛异常，
 * 视野自适应就再也跑不到 —— 地图停在默认中心，只有附近那个点在屏内。
 */
function MapPanel({
  trip,
  activeDayIndex,
  focusedPlaceId,
  onFocusHandled,
}: {
  trip: Trip | null;
  activeDayIndex: number;
  focusedPlaceId?: number | null;
  onFocusHandled?: () => void;
}) {
  const boxRef = useRef<HTMLDivElement>(null);
  // 用 @types/leaflet 的真实类型代替 any（本轮 map logic 全部经过类型检查）
  const mapRef = useRef<LeafletNS.Map | null>(null);
  const layerRef = useRef<LeafletNS.LayerGroup | null>(null);
  const tileRef = useRef<LeafletNS.TileLayer | null>(null);
  /** place.id → marker，用于"点击列表定位到标记" */
  const markersRef = useRef<Map<number, LeafletNS.Marker>>(new Map());
  /** 已经处理过的定位请求 id（在 effect 内读写；渲染期不碰 ref） */
  const focusConsumedRef = useRef<number | null>(null);
  const [ready, setReady] = useState(false);
  const [basemap, setBasemap] = useState<string>("carto");
  const [photoOnMap, setPhotoOnMap] = useState(true);
  const [mapError, setMapError] = useState("");

  const conf = BASEMAPS.find((b) => b.key === basemap) ?? BASEMAPS[0];

  // ── 初始化地图 ──
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const L = (await import("leaflet")).default;
        if (cancelled || !boxRef.current || mapRef.current) return;
        const map = L.map(boxRef.current, {
          center: [29.657, 91.117],
          zoom: 11,
          zoomControl: true,
          worldCopyJump: true,
        });
        L.control.scale({ imperial: false }).addTo(map);
        layerRef.current = L.layerGroup().addTo(map);
        mapRef.current = map;
        // 布局稳定后再量一次尺寸，否则会出现半白/错位
        setTimeout(() => {
          try {
            map.invalidateSize();
          } catch {
            /* 忽略 */
          }
        }, 250);
        setReady(true);
      } catch (e) {
        setMapError(`地图初始化失败：${(e as Error)?.message || e}`);
      }
    })();
    return () => {
      cancelled = true;
      try {
        mapRef.current?.remove?.();
      } catch {
        /* 忽略 */
      }
      mapRef.current = null;
    };
  }, []);

  // ── 底图（可切换）──
  useEffect(() => {
    if (!ready) return;
    let cancelled = false;
    (async () => {
      const L = (await import("leaflet")).default;
      const map = mapRef.current;
      if (cancelled || !map) return;
      try {
        if (tileRef.current) map.removeLayer(tileRef.current);
        tileRef.current = L.tileLayer(conf.url, {
          subdomains: conf.subdomains.split(""),
          maxZoom: conf.maxZoom,
          attribution: "&copy; OpenStreetMap contributors",
        }).addTo(map);
        tileRef.current.on("tileerror", () => {
          // 个别瓦片失败不致命，但要让用户能看到提示而不是面对一片白
          setMapError(`部分地图瓦片加载失败（${conf.label}），可换个底图试试`);
        });
      } catch (e) {
        setMapError(`底图加载失败：${(e as Error)?.message || e}`);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [conf, ready]);

  /** 当前选中那天的地点（T1-E1：地图跟随日期切换）。
   *
   * 修的问题：原来这里遍历**所有天**，于是切到第 2 天地图仍把第 1 天的点一起画，
   * 视野被拉大到覆盖全部行程，"切换日期"对地图没有任何影响。
   */
  const activeDay = trip?.days?.[activeDayIndex] ?? null;
  /** 城市名单独取出来：popup 里取照片要用它，直接写 trip?.city 会被 lint 判为缺依赖 */
  const tripCity = trip?.city ?? "";

  /** 可选点位：只取当前天 + 坐标可靠的地点。缺/非法坐标的**不画**，也不伪造位置。 */
  const points = useMemo(() => {
    const out: {
      id: number;
      lat: number;
      lon: number;
      label: string;
      color: string;
      name: string;
    }[] = [];
    (activeDay?.places ?? []).forEach((p, i) => {
      if (!hasReliableCoords(p)) return;
      out.push({
        id: p.id,
        lat: p.lat as number,
        lon: p.lon as number,
        label: `D${activeDayIndex + 1}-${i + 1} ${p.name}`,
        color: dayColor(activeDayIndex),
        name: p.name,
      });
    });
    return out;
  }, [activeDay, activeDayIndex]);

  /** 当天无法上图的地点数量 → 给出明确状态而不是静默消失 */
  const missingCoordsCount = useMemo(
    () => (activeDay?.places ?? []).filter((p) => !hasReliableCoords(p)).length,
    [activeDay],
  );

  /** 与其他点位明显不在一个城市尺度上的点（只提示，不删数据、不改坐标） */
  const suspiciousIds = useMemo(
    () => suspiciousPlaceIds(activeDay?.places ?? []),
    [activeDay],
  );

  /* ── 真实道路路线（T1-F1）─────────────────────────────────────────
   * 请求键只由「当日景点的 id + 坐标 + 顺序 + 出行方式」组成：
   *   · 无关的 React 状态更新（开关照片、输入搜索词…）不会改变这个键
   *     → 不会触发外部路线请求；
   *   · 顺序或坐标一变，键就变 → 必然重新取，**不会返回旧顺序的路线**；
   *   · 内存缓存只作为"避免重复请求"的手段，不作为渲染数据源，
   *     且读取发生在 await 之后（避免 effect 内同步 setState）。
   */
  const [routeMode, setRouteMode] = useState<RouteMode>("driving");
  const [routeState, setRouteState] = useState<
    { key: string; route: DayRoute | null; error: string | null } | null
  >(null);
  const routeCacheRef = useRef<Map<string, DayRoute>>(new Map());

  const routeKey = useMemo(() => {
    const parts = (activeDay?.places ?? []).map(
      (p) => `${p.id}:${hasReliableCoords(p) ? `${p.lat},${p.lon}` : "na"}`,
    );
    return `${trip?.id ?? 0}|${activeDayIndex}|${routeMode}|${parts.join(">")}`;
  }, [activeDay, activeDayIndex, routeMode, trip?.id]);

  const tripIdForRoute = trip?.id ?? 0;
  useEffect(() => {
    if (!tripIdForRoute) return;
    let cancelled = false;
    void (async () => {
      // 先让出一拍：保证本 effect 内所有 setState 都发生在 await 之后
      await Promise.resolve();
      if (cancelled) return;
      const hit = routeCacheRef.current.get(routeKey);
      if (hit) {
        setRouteState({ key: routeKey, route: hit, error: null });
        return;
      }
      try {
        const data = await fetchDayRoute(tripIdForRoute, activeDayIndex, routeMode);
        if (cancelled) return;
        routeCacheRef.current.set(routeKey, data.route);
        setRouteState({ key: routeKey, route: data.route, error: null });
      } catch (err) {
        if (cancelled) return;
        setRouteState({
          key: routeKey,
          route: null,
          error: err instanceof Error ? err.message : "路线请求失败",
        });
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [routeKey, tripIdForRoute, activeDayIndex, routeMode]);

  // 只有"键匹配"的路线才算当前数据，避免切换瞬间短暂显示上一天的路线
  const route = routeState?.key === routeKey ? routeState.route : null;
  const routeError = routeState?.key === routeKey ? routeState.error : null;
  const routePending = !routeState || routeState.key !== routeKey;
  const okLegs = (route?.legs ?? []).filter(
    (l) => l.status === "ok" && (l.geometry?.length ?? 0) >= 2,
  );

  // ── 画点 / 连线 / 视野自适应 ──
  useEffect(() => {
    if (!ready) return;
    let cancelled = false;
    (async () => {
      const L = (await import("leaflet")).default;
      const map = mapRef.current;
      const layer = layerRef.current;
      if (cancelled || !map || !layer) return;

      layer.clearLayers();
      markersRef.current.clear();

      // 高德底图是 GCJ-02，点位要跟着纠偏，否则整体偏移上百米
      const toView = (lat: number, lon: number): [number, number] =>
        conf.gcj ? wgs84ToGcj02(lat, lon) : [lat, lon];

      const latlngs: [number, number][] = [];
      points.forEach((pt) => {
        const [la, lo] = toView(pt.lat, pt.lon);
        latlngs.push([la, lo]);

        const icon = L.divIcon({
          className: "",
          html:
            `<div style="width:16px;height:16px;border-radius:9999px;background:${pt.color};` +
            `border:2px solid #fff;box-shadow:0 1px 5px rgba(0,0,0,.35)"></div>`,
          iconSize: [16, 16],
          iconAnchor: [8, 8],
        });
        const marker = L.marker([la, lo], { icon, title: pt.label }).addTo(layer);
        markersRef.current.set(pt.id, marker);

        if (!photoOnMap) {
          marker.bindPopup(`<div style="font-size:13px;font-weight:600">${escapeHtml(pt.label)}</div>`);
          return;
        }
        marker.bindPopup(
          `<div style="min-width:170px">
             <div style="font-weight:600;font-size:13px;margin-bottom:4px">${escapeHtml(pt.label)}</div>
             <div class="yedu-pop" style="height:92px;background:#f3f4f6;border-radius:8px;
                  display:flex;align-items:center;justify-content:center;color:#9ca3af;font-size:12px">
               照片加载中…
             </div>
           </div>`,
        );
        marker.on("popupopen", (ev: LeafletNS.PopupEvent) => {
          const node = ev.popup?.getElement?.()?.querySelector(".yedu-pop") as HTMLElement | null;
          const paint = (url?: string) => {
            if (node && url) {
              // 后端返回的是站内相对路径（/api/images/…），必须补上 API 基址；
              // 否则浏览器会把它拼到**前端** origin 上 → 必然 404 破图。
              // resolveApiUrl 对已是绝对地址的 URL 原样返回，不会重复加前缀。
              node.innerHTML =
                `<img src="${resolveApiUrl(url)}" alt="" style="width:100%;height:100%;object-fit:cover;border-radius:8px">`;
            } else if (node) {
              node.textContent = "暂无照片";
            }
          };
          const ck = pkey(tripCity, pt.name);
          const cached = photoCache.get(ck);
          if (cached?.length) {
            paint(cached[0].thumb_url || cached[0].url);
          } else {
            void fetchPlacePhotos(pt.name, 1, tripCity).then((ps) => {
              photoCache.set(ck, ps);
              paint(ps[0]?.thumb_url || ps[0]?.url);
            });
          }
        });
      });

      // 当天路线（T1-F1）：
      //   · 有真实道路几何就画**真实路线**（实线）；
      //   · 拿不到几何的段才退回"顺序虚线"，并且**明确标注不是道路路线** ——
      //     绝不用直线冒充真实路线，也不展示任何估算距离/耗时。
      const toViewGeom = (geom: [number, number][]) =>
        geom.map(([la, lo]) => toView(la, lo));

      // 在 effect 内推导（而不是用外层的数组）：外层数组每次渲染都是新引用，
      // 若放进依赖会让本 effect 每渲染都重绘一遍图层。
      const okLegsHere = (route?.legs ?? []).filter(
        (l) => l.status === "ok" && (l.geometry?.length ?? 0) >= 2,
      );

      if (okLegsHere.length > 0) {
        okLegsHere.forEach((leg) => {
          L.polyline(toViewGeom(leg.geometry as [number, number][]), {
            color: dayColor(activeDayIndex),
            weight: 4,
            opacity: 0.9,
          }).addTo(layer);
        });
      }

      // 哪些相邻点对**没有**真实几何：这些才用虚线示意顺序
      const realPairs = new Set(
        okLegsHere.map((l) => `${l.from_place_id}->${l.to_place_id}`),
      );
      const viewPoints = (activeDay?.places ?? [])
        .filter(hasReliableCoords)
        .map((p) => ({ id: p.id, pos: toView(p.lat as number, p.lon as number) }));
      for (let i = 0; i < viewPoints.length - 1; i += 1) {
        const a = viewPoints[i];
        const b = viewPoints[i + 1];
        if (realPairs.has(`${a.id}->${b.id}`)) continue;
        L.polyline([a.pos, b.pos], {
          color: "#9ca3af",          // 灰色虚线：与真实路线的实线明显区分
          weight: 2,
          dashArray: "6 6",
          opacity: 0.7,
        }).addTo(layer);
      }

      // ★ 视野自适应：修"只看到一个点"。无论有几个点都要跑到这里。
      try {
        if (latlngs.length === 1) {
          map.setView(latlngs[0], 14);
        } else if (latlngs.length > 1) {
          map.fitBounds(L.latLngBounds(latlngs).pad(0.2), { maxZoom: 15 });
        }
      } catch {
        /* 忽略 */
      }

      // ── 点击列表后的定位（T1-E1）──
      // 放在绘制 effect 内部而不是单独的 effect：标记刚在本轮建好，
      // 这样"换天 + 定位"同时发生时不会出现"标记还没画就去定位"的竞争。
      // 用 focusConsumedRef 记录已处理的 id（**只在 effect 内读写**，渲染期不碰 ref）。
      // 视野自适应在前，所以定位会覆盖 fitBounds，把镜头落到目标点上。
      if (
        focusedPlaceId !== null &&
        focusedPlaceId !== undefined &&
        focusConsumedRef.current !== focusedPlaceId
      ) {
        focusConsumedRef.current = focusedPlaceId;
        try {
          const marker = markersRef.current.get(focusedPlaceId);
          if (marker) {
            map.setView(marker.getLatLng(), Math.max(map.getZoom?.() ?? 13, 14), { animate: true });
            marker.openPopup();
          }
          // 找不到标记（该地点无可靠坐标 / 不在当天）就只清掉请求，绝不伪造定位
        } catch {
          /* 定位失败不影响其它功能 */
        }
        onFocusHandled?.();
      } else if (focusedPlaceId === null || focusedPlaceId === undefined) {
        focusConsumedRef.current = null;   // 允许下次再定位同一个点
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [points, activeDay, activeDayIndex, photoOnMap, conf, ready, focusedPlaceId, onFocusHandled, tripCity, route]);

  return (
    <section className="bg-surface rounded-[var(--radius-card)] border border-line overflow-hidden">
      <div className="px-4 py-2.5 flex items-center gap-3 border-b border-line flex-wrap">
        <h2 className="text-sm font-bold text-ink-700">地图</h2>
        <select
          value={basemap}
          onChange={(e) => setBasemap(e.target.value)}
          className="text-xs px-2 py-1 rounded-lg border border-line"
        >
          {BASEMAPS.map((b) => (
            <option key={b.key} value={b.key}>
              {b.label}
            </option>
          ))}
        </select>
        <span className="text-[11px] text-ink-400">
          {conf.note} {trip ? `· ${trip.city || trip.title}` : ""}
        </span>
        {/* 路线口径必须说清楚：实线是真实道路，虚线只是顺序示意 */}
        <span className="text-[10px] text-ink-300">
          {okLegs.length > 0
            ? "实线 = 真实道路路线（含距离/耗时）"
            : "虚线 = 当日访问顺序示意，非道路路线／不含距离与耗时"}
        </span>
        <label className="ml-auto flex items-center gap-1.5 text-xs text-ink-600">
          <span className="text-ink-400">出行</span>
          <select
            value={routeMode}
            onChange={(e) => setRouteMode(e.target.value as RouteMode)}
            className="text-xs px-2 py-1 rounded-lg border border-line"
          >
            <option value="driving">驾车</option>
            <option value="walking">步行</option>
            <option value="cycling">骑行</option>
          </select>
        </label>
        <label className="ml-auto flex items-center gap-1.5 text-xs text-ink-600 cursor-pointer select-none">
          <input
            type="checkbox"
            checked={photoOnMap}
            onChange={(e) => setPhotoOnMap(e.target.checked)}
          />
          点标记显示照片
        </label>
      </div>
      {/* ── 路线汇总与分段（T1-F1）：失败/未配置时给清晰降级，不显示虚假数字 ── */}
      {(activeDay?.places?.length ?? 0) >= 2 && (
        <div className="px-4 py-2 border-t border-line text-[11px]">
          {routePending && <span className="text-ink-400">路线计算中…</span>}

          {routeError && (
            <span className="text-amber-800">
              路线请求失败：{routeError}（已保留景点与顺序，地图上仅显示顺序虚线）
            </span>
          )}

          {route && !routeError && (
            <>
              {route.status === "ok" && route.total_distance_m !== null && (
                <span className="text-ink-700">
                  当日 {route.legs_ok} 段 · 合计 <b>{fmtDistance(route.total_distance_m)}</b>
                  {route.total_duration_s !== null && (
                    <> · 约 <b>{fmtDuration(route.total_duration_s)}</b></>
                  )}
                  <span className="text-ink-400"> · 来源 {route.provider}</span>
                </span>
              )}

              {(route.status === "not_configured" ||
                route.status === "mode_unsupported" ||
                route.status === "unavailable" ||
                route.status === "no_route" ||
                route.status === "incomplete") && (
                <span className="text-amber-800">
                  {route.status === "not_configured" && "未配置路线服务"}
                  {route.status === "mode_unsupported" && "该服务不支持所选出行方式"}
                  {route.status === "unavailable" && "路线服务暂时不可用"}
                  {route.status === "no_route" && "两点之间没有可用道路路线"}
                  {route.status === "incomplete" && "上游返回的路线数据不完整"}
                  {route.message ? `：${route.message}` : ""}
                  <span className="text-ink-500">
                    （未显示距离与耗时；地图上是顺序虚线，不代表真实路线）
                  </span>
                </span>
              )}

              {route.status === "partial" && (
                <span className="text-amber-800">
                  {route.message}
                  <span className="text-ink-500">（失败段为虚线，不计入合计）</span>
                </span>
              )}

              {!routePending && route.status === "ok" && route.legs_ok === 0 && (
                <span className="text-ink-400">{route.message || "当天没有可计算的路线段"}</span>
              )}
            </>
          )}

          {/* 缺坐标的点：明确报告它没参与计算 */}
          {route && route.skipped.length > 0 && (
            <div className="mt-1 text-amber-700">
              {route.skipped.length} 个地点因缺少可靠坐标未参与路线计算：
              {route.skipped.map((s) => s.name || `#${s.place_id}`).join("、")}
            </div>
          )}

          {/* 分段明细：只列有真实数据的段 */}
          {route && route.legs.length > 0 && (
            <ul className="mt-1.5 space-y-0.5">
              {route.legs.map((leg, i) => (
                <li key={`${leg.from_place_id}-${leg.to_place_id}-${i}`} className="flex items-center gap-2">
                  <span className="text-ink-500 truncate">
                    {i + 1}. {leg.from_name} → {leg.to_name}
                  </span>
                  {leg.status === "ok" ? (
                    <span className="text-ink-700 shrink-0">
                      {fmtDistance(leg.distance_m ?? 0)}
                      {leg.duration_s !== undefined && ` · ${fmtDuration(leg.duration_s)}`}
                    </span>
                  ) : (
                    <span className="text-amber-700 shrink-0">
                      无路线数据（{leg.status}）
                    </span>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      <div className="relative">
        <div ref={boxRef} className="h-[340px] sm:h-[420px] w-full bg-paper-2 z-0" />
        {mapError && (
          <div className="absolute bottom-2 left-2 right-2 text-[11px] bg-amber-50 border border-amber-200 text-amber-700 rounded-lg px-2 py-1.5">
            {mapError}
          </div>
        )}
        {/* 缺坐标 / 坐标可疑：明确状态，不静默消失、也不伪造位置 */}
        {(missingCoordsCount > 0 || suspiciousIds.size > 0) && !mapError && (
          <div className="absolute top-2 left-2 right-2 text-[11px] bg-amber-50/95 border border-amber-200 text-amber-700 rounded-lg px-2 py-1.5">
            {missingCoordsCount > 0 && (
              <span>{missingCoordsCount} 个地点缺少可用坐标，未显示在地图上</span>
            )}
            {missingCoordsCount > 0 && suspiciousIds.size > 0 && <span> · </span>}
            {suspiciousIds.size > 0 && (
              <span>{suspiciousIds.size} 个坐标与当日其他地点相距过远，可能不准确</span>
            )}
          </div>
        )}
        {points.length === 0 && !mapError && (activeDay?.places?.length ?? 0) === 0 && (
          <div className="absolute top-2 left-2 text-[11px] bg-surface/90 border border-line text-ink-600 rounded-lg px-2 py-1">
            {trip ? "这一天还没有地点，加入后会显示点位与访问顺序" : "加入地点后，这里会显示它们的点位与访问顺序"}
          </div>
        )}
      </div>
    </section>
  );
}
function escapeHtml(s: string): string {
  return s.replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c] as string,
  );
}

/** 距离格式化（输入单位：米）。仅做单位换算展示，不改变数值含义。 */
function fmtDistance(m: number): string {
  if (!Number.isFinite(m)) return "—";
  return m >= 1000 ? `${(m / 1000).toFixed(1)} km` : `${Math.round(m)} m`;
}

/** 耗时格式化（输入单位：秒）。仅做单位换算展示，不改变数值含义。 */
function fmtDuration(s: number): string {
  if (!Number.isFinite(s)) return "—";
  const total = Math.round(s / 60);
  if (total < 60) return `${total} 分钟`;
  const h = Math.floor(total / 60);
  const min = total % 60;
  return min ? `${h} 小时 ${min} 分` : `${h} 小时`;
}

/**
 * 坐标是否可用于地图（T1-E1）。
 *
 * 为什么不能只判 `typeof === "number"`：NaN、Infinity、越界值都是 number，
 * 但 Leaflet 遇到它们会抛错或把视野拉到爆。真实库里也确实出现过跨城错配的坐标
 * （拉萨行程里的「大昭寺」落在日本北海道），所以这里要做范围校验，
 * 而不是假设后端给的一定对。
 */
function hasReliableCoords(p: TripPlace): boolean {
  if (typeof p.lat !== "number" || typeof p.lon !== "number") return false;
  if (!Number.isFinite(p.lat) || !Number.isFinite(p.lon)) return false;
  return p.lat >= -90 && p.lat <= 90 && p.lon >= -180 && p.lon <= 180;
}

/** 两个坐标之间的近似距离（km），用于识别明显不合理的点位；只做提示，不用于导航。 */
function approxKm(aLat: number, aLon: number, bLat: number, bLon: number): number {
  const R = 6371;
  const dLat = ((bLat - aLat) * Math.PI) / 180;
  const dLon = ((bLon - aLon) * Math.PI) / 180;
  const s =
    Math.sin(dLat / 2) ** 2 +
    Math.cos((aLat * Math.PI) / 180) * Math.cos((bLat * Math.PI) / 180) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.min(1, Math.sqrt(s)));
}

/** 同一天里"相距过远"的地点 id 集合（>200km 视为坐标可疑）。
 *
 * 抽成共享函数的原因：地图要据此提示，景点列表要据此提供「重新定位」入口。
 * 两处各写一份启发式必然会漂移，所以只留一份。
 * 它在真实数据上确实有产出 —— 拉萨行程里的「大昭寺」坐标为日本北海道（约 3600km 外）。
 */
function suspiciousPlaceIds(places: TripPlace[]): Set<number> {
  const valid = places.filter(hasReliableCoords);
  if (valid.length < 2) return new Set<number>();
  const flags = new Set<number>();
  valid.forEach((p) => {
    const others = valid.filter((q) => q.id !== p.id);
    const nearest = Math.min(
      ...others.map((q) =>
        approxKm(p.lat as number, p.lon as number, q.lat as number, q.lon as number),
      ),
    );
    if (nearest > 200) flags.add(p.id);
  });
  return flags;
}

function cssEscape(s: string): string {
  return s.replace(/["\\]/g, "\\$&");
}
