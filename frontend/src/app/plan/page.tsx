"use client";

import { useState, useEffect, useRef, useCallback, useMemo } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { useRouter } from "next/navigation";
import ReactMarkdown from "react-markdown";
import { streamChat, savePlanToHistory, resolveApiUrl } from "@/lib/api";
import dynamic from "next/dynamic";
import UserNav from "@/components/UserNav";
import LanguageSwitcher from "@/components/LanguageSwitcher";
import { useAuth } from "@/lib/auth";
import {
  // 只引入本页实际用到的图标（批量替换 emoji 时一度引入重复项，构建会直接报
  // "the name `Moon` is defined multiple times"，所以合并成一条并去重）
  MapPin, Clock, Wallet, UtensilsCrossed, Baby, Moon, RefreshCw, Leaf,
  Star, Ticket, Search, ImageOff, PenLine, X, Check, Images, Link as LinkIcon,
} from "lucide-react";

const RouteMap = dynamic(() => import("@/components/RouteMap"), { ssr: false });

interface ChatMsg {
  role: "user" | "ai";
  content: string;
  isModification?: boolean;
  isPreview?: boolean;
  pendingMessage?: string;
}

const STORAGE_KEY_PLAN = "yedu_plan";
const STORAGE_KEY_SPOTS = "yedu_selected_spots";
const STORAGE_KEY_SESSION = "yedu_session_id";
const STORAGE_KEY_CITY = "yedu_to_city";
const STORAGE_KEY_PARAMS = "yedu_user_params"; // recommend / history 页写入的同一把 key
const STORAGE_KEY_PLAN_ID = "yedu_plan_id";    // 已保存攻略的 id，用于就地更新

const quickActions = [
  { label: "太累了，行程松一点", Icon: Moon, prompt: "请把行程安排得轻松一些，减少每天景点数量，增加休息时间" },
  { label: "预算超了，省一点", Icon: Wallet, prompt: "请帮我优化预算，选择更经济的交通、住宿和餐饮方案" },
  { label: "加几个景点", Icon: MapPin, prompt: "请再推荐几个值得去的景点，并合理融入现有行程" },
  { label: "换个玩法", Icon: RefreshCw, prompt: "请换一种旅行风格重新规划行程" },
  { label: "带小孩方便吗", Icon: Baby, prompt: "请考虑带小孩出行的便利性，调整景点和行程安排" },
  { label: "想吃当地美食", Icon: UtensilsCrossed, prompt: "请在行程中加入当地特色美食和餐厅推荐" },
];

