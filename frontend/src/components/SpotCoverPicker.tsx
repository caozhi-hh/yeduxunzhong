"use client";

/**
 * 第 5 步「景点选择」——封面卡片式待选区 + 已选区
 *
 * 交互（按产品要求）：
 *   · **一个景点只展示一张封面**（封面来自已有的 /api/spot-images，不再为每个景点铺九张机位图）
 *   · **待选区固定 4 个不同景点**；选中一个立即移出，下一个未选景点自动补位
 *   · 下方单独展示已选景点（封面 + 名称 + 取消）；取消后该景点回到待选区
 *   · 保留 AI 返回的景点顺序：待选区始终取"按 AI 顺序的前 4 个未选景点"
 *
 * 补位同样是**派生值**，不是手写数组搬移：
 *      待选 = spots.filter(s => !selected.has(s.name)).slice(0, 4)
 * 这样"选中→移出→下一个补位"和"取消→回到待选区"都自动成立，也不会重复。
 *
 * 图片加载策略（按产品要求）：
 *   · **只为当前可见的 4 个 + 后续预取的 2 个**请求封面（共 6 个），不对全部景点批量拉图
 *   · 复用已有接口 /api/spot-images 与后端磁盘缓存，不新建数据链路
 *   · 后端 Pixabay 分支返回的是**站内相对路径**（/api/images/…），
 *     必须经 resolveApiUrl 补 API 基址，否则会打到前端 origin 上 404
 *   · 失败/无图 → 明确占位 + 「重试」，不做无限转圈、不出现破图
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { Check, ImageOff, Loader2, RotateCcw, Search, Star, Ticket, X } from "lucide-react";

import { fetchSpotImages, resolveApiUrl } from "@/lib/api";

/** 待选区固定展示的景点数 */
const SLOT_COUNT = 4;
/** 额外预取的景点数（用户点选后能更快补位） */
const PRELOAD = 2;

/** 一个景点的封面（原样保存后端返回值，渲染时才解析成可访问地址） */
export interface SpotCover {
  name: string;
  image_url: string;
  thumb_url: string;
  large_url: string;
  source: string;
  source_url: string;
  author: string;
  author_url: string;
  note?: string;
}

export interface CoverZoomInfo {
  src: string;
  name: string;
  source?: string;
  source_url?: string;
  author?: string;
  author_url?: string;
}

export interface PickerSpot {
  name: string;
  selected: boolean;
  rating?: string;
  duration?: string;
  ticket?: string;
  desc?: string;
}

interface Props {
  /** AI 返回的景点列表（顺序即 AI 顺序，必须保留） */
  spots: PickerSpot[];
  /** 已选景点名（按 AI 顺序） */
  selectedNames: string[];
  city: string;
  /** 已取到的封面（父级持有，用于持久化与 /plan 复用） */
  covers: Record<string, SpotCover>;
  onCoverLoaded: (cover: SpotCover) => void;
  onToggle: (name: string) => void;
  onZoom: (info: CoverZoomInfo) => void;
}

type LoadState = "idle" | "loading" | "failed";

