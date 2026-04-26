"use client";

import { useState, useMemo } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { useRouter } from "next/navigation";
import { streamChat, fetchSpotPhoto } from "@/lib/api";

interface Spot {
  name: string;
  selected: boolean;
  imageLoading: boolean;
  imageBase64: string;
}

const travelTypes = [
  { icon: "🎒", label: "特种兵旅行", desc: "行程紧凑，火力全开", color: "from-red-400 to-orange-400" },
  { icon: "💰", label: "性价比出行", desc: "花最少的钱，玩最多的地方", color: "from-yellow-400 to-amber-400" },
  { icon: "👑", label: "享受出行", desc: "品质优先，舒适体验", color: "from-purple-400 to-pink-400" },
  { icon: "🚶", label: "City Walk", desc: "漫无目的，随性而走", color: "from-blue-400 to-cyan-400" },
  { icon: "🧘", label: "慢旅行", desc: "不赶路，感受路", color: "from-teal-400 to-green-400" },
  { icon: "😴", label: "窝囊旅游", desc: "睡到自然醒，饿了就吃", color: "from-indigo-400 to-blue-400" },
  { icon: "🍜", label: "美食之旅", desc: "为一顿饭赴一座城", color: "from-orange-400 to-red-400" },
  { icon: "📸", label: "打卡出片", desc: "出片就是正义", color: "from-pink-400 to-rose-400" },
  { icon: "🏔️", label: "探索冒险", desc: "不走寻常路", color: "from-emerald-400 to-teal-400" },
  { icon: "🎯", label: "主题深度游", desc: "深挖一个主题，玩透一座城", color: "from-cyan-400 to-blue-400" },
];

const hotCities = [
  { name: "成都", emoji: "🐼" },
  { name: "重庆", emoji: "🌶️" },
  { name: "西安", emoji: "🏛️" },
  { name: "大理", emoji: "🏔️" },
  { name: "三亚", emoji: "🏖️" },
  { name: "厦门", emoji: "🌊" },
  { name: "长沙", emoji: "🍵" },
  { name: "杭州", emoji: "🍃" },
  { name: "北京", emoji: "🏯" },
  { name: "丽江", emoji: "🌄" },
  { name: "青岛", emoji: "🍺" },
  { name: "南京", emoji: "🌸" },
];

const datePresets = [
  { label: "五一假期", start: "2026-05-01T08:00", end: "2026-05-05T18:00" },
  { label: "端午假期", start: "2026-05-31T08:00", end: "2026-06-02T18:00" },
  { label: "暑假出行", start: "2026-07-01T09:00", end: "2026-07-07T18:00" },
  { label: "国庆假期", start: "2026-10-01T08:00", end: "2026-10-07T18:00" },
];

const budgetHints = [
  { max: 1500, label: "经济游", emoji: "💵", desc: "青旅+公共交通+街边美食" },
  { max: 3000, label: "舒适游", emoji: "💳", desc: "经济酒店+高铁+特色餐厅" },
  { max: 6000, label: "品质游", emoji: "💎", desc: "星级酒店+飞机+网红打卡" },
  { max: 20000, label: "奢华游", emoji: "👑", desc: "五星酒店+专车+米其林餐厅" },
];

const transportOptions = ["🚄 高铁", "🚂 火车", "✈️ 飞机", "🚗 自驾"];
const hotelOptions = ["🛏️ 青旅", "🏢 经济酒店", "🏡 民宿", "⭐ 星级酒店"];
const companionTypes = ["🧑 独自出行", "💑 情侣", "👫 朋友", "👨‍👩‍👧 家庭", "🏢 团建"];
const userTypes = ["🎒 学生", "👤 成人", "👴 老人(60+)", "🎖️ 军人/退役军人", "👶 儿童(1.2m以下)"];

