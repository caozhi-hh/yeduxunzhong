const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000";

export function getLang(): string {
  if (typeof window === "undefined") return "zh";
  return localStorage.getItem("yedu_lang") || "zh";
}

function getAuthHeaders(): Record<string, string> {
  const token = typeof window !== "undefined" ? localStorage.getItem("yedu_auth_token") : null;
  return token ? { Authorization: `Bearer ${token}` } : {};
}

/** XSS 防护：转义 HTML 特殊字符 */
function sanitize(input: string): string {
  return input
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#x27;");
}

/** 统一错误类 */
export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number = 500) {
    super(message);
    this.status = status;
  }
}

/**
 * 把后端返回的**站内相对路径**解析成浏览器可访问的绝对地址。
 *
 * 为什么必须有它（现已实测验证）：后端自托管图片返回的是 `/api/images/xxx.jpg`
 * 这种相对路径，而前端与后端**常常不同 origin**：
 *   · 本地 dev：前端 :3001 / 后端 :8000
 *   · 线上：Cloudflare Pages + HF Space
 * 直接把相对路径放进 `<img src>`，浏览器会拼到**前端** origin 上 → 必然 404 破图。
 * （这正是基线审计记录的"景点图片在前端必然 404"的根因。）
 *
 * 已是绝对地址（http(s):// 或 data:）时原样返回，不做二次拼接。
 */
