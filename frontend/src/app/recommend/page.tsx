"use client";

import { useState, useMemo, useEffect, useRef } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { useRouter } from "next/navigation";
import { streamChat } from "@/lib/api";
import SpotCoverPicker, { type SpotCover, type CoverZoomInfo } from "@/components/SpotCoverPicker";
import UserNav from "@/components/UserNav";
import LanguageSwitcher from "@/components/LanguageSwitcher";
import { useAuth } from "@/lib/auth";
import {
  Backpack, Wallet, Crown, Footprints, Flower2, Moon, UtensilsCrossed, Camera,
  Mountain, Target, Banknote, CreditCard, Gem, MapPin, Clock, Flame, Zap,
  CalendarDays, IdCard, Rocket, Compass, Sparkles, Home, Link as LinkIcon,
  FileText, PenLine, Check,
} from "lucide-react";

interface Spot {
  name: string;
  selected: boolean;
  rating: string;
  duration: string;
  ticket: string;
  desc: string;
  // 图片为异步补上；Unsplash 要求 hotlink，署名必须跟着一起展示
  image?: string;
  large?: string; // 点击放大用的高清图
  author?: string;
  author_url?: string;
  source?: string;
  source_url?: string;
}

const travelTypes = [
  { Icon: Backpack, label: "特种兵旅行", desc: "行程紧凑，火力全开", color: "from-red-400 to-orange-400" },
  { Icon: Wallet, label: "性价比出行", desc: "花最少的钱，玩最多的地方", color: "from-yellow-400 to-amber-400" },
  { Icon: Crown, label: "享受出行", desc: "品质优先，舒适体验", color: "from-purple-400 to-pink-400" },
  { Icon: Footprints, label: "City Walk", desc: "漫无目的，随性而走", color: "from-brand-400 to-brand-300" },
  { Icon: Flower2, label: "慢旅行", desc: "不赶路，感受路", color: "from-brand-500 to-green-400" },
  { Icon: Moon, label: "窝囊旅游", desc: "睡到自然醒，饿了就吃", color: "from-brand-500 to-brand-400" },
  { Icon: UtensilsCrossed, label: "美食之旅", desc: "为一顿饭赴一座城", color: "from-orange-400 to-red-400" },
  { Icon: Camera, label: "打卡出片", desc: "出片就是正义", color: "from-pink-400 to-rose-400" },
  { Icon: Mountain, label: "探索冒险", desc: "不走寻常路", color: "from-brand-400 to-brand-400" },
  { Icon: Target, label: "主题深度游", desc: "深挖一个主题，玩透一座城", color: "from-brand-400 to-brand-400" },
];

const hotCities = [
  { name: "成都" },
  { name: "重庆" },
  { name: "西安" },
  { name: "大理" },
  { name: "三亚" },
  { name: "厦门" },
  { name: "长沙" },
  { name: "杭州" },
  { name: "北京" },
  { name: "丽江" },
  { name: "青岛" },
  { name: "南京" },
];

const datePresets = [
  { label: "五一假期", start: "2026-05-01T08:00", end: "2026-05-05T18:00" },
  { label: "端午假期", start: "2026-05-31T08:00", end: "2026-06-02T18:00" },
  { label: "暑假出行", start: "2026-07-01T09:00", end: "2026-07-07T18:00" },
  { label: "国庆假期", start: "2026-10-01T08:00", end: "2026-10-07T18:00" },
];

const budgetHints = [
  { max: 1500, label: "经济游", Icon: Banknote, desc: "青旅+公共交通+街边美食" },
  { max: 3000, label: "舒适游", Icon: CreditCard, desc: "经济酒店+高铁+特色餐厅" },
  { max: 6000, label: "品质游", Icon: Gem, desc: "星级酒店+飞机+网红打卡" },
  { max: 20000, label: "奢华游", Icon: Crown, desc: "五星酒店+专车+米其林餐厅" },
];

const transportOptions = ["高铁", "火车", "飞机", "自驾"];
const hotelOptions = ["青旅", "经济酒店", "民宿", "星级酒店"];
const companionTypes = ["独自出行", "情侣", "朋友", "家庭", "团建"];
const userTypes = ["学生", "成人", "老人(60+)", "军人/退役军人", "儿童(1.2m以下)"];

const STEPS = [
  { num: 1, label: "目的地" },
  { num: 2, label: "时间" },
  { num: 3, label: "预算" },
  { num: 4, label: "偏好" },
  { num: 5, label: "推荐" },
];

