"use client";

/**
 * 九宫格景点选图（SpotImagePicker）
 *
 * 目标交互：**始终优先展示 9 张未选中的候选图片；每选中一张，立即从候选池取
 * 下一张未展示、未选择的图片补入空出的位置。**
 *
 * ── 核心实现思路（为什么这样写）────────────────────────────────────
 * 补位**不是靠手动的"插入/搬移数组"**，而是让"可见的 9 张"成为候选池的一个**派生值**：
 *
 *     可见 = 候选池里"未被选中"的前 9 张
 *     可见 = pool.filter(c => !chosen.has(c.id)).slice(0, 9)
 *
 * 这样一次性消除了三类最容易出的 bug：
 *   · 选中后忘记补位 / 补位错位  → 派生值自动前移，下一位自然补上
 *   · 取消选择造成重复或丢失     → 取消后该图回到它在池中的原位，不需要"塞回数组"
 *   · 并发点击导致重复图         → 池与选中集合都是按稳定 id 的集合语义，天然去重
 *
 * ── 按景点隔离 ───────────────────────────────────────────────────
 * 组件以 `spotName` 为 key 挂载（见调用方），内部状态只服务当前景点；
 * 候选池缓存也按 `city|spotName` 分开，绝不跨景点混用。
 *
 * ── 图片来源 ─────────────────────────────────────────────────────
 * 全部来自后端 `/api/poi/photos`（Tavily 图搜 + Pixabay 兜底，下载后自托管）。
 * **不伪造任何图片、来源或数量**：拿不到就显示"没有更多候选"。
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { Check, ImageOff, Loader2, RotateCcw, Search, Trash2, X } from "lucide-react";

import { fetchPhotoPool, resolveApiUrl, type PhotoCandidate } from "@/lib/api";

const SLOT_COUNT = 9;      // 九宫格：同时最多展示 9 张
const PAGE_SIZE = 9;       // 每页向后端要 9 张
const PRELOAD = 3;         // 池里还剩不到 9+PRELOAD 张时就继续预取，保证补位不卡顿

export interface ZoomInfo {
  src: string;
  name: string;
  source?: string;
  source_url?: string;
  credit?: string;
}

interface Props {
  /** 景点名（必填）：候选池与已选状态都按它隔离 */
  spotName: string;
  city?: string;
  /** 已选（受控，来自父级，保证与最终攻略一致） */
  selectedIds: string[];
  /** 已选图片对象（父级持有，用于在候选区外展示缩略图与持久化） */
  selectedPhotos: PhotoCandidate[];
  onChange: (nextIds: string[], nextPhotos: PhotoCandidate[]) => void;
  onZoom: (info: ZoomInfo) => void;
  onClose?: () => void;
}