const STEPS = [
  { num: 1, label: "目的地", icon: "📍" },
  { num: 2, label: "时间", icon: "🕐" },
  { num: 3, label: "预算", icon: "💰" },
  { num: 4, label: "偏好", icon: "🎯" },
  { num: 5, label: "推荐", icon: "🌿" },
];

export default function RecommendPage() {
  const router = useRouter();

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
        const spotList = extractedSpots.map((name) => ({ name, selected: false, imageLoading: true, imageBase64: "" }));
        setSpots(spotList);
        setLoading(false);
        // 自动加载每个景点的照片
        spotList.forEach((spot, idx) => {
          fetchSpotPhoto(spot.name, toCity).then((url) => {
            if (url) {
              setSpots((prev) => prev.map((s, i) => i === idx ? { ...s, imageLoading: false, imageBase64: url } : s));
            } else {
              setSpots((prev) => prev.map((s, i) => i === idx ? { ...s, imageLoading: false } : s));
            }
          });
        });
      },
    );
  };

  const toggleSpot = (idx: number) => {
    setSpots((prev) => prev.map((s, i) => (i === idx ? { ...s, selected: !s.selected } : s)));
  };

  const handleConfirm = () => {
    const selected = spots.filter((s) => s.selected).map((s) => s.name);
    if (selected.length === 0) return;
    sessionStorage.setItem("selected_spots", JSON.stringify(selected));
    sessionStorage.setItem("plan_session", "s1");
    router.push("/plan");
  };

  const selectedCount = spots.filter((s) => s.selected).length;

  const fmtDate = (d: string) => {
    if (!d) return "";
    const dt = new Date(d);
    return `${dt.getFullYear()}年${dt.getMonth() + 1}月${dt.getDate()}日${dt.getHours()}点`;
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-emerald-50 via-white to-emerald-50 flex flex-col relative overflow-hidden">
      {/* 背景装饰 */}
      <div className="absolute top-20 left-10 w-64 h-64 bg-emerald-200/20 rounded-full blur-3xl pointer-events-none" />
      <div className="absolute bottom-40 right-10 w-80 h-80 bg-teal-200/20 rounded-full blur-3xl pointer-events-none" />
      <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[600px] h-[600px] bg-emerald-100/10 rounded-full blur-3xl pointer-events-none" />

      {/* 顶部步骤条 */}
      <nav className="sticky top-0 z-20 bg-white/70 backdrop-blur-xl border-b border-gray-100/50 px-3 sm:px-6 py-3 sm:py-4">
        <div className="max-w-3xl mx-auto flex items-center justify-between">
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
                      ? "bg-emerald-500 text-white shadow-lg shadow-emerald-200"
                      : step > s.num
                        ? "bg-emerald-100 text-emerald-600"
                        : "bg-gray-100 text-gray-400"
                  }`}
                >
                  {step > s.num ? "✓" : s.num}
                </motion.div>
                <span className={`text-xs sm:text-sm font-medium hidden sm:inline ${
                  step === s.num ? "text-emerald-700" : step > s.num ? "text-emerald-500" : "text-gray-400"
                }`}>
                  {s.label}
                </span>
              </button>
              {i < STEPS.length - 1 && (
                <div className={`w-4 sm:w-16 h-0.5 mx-0.5 sm:mx-1 rounded-full transition-all duration-500 ${
                  step > s.num ? "bg-emerald-400" : "bg-gray-200"
                }`} />
              )}
            </div>
          ))}
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
                    className="inline-flex items-center justify-center w-20 h-20 rounded-2xl bg-gradient-to-br from-emerald-400 to-teal-500 shadow-xl shadow-emerald-200/50 mb-4"
                  >
                    <span className="text-4xl">📍</span>
                  </motion.div>
                  <h2 className="text-2xl sm:text-3xl font-extrabold text-gray-800">你想去哪？</h2>
                  <p className="text-gray-500 mt-2">选择你的出发地和梦想目的地</p>
                </div>

                <div className="space-y-5 max-w-md mx-auto">
                  <div>
                    <label className="block text-sm font-medium text-gray-600 mb-2">🏠 出发城市</label>
                    <input
                      type="text" value={fromCity} onChange={(e) => setFromCity(e.target.value)}
                      className="w-full px-4 py-3.5 rounded-xl border border-gray-200 bg-white text-gray-800 text-lg focus:ring-2 focus:ring-emerald-400 focus:border-emerald-400 outline-none transition-all shadow-sm"
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-gray-600 mb-2">✈️ 目的地</label>
                    <input
                      type="text" value={toCity} onChange={(e) => setToCity(e.target.value)}
                      placeholder="输入你想去的城市..."
                      className="w-full px-4 py-3.5 rounded-xl border border-gray-200 bg-white text-gray-800 text-lg focus:ring-2 focus:ring-emerald-400 focus:border-emerald-400 outline-none transition-all placeholder:text-gray-300 shadow-sm"
                    />
                  </div>
                </div>

                {/* 热门城市 */}
                <div className="mt-8 max-w-lg mx-auto">
                  <p className="text-center text-sm font-medium text-gray-400 mb-3">🔥 热门目的地</p>
                  <div className="flex flex-wrap justify-center gap-2">
                    {hotCities.map((city) => (
                      <motion.button
                        key={city.name}
                        whileHover={{ scale: 1.05, y: -2 }}
                        whileTap={{ scale: 0.95 }}
                        onClick={() => setToCity(city.name)}
                        className={`px-4 py-2 rounded-full text-sm font-medium transition-all shadow-sm ${
                          toCity === city.name
                            ? "bg-emerald-500 text-white shadow-md shadow-emerald-200"
                            : "bg-white text-gray-600 border border-gray-100 hover:border-emerald-300 hover:text-emerald-600"
                        }`}
                      >
                        {city.emoji} {city.name}
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
                    className="inline-flex items-center justify-center w-20 h-20 rounded-2xl bg-gradient-to-br from-blue-400 to-indigo-500 shadow-xl shadow-blue-200/50 mb-4"
                  >
                    <span className="text-4xl">🕐</span>
                  </motion.div>
                  <h2 className="text-2xl sm:text-3xl font-extrabold text-gray-800">什么时候出发？</h2>
                  <p className="text-gray-500 mt-2">选择你的出行日期</p>
                </div>

                {/* 快速日期预设 */}
                <div className="max-w-md mx-auto mb-6">
                  <p className="text-center text-sm font-medium text-gray-400 mb-3">⚡ 快速选择</p>
                  <div className="grid grid-cols-2 gap-2">
                    {datePresets.map((p) => (
                      <motion.button
                        key={p.label}
                        whileHover={{ scale: 1.02 }}
                        whileTap={{ scale: 0.98 }}
                        onClick={() => { setDepDate(p.start); setRetDate(p.end); }}
                        className={`px-4 py-3 rounded-xl text-sm font-medium transition-all ${
                          depDate === p.start && retDate === p.end
                            ? "bg-blue-500 text-white shadow-md shadow-blue-200"
                            : "bg-white text-gray-600 border border-gray-100 hover:border-blue-300 hover:text-blue-600 shadow-sm"
                        }`}
                      >
                        {p.label}
                      </motion.button>
                    ))}
                  </div>
                </div>

                <div className="space-y-5 max-w-md mx-auto">
                  <div>
                    <label className="block text-sm font-medium text-gray-600 mb-2">📅 到达时间</label>
                    <input
                      type="datetime-local" value={depDate} onChange={(e) => setDepDate(e.target.value)}
                      className="w-full px-4 py-3.5 rounded-xl border border-gray-200 bg-white text-gray-800 text-lg focus:ring-2 focus:ring-emerald-400 focus:border-emerald-400 outline-none transition-all shadow-sm"
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-gray-600 mb-2">📅 返程时间</label>
                    <input
                      type="datetime-local" value={retDate} onChange={(e) => setRetDate(e.target.value)}
                      className="w-full px-4 py-3.5 rounded-xl border border-gray-200 bg-white text-gray-800 text-lg focus:ring-2 focus:ring-emerald-400 focus:border-emerald-400 outline-none transition-all shadow-sm"
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
                    <div className="inline-flex items-center gap-3 px-6 py-3 bg-gradient-to-r from-emerald-50 to-teal-50 rounded-2xl border border-emerald-100">
                      <span className="text-2xl">🗓️</span>
                      <div className="text-left">
                        <p className="text-xs text-gray-500">{fmtDate(depDate)} — {fmtDate(retDate)}</p>
                        <p className="text-emerald-700 font-bold text-lg">{days} 天行程</p>
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
                    className="inline-flex items-center justify-center w-20 h-20 rounded-2xl bg-gradient-to-br from-amber-400 to-orange-500 shadow-xl shadow-amber-200/50 mb-4"
                  >
                    <span className="text-4xl">💰</span>
                  </motion.div>
                  <h2 className="text-2xl sm:text-3xl font-extrabold text-gray-800">预算和身份</h2>
                  <p className="text-gray-500 mt-2">告诉我们你的预算，帮你精打细算</p>
                </div>

                <div className="space-y-6 max-w-md mx-auto">
                  {/* 预算展示卡 */}
                  <motion.div
                    key={budgetLevel.label}
                    initial={{ opacity: 0, scale: 0.95 }}
                    animate={{ opacity: 1, scale: 1 }}
                    className="text-center py-4 px-6 bg-gradient-to-r from-amber-50 to-orange-50 rounded-2xl border border-amber-100"
                  >
                    <span className="text-3xl">{budgetLevel.emoji}</span>
                    <p className="text-2xl font-extrabold text-gray-800 mt-1">¥{budget.toLocaleString()}</p>
                    <p className="text-amber-600 font-medium text-sm">{budgetLevel.label} / 人</p>
                    <p className="text-gray-400 text-xs mt-1">{budgetLevel.desc}</p>
                  </motion.div>

                  {/* 滑块 */}
                  <div>
                    <input
                      type="range" min={500} max={20000} step={500} value={budget}
                      onChange={(e) => setBudget(Number(e.target.value))}
                      className="w-full h-2 bg-gray-200 rounded-full appearance-none cursor-pointer accent-emerald-500"
                    />
                    <div className="flex justify-between text-xs text-gray-400 mt-2">
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
                            ? "bg-emerald-500 text-white shadow-md"
                            : "bg-gray-50 text-gray-500 hover:bg-emerald-50"
                        }`}
                      >
                        {b.emoji} {b.label}
                      </button>
                    ))}
                  </div>

                  {/* 身份选择 */}
                  <div>
                    <label className="block text-sm font-medium text-gray-600 mb-3">🪪 你的身份</label>
                    <div className="grid grid-cols-3 gap-2">
                      {userTypes.map((u) => (
                        <motion.button
                          key={u} onClick={() => setUserType(u)}
                          whileTap={{ scale: 0.95 }}
                          className={`px-3 py-3 rounded-xl text-sm font-medium transition-all ${
                            userType === u
                              ? "bg-emerald-500 text-white shadow-lg shadow-emerald-200"
                              : "bg-white text-gray-600 border border-gray-100 hover:border-emerald-200 hover:text-emerald-600 shadow-sm"
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
                    className="inline-flex items-center justify-center w-20 h-20 rounded-2xl bg-gradient-to-br from-purple-400 to-pink-500 shadow-xl shadow-purple-200/50 mb-4"
                  >
                    <span className="text-4xl">🎯</span>
                  </motion.div>
                  <h2 className="text-2xl sm:text-3xl font-extrabold text-gray-800">你的旅行风格</h2>
                  <p className="text-gray-500 mt-2">选择最符合你的出行方式</p>
                </div>

                <div className="space-y-6">
                  {/* 旅行类型卡片 */}
                  <div className="grid grid-cols-2 gap-3">
                    {travelTypes.map((t, idx) => (
                      <motion.button
                        key={t.label}
                        onClick={() => setTravelType(t.label)}
                        whileTap={{ scale: 0.97 }}
                        className={`text-left p-4 rounded-2xl transition-all relative overflow-hidden ${
                          travelType === t.label
                            ? "bg-gradient-to-br " + t.color + " text-white shadow-xl scale-[1.02]"
                            : "bg-white text-gray-700 border border-gray-100 hover:border-emerald-200 hover:shadow-lg"
                        }`}
                      >
                        <div className="flex items-center gap-2">
                          <span className="text-2xl">{t.icon}</span>
                          <span className="font-bold text-sm">{t.label}</span>
                        </div>
                        <p className={`text-xs mt-2 leading-relaxed ${travelType === t.label ? "text-white/80" : "text-gray-400"}`}>
                          {t.desc}
                        </p>
                        {travelType === t.label && (
                          <motion.div
                            layoutId="check"
                            className="absolute top-2 right-2 w-5 h-5 bg-white/30 rounded-full flex items-center justify-center text-xs"
                          >
                            ✓
                          </motion.div>
                        )}
                      </motion.button>
                    ))}
                  </div>

                  {/* 交通住宿同伴 */}
                  <div className="bg-white rounded-2xl p-5 border border-gray-100 shadow-sm">
                    <p className="text-sm font-medium text-gray-500 mb-4">🚀 更多偏好</p>
                    <div className="grid grid-cols-2 gap-4">
                      <div>
                        <label className="block text-xs font-medium text-gray-400 mb-1.5">去程交通</label>
                        <select value={transportGo} onChange={(e) => setTransportGo(e.target.value)}
                          className="w-full px-3 py-2.5 rounded-xl border border-gray-200 text-gray-800 text-sm outline-none focus:ring-2 focus:ring-emerald-400 bg-white">
                          {transportOptions.map((o) => <option key={o} value={o}>{o}</option>)}
                        </select>
                      </div>
                      <div>
                        <label className="block text-xs font-medium text-gray-400 mb-1.5">返程交通</label>
                        <select value={transportBack} onChange={(e) => setTransportBack(e.target.value)}
                          className="w-full px-3 py-2.5 rounded-xl border border-gray-200 text-gray-800 text-sm outline-none focus:ring-2 focus:ring-emerald-400 bg-white">
                          {transportOptions.map((o) => <option key={o} value={o}>{o}</option>)}
                        </select>
                      </div>
                      <div>
                        <label className="block text-xs font-medium text-gray-400 mb-1.5">住宿偏好</label>
                        <select value={hotel} onChange={(e) => setHotel(e.target.value)}
                          className="w-full px-3 py-2.5 rounded-xl border border-gray-200 text-gray-800 text-sm outline-none focus:ring-2 focus:ring-emerald-400 bg-white">
                          {hotelOptions.map((o) => <option key={o} value={o}>{o}</option>)}
                        </select>
                      </div>
                      <div>
                        <label className="block text-xs font-medium text-gray-400 mb-1.5">同行关系</label>
                        <select value={companionType} onChange={(e) => setCompanionType(e.target.value)}
                          className="w-full px-3 py-2.5 rounded-xl border border-gray-200 text-gray-800 text-sm outline-none focus:ring-2 focus:ring-emerald-400 bg-white">
                          {companionTypes.map((o) => <option key={o} value={o}>{o}</option>)}
                        </select>
                      </div>
                    </div>
                    <div className="mt-4 max-w-[160px]">
                      <label className="block text-xs font-medium text-gray-400 mb-1.5">出行人数</label>
                      <input
                        type="number" min={1} max={20} value={companions}
                        onChange={(e) => setCompanions(Number(e.target.value))}
                        className="w-full px-3 py-2.5 rounded-xl border border-gray-200 text-gray-800 text-sm outline-none focus:ring-2 focus:ring-emerald-400"
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
                    className="inline-flex items-center justify-center w-20 h-20 rounded-2xl bg-gradient-to-br from-emerald-400 to-green-500 shadow-xl shadow-emerald-200/50 mb-4"
                  >
                    <span className="text-4xl">🌿</span>
                  </motion.div>
                  <h2 className="text-2xl sm:text-3xl font-extrabold text-gray-800">AI 为你推荐</h2>
                </div>

                {/* 行程摘要卡 */}
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 sm:gap-3 mb-6">
                  <SummaryCard icon="📍" label="路线" value={`${fromCity}→${toCity}`} />
                  <SummaryCard icon="📅" label="时间" value={`${days}天`} />
                  <SummaryCard icon="💰" label="预算" value={`¥${budget}/人`} />
                  <SummaryCard icon="🎯" label="风格" value={travelType} />
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
                      className="px-12 py-4 bg-gradient-to-r from-emerald-500 to-teal-500 hover:from-emerald-400 hover:to-teal-400 text-white font-bold text-lg rounded-2xl shadow-xl shadow-emerald-200/60 transition-all"
                    >
                      🚀 开始推荐
                    </motion.button>
                    <p className="text-gray-400 text-xs mt-3">AI 将根据你的偏好推荐最适合的景点</p>
                  </motion.div>
                )}

                {/* AI 推荐内容 */}
                {(loading || recommendation) && (
                  <div className="bg-white rounded-2xl p-6 shadow-sm border border-gray-100 mb-6 text-left">
                    <h3 className="text-sm font-bold text-emerald-700 mb-3">📋 AI 景点推荐</h3>
                    {!recommendation && loading && (
                      <div className="flex flex-col items-center justify-center py-10">
                        <motion.div
                          animate={{ rotate: 360 }}
                          transition={{ duration: 1.5, repeat: Infinity, ease: "linear" }}
                          className="w-10 h-10 border-4 border-emerald-200 border-t-emerald-500 rounded-full mb-3"
                        />
                        <p className="text-emerald-600 font-medium text-sm">AI 正在分析最佳景点...</p>
                        <p className="text-gray-400 text-xs mt-1">首次响应约 10-30 秒</p>
                      </div>
                    )}
                    {recommendation && (
                      <div className="prose prose-sm max-w-none text-gray-700 whitespace-pre-wrap">
                        {recommendation}
                        {loading && <span className="animate-pulse text-emerald-500">▍</span>}
                      </div>
                    )}
                  </div>
                )}

                {/* 景点勾选 */}
                {spots.length > 0 && (
                  <>
                    <h3 className="text-sm font-bold text-emerald-700 mb-3">✅ 勾选你想去的景点</h3>
                    <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 mb-6">
                      {spots.map((spot, idx) => (
                        <motion.div
                          key={spot.name}
                          initial={{ opacity: 0, y: 20 }}
                          animate={{ opacity: 1, y: 0 }}
                          transition={{ delay: idx * 0.06 }}
                          whileHover={{ y: -3 }}
                          onClick={() => toggleSpot(idx)}
                          className={`cursor-pointer rounded-2xl overflow-hidden transition-all ${
                            spot.selected
                              ? "border-2 border-emerald-500 shadow-xl shadow-emerald-100 ring-2 ring-emerald-200"
                              : "border-2 border-gray-100 hover:border-emerald-200 hover:shadow-lg bg-white"
                          }`}
                        >
                          <div className="h-32 bg-gradient-to-br from-emerald-100 to-teal-50 flex items-center justify-center relative">
                            {spot.imageBase64 ? (
                              <img src={spot.imageBase64} alt={spot.name} className="w-full h-full object-cover" crossOrigin="anonymous" />
                            ) : spot.imageLoading ? (
                              <div className="w-6 h-6 border-2 border-emerald-300 border-t-emerald-500 rounded-full animate-spin" />
                            ) : (
                              <span className="text-4xl">🏞️</span>
                            )}
                            {spot.selected && (
                              <motion.div
                                initial={{ scale: 0 }}
                                animate={{ scale: 1 }}
                                className="absolute top-2 right-2 w-7 h-7 bg-emerald-500 rounded-full flex items-center justify-center text-white text-sm shadow-md"
                              >
                                ✓
                              </motion.div>
                            )}
                          </div>
                          <div className="p-3">
                            <h4 className="font-bold text-gray-800 text-sm">{spot.name}</h4>
                            {spot.selected && (
                              <motion.span
                                initial={{ opacity: 0 }}
                                animate={{ opacity: 1 }}
                                className="inline-block mt-1 text-xs bg-emerald-500 text-white px-2.5 py-0.5 rounded-full"
                              >
                                ✓ 已选择
                              </motion.span>
                            )}
                          </div>
                        </motion.div>
                      ))}
                    </div>

                    {/* 底部操作栏 */}
                    <motion.div
                      initial={{ opacity: 0, y: 20 }}
                      animate={{ opacity: 1, y: 0 }}
                      className="flex flex-col sm:flex-row items-center justify-between gap-3 bg-white rounded-2xl p-4 sm:p-5 shadow-lg border border-gray-100"
                    >
                      <span className="text-gray-600 text-sm">
                        已选 <strong className="text-emerald-600 text-lg">{selectedCount}</strong> 个景点
                      </span>
                      <button
                        onClick={handleConfirm}
                        disabled={selectedCount === 0}
                        className="px-6 sm:px-8 py-2.5 rounded-xl bg-gradient-to-r from-emerald-500 to-teal-500 hover:from-emerald-400 hover:to-teal-400 disabled:from-gray-300 disabled:to-gray-300 text-white text-sm font-bold transition-all shadow-lg shadow-emerald-200/50 disabled:shadow-none"
                      >
                        ✅ 生成攻略
                      </button>
                    </motion.div>
                  </>
                )}
              </StepWrapper>
            )}
          </AnimatePresence>
        </div>
      </div>

      {/* 底部导航 */}
      {step < 5 && (
        <div className="sticky bottom-0 z-20 bg-white/70 backdrop-blur-xl border-t border-gray-100/50 px-4 sm:px-6 py-3 sm:py-4" style={{ paddingBottom: "max(0.75rem, env(safe-area-inset-bottom))" }}>
          <div className="max-w-2xl mx-auto flex justify-between items-center">
            <button
              onClick={prev}
              disabled={step === 1}
              className="px-6 py-2.5 rounded-xl text-gray-500 font-medium hover:bg-gray-100 disabled:opacity-0 disabled:pointer-events-none transition-all"
            >
              ← 上一步
            </button>
            <p className="text-xs text-gray-400 hidden sm:block">
              第 {step}/4 步
            </p>
            <motion.button
              onClick={next}
              disabled={!canNext()}
              whileHover={canNext() ? { scale: 1.03 } : {}}
              whileTap={canNext() ? { scale: 0.97 } : {}}
              className="px-8 py-2.5 rounded-xl bg-gradient-to-r from-emerald-500 to-teal-500 hover:from-emerald-400 hover:to-teal-400 disabled:from-gray-200 disabled:to-gray-200 disabled:text-gray-400 text-white font-bold transition-all shadow-lg shadow-emerald-200/30 disabled:shadow-none"
            >
              下一步 →
            </motion.button>
          </div>
        </div>
      )}
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

function SummaryCard({ icon, label, value }: { icon: string; label: string; value: string }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      className="bg-white rounded-xl p-3 text-center border border-gray-100 shadow-sm"
    >
      <span className="text-lg">{icon}</span>
      <p className="text-[10px] text-gray-400 mt-0.5">{label}</p>
      <p className="text-xs font-bold text-gray-700 mt-0.5 truncate">{value}</p>
    </motion.div>
  );
}