export default function PlanPage() {
  const router = useRouter();
  const { isAuthenticated } = useAuth();
  const chatEndRef = useRef<HTMLDivElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);

  const [plan, setPlan] = useState("");
  const [loading, setLoading] = useState(false);
  const [chatInput, setChatInput] = useState("");
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [sessionId, setSessionId] = useState("s1");
  const [spots, setSpots] = useState<string[]>([]);
  const [spotCoords, setSpotCoords] = useState<{ name: string; lng: number; lat: number }[]>([]);
  const [exporting, setExporting] = useState(false);
  const [aiTyping, setAiTyping] = useState(false);
  const [initialized, setInitialized] = useState(false);
  const [sharing, setSharing] = useState(false);
  const [city, setCity] = useState("");
  /** 加载失败的已选图 id：用于显示占位而不是破图 */
  const [brokenPlanImgs, setBrokenPlanImgs] = useState<Set<string>>(new Set());

  /** 已选景点的封面（**每个景点最多一张**）。
   * 数据来自 recommend 第 5 步写入的 yedu_selected_images：
   * 每个景点名对应一个只含一张封面的数组，这里再 slice(0,1) 兜底，
   * 防止历史数据里残留多张时本页展示出多张。 */
  const pickedImagesForSpots = useMemo(() => {
    if (typeof window === "undefined") return [];
    try {
      const raw = localStorage.getItem("yedu_selected_images");
      if (!raw) return [];
      const all = JSON.parse(raw) as Record<string, { id: string; url: string; thumb_url: string; source?: string }[]>;
      if (!all || typeof all !== "object") return [];
      return Object.entries(all)
        .filter(([spot, photos]) => spots.includes(spot) && Array.isArray(photos) && photos.length > 0)
        .map(([spot, photos]) => ({ spot, cover: photos.slice(0, 1)[0] }));
    } catch {
      return [];
    }
  }, [spots]);
  const planRef = useRef<HTMLDivElement>(null);

  // P0（Demo 阶段）：**移除登录门禁** —— 原来未登录会跳 /login。
  // 本页展示的攻略内容来自 localStorage 与 /api/generate-plan（均不需要登录），
  // 所以游客可以直接看。isAuthenticated 仍用于"是否回写历史"，但不拦人。

  // 页面加载时从 localStorage 恢复数据
  useEffect(() => {
    const savedPlan = localStorage.getItem(STORAGE_KEY_PLAN);
    const savedSpots = localStorage.getItem(STORAGE_KEY_SPOTS);
    const savedSession = localStorage.getItem(STORAGE_KEY_SESSION);

    if (savedPlan) {
      setPlan(savedPlan);
    }

    if (savedSpots) {
      try {
        setSpots(JSON.parse(savedSpots));
      } catch {}
    }
    if (savedSession) setSessionId(savedSession);

    const savedCoords = localStorage.getItem("yedu_spot_coords");
    if (savedCoords) {
      try { setSpotCoords(JSON.parse(savedCoords)); } catch {}
    }

    const savedCity = localStorage.getItem(STORAGE_KEY_CITY);
    if (savedCity) setCity(savedCity);

    // 只有当没有已保存的攻略时，才自动生成
    if (!savedPlan && savedSpots && savedSession) {
      generatePlan(JSON.parse(savedSpots), savedSession);
    }

    setInitialized(true);
  }, []);

  // plan 变化时保存到 localStorage
  useEffect(() => {
    if (initialized && plan) {
      localStorage.setItem(STORAGE_KEY_PLAN, plan);
    }
  }, [plan, initialized]);

  // spots 变化时保存
  useEffect(() => {
    if (initialized && spots.length > 0) {
      localStorage.setItem(STORAGE_KEY_SPOTS, JSON.stringify(spots));
    }
  }, [spots, initialized]);

  // 自动保存到历史（登录用户 + 攻略生成完毕）
  // 2026-10-10 修复三处：
  //   ① 这里读 yedu_user_params，而历史页写的是 yedu_session_params → 从历史恢复后永不回写
  //   ② 每轮修改都无条件新增一条 → 改为带 plan_id 就地更新，历史列表不再刷屏
  //   ③ 保存失败被静默吞掉 → savePlanToHistory 现在会留下 console 警告
  useEffect(() => {
    if (!initialized || !isAuthenticated || !plan || loading) return;
    const raw = localStorage.getItem(STORAGE_KEY_PARAMS);
    if (!raw) return;

    let params: Record<string, any>;
    try {
      params = JSON.parse(raw);
    } catch {
      return;
    }

    const savedPlanId = Number(localStorage.getItem(STORAGE_KEY_PLAN_ID)) || undefined;

    savePlanToHistory({
      ...(savedPlanId ? { plan_id: savedPlanId } : {}),
      title: `${params.to_city || city} ${params.days || 3}日游`,
      from_city: params.from_city || "",
      to_city: params.to_city || city,
      days: params.days || 3,
      budget: params.budget || 3000,
      travel_type: params.travel_type || "",
      user_type: params.user_type || "",
      dep_date: params.dep_date || "",
      ret_date: params.ret_date || "",
      spots,
      plan_text: plan,
      params,
    }).then((res) => {
      // 首次保存后记住 id，后续修改才是更新而不是新增
      if (res?.plan_id && res.plan_id !== savedPlanId) {
        localStorage.setItem(STORAGE_KEY_PLAN_ID, String(res.plan_id));
      }
    });
  }, [plan, loading, initialized, isAuthenticated]);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, aiTyping]);

  const generatePlan = async (spotList: string[], sid: string) => {
    setLoading(true);
    setPlan("");
    let fullText = "";
    let lastUpdate = 0;
    let pendingText = "";
    let rafId = 0;

    // 节流更新：用 requestAnimationFrame 合并渲染，避免每个 chunk 都重渲染
    const scheduleUpdate = () => {
      cancelAnimationFrame(rafId);
      rafId = requestAnimationFrame(() => {
        setPlan(fullText);
        pendingText = "";
      });
    };

    await streamChat(
      "/api/generate-plan",
      { session_id: sid, spots: spotList },
      (chunk) => {
        fullText += chunk;
        scheduleUpdate();
      },
      () => {
        cancelAnimationFrame(rafId);
        setPlan(fullText); // 最终确保完整内容
        setLoading(false);
      },
    );
  };

  // 第一步：发送修改请求 → AI 返回方案摘要
  const handleSend = async (message: string) => {
    const text = message.trim();
    if (!text || loading) return;

    setMessages((prev) => [...prev, { role: "user", content: text }]);
    setChatInput("");
    setLoading(true);
    setAiTyping(true);
    let fullText = "";
    let rafId = 0;

    const scheduleMsgUpdate = (current: string) => {
      cancelAnimationFrame(rafId);
      const ft = current;
      rafId = requestAnimationFrame(() => {
        setMessages((prev) => {
          const updated = [...prev];
          const lastIdx = updated.length - 1;
          if (lastIdx >= 0 && updated[lastIdx].role === "ai" && updated[lastIdx].isPreview) {
            updated[lastIdx] = { ...updated[lastIdx], content: ft };
          } else {
            updated.push({ role: "ai", content: ft, isPreview: true, pendingMessage: text });
          }
          return updated;
        });
      });
    };

    await streamChat(
      "/api/modify",
      { session_id: sessionId, message: text, preview: true },
      (chunk) => {
        fullText += chunk;
        scheduleMsgUpdate(fullText);
      },
      () => {
        setLoading(false);
        setAiTyping(false);
      },
    );
  };

  // 第二步：用户确认后 → AI 生成完整新攻略
  const handleConfirmModify = async (pendingMessage: string, msgIdx: number) => {
    setLoading(true);
    setAiTyping(true);
    let fullText = "";

    // 给预览消息追加"已确认"标记，移除 pendingMessage
    setMessages((prev) => {
      const updated = [...prev];
      if (updated[msgIdx]) {
        updated[msgIdx] = { ...updated[msgIdx], pendingMessage: undefined };
      }
      return updated;
    });

    let rafId2 = 0;
    await streamChat(
      "/api/modify",
      { session_id: sessionId, message: pendingMessage, preview: false },
      (chunk) => {
        fullText += chunk;
        cancelAnimationFrame(rafId2);
        rafId2 = requestAnimationFrame(() => setPlan(fullText));
      },
      () => {
        cancelAnimationFrame(rafId2);
        setPlan(fullText);
        setLoading(false);
        setAiTyping(false);
        setMessages([]);
      },
    );
  };

  // 用户取消修改
  const handleCancelModify = (msgIdx: number) => {
    setMessages((prev) => {
      const updated = [...prev];
      if (updated[msgIdx]) {
        // 注意：这里是**字符串拼接**（追加到消息正文），不是 JSX ——
        // 所以只能放文本标记，不能放图标组件。批量替换 emoji 时踩过这个坑（把 ❌ 换成了 JSX 导致语法错误）。
        updated[msgIdx] = { ...updated[msgIdx], pendingMessage: undefined, content: updated[msgIdx].content + "\n\n（已取消）" };
      }
      return updated;
    });
  };

  // 清除缓存，重新开始
  const handleReset = () => {
    localStorage.removeItem(STORAGE_KEY_PLAN);
    localStorage.removeItem(STORAGE_KEY_SPOTS);
    localStorage.removeItem(STORAGE_KEY_SESSION);
    setPlan("");
    setSpots([]);
    setMessages([]);
    router.push("/recommend");
  };

  const handleExport = async () => {
    setExporting(true);
    try {
      const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000";
      const res = await fetch(`${API_BASE}/api/export-word`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ plan_text: plan, session_id: sessionId }),
      });
      if (!res.ok) throw new Error("导出失败");
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "野渡寻踪-旅行攻略.docx";
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      alert("导出失败，请稍后重试");
    }
    setExporting(false);
  };

  const handleShare = async () => {
    if (!planRef.current) return;
    setSharing(true);
    try {
      const html2canvas = (await import("html2canvas")).default;
      const canvas = await html2canvas(planRef.current, {
        backgroundColor: "#ffffff",
        scale: 2,
        useCORS: true,
        logging: false,
      });
      const url = canvas.toDataURL("image/png");
      const a = document.createElement("a");
      a.href = url;
      a.download = "野渡寻踪-旅行攻略.png";
      a.click();
    } catch {
      try {
        await navigator.clipboard.writeText(plan);
        alert("截图失败，攻略文本已复制到剪贴板");
      } catch {
        alert("分享失败，请截图分享");
      }
    }
    setSharing(false);
  };

  return (
    <div className="min-h-screen bg-gradient-to-b from-paper-2 to-brand-50/30 flex flex-col">
      {/* 顶部导航 */}
      <nav className="sticky top-0 z-20 bg-surface/80 backdrop-blur-xl border-b border-line/50 px-3 sm:px-6 py-3 flex items-center justify-between  gap-2">
        <button onClick={handleReset} className="text-brand-600 font-medium hover:text-blue-700 flex items-center gap-1 transition-all shrink-0">
          <span>←</span> <span className="hidden sm:inline">重新开始</span>
        </button>
        <h1 className="text-sm sm:text-lg font-bold text-ink-900 truncate">详细攻略</h1>
        <div className="flex items-center gap-2 shrink-0">
          <LanguageSwitcher />
          <UserNav />
          <button
            onClick={handleShare}
            disabled={sharing || !plan}
            className="px-2 sm:px-3 py-2 bg-gradient-to-r from-orange-400 to-pink-500 hover:from-orange-300 hover:to-pink-400 disabled:from-gray-300 disabled:to-gray-300 text-white text-xs sm:text-sm font-medium rounded-xl transition-all "
          >
            {sharing ? "生成中..." : "分享"}
          </button>
          <button
            onClick={handleExport}
            disabled={exporting || !plan}
            className="px-2 sm:px-3 py-2 bg-gradient-to-r from-brand-700 to-brand-600 hover:from-brand-600 hover:to-brand-500 disabled:from-gray-300 disabled:to-gray-300 text-white text-xs sm:text-sm font-medium rounded-xl transition-all "
          >
            {exporting ? "导出中..." : "Word"}
          </button>
        </div>
      </nav>

      {/* 攻略内容区 - 可滚动 */}
      <div ref={contentRef} className="flex-1 overflow-y-auto">
        <div className="max-w-4xl mx-auto px-4 py-6">
          {/* 已选景点 */}
          {spots.length > 0 && (
            <motion.div initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }} className="mb-6">
              <div className="flex items-center gap-2 flex-wrap">
                <span className="text-sm text-ink-600">已选景点：</span>
                {spots.map((s) => (
                  <span key={s} className="px-3 py-1 bg-brand-50 text-brand-700 text-sm rounded-full border border-brand-200">
                    {s}
                  </span>
                ))}
              </div>
            </motion.div>
          )}

          {/* 景点路线地图 */}
          {spotCoords.length > 0 && city && !loading && (
            <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}>
              <RouteMap spots={spots} city={city} coords={spotCoords} />
            </motion.div>
          )}

          {/* 已选景点的封面（每个景点一张，来自 recommend 第 5 步） */}
          {pickedImagesForSpots.length > 0 && (
            <motion.div
              initial={{ opacity: 0, y: -10 }}
              animate={{ opacity: 1, y: 0 }}
              className="mb-6 rounded-[var(--radius-card)] border border-line bg-surface p-4"
            >
              <div className="flex items-center gap-2 mb-3 flex-wrap">
                <Images className="w-4 h-4 text-brand-600" strokeWidth={1.8} />
                <span className="text-sm font-bold text-ink-700">已选景点封面</span>
                <span className="text-[11px] text-ink-400" data-testid="plan-cover-count">
                  {pickedImagesForSpots.length} 个景点 · 每个景点一张封面
                </span>
              </div>
              <ul className="flex flex-wrap gap-3">
                {pickedImagesForSpots.map((group) => (
                  <li key={group.spot} className="w-[116px]" data-testid="plan-cover-item" data-name={group.spot}>
                    {brokenPlanImgs.has(group.cover.id) ? (
                      // 图片失效时给占位，不露出浏览器破图图标
                      <div className="w-full aspect-[4/3] rounded-lg border border-line bg-paper-2 flex items-center justify-center text-ink-300">
                        <ImageOff className="w-5 h-5" strokeWidth={1.4} />
                      </div>
                    ) : (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img
                        src={resolveApiUrl(group.cover.thumb_url || group.cover.url)}
                        alt={`${group.spot} 封面`}
                        loading="lazy"
                        className="w-full aspect-[4/3] object-cover rounded-lg border border-line"
                        onError={() =>
                          setBrokenPlanImgs((s) => {
                            const n = new Set(s);
                            n.add(group.cover.id);
                            return n;
                          })
                        }
                      />
                    )}
                    <div className="text-[11px] text-ink-700 mt-1 truncate" title={group.spot}>
                      {group.spot}
                    </div>
                    <div className="text-[9px] text-ink-400 truncate">
                      {group.cover.source === "pixabay"
                        ? "Pixabay"
                        : group.cover.source === "unsplash"
                          ? "Unsplash"
                          : group.cover.source === "tavily"
                            ? "Tavily"
                            : "图源"}
                    </div>
                  </li>
                ))}
              </ul>
            </motion.div>
          )}

          {/* 攻略内容 */}
          <div ref={planRef} className="bg-surface rounded-[var(--radius-card)] p-4 sm:p-8  border border-line mb-6 min-h-[300px]">
            {!plan && loading && (
              <div className="flex flex-col items-center justify-center py-20">
                <motion.div
                  animate={{ rotate: 360 }}
                  transition={{ duration: 2, repeat: Infinity, ease: "linear" }}
                  className="w-12 h-12 border-4 border-brand-200 border-t-blue-500 rounded-full mb-4"
                />
                <p className="text-brand-600 font-medium">AI 正在生成详细攻略...</p>
                <p className="text-ink-400 text-xs mt-2">首次响应可能需要 10-30 秒，请稍候</p>
              </div>
            )}
            {!plan && !loading && (
              <div className="flex flex-col items-center justify-center py-20 text-ink-400">
                <PenLine className="w-10 h-10 mx-auto mb-4 text-ink-300" strokeWidth={1.3} />
                <p>等待生成攻略...</p>
              </div>
            )}

            {plan && (
              <div className="prose prose-sm max-w-none text-ink-700">
                <ReactMarkdown>{plan}</ReactMarkdown>
                {loading && <span className="animate-pulse text-brand-600 text-lg">▍</span>}
              </div>
            )}
          </div>

          {/* 快捷操作 */}
          {!loading && plan && (
            <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="mb-6">
              <h3 className="text-sm font-medium text-ink-400 mb-3">快捷调整</h3>
              <div className="flex flex-wrap gap-2">
                {quickActions.map((action) => (
                  <motion.button
                    key={action.label}
                    whileHover={{ scale: 1.03 }}
                    whileTap={{ scale: 0.97 }}
                    onClick={() => handleSend(action.prompt)}
                    className="px-4 py-2 bg-surface border border-line rounded-xl text-sm text-ink-600 hover:border-blue-300 hover:bg-brand-50 hover:text-blue-700 transition-all "
                  >
                    <action.Icon className="w-3.5 h-3.5 shrink-0" strokeWidth={1.7} /> {action.label}
                  </motion.button>
                ))}
              </div>
            </motion.div>
          )}
        </div>
      </div>

      {/* 底部 AI 助手对话面板 */}
      {plan && (
        <div className="sticky bottom-0 z-10 bg-surface border-t border-line shadow-[0_-4px_20px_rgba(0,0,0,0.06)]" style={{ paddingBottom: "env(safe-area-inset-bottom, 0px)" }}>
          {/* 对话消息区 */}
          <div className="max-w-4xl mx-auto px-3 sm:px-4">
            <div className="max-h-28 sm:max-h-48 overflow-y-auto py-2 sm:py-3 space-y-2">
              <AnimatePresence>
                {messages.map((msg, i) => (
                  <motion.div
                    key={i}
                    initial={{ opacity: 0, y: 8, scale: 0.98 }}
                    animate={{ opacity: 1, y: 0, scale: 1 }}
                    transition={{ duration: 0.2 }}
                    className={`flex gap-2 ${msg.role === "user" ? "justify-end" : "justify-start"}`}
                  >
                    {msg.role === "ai" && (
                      <div className="w-7 h-7 rounded-full bg-gradient-to-br from-brand-400 to-brand-600 flex items-center justify-center text-white text-xs shrink-0  mt-0.5">
                        <Leaf className="w-3.5 h-3.5 inline -mt-px" strokeWidth={1.8} />
                      </div>
                    )}
                    <div
                      className={`max-w-[75%] px-4 py-2.5 text-sm leading-relaxed ${
                        msg.role === "user"
                          ? "bg-brand-700 text-white rounded-[var(--radius-card)] rounded-br-md "
                          : msg.isModification
                            ? "bg-amber-50 text-ink-700 rounded-[var(--radius-card)] rounded-bl-md border border-amber-200"
                            : msg.isPreview
                              ? "bg-brand-50 text-ink-700 rounded-[var(--radius-card)] rounded-bl-md border border-brand-200"
                              : "bg-paper-2 text-ink-700 rounded-[var(--radius-card)] rounded-bl-md border border-line"
                      }`}
                    >
                      {(msg.isModification || msg.isPreview) ? (
                        <div className="prose prose-sm max-w-none text-ink-700 [&_p:first-child]:mt-0 [&_p:last-child]:mb-0">
                          <ReactMarkdown>{msg.content}</ReactMarkdown>
                        </div>
                      ) : (
                        msg.content
                      )}
                      {msg.isPreview && msg.pendingMessage && (
                        <div className="flex gap-2 mt-3 pt-2 border-t border-brand-200">
                          <button
                            onClick={() => handleConfirmModify(msg.pendingMessage!, i)}
                            disabled={loading}
                            className="px-4 py-1.5 bg-brand-700 hover:bg-blue-600 text-white text-xs font-bold rounded-lg transition-all disabled:opacity-50"
                          >
                            确认修改
                          </button>
                          <button
                            onClick={() => handleCancelModify(i)}
                            disabled={loading}
                            className="px-4 py-1.5 bg-line-strong hover:bg-gray-300 text-ink-600 text-xs font-medium rounded-lg transition-all disabled:opacity-50"
                          >
                            取消
                          </button>
                        </div>
                      )}
                    </div>
                    {msg.role === "user" && (
                      <div className="w-7 h-7 rounded-full bg-brand-100 flex items-center justify-center text-brand-600 text-xs shrink-0 mt-0.5">
                        你
                      </div>
                    )}
                  </motion.div>
                ))}
              </AnimatePresence>

              {/* AI 打字动画 */}
              {aiTyping && (
                <motion.div
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  className="flex gap-2 justify-start"
                >
                  <div className="w-7 h-7 rounded-full bg-gradient-to-br from-brand-400 to-brand-600 flex items-center justify-center text-white text-xs shrink-0 ">
                    <Leaf className="w-3.5 h-3.5 inline -mt-px" strokeWidth={1.8} />
                  </div>
                  <div className="bg-paper-2 rounded-[var(--radius-card)] rounded-bl-md border border-line px-4 py-3">
                    <div className="flex gap-1">
                      <span className="w-2 h-2 bg-brand-400 rounded-full animate-bounce" style={{ animationDelay: "0ms" }} />
                      <span className="w-2 h-2 bg-brand-400 rounded-full animate-bounce" style={{ animationDelay: "150ms" }} />
                      <span className="w-2 h-2 bg-brand-400 rounded-full animate-bounce" style={{ animationDelay: "300ms" }} />
                    </div>
                  </div>
                </motion.div>
              )}
              <div ref={chatEndRef} />
            </div>

            {/* 输入框 */}
            <div className="flex gap-2 sm:gap-3 pb-3 sm:pb-4 pt-1">
              <div className="flex-1 relative">
                <input
                  type="text"
                  value={chatInput}
                  onChange={(e) => setChatInput(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && handleSend(chatInput)}
                  placeholder="告诉 AI 怎么调整攻略..."
                  disabled={loading}
                  className="w-full px-3 sm:px-4 py-2.5 sm:py-3 rounded-xl bg-paper-2 text-ink-900 text-sm outline-none focus:ring-2 focus:ring-blue-400 focus:bg-white border border-line transition-all disabled:opacity-40"
                />
              </div>
              <motion.button
                onClick={() => handleSend(chatInput)}
                disabled={loading || !chatInput.trim()}
                whileHover={!loading && chatInput.trim() ? { scale: 1.03 } : {}}
                whileTap={!loading && chatInput.trim() ? { scale: 0.97 } : {}}
                className="px-4 sm:px-5 py-2.5 sm:py-3 bg-gradient-to-r from-brand-700 to-brand-600 hover:from-brand-600 hover:to-brand-500 disabled:from-gray-300 disabled:to-gray-300 text-white text-sm font-medium rounded-xl transition-all shadow-lg shadow-black/10 disabled:shadow-none"
              >
                发送
              </motion.button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