export default function SpotCoverPicker({
  spots,
  selectedNames,
  city,
  covers,
  onCoverLoaded,
  onToggle,
  onZoom,
}: Props) {
  const [states, setStates] = useState<Record<string, LoadState>>({});
  const [brokenIds, setBrokenIds] = useState<Set<string>>(new Set());
  const [retryTick, setRetryTick] = useState(0);

  // 并发与卸载保护：同一个景点不重复请求；卸载后不再 setState
  const inFlightRef = useRef<Set<string>>(new Set());
  const requestedRef = useRef<Set<string>>(new Set());
  const aliveRef = useRef(true);
  useEffect(() => {
    aliveRef.current = true;
    return () => {
      aliveRef.current = false;
    };
  }, []);

  const selected = useMemo(() => new Set(selectedNames), [selectedNames]);

  /** 待选 = AI 顺序里前 4 个未选景点（派生值 → 补位与回退都自动成立） */
  const candidates = useMemo(
    () => spots.filter((s) => !selected.has(s.name)).slice(0, SLOT_COUNT),
    [spots, selected],
  );
  /** 预取 = 紧随其后的 2 个未选景点 */
  const preloadNames = useMemo(
    () =>
      spots
        .filter((s) => !selected.has(s.name))
        .slice(SLOT_COUNT, SLOT_COUNT + PRELOAD)
        .map((s) => s.name),
    [spots, selected],
  );

  const loadCovers = useCallback(
    async (names: string[]) => {
      const need = names.filter(
        (n) => n && !covers[n] && !inFlightRef.current.has(n) && states[n] !== "failed",
      );
      if (!need.length) return;
      need.forEach((n) => inFlightRef.current.add(n));
      setStates((prev) => {
        const next = { ...prev };
        need.forEach((n) => {
          next[n] = "loading";
        });
        return next;
      });
      try {
        // 20s 兜底超时：request() 的 fetch 没有超时，后端挂住时"加载中"会永久转圈。
        // 超时后走 catch → 标记 failed → 显示占位 + 「重试」，界面不会卡死。
        const records = await Promise.race([
          fetchSpotImages(city, need),
          new Promise<never>((_, reject) =>
            setTimeout(() => reject(new Error("封面请求超时")), 20000),
          ),
        ]);
        if (!aliveRef.current) return;
        const byName = new Map(records.map((r) => [r.name, r]));
        setStates((prev) => {
          const next = { ...prev };
          need.forEach((n) => {
            const r = byName.get(n);
            // 有可用图才算成功；后端返回空图（配额用尽/未匹配）视为"暂无封面"，
            // 不是失败 —— 但仍允许用户重试（配额可能已恢复）。
            next[n] = r && (r.image_url || r.thumb_url) ? "idle" : "failed";
          });
          return next;
        });
        records.forEach((r) => {
          if (r.image_url || r.thumb_url) {
            onCoverLoaded({
              name: r.name,
              image_url: r.image_url || "",
              thumb_url: r.thumb_url || "",
              large_url: r.large_url || "",
              source: r.source || "",
              source_url: r.source_url || "",
              author: r.author || "",
              author_url: r.author_url || "",
              note: r.note,
            });
          }
        });
      } catch (err) {
        if (!aliveRef.current) return;
        console.warn("[covers] 取封面失败：", err);
        setStates((prev) => {
          const next = { ...prev };
          need.forEach((n) => {
            next[n] = "failed";
          });
          return next;
        });
      } finally {
        need.forEach((n) => inFlightRef.current.delete(n));
      }
    },
    [city, covers, states, onCoverLoaded],
  );

  // 只请求"当前可见 4 张 + 预取 2 张"
  useEffect(() => {
    const wanted = [...candidates.map((s) => s.name), ...preloadNames];
    const fresh = wanted.filter((n) => !covers[n] && states[n] !== "failed");
    if (!fresh.length) return;
    void loadCovers(fresh);
  }, [candidates, preloadNames, covers, states, loadCovers]);

  /** 失败/进行中的状态优先于"已有封面对象"：
   *  ⚠️ 不能写成"有 cover 就当 idle" —— 那样图 404 时 onError 写入的 failed 会被盖掉，
   *  界面会一直重渲染破图 img，占位与「重试」永远不出现（浏览器用例抓到过这个 bug）。 */
  const statusOf = (name: string): LoadState => states[name] || "idle";

  const retry = (name: string) => {
    requestedRef.current.delete(name);
    setStates((prev) => ({ ...prev, [name]: "idle" }));
    setBrokenIds((prev) => {
      const next = new Set(prev);
      next.delete(name);
      return next;
    });
    setRetryTick((t) => t + 1);
    void loadCovers([name]);
  };

  return (
    <div data-testid="spot-cover-picker">
      {/* ── 待选区：固定 4 个不同景点 ── */}
      <div className="flex items-center gap-2 mb-3 flex-wrap">
        <h3 className="text-sm font-bold text-brand-700">待选景点</h3>
        <span className="text-[11px] text-ink-400" data-testid="candidate-count">
          待选 {candidates.length} 个 · 已选 {selectedNames.length} 个 · 共找到 {spots.length} 个
        </span>
      </div>

      {spots.length > 0 && candidates.length === 0 && (
        <p className="text-[12px] text-ink-500 mb-4" data-testid="all-picked">
          所有景点都已选完（共 {spots.length} 个）。可在下方取消选择后再选。
        </p>
      )}

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-6" data-testid="candidate-grid">
        <AnimatePresence mode="popLayout" initial={false}>
          {candidates.map((spot) => {
            const cover = covers[spot.name];
            const st = statusOf(spot.name);
            const hasUrl = Boolean(cover && (cover.thumb_url || cover.image_url));
            const imgSrc = hasUrl ? resolveApiUrl(cover!.thumb_url || cover!.image_url) : "";
            const isBroken = brokenIds.has(spot.name);
            /** 只有"有地址 + 没被判失败"才渲染 <img>，否则一律占位（绝不露破图） */
            const showImg = hasUrl && st !== "failed" && !isBroken;
            return (
              <motion.div
                key={spot.name}
                layout
                initial={{ opacity: 0, scale: 0.94 }}
                animate={{ opacity: 1, scale: 1 }}
                exit={{ opacity: 0, scale: 0.94 }}
                transition={{ duration: 0.18, ease: "easeOut" }}
                data-testid="candidate-card"
                data-name={spot.name}
                className="rounded-xl overflow-hidden border-2 border-line bg-surface flex flex-col"
              >
                {/* 封面：一个景点只有这一张 */}
                <div className="relative aspect-[4/3] bg-paper-2">
                  {showImg ? (
                    <button
                      type="button"
                      onClick={() =>
                        onZoom({
                          src: resolveApiUrl(cover!.large_url || cover!.image_url || cover!.thumb_url),
                          name: spot.name,
                          source: cover!.source,
                          source_url: cover!.source_url,
                          author: cover!.author,
                          author_url: cover!.author_url,
                        })
                      }
                      title="点击看大图"
                      data-testid="zoom-btn"
                      className="block w-full h-full cursor-zoom-in group focus:outline-none focus:ring-2 focus:ring-blue-400"
                    >
                      {/* eslint-disable-next-line @next/next/no-img-element */}
                      <img
                        key={`${spot.name}-${retryTick}`}
                        src={imgSrc}
                        alt={spot.name}
                        loading="lazy"
                        decoding="async"
                        onError={() =>
                          setStates((prev) => ({ ...prev, [spot.name]: "failed" }))
                        }
                        className="w-full h-full object-cover transition-transform duration-300 group-hover:scale-105"
                      />
                      <span className="absolute bottom-1 left-1 text-[9px] px-1 rounded bg-black/45 text-white inline-flex items-center gap-0.5">
                        <Search className="w-2.5 h-2.5" strokeWidth={2} /> 看大图
                      </span>
                    </button>
                  ) : st === "loading" ? (
                    <div className="w-full h-full flex flex-col items-center justify-center gap-1 text-ink-400">
                      <Loader2 className="w-5 h-5 animate-spin" strokeWidth={1.8} />
                      <span className="text-[10px]">封面加载中…</span>
                    </div>
                  ) : (
                    <div className="w-full h-full flex flex-col items-center justify-center gap-1 text-ink-400 px-2 text-center">
                      <ImageOff className="w-6 h-6" strokeWidth={1.4} />
                      <span className="text-[10px]" data-testid="cover-placeholder">
                        {cover?.note || "暂无封面"}
                      </span>
                      <button
                        type="button"
                        onClick={() => retry(spot.name)}
                        data-testid="cover-retry"
                        className="text-[10px] px-1.5 py-0.5 rounded border border-line hover:bg-paper-2 inline-flex items-center gap-0.5"
                      >
                        <RotateCcw className="w-3 h-3" strokeWidth={2} /> 重试
                      </button>
                    </div>
                  )}

                  {/* 选择按钮（显式控件；点封面主体是看大图，不会误选） */}
                  <button
                    type="button"
                    onClick={() => onToggle(spot.name)}
                    aria-label={`选择景点 ${spot.name}`}
                    title="选择这个景点"
                    data-testid="select-btn"
                    className="absolute top-1 right-1 w-6 h-6 rounded-full border-2 border-white bg-black/35 hover:bg-brand-700 flex items-center justify-center transition-colors"
                  >
                    <Check className="w-3.5 h-3.5 text-white opacity-0 hover:opacity-100 transition-opacity" strokeWidth={3} />
                  </button>
                </div>

                {/* 名称与元信息：保留原有展示 */}
                <div className="p-2 flex-1 flex flex-col">
                  <div className="flex items-center gap-1 flex-wrap">
                    <span className="font-bold text-ink-900 text-[13px]" data-testid="candidate-name">
                      {spot.name}
                    </span>
                    {spot.rating && (
                      <span className="text-[10px] text-amber-500 bg-amber-50 px-1 rounded">
                        <Star className="w-2.5 h-2.5 inline -mt-px" strokeWidth={1.8} /> {spot.rating}
                      </span>
                    )}
                  </div>
                  <div className="flex items-center gap-1 flex-wrap mt-0.5">
                    {spot.duration && (
                      <span className="text-[10px] text-brand-600 bg-brand-50 px-1 rounded">⏱ {spot.duration}</span>
                    )}
                    {spot.ticket && (
                      <span className="text-[10px] text-green-600 bg-green-50 px-1 rounded">
                        <Ticket className="w-2.5 h-2.5 inline -mt-px" strokeWidth={1.8} /> {spot.ticket}
                      </span>
                    )}
                  </div>
                  <button
                    type="button"
                    onClick={() => onToggle(spot.name)}
                    data-testid="pick-btn"
                    className="mt-2 w-full text-[11px] py-1 rounded-lg bg-gradient-to-r from-brand-700 to-brand-600 hover:from-brand-600 hover:to-brand-500 text-white font-medium transition-colors"
                  >
                    选择
                  </button>
                  {/* 图源署名：Unsplash 条款要求展示图片时必须一起给出，保留原有行为 */}
                  {cover?.source && (
                    <p className="text-[9px] text-ink-400 mt-1 truncate">
                      图源：
                      <a
                        href={cover.source_url || "#"}
                        target="_blank"
                        rel="noreferrer"
                        className="underline hover:text-ink-600"
                      >
                        {cover.source === "unsplash" ? "Unsplash" : cover.source}
                      </a>
                      {cover.author && <> · {cover.author}</>}
                    </p>
                  )}
                </div>
              </motion.div>
            );
          })}
        </AnimatePresence>
      </div>

      {/* ── 已选区：封面 + 名称 + 取消 ── */}
      <div className="rounded-2xl border border-line bg-surface p-3 mb-6" data-testid="selected-area">
        <div className="flex items-center gap-2 mb-2 flex-wrap">
          <span className="text-[12px] font-bold text-ink-700" data-testid="selected-count">
            已选景点 <span className="text-brand-700">{selectedNames.length}</span> 个
          </span>
          <span className="text-[11px] text-ink-400">取消后会重新回到待选区</span>
        </div>
        {selectedNames.length === 0 ? (
          <p className="text-[11px] text-ink-400">还没选景点。点待选区卡片上的「选择」即可。</p>
        ) : (
          <ul className="flex flex-wrap gap-2">
            <AnimatePresence initial={false}>
              {selectedNames.map((name) => {
                const cover = covers[name];
                const src = cover ? resolveApiUrl(cover.thumb_url || cover.image_url) : "";
                return (
                  <motion.li
                    key={name}
                    layout
                    initial={{ opacity: 0, scale: 0.92 }}
                    animate={{ opacity: 1, scale: 1 }}
                    exit={{ opacity: 0, scale: 0.92 }}
                    transition={{ duration: 0.15 }}
                    data-testid="selected-item"
                    data-name={name}
                    className="relative w-[104px] rounded-lg overflow-hidden border-2 border-brand-400 bg-surface"
                  >
                    {src && !brokenIds.has(name) ? (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img
                        src={src}
                        alt={name}
                        className="w-full aspect-[4/3] object-cover"
                        onError={() =>
                          setBrokenIds((prev) => {
                            const next = new Set(prev);
                            next.add(name);
                            return next;
                          })
                        }
                      />
                    ) : (
                      <div className="w-full aspect-[4/3] flex items-center justify-center bg-paper-2 text-ink-300">
                        <ImageOff className="w-5 h-5" strokeWidth={1.4} />
                      </div>
                    )}
                    <div className="px-1 py-0.5 text-[10px] text-ink-700 truncate" title={name}>
                      {name}
                    </div>
                    <span className="absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-brand-700 flex items-center justify-center">
                      <Check className="w-2.5 h-2.5 text-white" strokeWidth={3} />
                    </span>
                    <button
                      type="button"
                      onClick={() => onToggle(name)}
                      aria-label={`取消选择 ${name}`}
                      title="取消选择"
                      data-testid="deselect-btn"
                      className="absolute top-0.5 right-0.5 w-4 h-4 rounded-full bg-black/50 hover:bg-red-600 flex items-center justify-center"
                    >
                      <X className="w-2.5 h-2.5 text-white" strokeWidth={3} />
                    </button>
                  </motion.li>
                );
              })}
            </AnimatePresence>
          </ul>
        )}
      </div>
    </div>
  );
}