export function resolveApiUrl(path?: string | null): string {
  if (!path) return "";
  if (/^(https?:)?\/\//i.test(path) || path.startsWith("data:")) return path;
  return `${API_BASE}${path.startsWith("/") ? "" : "/"}${path}`;
}

/** 统一 JSON 请求封装 */
async function request<T>(
  endpoint: string,
  options: RequestInit = {},
): Promise<T> {
  const res = await fetch(`${API_BASE}${endpoint}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...getAuthHeaders(),
      ...options.headers,
    },
  });

  const data = await res.json().catch(() => ({}));

  if (!res.ok || data.status === "error") {
    throw new ApiError(
      data.message || data.detail || `请求失败 (${res.status})`,
      res.status,
    );
  }

  return data as T;
}

export async function streamChat(
  endpoint: string,
  body: Record<string, unknown>,
  onChunk: (text: string) => void,
  onDone: (data?: Record<string, unknown>) => void,
  onError?: (message: string) => void,
) {
  let receivedDone = false;

  try {
    const res = await fetch(`${API_BASE}${endpoint}`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...getAuthHeaders() },
      body: JSON.stringify({ ...body, language: getLang() }),
    });

    if (!res.ok) {
      const message = `请求失败：${res.status} ${res.statusText}`;
      onChunk(`\n\n❌ ${message}`);
      onError?.(message);
      onDone();
      return;
    }

    const reader = res.body?.getReader();
    if (!reader) { onDone(); return; }

    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() || "";

      for (const line of lines) {
        if (!line.startsWith("data: ")) continue;

        let data: any;
        try {
          data = JSON.parse(line.slice(6));
        } catch {
          continue; // 只跳过这一行坏数据，不再把整个事件流一起吞掉
        }

        if (data.type === "chunk") {
          onChunk(data.content);
        } else if (data.type === "error") {
          // 2026-10-10 修复：此前没有任何 error 分支。
          // 后端把真实原因放在 content 里（如上游 401 身份验证失败），
          // 却在这里被静默丢弃 —— 用户只看到"⏳ 网络波动，正在重试..."然后永远等下去。
          const message = String(data.content || "生成失败，请稍后重试");
          onChunk(`\n\n❌ ${message}\n\n`);
          onError?.(message);
        } else if (data.type === "done") {
          receivedDone = true;
          onDone(data);
        }
      }
    }
  } catch {
    const message = "连接中断，请重试";
    onChunk(`\n\n⚠️ ${message}`);
    onError?.(message);
  }

  if (!receivedDone) onDone();
}

// History API
export async function fetchHistory(): Promise<any[]> {
  try {
    const data = await request<{ plans?: any[] }>("/api/history");
    return data.plans || [];
  } catch { return []; }
}

export async function fetchPlan(id: number): Promise<any> {
  try {
    return await request(`/api/history/${id}`);
  } catch { return null; }
}

export async function deletePlan(id: number): Promise<boolean> {
  try {
    await request(`/api/history/${id}`, { method: "DELETE" });
    return true;
  } catch { return false; }
}

export async function savePlanToHistory(
  data: Record<string, unknown>,
): Promise<{ plan_id?: number; updated?: boolean } | null> {
  try {
    return await request<{ plan_id?: number; updated?: boolean }>("/api/history", {
      method: "POST",
      body: JSON.stringify(data),
    });
  } catch (err) {
    // 2026-10-10 修复：以前是 `catch { return null }` 完全静默 ——
    // 401/500 全都无声无息，用户以为存上了，其实一条没有。
    console.warn("[history] 保存攻略失败：", err);
    return null;
  }
}

export interface SpotImage {
  name: string;
  image_url: string;   // 卡片用：400w，实测约 20KB
  thumb_url?: string;  // 低带宽备用：200w，实测约 6.6KB
  large_url?: string;  // 点击放大用：1080w，实测约 113KB（只在点开时才下载）
  source: string;
  author: string;
  author_url: string;
  source_url: string;
  policy: string;
  license?: string;
  /** 后端对"为什么没有图"的说明（配额用尽 / 未匹配 / 未配置 key），成功时为空 */
  note?: string;
  /** 命中方式（exact/fuzzy/none），用于区分"没匹配到"与"抓取失败" */
  match?: string;
}

/**
 * 批量取景点真实照片。
 *
 * ⚠️ 返回的 URL 有两种形态，渲染前必须过 resolveApiUrl：
 *   · Unsplash 分支 —— 图源 CDN 的**绝对地址**（条款要求 hotlink）
 *   · Pixabay 分支 —— 下载后自托管的**站内相对路径**（/api/images/…）
 * 直接把相对路径塞进 <img src> 会被浏览器拼到前端 origin 上 → 必然 404。
 * 署名信息随图返回，展示时必须一起渲染；key 留在后端，前端不需要图源 key。
 */
export async function fetchSpotImages(city: string, spots: string[]): Promise<SpotImage[]> {
  if (!spots.length) return [];
  try {
    const data = await request<{ images?: SpotImage[] }>("/api/spot-images", {
      method: "POST",
      body: JSON.stringify({ city, spots }),
    });
    return data.images || [];
  } catch (err) {
    console.warn("[spot-images] 取图失败：", err);
    return [];
  }
}

/* ==================== 真实地点（POI）====================
 * 全部免 key：后端走 Photon（搜索）与 Overpass（附近）。
 * 这一层是"把景点从模型编造换成查真实数据"的关键 —— 返回的每个地点都带经纬度，
 * 所以能画在地图上、能算路线、能拖到别的天。
 */
export interface RealPlace {
  name: string;
  lat: number;
  lon: number;
  address?: string;
  kind?: string;
  source?: string;
  source_url?: string;
}

export async function searchPlaces(
  query: string,
  limit = 8,
  near?: { lat: number; lon: number },
  maxKm = 0,
): Promise<RealPlace[]> {
  const q = query.trim();
  if (!q) return [];
  const data = await request<{ places?: RealPlace[]; status?: string; message?: string }>(
    "/api/poi/search",
    {
      method: "POST",
      body: JSON.stringify({
        query: q,
        limit,
        near_lat: near?.lat ?? null,
        near_lon: near?.lon ?? null,
        max_km: maxKm,
      }),
    },
  );
  // 后端在"搜索服务暂时不可用"时会返回 status=error + 可读原因（HTTP 仍是 200）。
  // 这里必须把它抛出而不是当成"没有结果"：T1-E2 的重新定位要区分
  // 「确实没有候选」和「搜索坏了」—— 后者应提示可重试，而不是让用户以为地点不存在。
  // （`request` 只把 status==="error" 当错误抛出，这里再兜一次自定义形状。）
  if (data.status === "error") {
    throw new ApiError(data.message || "地点搜索暂时不可用", 503);
  }
  return data.places || [];
}

/* ==================== 结构化行程 ====================
 * 与 fetchHistory 的区别：history 是「一整篇攻略文本」，这里是**可编辑的行程实体**
 * （行程 → 每天 → 地点），能拖拽换天、改时段、增删地点。
 */
export interface TripPlace {
  id: number;
  day_id: number;
  name: string;
  lat: number | null;
  lon: number | null;
  address: string;
  kind: string;
  source: string;
  source_url: string;
  sort_order: number;
  start_time: string;
  duration_min: number;
  note: string;
}

export interface TripDay {
  id: number;
  trip_id: number;
  day_index: number;
  date: string;
  note: string;
  places: TripPlace[];
}

export interface Trip {
  id: number;
  title: string;
  city: string;
  start_date: string;
  end_date: string;
  note: string;
  /** 旅行人数（T1-D1 加入；预算与行程共用这一个来源，不另建人数状态） */
  travelers?: number;
  /** 整趟旅行总预算上限（元）。null/缺省 = 未设置。 */
  budget_total_yuan?: number | null;
  budget_total_cent?: number | null;
  days: TripDay[];
}

export interface TripSummary {
  id: number;
  title: string;
  city: string;
  start_date: string;
  end_date: string;
  place_count: number;
  updated_at: string;
  travelers?: number;
  budget_total_yuan?: number | null;
}

export async function fetchTrips(): Promise<TripSummary[]> {
  const data = await request<{ trips?: TripSummary[] }>("/api/trips");
  return data.trips || [];
}

export async function createTrip(
  payload: { title?: string; city?: string; days?: number; start_date?: string; end_date?: string },
): Promise<number> {
  const data = await request<{ trip_id: number }>("/api/trips", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  return data.trip_id;
}

export async function fetchTrip(tripId: number): Promise<Trip | null> {
  try {
    const data = await request<{ trip: Trip }>(`/api/trips/${tripId}`);
    return data.trip;
  } catch (err) {
    console.warn("[trips] 取行程失败：", err);
    return null;
  }
}

export async function deleteTrip(tripId: number): Promise<boolean> {
  try {
    await request(`/api/trips/${tripId}`, { method: "DELETE" });
    return true;
  } catch {
    return false;
  }
}

export async function addDay(tripId: number): Promise<number | null> {
  try {
    const data = await request<{ day_id: number }>(`/api/trips/${tripId}/days`, { method: "POST" });
    return data.day_id;
  } catch {
    return null;
  }
}

export async function addPlaceToDay(dayId: number, place: RealPlace): Promise<number | null> {
  try {
    const data = await request<{ place_id: number }>(`/api/trips/days/${dayId}/places`, {
      method: "POST",
      body: JSON.stringify(place),
    });
    return data.place_id;
  } catch (err) {
    console.warn("[trips] 加地点失败：", err);
    return null;
  }
}

/**
 * 修改一个已保存的地点。
 *
 * 字段与后端白名单一致（backend/trips.py 的 PLACE_FIELDS）。坐标在 T1-E2 加入：
 * 「重新定位」用它把修正后的经纬度写回，且**只发坐标** ——
 * 所以名称/日期/排序/时段/备注以及费用关联都不会被这类调用改动。
 *
 * 注意：失败时返回 false（不抛异常）。调用方必须据此显示失败提示，
 * 不能把它当成"已保存成功"。
 */
export async function updatePlace(
  placeId: number,
  fields: Partial<
    Pick<
      TripPlace,
      "start_time" | "duration_min" | "note" | "name" | "lat" | "lon" | "address"
    >
  >,
): Promise<boolean> {
  try {
    await request(`/api/trips/places/${placeId}`, {
      method: "PATCH",
      body: JSON.stringify(fields),
    });
    return true;
  } catch {
    return false;
  }
}

export async function deletePlace(placeId: number): Promise<boolean> {
  try {
    await request(`/api/trips/places/${placeId}`, { method: "DELETE" });
    return true;
  } catch {
    return false;
  }
}

/** 拖拽落地的后端：把地点移到另一天或同一天的新位置 */
export async function movePlace(
  placeId: number,
  toDayId: number,
  toIndex: number,
): Promise<boolean> {
  try {
    await request(`/api/trips/places/${placeId}/move`, {
      method: "POST",
      body: JSON.stringify({ to_day_id: toDayId, to_index: toIndex }),
    });
    return true;
  } catch (err) {
    console.warn("[trips] 移动地点失败：", err);
    return false;
  }
}

/** 地点照片：图选自 Tavily，后端已下载到本机并自托管（/api/images/…） */
export interface PlacePhoto {
  url: string;
  thumb_url: string;
  source_url: string;
  credit: string;
}

export async function fetchPlacePhotos(
  name: string,
  limit = 3,
  city = "",
): Promise<PlacePhoto[]> {
  if (!name.trim()) return [];
  try {
    const data = await request<{ photos?: PlacePhoto[] }>("/api/poi/photos", {
      method: "POST",
      body: JSON.stringify({ query: name, limit, city }),
    });
    return data.photos || [];
  } catch (err) {
    console.warn("[photos] 取地点照片失败：", err);
    return [];
  }
}

/* ==================== 候选图片池（九宫格选图）====================
 * 与 fetchPlacePhotos 的区别：那个是"给我几张图展示"，这个是为了**选图** ——
 * 带 total / has_more / next_offset，可以翻页拿后续候选，供"选中一张 → 下一张补位"。
 *
 * id 由后端按"源图 host+path"哈希生成，**跨分页、跨会话稳定**：
 * 前端用它去重、做 React key、判断"已选是否重复"，不依赖数组下标。
 * source 是真实来源标识（tavily / pixabay），前端不得改写。
 */
export interface PhotoCandidate extends PlacePhoto {
  id: string;
  source: string;
}

export interface PhotoPool {
  photos: PhotoCandidate[];
  /** 该地点候选总数（后端统计的真实数量，非估算） */
  total: number;
  has_more: boolean;
  next_offset: number | null;
  sources: string[];
}

/**
 * 取某地点的**候选图片池**（可分页）。
 *
 * 为什么要分页（实测依据，不是猜）：上游单次能给的数量有限
 * （Tavily 的 include_images 每次固定约 5 张，max_results 调到 12 也一样），
 * 所以"初始 9 张 + 补位"必须靠 offset 翻页拿后续真实候选，
 * 而不是把同一批图重复展示来凑数。
 *
 * 失败时**抛出**：选图界面必须能区分"没有更多候选"与"搜索失败"。
 */
export async function fetchPhotoPool(
  name: string,
  city = "",
  opts: { limit?: number; offset?: number } = {},
): Promise<PhotoPool> {
  const empty: PhotoPool = { photos: [], total: 0, has_more: false, next_offset: null, sources: [] };
  if (!name.trim()) return empty;
  const data = await request<Partial<PhotoPool>>("/api/poi/photos", {
    method: "POST",
    body: JSON.stringify({
      query: name,
      city,
      limit: opts.limit ?? 9,
      offset: opts.offset ?? 0,
    }),
  });
  return {
    photos: data.photos || [],
    total: data.total ?? (data.photos || []).length,
    has_more: Boolean(data.has_more),
    next_offset: data.next_offset ?? null,
    sources: data.sources || [],
  };
}

/** 公开攻略内容（合规：正规搜索 API 拿公开结果，不抓取小红书站内内容） */
export interface WebResult {
  title: string;
  url: string;
  snippet: string;
  source: string;
}

export interface WebImage {
  url: string;
  description: string;
}

export async function fetchWebSearch(
  query: string,
  limit = 8,
): Promise<{ results: WebResult[]; images: WebImage[] }> {
  if (!query.trim()) return { results: [], images: [] };
  try {
    const data = await request<{ results?: WebResult[]; images?: WebImage[] }>(
      "/api/web/search",
      { method: "POST", body: JSON.stringify({ query, limit }) },
    );
    return { results: data.results || [], images: data.images || [] };
  } catch (err) {
    console.warn("[websearch] 失败：", err);
    return { results: [], images: [] };
  }
}

/* ==================== 旅行预算 / 费用（T1-D1）====================
 * 金额口径（前后端一致，务必不要各自解释）：
 *   * amount_yuan 表示**该条费用的总金额**，不是人均金额。
 *     住宿/交通等由用户输入整项预计支出；每人/每间/每晚等模式留待后续版本。
 *   * 后端以整数「分」存储与计算，返回 *_cent 与 *_yuan 两套视图；
 *     **所有合计都由服务端算好**，前端只展示，绝不自己加总 ——
 *     这样"明细"和"合计"永远来自同一处，不会对不上。
 *   * status 三态：confirmed(已确认) / estimated(估算) / pending(待确认)。
 *     pending 不计入任何合计，只单独展示。
 */
export type CostCategory = "transport" | "stay" | "food" | "ticket" | "other";
export type CostStatus = "estimated" | "confirmed" | "pending";

export const COST_CATEGORY_LABELS: Record<CostCategory, string> = {
  transport: "交通",
  stay: "住宿",
  food: "餐饮",
  ticket: "景点门票",
  other: "其他",
};

export const COST_STATUS_LABELS: Record<CostStatus, string> = {
  estimated: "估算",
  confirmed: "已确认",
  pending: "待确认",
};

export interface TripCost {
  id: number;
  trip_id: number;
  category: CostCategory;
  category_label: string;
  title: string;
  /** 总金额（元） */
  amount_yuan: number;
  /** 总金额（分）—— 精确值，用于展示与校验 */
  amount_cent: number;
  status: CostStatus;
  status_label: string;
  note: string;
  day_id: number | null;
  place_id: number | null;
  created_at: string;
  updated_at: string;
}

export interface BudgetCategoryRow {
  category: CostCategory;
  label: string;
  confirmed_cent: number;
  estimated_cent: number;
  pending_cent: number;
  total_cent: number;
  count: number;
}

export interface BudgetSummary {
  trip_id: number;
  travelers: number;
  currency: string;
  amount_unit: string;
  budget_total_cent: number | null;
  budget_total_yuan: number | null;
  confirmed_cent: number;
  estimated_cent: number;
  pending_cent: number;
  spent_expected_cent: number;
  spent_all_cent: number;
  confirmed_yuan: number;
  estimated_yuan: number;
  pending_yuan: number;
  spent_expected_yuan: number;
  spent_all_yuan: number;
  per_person_cent: number;
  per_person_yuan: number;
  remaining_cent: number | null;
  remaining_yuan: number | null;
  over_budget: boolean | null;
  over_by_cent: number | null;
  over_by_yuan: number | null;
  cost_count: number;
  by_category: BudgetCategoryRow[];
}

export interface BudgetPayload {
  costs: TripCost[];
  budget: BudgetSummary;
}

/** 取一条行程的费用明细 + 预算汇总（一次请求拿全，前端不自行加总） */
export async function fetchTripBudget(tripId: number): Promise<BudgetPayload> {
  const data = await request<{ costs?: TripCost[]; budget: BudgetSummary }>(
    `/api/trips/${tripId}/budget`,
  );
  return { costs: data.costs || [], budget: data.budget };
}

/** 设置整趟旅行总预算（元）与人数。budgetYuan 传 null = 清空预算上限。 */
export async function setTripBudget(
  tripId: number,
  payload: { budget_total_yuan?: number | null; travelers?: number },
): Promise<BudgetSummary> {
  const data = await request<{ budget: BudgetSummary }>(`/api/trips/${tripId}/budget`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
  return data.budget;
}

/**
 * 新增一条费用。
 *
 * clientToken：幂等键。前端为"一次用户提交"生成一个（见 trip 页的 makeIdempotencyKey），
 * 双击或网络重试带着同一个 token 再发一次时，服务端只会返回同一条记录，不会重复计费。
 *
 * 注意：这里**不吞异常** —— 与其它接口不同，费用写入必须让调用方知道失败，
 * 否则界面会显示虚假的成功状态。
 */
export async function addTripCost(
  tripId: number,
  payload: {
    category: CostCategory;
    title: string;
    amount_yuan: number;
    status: CostStatus;
    note?: string;
    day_id?: number | null;
    place_id?: number | null;
    client_token?: string;
  },
): Promise<{ cost_id: number; budget: BudgetSummary }> {
  const data = await request<{ cost_id: number; budget: BudgetSummary }>(
    `/api/trips/${tripId}/costs`,
    { method: "POST", body: JSON.stringify(payload) },
  );
  return { cost_id: data.cost_id, budget: data.budget };
}

/** 编辑一条费用（只传要改的字段）。同样不吞异常。 */
export async function updateTripCost(
  costId: number,
  payload: Partial<{
    category: CostCategory;
    title: string;
    amount_yuan: number;
    status: CostStatus;
    note: string;
  }>,
): Promise<void> {
  await request(`/api/trips/costs/${costId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

/** 删除一条费用。同样不吞异常。 */
export async function deleteTripCost(costId: number): Promise<void> {
  await request(`/api/trips/costs/${costId}`, { method: "DELETE" });
}

/* ==================== 真实道路路线（T1-F1）====================
 * 关键约定：
 *   * `distance_m` 单位**米**，`duration_s` 单位**秒** —— 都是上游给出的真实值，
 *     前端只做展示与求和格式化，绝不自行估算或补齐。
 *   * `geometry` 是 `[lat, lon]` 数组（后端已把 OSRM 的 [lon,lat] 归一化），
 *     可直接喂给 Leaflet。
 *   * 只有 `status === "ok"` 的段才带 geometry/距离/耗时。**失败或缺失的段
 *     必须当失败处理**，不能用直线顶替（那会把顺序连线包装成真实路线）。
 */
export type RouteMode = "driving" | "walking" | "cycling";

export type RouteStatus =
  | "ok"
  | "partial"
  | "not_configured"
  | "unavailable"
  | "no_route"
  | "mode_unsupported"
  | "incomplete"
  | "invalid_coords";

export interface RouteLeg {
  from_place_id: number | null;
  from_name: string;
  to_place_id: number | null;
  to_name: string;
  status: RouteStatus;
  detail?: string;
  distance_m?: number;
  duration_s?: number;
  /** [lat, lon] 序列；仅 status==="ok" 时存在 */
  geometry?: [number, number][];
  source?: string;
  provider?: string;
  mode?: RouteMode;
  elapsed_ms?: number;
}

export interface RouteSkippedPlace {
  place_id: number | null;
  name: string;
  /** 目前只有 invalid_coords：缺少可靠经纬度，无法参与路线计算 */
  reason: string;
  detail?: string;
}

export interface RouteProviderInfo {
  provider: string | null;
  amap_configured: boolean;
  osrm_base_url: string;
  osrm_modes: string[];
  supported_modes: string[];
  requires_env: string[];
  note: string;
}

export interface DayRoute {
  status: RouteStatus;
  message: string;
  provider: string | null;
  provider_info: RouteProviderInfo;
  mode: RouteMode;
  /** 参与计算的地点（**按用户编排顺序**），便于核对顺序是否一致 */
  ordered_place_ids: (number | null)[];
  skipped: RouteSkippedPlace[];
  legs: RouteLeg[];
  total_distance_m: number | null;
  total_duration_s: number | null;
  legs_ok: number;
  legs_total: number;
}

export interface DayRouteResponse {
  trip_id: number;
  day_index: number;
  day_id: number;
  date: string;
  place_count: number;
  route: DayRoute;
}

/**
 * 取某一天的真实道路路线。
 *
 * 注意：路线服务未配置 / 上游失败 / 没有路线等**降级状态仍返回 HTTP 200**，
 * 由 `route.status` 表达；只有鉴权失败(404)或参数非法(422)才会抛异常。
 * 所以调用方既要 catch，也要检查 `status`。
 */
export async function fetchDayRoute(
  tripId: number,
  dayIndex: number,
  mode: RouteMode = "driving",
): Promise<DayRouteResponse> {
  return await request<DayRouteResponse>(
    `/api/trips/${tripId}/route?day_index=${dayIndex}&mode=${mode}`,
  );
}

export { sanitize };