export default function RecommendPage() {
  const router = useRouter();
  const { isAuthenticated, loading: authLoading } = useAuth();

  const [fromCity, setFromCity] = useState("苏州");
  const [toCity, setToCity] = useState("");
  const [depDate, setDepDate] = useState("");
  const [retDate, setRetDate] = useState("");
  const [budget, setBudget] = useState(3000);
  const [travelType, setTravelType] = useState(travelTypes[0].label);
  const [userType, setUserType] = useState(userTypes[0]);
  const [transportGo, setTransportGo] = useState(transportOptions[0]);
  const [transportBack, setTransportBack] = useState(transportOptions[0]);
  const [hotel, setHotel] = useState(hotelOptions[1]);
  const [companions, setCompanions] = useState(1);
  const [companionType, setCompanionType] = useState(companionTypes[0]);

  const [step, setStep] = useState(1);
  const [direction, setDirection] = useState(1);
  const [loading, setLoading] = useState(false);
  const [recommendation, setRecommendation] = useState("");
  const [spots, setSpots] = useState<Spot[]>([]);
  // 点击放大：null = 未打开。高清图只在打开那一刻才下载（列表里用的是小图）。
  const [zoom, setZoom] = useState<{
    src: string; name: string;
    source?: string; source_url?: string; author?: string; author_url?: string;
  } | null>(null);

  /* ── 第 5 步景点封面 ────────────────────────────────────────────────
   * covers 按景点名存**一张**封面（一个景点一个封面，不再是每景点九张机位图）。
   * 由 SpotCoverPicker 按需取图后回调写入；同时持久化供 /plan 复用。
   */
  const [covers, setCovers] = useState<Record<string, SpotCover>>({});
  /** 选图步骤用到的城市上下文（后端查询要带城市，裸名字搜出的图大量不可达） */
  const selectedCityForPicker = toCity;
  /** 是否已完成本地读取：用来阻止保存 effect 在读取之前用空值覆盖存储 */
  const hydratedRef = useRef(false);

  const selectedNames = useMemo(
    () => spots.filter((s) => s.selected).map((s) => s.name),
    [spots],
  );

  // 挂载后恢复：推荐景点列表 + 已选景点 + 封面（刷新不丢）
  useEffect(() => {
    let alive = true;
    void (async () => {
      await Promise.resolve();
      if (!alive) return;
      try {
        const rawSpots = localStorage.getItem("yedu_recommended_spots");
        const rawSelected = localStorage.getItem("yedu_selected_spots");
        const rawCovers = localStorage.getItem("yedu_spot_covers");
        const restored = rawSpots ? (JSON.parse(rawSpots) as Spot[]) : null;
        if (Array.isArray(restored) && restored.length > 0) {
          const sel = new Set<string>(rawSelected ? JSON.parse(rawSelected) : []);
          const list: Spot[] = restored.map((s) => ({ ...s, selected: sel.has(s.name) }));
          setSpots(list);
          // 恢复后直接回到第 5 步，用户看不到"已选丢失"
          setRecommendation("（已恢复上次的推荐结果）");
          setStep(5);
        }
        if (rawCovers) {
          const parsed = JSON.parse(rawCovers);
          if (parsed && typeof parsed === "object") setCovers(parsed);
        }
      } catch {
        /* 坏数据就当没有，不影响主流程 */
      } finally {
        hydratedRef.current = true;
      }
    })();
    return () => {
      alive = false;
    };
  }, []);

  // 保存：推荐景点列表 / 已选景点 / 封面（等恢复完成后再写，避免用空值覆盖）
  useEffect(() => {
    if (!hydratedRef.current) return;
    try {
      if (spots.length > 0) {
        localStorage.setItem("yedu_recommended_spots", JSON.stringify(spots));
        localStorage.setItem("yedu_selected_spots", JSON.stringify(selectedNames));
        localStorage.setItem("yedu_spot_covers", JSON.stringify(covers));
        // 已选景点的封面按**每景点一张**写入既有 key，/plan 直接复用、无需改格式
        const perSpot: Record<string, unknown[]> = {};
        for (const name of selectedNames) {
          const c = covers[name];
          if (c && (c.image_url || c.thumb_url)) {
            perSpot[name] = [
              {
                id: `cover:${name}`,
                url: c.large_url || c.image_url || c.thumb_url,
                thumb_url: c.thumb_url || c.image_url,
                source: c.source,
                source_url: c.source_url,
                credit: c.author,
              },
            ];
          }
        }
        localStorage.setItem("yedu_selected_images", JSON.stringify(perSpot));
      }
    } catch {
      /* 存不下不影响本次使用 */
    }
  }, [spots, selectedNames, covers]);

  // Esc 关闭放大层 —— 开了关不掉是最基础的可用性缺陷
  useEffect(() => {
    if (!zoom) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setZoom(null); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [zoom]);

  const days = useMemo(() => {
    try {
      const d1 = new Date(depDate);
      const d2 = new Date(retDate);
      if (depDate && retDate && d2 >= d1) return Math.ceil((d2.getTime() - d1.getTime()) / 86400000) + 1;
    } catch {}
    return 3;
  }, [depDate, retDate]);

  const budgetLevel = useMemo(() => budgetHints.find((b) => budget <= b.max) || budgetHints[3], [budget]);

  const next = () => { setDirection(1); setStep((s) => Math.min(s + 1, 5)); };
  const prev = () => { setDirection(-1); setStep((s) => Math.max(s - 1, 1)); };

  const canNext = () => {
    if (step === 1) return !!toCity.trim();
    if (step === 2) return !!depDate && !!retDate;
    return true;
  };

  const handleRecommend = async () => {
    if (!toCity) return;
    setLoading(true);
    setRecommendation("");
    setSpots([]);

    const params = {
      from_city: fromCity, to_city: toCity, days, budget,
      travel_type: travelType,
      user_type: userType.split(" ").pop() || userType,
      dep_datetime: depDate || "未定",
      ret_datetime: retDate || "未定",
      transport_go: transportGo, transport_back: transportBack,
      accommodation: hotel,
      companions_count: companions, companion_type: companionType,
    };

    let fullText = "";
    await streamChat(
      "/api/recommend",
      { params, session_id: "s1" },
      (chunk) => { fullText += chunk; setRecommendation(fullText); },
      (data) => {
        const extractedSpots = (data?.spots as string[]) || [];
        const spotDetails = (data?.spot_details as { name: string; rating: string; duration: string; ticket: string; desc: string }[]) || [];
        const coords = (data?.coords as { name: string; lng: number; lat: number }[]) || [];

        // 用 spot_details 构建富信息列表，降级用纯名字
        const detailMap = new Map(spotDetails.map((s) => [s.name, s]));
        const spotList = extractedSpots.map((name) => ({
          name,
          selected: false,
          rating: detailMap.get(name)?.rating || "",
          duration: detailMap.get(name)?.duration || "",
          ticket: detailMap.get(name)?.ticket || "",
          desc: detailMap.get(name)?.desc || "",
        }));
        setSpots(spotList);
        setLoading(false);
        // 保存坐标到 localStorage 供地图使用
        if (coords.length > 0) {
          localStorage.setItem("yedu_spot_coords", JSON.stringify(coords));
        }
        // 封面不再在这里批量预取：改为由 SpotCoverPicker **按需**只为
        // "当前可见的 4 个 + 预取 2 个"景点取图（避免为十几个景点一次性拉图）。
        // 缓存与接口沿用 getSpotImages 同一条链路（/api/spot-images + 后端磁盘缓存）。
      },
    );
  };

  /** 按景点名切换选择（待选区卡片 / 已选区取消都走它） */
  const toggleSpotByName = (name: string) => {
    setSpots((prev) => prev.map((s) => (s.name === name ? { ...s, selected: !s.selected } : s)));
  };

  const handleConfirm = () => {
    const selected = spots.filter((s) => s.selected).map((s) => s.name);
    if (selected.length === 0) return;
    // 清除旧攻略数据，确保 plan 页面重新生成
    localStorage.removeItem("yedu_plan");
    localStorage.removeItem("yedu_spot_coords");
    // 同时清掉上一份攻略的 history id，否则这份新攻略会就地覆盖历史里的旧记录
    localStorage.removeItem("yedu_plan_id");
    localStorage.setItem("yedu_selected_spots", JSON.stringify(selected));
    localStorage.setItem("yedu_session_id", "s1");
    localStorage.setItem("yedu_to_city", toCity);
    localStorage.setItem("yedu_user_params", JSON.stringify({
      from_city: fromCity, to_city: toCity, days, budget,
      travel_type: travelType, user_type: userType,
      dep_date: depDate, ret_date: retDate,
      transport_go: transportGo, transport_back: transportBack,
      accommodation: hotel, companions, companion_type: companionType,
    }));
    router.push("/plan");
  };

  const selectedCount = spots.filter((s) => s.selected).length;

  const fmtDate = (d: string) => {
    if (!d) return "";
    const dt = new Date(d);
    return `${dt.getFullYear()}年${dt.getMonth() + 1}月${dt.getDate()}日${dt.getHours()}点`;
  };

  // P0（Demo 阶段）：**移除登录门禁** —— 原来是「未登录就 replace("/login")」+
  // 「未登录直接 return null」，等于第一屏就把人挡住。
  // 本页用到的接口（/api/recommend、/api/generate-plan）都不需要登录，游客可直接走完流程。
  // authLoading / isAuthenticated 仍保留供后续"登录后存历史"用，但不再拦人。

  return (
    <div className="min-h-screen bg-gradient-to-br from-brand-50 via-white to-brand-50 flex flex-col relative overflow-hidden">
      {/* 背景装饰 */}
      <div className="absolute top-20 left-10 w-64 h-64 bg-brand-200/20 rounded-full blur-3xl pointer-events-none" />
      <div className="absolute bottom-40 right-10 w-80 h-80 bg-brand-200/20 rounded-full blur-3xl pointer-events-none" />
      <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[600px] h-[600px] bg-brand-100/10 rounded-full blur-3xl pointer-events-none" />

      {/* 顶部步骤条 */}
      <nav className="sticky top-0 z-20 bg-surface/70 backdrop-blur-xl border-b border-line/50 px-3 sm:px-6 py-3 sm:py-4">
        <div className="max-w-3xl mx-auto flex items-center justify-between">
          <div className="flex items-center gap-1">
          {STEPS.map((s, i) => (
            <div key={s.num} className="flex items-center">
              <button
                onClick={() => { if (s.num <= step || s.num < 5) { setDirection(s.num > step ? 1 : -1); setStep(s.num); } }}
                className="flex items-center gap-1 sm:gap-2 group"
              >
                <motion.div
                  animate={step === s.num ? { scale: [1, 1.1, 1] } : {}}
                  transition={{ duration: 0.4 }}
                  className={`w-7 h-7 sm:w-9 sm:h-9 rounded-full flex items-center justify-center text-xs sm:text-sm font-bold transition-all ${
                    step === s.num
                      ? "bg-brand-700 text-white shadow-lg shadow-black/10"
                      : step > s.num
                        ? "bg-brand-100 text-brand-600"
                        : "bg-paper-2 text-ink-400"
                  }`}
                >
                  {step > s.num ? "✓" : s.num}
                </motion.div>
                <span className={`text-xs sm:text-sm font-medium hidden sm:inline ${
                  step === s.num ? "text-brand-700" : step > s.num ? "text-brand-600" : "text-ink-400"
                }`}>
                  {s.label}
                </span>
              </button>
              {i < STEPS.length - 1 && (
                <div className={`w-4 sm:w-16 h-0.5 mx-0.5 sm:mx-1 rounded-full transition-all duration-500 ${
                  step > s.num ? "bg-brand-400" : "bg-line-strong"
                }`} />
              )}
            </div>
          ))}
          </div>
          <LanguageSwitcher />
          <UserNav />
        </div>
      </nav>

      {/* 主内容区 */}
      <div className="flex-1 flex items-start justify-center px-4 py-10">
        <div className="w-full max-w-2xl">
          <AnimatePresence mode="wait" custom={direction}>
            {/* Step 1: 目的地 */}
            {step === 1 && (
              <StepWrapper key="s1" direction={direction}>
                <div className="text-center mb-8">
                  <motion.div
                    initial={{ scale: 0.5, opacity: 0 }}
                    animate={{ scale: 1, opacity: 1 }}
                    transition={{ type: "spring", stiffness: 200 }}
                    className="inline-flex items-center justify-center w-20 h-20 rounded-[var(--radius-card)] bg-gradient-to-br from-brand-400 to-brand-600 shadow-xl shadow-black/10 mb-4"
                  >
                    <MapPin className="w-9 h-9 mx-auto text-brand-700" strokeWidth={1.4} />
                  </motion.div>
                  <h2 className="text-2xl sm:text-3xl font-extrabold text-ink-900">你想去哪？</h2>
                  <p className="text-ink-600 mt-2">选择你的出发地和梦想目的地</p>
                </div>

                <div className="space-y-5 max-w-md mx-auto">
                  <div>
                    <label className="block text-sm font-medium text-ink-600 mb-2">出发城市</label>
                    <input
                      type="text" value={fromCity} onChange={(e) => setFromCity(e.target.value)}
                      className="w-full px-4 py-3.5 rounded-xl border border-line bg-surface text-ink-900 text-lg focus:ring-2 focus:ring-blue-400 focus:border-blue-400 outline-none transition-all "
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-ink-600 mb-2">目的地</label>
                    <input
                      type="text" value={toCity} onChange={(e) => setToCity(e.target.value)}
                      placeholder="输入你想去的城市..."
                      className="w-full px-4 py-3.5 rounded-xl border border-line bg-surface text-ink-900 text-lg focus:ring-2 focus:ring-blue-400 focus:border-blue-400 outline-none transition-all placeholder:text-gray-300 "
                    />
                  </div>
                </div>

                {/* 热门城市 */}
                <div className="mt-8 max-w-lg mx-auto">
                  <p className="text-center text-sm font-medium text-ink-400 mb-3">热门目的地</p>
                  <div className="flex flex-wrap justify-center gap-2">
                    {hotCities.map((city) => (
                      <motion.button
                        key={city.name}
                        whileHover={{ scale: 1.05, y: -2 }}
                        whileTap={{ scale: 0.95 }}
                        onClick={() => setToCity(city.name)}
                        className={`px-4 py-2 rounded-full text-sm font-medium transition-all  ${
                          toCity === city.name
                            ? "bg-brand-700 text-white shadow-md shadow-black/10"
                            : "bg-surface text-ink-600 border border-line hover:border-blue-300 hover:text-brand-700"
                        }`}
                      >
                        {city.name}
                      </motion.button>
                    ))}
                  </div>
                </div>
              </StepWrapper>
            )}

            {/* Step 2: 时间 */}
            {step === 2 && (
              <StepWrapper key="s2" direction={direction}>
                <div className="text-center mb-8">
                  <motion.div
                    initial={{ scale: 0.5, opacity: 0 }}
                    animate={{ scale: 1, opacity: 1 }}
                    transition={{ type: "spring", stiffness: 200 }}
                    className="inline-flex items-center justify-center w-20 h-20 rounded-[var(--radius-card)] bg-gradient-to-br from-brand-400 to-brand-600 shadow-xl shadow-black/10 mb-4"
                  >
                    <Clock className="w-9 h-9 mx-auto text-brand-700" strokeWidth={1.4} />
                  </motion.div>
                  <h2 className="text-2xl sm:text-3xl font-extrabold text-ink-900">什么时候出发？</h2>
                  <p className="text-ink-600 mt-2">选择你的出行日期</p>
                </div>

                {/* 快速日期预设 */}
                <div className="max-w-md mx-auto mb-6">
                  <p className="text-center text-sm font-medium text-ink-400 mb-3">快速选择</p>
                  <div className="grid grid-cols-2 gap-2">
                    {datePresets.map((p) => (
                      <motion.button
                        key={p.label}
                        whileHover={{ scale: 1.02 }}
                        whileTap={{ scale: 0.98 }}
                        onClick={() => { setDepDate(p.start); setRetDate(p.end); }}
                        className={`px-4 py-3 rounded-xl text-sm font-medium transition-all ${
                          depDate === p.start && retDate === p.end
                            ? "bg-brand-700 text-white shadow-md shadow-black/10"
                            : "bg-surface text-ink-600 border border-line hover:border-blue-300 hover:text-brand-700 "
                        }`}
                      >
                        {p.label}
                      </motion.button>
                    ))}
                  </div>
                </div>

                <div className="space-y-5 max-w-md mx-auto">
                  <div>
                    <label className="block text-sm font-medium text-ink-600 mb-2">到达时间</label>
                    <input
                      type="datetime-local" value={depDate} onChange={(e) => setDepDate(e.target.value)}
                      className="w-full px-4 py-3.5 rounded-xl border border-line bg-surface text-ink-900 text-lg focus:ring-2 focus:ring-blue-400 focus:border-blue-400 outline-none transition-all "
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-ink-600 mb-2">返程时间</label>
                    <input
                      type="datetime-local" value={retDate} onChange={(e) => setRetDate(e.target.value)}
                      className="w-full px-4 py-3.5 rounded-xl border border-line bg-surface text-ink-900 text-lg focus:ring-2 focus:ring-blue-400 focus:border-blue-400 outline-none transition-all "
                    />
                  </div>
                </div>

                {/* 天数展示 */}
                {depDate && retDate && (
                  <motion.div
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    className="mt-6 text-center"
                  >
                    <div className="inline-flex items-center gap-3 px-6 py-3 bg-gradient-to-r from-brand-50 to-brand-50 rounded-[var(--radius-card)] border border-brand-100">
                      <CalendarDays className="w-6 h-6 text-brand-700" strokeWidth={1.5} />
                      <div className="text-left">
                        <p className="text-xs text-ink-600">{fmtDate(depDate)} — {fmtDate(retDate)}</p>
                        <p className="text-brand-700 font-bold text-lg">{days} 天行程</p>
                      </div>
                    </div>
                  </motion.div>
                )}
              </StepWrapper>
            )}

            {/* Step 3: 预算 */}
            {step === 3 && (
              <StepWrapper key="s3" direction={direction}>
                <div className="text-center mb-8">
                  <motion.div
                    initial={{ scale: 0.5, opacity: 0 }}
                    animate={{ scale: 1, opacity: 1 }}
                    transition={{ type: "spring", stiffness: 200 }}
                    className="inline-flex items-center justify-center w-20 h-20 rounded-[var(--radius-card)] bg-gradient-to-br from-amber-400 to-orange-500 shadow-xl shadow-amber-200/50 mb-4"
                  >
                    <Wallet className="w-9 h-9 mx-auto text-brand-700" strokeWidth={1.4} />
                  </motion.div>
                  <h2 className="text-2xl sm:text-3xl font-extrabold text-ink-900">预算和身份</h2>
                  <p className="text-ink-600 mt-2">告诉我们你的预算，帮你精打细算</p>
                </div>

                <div className="space-y-6 max-w-md mx-auto">
                  {/* 预算展示卡 */}
                  <motion.div
                    key={budgetLevel.label}
                    initial={{ opacity: 0, scale: 0.95 }}
                    animate={{ opacity: 1, scale: 1 }}
                    className="text-center py-4 px-6 bg-gradient-to-r from-amber-50 to-orange-50 rounded-[var(--radius-card)] border border-amber-100"
                  >
                    <budgetLevel.Icon className="w-7 h-7 mx-auto text-amber-600" strokeWidth={1.5} />
                    <p className="text-2xl font-extrabold text-ink-900 mt-1">¥{budget.toLocaleString()}</p>
                    <p className="text-amber-600 font-medium text-sm">{budgetLevel.label} / 人</p>
                    <p className="text-ink-400 text-xs mt-1">{budgetLevel.desc}</p>
                  </motion.div>

                  {/* 滑块 */}
                  <div>
                    <input
                      type="range" min={500} max={20000} step={500} value={budget}
                      onChange={(e) => setBudget(Number(e.target.value))}
                      className="w-full h-2 bg-line-strong rounded-full appearance-none cursor-pointer accent-blue-500"
                    />
                    <div className="flex justify-between text-xs text-ink-400 mt-2">
                      <span>¥500</span>
                      <span>¥5,000</span>
                      <span>¥10,000</span>
                      <span>¥20,000</span>
                    </div>
                  </div>

                  {/* 预算档次 */}
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                    {budgetHints.map((b) => (
                      <button
                        key={b.label}
                        onClick={() => setBudget(b.max === 1500 ? 1500 : b.max === 3000 ? 3000 : b.max === 6000 ? 6000 : 10000)}
                        className={`py-2 px-2 rounded-xl text-xs font-medium transition-all ${
                          budget <= b.max && budget > (b.max === 1500 ? 0 : budgetHints[budgetHints.indexOf(b) - 1]?.max || 0)
                            ? "bg-brand-700 text-white shadow-md"
                            : "bg-paper-2 text-ink-600 hover:bg-brand-50"
                        }`}
                      >
                        <b.Icon className="w-3.5 h-3.5" strokeWidth={1.7} /> {b.label}
                      </button>
                    ))}
                  </div>

                  {/* 身份选择 */}
                  <div>
                    <label className="block text-sm font-medium text-ink-600 mb-3">你的身份</label>
                    <div className="grid grid-cols-3 gap-2">
                      {userTypes.map((u) => (
                        <motion.button
                          key={u} onClick={() => setUserType(u)}
                          whileTap={{ scale: 0.95 }}
                          className={`px-3 py-3 rounded-xl text-sm font-medium transition-all ${
                            userType === u
                              ? "bg-brand-700 text-white shadow-lg shadow-black/10"
                              : "bg-surface text-ink-600 border border-line hover:border-blue-200 hover:text-brand-700 "
                          }`}
                        >
                          {u}
                        </motion.button>
                      ))}
                    </div>
                  </div>
                </div>
              </StepWrapper>
            )}

            {/* Step 4: 偏好 */}
            {step === 4 && (
              <StepWrapper key="s4" direction={direction}>
                <div className="text-center mb-8">
                  <motion.div
                    initial={{ scale: 0.5, opacity: 0 }}
                    animate={{ scale: 1, opacity: 1 }}
                    transition={{ type: "spring", stiffness: 200 }}
                    className="inline-flex items-center justify-center w-20 h-20 rounded-[var(--radius-card)] bg-gradient-to-br from-purple-400 to-pink-500 shadow-xl shadow-purple-200/50 mb-4"
                  >
                    <Target className="w-9 h-9 mx-auto text-brand-700" strokeWidth={1.4} />
                  </motion.div>
                  <h2 className="text-2xl sm:text-3xl font-extrabold text-ink-900">你的旅行风格</h2>
                  <p className="text-ink-600 mt-2">选择最符合你的出行方式</p>
                </div>

                <div className="space-y-6">
                  {/* 旅行类型卡片 */}
                  <div className="grid grid-cols-2 gap-3">
                    {travelTypes.map((t, idx) => (
                      <motion.button
                        key={t.label}
                        onClick={() => setTravelType(t.label)}
                        whileTap={{ scale: 0.97 }}
                        className={`text-left p-4 rounded-[var(--radius-card)] transition-all relative overflow-hidden ${
                          travelType === t.label
                            ? "bg-gradient-to-br " + t.color + " text-white shadow-xl scale-[1.02]"
                            : "bg-surface text-ink-700 border border-line hover:border-blue-200 hover:shadow-lg"
                        }`}
                      >
                        <div className="flex items-center gap-2">
                          <t.Icon className="w-[18px] h-[18px] shrink-0" strokeWidth={1.7} />
                          <span className="font-bold text-sm">{t.label}</span>
                        </div>
                        <p className={`text-xs mt-2 leading-relaxed ${travelType === t.label ? "text-white/80" : "text-ink-400"}`}>
                          {t.desc}
                        </p>
                        {travelType === t.label && (
                          <motion.div
                            layoutId="check"
                            className="absolute top-2 right-2 w-5 h-5 bg-surface/30 rounded-full flex items-center justify-center text-xs"
                          >
                            ✓
                          </motion.div>
                        )}
                      </motion.button>
                    ))}
                  </div>

                  {/* 交通住宿同伴 */}
                  <div className="bg-surface rounded-[var(--radius-card)] p-5 border border-line ">
                    <p className="text-sm font-medium text-ink-600 mb-4">更多偏好</p>
                    <div className="grid grid-cols-2 gap-4">
                      <div>
                        <label className="block text-xs font-medium text-ink-400 mb-1.5">去程交通</label>
                        <select value={transportGo} onChange={(e) => setTransportGo(e.target.value)}
                          className="w-full px-3 py-2.5 rounded-xl border border-line text-ink-900 text-sm outline-none focus:ring-2 focus:ring-blue-400 bg-surface">
                          {transportOptions.map((o) => <option key={o} value={o}>{o}</option>)}
                        </select>
                      </div>
                      <div>
                        <label className="block text-xs font-medium text-ink-400 mb-1.5">返程交通</label>
                        <select value={transportBack} onChange={(e) => setTransportBack(e.target.value)}
                          className="w-full px-3 py-2.5 rounded-xl border border-line text-ink-900 text-sm outline-none focus:ring-2 focus:ring-blue-400 bg-surface">
                          {transportOptions.map((o) => <option key={o} value={o}>{o}</option>)}
                        </select>
                      </div>
                      <div>
                        <label className="block text-xs font-medium text-ink-400 mb-1.5">住宿偏好</label>
                        <select value={hotel} onChange={(e) => setHotel(e.target.value)}
                          className="w-full px-3 py-2.5 rounded-xl border border-line text-ink-900 text-sm outline-none focus:ring-2 focus:ring-blue-400 bg-surface">
                          {hotelOptions.map((o) => <option key={o} value={o}>{o}</option>)}
                        </select>
                      </div>
                      <div>
                        <label className="block text-xs font-medium text-ink-400 mb-1.5">同行关系</label>
                        <select value={companionType} onChange={(e) => setCompanionType(e.target.value)}
                          className="w-full px-3 py-2.5 rounded-xl border border-line text-ink-900 text-sm outline-none focus:ring-2 focus:ring-blue-400 bg-surface">
                          {companionTypes.map((o) => <option key={o} value={o}>{o}</option>)}
                        </select>
                      </div>
                    </div>
                    <div className="mt-4 max-w-[160px]">
                      <label className="block text-xs font-medium text-ink-400 mb-1.5">出行人数</label>
                      <input
                        type="number" min={1} max={20} value={companions}
                        onChange={(e) => setCompanions(Number(e.target.value))}
                        className="w-full px-3 py-2.5 rounded-xl border border-line text-ink-900 text-sm outline-none focus:ring-2 focus:ring-blue-400"
                      />
                    </div>
                  </div>
                </div>
              </StepWrapper>
            )}

            {/* Step 5: AI 推荐 */}
            {step === 5 && (
              <StepWrapper key="s5" direction={direction}>
                <div className="text-center mb-6">
                  <motion.div
                    initial={{ scale: 0.5, opacity: 0 }}
                    animate={{ scale: 1, opacity: 1 }}
                    transition={{ type: "spring", stiffness: 200 }}
                    className="inline-flex items-center justify-center w-20 h-20 rounded-[var(--radius-card)] bg-gradient-to-br from-brand-400 to-brand-600 shadow-xl shadow-black/10 mb-4"
                  >
                    <Compass className="w-9 h-9 mx-auto text-brand-700" strokeWidth={1.4} />
                  </motion.div>
                  <h2 className="text-2xl sm:text-3xl font-extrabold text-ink-900">AI 为你推荐</h2>
                </div>

                {/* 行程摘要卡 */}
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 sm:gap-3 mb-6">
                  <SummaryCard Icon={MapPin} label="路线" value={`${fromCity}→${toCity}`} />
                  <SummaryCard Icon={CalendarDays} label="时间" value={`${days}天`} />
                  <SummaryCard Icon={Wallet} label="预算" value={`¥${budget}/人`} />
                  <SummaryCard Icon={Target} label="风格" value={travelType} />
                </div>

                {/* 生成按钮 */}
                {!recommendation && !loading && (
                  <motion.div
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    className="text-center"
                  >
                    <motion.button
                      onClick={handleRecommend}
                      whileHover={{ scale: 1.03 }}
                      whileTap={{ scale: 0.97 }}
                      className="px-12 py-4 bg-gradient-to-r from-brand-700 to-brand-600 hover:from-brand-600 hover:to-brand-500 text-white font-bold text-lg rounded-[var(--radius-card)] shadow-xl shadow-black/10/60 transition-all"
                    >
                      开始推荐
                    </motion.button>
                    <p className="text-ink-400 text-xs mt-3">AI 将根据你的偏好推荐最适合的景点</p>
                  </motion.div>
                )}

                {/* AI 加载动画（只在 loading 时显示） */}
                {loading && (
                  <motion.div
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ duration: 0.4 }}
                    className="bg-surface rounded-[var(--radius-card)] p-6  border border-line mb-6 text-center"
                  >
                    <div className="flex items-center justify-center gap-1.5 mb-3">
                      <Compass className="w-6 h-6 text-brand-700" strokeWidth={1.5} />
                      <motion.span
                        animate={{ rotate: [0, 15, -15, 0] }}
                        transition={{ duration: 1.2, repeat: Infinity, ease: "easeInOut" }}
                        className="text-2xl inline-block"
                      >
                        
                      </motion.span>
                    </div>
                    <div className="flex justify-center gap-1.5 mb-4">
                      <motion.span
                        animate={{ y: [0, -8, 0] }}
                        transition={{ duration: 0.6, repeat: Infinity, delay: 0 }}
                        className="w-3 h-3 bg-gradient-to-br from-brand-400 to-brand-600 rounded-full shadow-md shadow-black/10"
                      />
                      <motion.span
                        animate={{ y: [0, -8, 0] }}
                        transition={{ duration: 0.6, repeat: Infinity, delay: 0.15 }}
                        className="w-3 h-3 bg-gradient-to-br from-brand-500 to-brand-500 rounded-full shadow-md shadow-black/10"
                      />
                      <motion.span
                        animate={{ y: [0, -8, 0] }}
                        transition={{ duration: 0.6, repeat: Infinity, delay: 0.3 }}
                        className="w-3 h-3 bg-gradient-to-br from-brand-400 to-brand-300 rounded-full shadow-md shadow-black/10"
                      />
                    </div>
                    <p className="text-brand-600 font-medium text-sm">AI 正在搜索最佳景点...</p>
                    <p className="text-ink-400 text-xs mt-1">首次响应约 10-30 秒</p>
                  </motion.div>
                )}

                {/* 景点选择（封面卡片：待选区固定 4 个 + 已选区） */}
                {spots.length > 0 && (
                  <>
                    <SpotCoverPicker
                      spots={spots}
                      selectedNames={selectedNames}
                      city={selectedCityForPicker}
                      covers={covers}
                      onCoverLoaded={(cover) => setCovers((prev) => ({ ...prev, [cover.name]: cover }))}
                      onToggle={toggleSpotByName}
                      onZoom={(info: CoverZoomInfo) =>
                        setZoom({
                          src: info.src,
                          name: info.name,
                          source: info.source,
                          source_url: info.source_url,
                          author: info.author,
                          author_url: info.author_url,
                        })
                      }
                    />
                  </>
                )}

                    {/* 底部操作栏（与原先一致：仅在已有景点时出现） */}
                    {spots.length > 0 && (
                    <motion.div
                      initial={{ opacity: 0, y: 20 }}
                      animate={{ opacity: 1, y: 0 }}
                      className="flex flex-col sm:flex-row items-center justify-between gap-3 bg-surface rounded-[var(--radius-card)] p-4 sm:p-5 shadow-lg border border-line"
                    >
                      <span className="text-ink-600 text-sm">
                        已选 <strong className="text-brand-600 text-lg">{selectedCount}</strong> 个景点
                      </span>
                      <button
                        onClick={handleConfirm}
                        disabled={selectedCount === 0}
                        className="px-6 sm:px-8 py-2.5 rounded-xl bg-gradient-to-r from-brand-700 to-brand-600 hover:from-brand-600 hover:to-brand-500 disabled:from-gray-300 disabled:to-gray-300 text-white text-sm font-bold transition-all shadow-lg shadow-black/10 disabled:shadow-none"
                      >
                        生成攻略
                      </button>
                    </motion.div>
                    )}
              </StepWrapper>
            )}
          </AnimatePresence>
        </div>
      </div>

      {/* 底部导航 */}
      {step < 5 && (
        <div className="sticky bottom-0 z-20 bg-surface/70 backdrop-blur-xl border-t border-line/50 px-4 sm:px-6 py-3 sm:py-4" style={{ paddingBottom: "max(0.75rem, env(safe-area-inset-bottom))" }}>
          <div className="max-w-2xl mx-auto flex justify-between items-center">
            <button
              onClick={prev}
              disabled={step === 1}
              className="px-6 py-2.5 rounded-xl text-ink-600 font-medium hover:bg-paper-2 disabled:opacity-0 disabled:pointer-events-none transition-all"
            >
              ← 上一步
            </button>
            <p className="text-xs text-ink-400 hidden sm:block">
              第 {step}/4 步
            </p>
            <motion.button
              onClick={next}
              disabled={!canNext()}
              whileHover={canNext() ? { scale: 1.03 } : {}}
              whileTap={canNext() ? { scale: 0.97 } : {}}
              className="px-8 py-2.5 rounded-xl bg-gradient-to-r from-brand-700 to-brand-600 hover:from-brand-600 hover:to-brand-500 disabled:from-gray-200 disabled:to-gray-200 disabled:text-gray-400 text-white font-bold transition-all shadow-lg shadow-black/10 disabled:shadow-none"
            >
              下一步 →
            </motion.button>
          </div>
        </div>
      )}

      {/* 点击放大层（lightbox）
          高清图只在这一刻下载（列表里用的是 400w 小图）；
          Esc / 点遮罩 / 点右下关闭按钮三种关法都有 —— 开了关不掉是最基础的可用性缺陷 */}
      <AnimatePresence>
        {zoom && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={() => setZoom(null)}
            className="fixed inset-0 z-[100] bg-black/85 backdrop-blur-sm flex flex-col items-center justify-center p-4"
          >
            <button
              type="button"
              onClick={(e) => { e.stopPropagation(); setZoom(null); }}
              aria-label="关闭"
              className="absolute top-4 right-4 w-10 h-10 rounded-full bg-surface/15 hover:bg-white/25 text-white text-xl flex items-center justify-center transition-colors"
            >
              ✕
            </button>
            <motion.img
              initial={{ scale: 0.92, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.92, opacity: 0 }}
              src={zoom.src}
              alt={zoom.name}
              onClick={(e) => e.stopPropagation()}
              className="max-h-[78vh] max-w-full rounded-xl shadow-2xl object-contain"
            />
            <div className="mt-4 text-center" onClick={(e) => e.stopPropagation()}>
              <p className="text-white font-bold">{zoom.name}</p>
              {zoom.source && (
                <p className="text-[11px] text-white/55 mt-1">
                  图源：
                  <a
                    href={zoom.source_url || "#"}
                    target="_blank"
                    rel="noreferrer"
                    className="underline hover:text-white/80"
                  >
                    {zoom.source === "unsplash" ? "Unsplash" : zoom.source}
                  </a>
                  {zoom.author && (
                    <>
                      {" · "}
                      <a
                        href={zoom.author_url || "#"}
                        target="_blank"
                        rel="noreferrer"
                        className="underline hover:text-white/80"
                      >
                        {zoom.author}
                      </a>
                    </>
                  )}
                </p>
              )}
              <p className="text-[11px] text-white/40 mt-2">点击图片外部、按 Esc 或点右上角 ✕ 关闭</p>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

function StepWrapper({ direction, children }: { direction: number; children: React.ReactNode }) {
  return (
    <motion.div
      custom={direction}
      variants={{
        enter: (d: number) => ({ x: d > 0 ? 120 : -120, opacity: 0 }),
        center: { x: 0, opacity: 1 },
        exit: (d: number) => ({ x: d > 0 ? -120 : 120, opacity: 0 }),
      }}
      initial="enter"
      animate="center"
      exit="exit"
      transition={{ duration: 0.35, ease: [0.25, 0.46, 0.45, 0.94] }}
    >
      {children}
    </motion.div>
  );
}

function SummaryCard({ Icon, label, value }: { Icon: typeof MapPin; label: string; value: string }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      className="bg-surface rounded-xl p-3 text-center border border-line "
    >
      <Icon className="w-4 h-4 mx-auto text-brand-700" strokeWidth={1.6} />
      <p className="text-[10px] text-ink-400 mt-0.5">{label}</p>
      <p className="text-xs font-bold text-ink-700 mt-0.5 truncate">{value}</p>
    </motion.div>
  );
}