export default function SpotImagePicker({
  spotName,
  city = "",
  selectedIds,
  selectedPhotos,
  onChange,
  onZoom,
  onClose,
}: Props) {
  const [pool, setPool] = useState<PhotoCandidate[]>([]);
  // loading 初值就是 true：首次取数在挂载 effect 里发起，
  // 这样 effect 内不需要"同步 setLoading(true)"（那会触发级联渲染，本仓库规则会报错）
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const [nextOffset, setNextOffset] = useState<number | null>(null);
  const [sources, setSources] = useState<string[]>([]);
  const [total, setTotal] = useState(0);
  const [broken, setBroken] = useState<Set<string>>(new Set());   // 图片加载失败
  const [retryTick, setRetryTick] = useState(0);                  // 重试：换 key 强制重载

  // 并发与卸载保护：避免重复请求、并发补位重复图、卸载后 setState
  const inFlightRef = useRef(false);
  const aliveRef = useRef(true);
  const poolIdsRef = useRef<Set<string>>(new Set());
  /** 已经为哪个 offset 发过请求：防止同一个 offset 被重复请求（重复补位/重复图） */
  const requestedOffsetRef = useRef<number | null>(null);

  useEffect(() => {
    aliveRef.current = true;
    return () => {
      aliveRef.current = false;
    };
  }, []);

  const chosen = useMemo(() => new Set(selectedIds), [selectedIds]);

  /** 可见的 9 张 = 候选池里未选中的前 9 张（**派生值，不是手动维护的数组**） */
  const visible = useMemo(
    () => pool.filter((c) => !chosen.has(c.id)).slice(0, SLOT_COUNT),
    [pool, chosen],
  );

  const appendUnique = useCallback((incoming: PhotoCandidate[]) => {
    // 以稳定 id 去重后再入池，保证"同一张图不会出现两次"
    const fresh = incoming.filter((c) => c.id && !poolIdsRef.current.has(c.id));
    if (!fresh.length) return 0;
    fresh.forEach((c) => poolIdsRef.current.add(c.id));
    setPool((prev) => [...prev, ...fresh]);
    return fresh.length;
  }, []);

  const loadPage = useCallback(
    async (offset: number, initial: boolean) => {
      if (inFlightRef.current) return;      // 并发保护：同一时刻只允许一个取数请求
      inFlightRef.current = true;
      requestedOffsetRef.current = offset;
      void initial;   // initial 只用于调用方语义；loading 初值/重试按钮已负责"加载中"状态
      try {
        const res = await fetchPhotoPool(spotName, city, { limit: PAGE_SIZE, offset });
        if (!aliveRef.current) return;
        appendUnique(res.photos);
        setHasMore(res.has_more);
        setNextOffset(res.next_offset);
        setTotal(res.total);
        setSources(res.sources);
        setError(null);
      } catch (err) {
        if (!aliveRef.current) return;
        // 区分"没有更多候选"与"搜索失败"：失败必须让用户看到并可以重试
        setError(err instanceof Error ? err.message : "候选图片获取失败");
        setHasMore(false);
      } finally {
        inFlightRef.current = false;
        if (aliveRef.current) setLoading(false);
      }
    },
    [spotName, city, appendUnique],
  );

  /** 重试：事件处理器里可以安全地同步 setState（不在 effect 内） */
  const retry = useCallback(() => {
    setLoading(true);
    setError(null);
    requestedOffsetRef.current = null;
    void loadPage(0, true);
  }, [loadPage]);

  // 首次加载。
  // 注意：这里**不做**任何"重置状态"的同步 setState ——
  // 调用方用 key={spot|city} 让本组件在切换景点时整体重挂载，
  // 池与已选状态天然是干净的，不需要 effect 里手动清空。
  useEffect(() => {
    // loadPage 内部**所有** setState 都发生在 `await fetchPhotoPool(...)` 之后（真异步），
    // 不存在"effect 内同步 setState → 级联渲染"的问题。
    // 规则做的是跨函数静态分析，无法证明这一 await 边界，故就地说明后抑制。
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void loadPage(0, true);
  }, [loadPage]);

  // 预取：可见不足 9 张（或余量太少）且还有更多时，继续取下一页。
  // 用 requestedOffsetRef 做去重，避免同一个 offset 被反复请求（那会产生重复图与重复请求）。
  useEffect(() => {
    if (loading || !hasMore || nextOffset === null) return;
    const unselected = pool.length - chosen.size;
    if (unselected >= SLOT_COUNT + PRELOAD) return;
    if (requestedOffsetRef.current === nextOffset) return;
    void loadPage(nextOffset, false);
  }, [pool.length, chosen.size, hasMore, nextOffset, loading, loadPage]);

  /** 是否正在等待后续候选（**派生值**，不需要在 effect 里 setState） */
  const loadingMore = !loading && hasMore && pool.length - chosen.size < SLOT_COUNT + PRELOAD;

  const toggle = useCallback(
    (c: PhotoCandidate) => {
      const isChosen = chosen.has(c.id);
      if (isChosen) {
        // 取消选择：只从已选集合里去掉；可见区是派生值，该图会自动回到原位
        const ids = selectedIds.filter((id) => id !== c.id);
        onChange(ids, selectedPhotos.filter((p) => p.id !== c.id));
      } else {
        // 选中：加入已选集合；可见区自动让出位置、由池中下一张补上
        const ids = [...selectedIds, c.id];
        const photos = selectedPhotos.some((p) => p.id === c.id)
          ? selectedPhotos
          : [...selectedPhotos, c];
        onChange(ids, photos);
      }
    },
    [chosen, selectedIds, selectedPhotos, onChange],
  );

  const removeCandidate = useCallback((c: PhotoCandidate) => {
    // "移除"：把这张坏图从候选池里丢掉，且不影响已选集合
    poolIdsRef.current.delete(c.id);
    setPool((prev) => prev.filter((x) => x.id !== c.id));
  }, []);

  const exhausted = !loading && !hasMore && visible.length === 0;
  const nothingAtAll = !loading && !error && pool.length === 0;
  /** 还在等后续候选（补位中）：用于把空格补成骨架，保持 3×3 布局不塌陷 */
  const awaitingMore = (loadingMore || hasMore) && !loading;
  const skeletonCount = awaitingMore ? Math.max(0, SLOT_COUNT - visible.length) : 0;

  return (
    <section className="rounded-2xl border-2 border-brand-200 bg-brand-50/40 p-4" data-testid="spot-picker" data-spot={spotName}>
      {/* 标题栏：明确当前是哪个景点的候选（按景点隔离的可见证据） */}
      <div className="flex items-center gap-2 mb-3 flex-wrap">
        <h4 className="text-sm font-bold text-brand-700">
          「{spotName}」候选图片
        </h4>
        <span className="text-[11px] text-ink-500">
          已选 <strong className="text-brand-700">{selectedIds.length}</strong> 张
          {total > 0 && <> · 候选池 {total} 张</>}
          {sources.length > 0 && <> · 来源 {sources.join(" / ")}</>}
        </span>
        {loadingMore && (
          <span className="text-[11px] text-ink-400 inline-flex items-center gap-1">
            <Loader2 className="w-3 h-3 animate-spin" strokeWidth={2} /> 正在准备后续候选…
          </span>
        )}
        {onClose && (
          <button
            type="button"
            onClick={onClose}
            className="ml-auto text-xs text-ink-400 hover:text-ink-700 inline-flex items-center gap-1"
          >
            <X className="w-3.5 h-3.5" strokeWidth={2} /> 收起
          </button>
        )}
      </div>

      {/* 状态区：加载中 / 搜索失败（可重试）/ 池为空 / 候选耗尽 —— 各不相同 */}
      {loading && (
        <div className="grid grid-cols-3 gap-2 mb-3">
          {Array.from({ length: SLOT_COUNT }).map((_, i) => (
            <div key={i} className="aspect-[4/3] rounded-xl bg-paper-2 animate-pulse" />
          ))}
        </div>
      )}

      {error && (
        <div className="mb-3 rounded-xl border border-amber-300 bg-amber-50 px-3 py-2 text-[12px] text-amber-800 flex items-center gap-2 flex-wrap">
          <span>候选图片获取失败：{error}</span>
          <button
            type="button"
            onClick={retry}
            className="px-2 py-0.5 rounded-md border border-amber-400 hover:bg-amber-100 font-medium"
          >
            重试
          </button>
        </div>
      )}

      {nothingAtAll && !error && (
        <p className="text-[12px] text-ink-500 mb-3">
          这个景点暂时没有可用的候选图片（来源没有返回可用图片，未做任何伪造）。
        </p>
      )}

      {/* ── 九宫格候选区（三列，最多 9 张）── */}
      {!loading && visible.length > 0 && (
        <div className="grid grid-cols-3 gap-2 mb-3" data-testid="candidate-grid">
          <AnimatePresence mode="popLayout" initial={false}>
            {visible.map((c) => {
              const isBroken = broken.has(c.id);
              return (
                <motion.div
                  key={c.id}
                  layout
                  initial={{ opacity: 0, scale: 0.92 }}
                  animate={{ opacity: 1, scale: 1 }}
                  exit={{ opacity: 0, scale: 0.92 }}
                  transition={{ duration: 0.18, ease: "easeOut" }}
                  className="relative group rounded-xl overflow-hidden border-2 border-line bg-paper-2"
                  data-testid="candidate-card"
                  data-id={c.id}
                >
                  {/* 图片主体：点击看大图（**不触发选择**，故用独立按钮 + stopPropagation） */}
                  {isBroken ? (
                    <div className="aspect-[4/3] flex flex-col items-center justify-center gap-1 text-ink-400">
                      <ImageOff className="w-5 h-5" strokeWidth={1.5} />
                      <span className="text-[10px]">图片加载失败</span>
                      <div className="flex gap-1">
                        <button
                          type="button"
                          onClick={() => {
                            setBroken((s) => {
                              const n = new Set(s);
                              n.delete(c.id);
                              return n;
                            });
                            setRetryTick((t) => t + 1);
                          }}
                          className="text-[10px] px-1.5 py-0.5 rounded border border-line hover:bg-surface inline-flex items-center gap-0.5"
                        >
                          <RotateCcw className="w-3 h-3" strokeWidth={2} /> 重试
                        </button>
                        <button
                          type="button"
                          onClick={() => removeCandidate(c)}
                          className="text-[10px] px-1.5 py-0.5 rounded border border-line hover:bg-surface inline-flex items-center gap-0.5"
                        >
                          <Trash2 className="w-3 h-3" strokeWidth={2} /> 移除
                        </button>
                      </div>
                    </div>
                  ) : (
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        onZoom({
                          src: resolveApiUrl(c.url),
                          name: spotName,
                          source: c.source,
                          source_url: c.source_url,
                          credit: c.credit,
                        });
                      }}
                      title="点击看大图"
                      className="block w-full cursor-zoom-in focus:outline-none focus:ring-2 focus:ring-blue-400"
                      data-testid="zoom-btn"
                    >
                      {/* 外部图源自托管路径：用原生 img，最小改动 */}
                      {/* eslint-disable-next-line @next/next/no-img-element */}
                      <img
                        key={`${c.id}-${retryTick}`}
                        src={resolveApiUrl(c.thumb_url || c.url)}
                        alt={`${spotName} 候选图`}
                        loading="lazy"
                        decoding="async"
                        onError={() =>
                          setBroken((s) => {
                            const n = new Set(s);
                            n.add(c.id);
                            return n;
                          })
                        }
                        className="w-full aspect-[4/3] object-cover transition-transform duration-300 group-hover:scale-[1.04]"
                      />
                      <span className="absolute bottom-1 left-1 text-[9px] px-1 rounded bg-black/45 text-white inline-flex items-center gap-0.5">
                        <Search className="w-2.5 h-2.5" strokeWidth={2} /> 看大图
                      </span>
                    </button>
                  )}

                  {/* 选中控件：独立的显式按钮（不依赖点击图片主体） */}
                  {!isBroken && (
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        toggle(c);
                      }}
                      aria-label={`选择 ${spotName} 的这张图`}
                      title="选中这张图"
                      data-testid="select-btn"
                      className="absolute top-1 right-1 w-6 h-6 rounded-full border-2 border-white bg-black/35 hover:bg-brand-700 flex items-center justify-center transition-colors"
                    >
                      <Check className="w-3.5 h-3.5 text-white opacity-0 group-hover:opacity-90 transition-opacity" strokeWidth={3} />
                    </button>
                  )}
                </motion.div>
              );
            })}
          </AnimatePresence>

          {/* 补位等待中的占位格：让"选中 → 下一张补入"期间九宫格不塌陷、不整组闪烁。
              只有"确实还有后续候选"时才补骨架 —— 候选真耗尽时不制造假格子。 */}
          {Array.from({ length: skeletonCount }).map((_, i) => (
            <div
              key={`sk-${i}`}
              data-testid="candidate-skeleton"
              className="aspect-[4/3] rounded-xl bg-paper-2 animate-pulse border-2 border-dashed border-line"
            />
          ))}
        </div>
      )}

      {/* 候选耗尽：明确说明，不造假图 */}
      {exhausted && !error && pool.length > 0 && (
        <p className="text-[12px] text-ink-500 mb-3">
          候选图片已全部选完（共 {pool.length} 张）——没有更多可用候选了。
        </p>
      )}

      {!loading && !hasMore && !error && visible.length > 0 && visible.length < SLOT_COUNT && (
        <p className="text-[12px] text-ink-400 mb-3">
          只剩 {visible.length} 张未选候选（来源就只有这些，未补造图片）。
        </p>
      )}

      {/* ── 已选区（候选区之外）：数量 + 缩略图 + 可取消 ── */}
      <div className="rounded-xl border border-line bg-surface p-3" data-testid="selected-area">
        <div className="flex items-center gap-2 mb-2">
          <span className="text-[12px] font-bold text-ink-700" data-testid="selected-count">
            已选图片 <span className="text-brand-700">{selectedPhotos.length}</span> 张
          </span>
          <span className="text-[11px] text-ink-400">
            已选图片会从候选区消失，但仍保留在这里；取消后不会被重复或丢失
          </span>
        </div>
        {selectedPhotos.length === 0 ? (
          <p className="text-[11px] text-ink-400">还没选图。点候选图右上角的 ✓ 即可选中。</p>
        ) : (
          <ul className="flex flex-wrap gap-2">
            <AnimatePresence initial={false}>
              {selectedPhotos.map((p) => (
                <motion.li
                  key={p.id}
                  layout
                  initial={{ opacity: 0, scale: 0.9 }}
                  animate={{ opacity: 1, scale: 1 }}
                  exit={{ opacity: 0, scale: 0.9 }}
                  transition={{ duration: 0.15 }}
                  className="relative w-[92px] rounded-lg overflow-hidden border-2 border-brand-400"
                  data-testid="selected-item"
                  data-id={p.id}
                >
                  {broken.has(p.id) ? (
                    // 已选缩略图也要有失败兜底，否则 404 时会露出浏览器的破图图标
                    <div className="w-full aspect-[4/3] flex flex-col items-center justify-center gap-0.5 bg-paper-2 text-ink-400">
                      <ImageOff className="w-4 h-4" strokeWidth={1.5} />
                      <span className="text-[9px]">已失效</span>
                    </div>
                  ) : (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img
                      src={resolveApiUrl(p.thumb_url || p.url)}
                      alt={`${spotName} 已选图`}
                      className="w-full aspect-[4/3] object-cover"
                      onError={() =>
                        setBroken((s) => {
                          const n = new Set(s);
                          n.add(p.id);
                          return n;
                        })
                      }
                    />
                  )}
                  <span className="absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-brand-700 flex items-center justify-center">
                    <Check className="w-2.5 h-2.5 text-white" strokeWidth={3} />
                  </span>
                  <button
                    type="button"
                    onClick={() => toggle(p)}
                    aria-label="取消选择这张图"
                    title="取消选择"
                    data-testid="deselect-btn"
                    className="absolute top-0.5 right-0.5 w-4 h-4 rounded-full bg-black/50 hover:bg-red-600 flex items-center justify-center"
                  >
                    <X className="w-2.5 h-2.5 text-white" strokeWidth={3} />
                  </button>
                </motion.li>
              ))}
            </AnimatePresence>
          </ul>
        )}
      </div>
    </section>
  );
}