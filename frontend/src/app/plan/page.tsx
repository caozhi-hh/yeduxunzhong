"use client";

import { useState, useEffect, useRef } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { useRouter } from "next/navigation";
import ReactMarkdown from "react-markdown";
import { streamChat } from "@/lib/api";

interface ChatMsg {
  role: "user" | "ai";
  content: string;
  typing?: boolean;
}

const quickActions = [
  { label: "太累了，行程松一点", icon: "😴", prompt: "请把行程安排得轻松一些，减少每天景点数量，增加休息时间" },
  { label: "预算超了，省一点", icon: "💰", prompt: "请帮我优化预算，选择更经济的交通、住宿和餐饮方案" },
  { label: "加几个景点", icon: "📍", prompt: "请再推荐几个值得去的景点，并合理融入现有行程" },
  { label: "换个玩法", icon: "🔄", prompt: "请换一种旅行风格重新规划行程" },
  { label: "带小孩方便吗", icon: "👶", prompt: "请考虑带小孩出行的便利性，调整景点和行程安排" },
  { label: "想吃当地美食", icon: "🍜", prompt: "请在行程中加入当地特色美食和餐厅推荐" },
];

export default function PlanPage() {
  const router = useRouter();
  const chatEndRef = useRef<HTMLDivElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);

  const [plan, setPlan] = useState("");
  const [loading, setLoading] = useState(false);
  const [chatInput, setChatInput] = useState("");
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [sessionId, setSessionId] = useState("s1");
  const [spots, setSpots] = useState<string[]>([]);
  const [exporting, setExporting] = useState(false);
  const [aiTyping, setAiTyping] = useState(false);

  useEffect(() => {
    const savedSpots = sessionStorage.getItem("selected_spots");
    const savedSession = sessionStorage.getItem("plan_session");
    if (savedSpots) {
      const parsed = JSON.parse(savedSpots) as string[];
      setSpots(parsed);
    }
    if (savedSession) setSessionId(savedSession);

    if (savedSpots && savedSession) {
      generatePlan(JSON.parse(savedSpots), savedSession);
    }
  }, []);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, aiTyping]);

  const generatePlan = async (spotList: string[], sid: string) => {
    setLoading(true);
    setPlan("");
    let fullText = "";

    await streamChat(
      "/api/generate-plan",
      { session_id: sid, spots: spotList },
      (chunk) => {
        fullText += chunk;
        setPlan(fullText);
      },
      () => {
        setLoading(false);
        setMessages([{ role: "ai", content: "攻略已生成完毕！你可以让我帮你调整行程、优化预算、添加景点等，随时告诉我 😊" }]);
      },
    );
  };

  const handleSend = async (message: string) => {
    const text = message.trim();
    if (!text || loading) return;

    setMessages((prev) => [...prev, { role: "user", content: text }]);
    setChatInput("");
    setLoading(true);
    setAiTyping(true);
    let fullText = "";

    await streamChat(
      "/api/modify",
      { session_id: sessionId, message: text },
      (chunk) => {
        fullText += chunk;
        setPlan(fullText);
      },
      () => {
        setLoading(false);
        setAiTyping(false);
        setMessages((prev) => [...prev, { role: "ai", content: "已根据你的要求更新攻略，看看新的安排怎么样？如果不满意可以继续调整~" }]);
      },
    );
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

  return (
    <div className="min-h-screen bg-gradient-to-b from-gray-50 to-emerald-50/30 flex flex-col">
      {/* 顶部导航 */}
      <nav className="sticky top-0 z-20 bg-white/80 backdrop-blur-xl border-b border-gray-100/50 px-3 sm:px-6 py-3 flex items-center justify-between shadow-sm gap-2">
        <button onClick={() => router.push("/recommend")} className="text-emerald-600 font-medium hover:text-emerald-700 flex items-center gap-1 transition-all shrink-0">
          <span>←</span> <span className="hidden sm:inline">返回推荐</span>
        </button>
        <h1 className="text-sm sm:text-lg font-bold text-gray-800 truncate">🗺️ 详细攻略</h1>
        <button
          onClick={handleExport}
          disabled={exporting || !plan}
          className="px-3 sm:px-4 py-2 bg-gradient-to-r from-emerald-500 to-teal-500 hover:from-emerald-400 hover:to-teal-400 disabled:from-gray-300 disabled:to-gray-300 text-white text-xs sm:text-sm font-medium rounded-xl transition-all shadow-sm shrink-0"
        >
          {exporting ? "导出中..." : "📄 Word"}
        </button>
      </nav>

      {/* 攻略内容区 - 可滚动 */}
      <div ref={contentRef} className="flex-1 overflow-y-auto">
        <div className="max-w-4xl mx-auto px-4 py-6">
          {/* 已选景点 */}
          {spots.length > 0 && (
            <motion.div initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }} className="mb-6">
              <div className="flex items-center gap-2 flex-wrap">
                <span className="text-sm text-gray-500">已选景点：</span>
                {spots.map((s) => (
                  <span key={s} className="px-3 py-1 bg-emerald-50 text-emerald-700 text-sm rounded-full border border-emerald-200">
                    {s}
                  </span>
                ))}
              </div>
            </motion.div>
          )}

          {/* 攻略内容 */}
          <div className="bg-white rounded-2xl p-4 sm:p-8 shadow-sm border border-gray-100 mb-6 min-h-[300px]">
            {!plan && loading && (
              <div className="flex flex-col items-center justify-center py-20">
                <motion.div
                  animate={{ rotate: 360 }}
                  transition={{ duration: 2, repeat: Infinity, ease: "linear" }}
                  className="w-12 h-12 border-4 border-emerald-200 border-t-emerald-500 rounded-full mb-4"
                />
                <p className="text-emerald-600 font-medium">AI 正在生成详细攻略...</p>
                <p className="text-gray-400 text-xs mt-2">首次响应可能需要 10-30 秒，请稍候</p>
              </div>
            )}
            {!plan && !loading && (
              <div className="flex flex-col items-center justify-center py-20 text-gray-400">
                <div className="text-5xl mb-4">📝</div>
                <p>等待生成攻略...</p>
              </div>
            )}

            {plan && (
              <div className="prose prose-sm max-w-none text-gray-700">
                <ReactMarkdown>{plan}</ReactMarkdown>
                {loading && <span className="animate-pulse text-emerald-500 text-lg">▍</span>}
              </div>
            )}
          </div>

          {/* 快捷操作 */}
          {!loading && plan && (
            <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="mb-6">
              <h3 className="text-sm font-medium text-gray-400 mb-3">⚡ 快捷调整</h3>
              <div className="flex flex-wrap gap-2">
                {quickActions.map((action) => (
                  <motion.button
                    key={action.label}
                    whileHover={{ scale: 1.03 }}
                    whileTap={{ scale: 0.97 }}
                    onClick={() => handleSend(action.prompt)}
                    className="px-4 py-2 bg-white border border-gray-200 rounded-xl text-sm text-gray-600 hover:border-emerald-300 hover:bg-emerald-50 hover:text-emerald-700 transition-all shadow-sm"
                  >
                    {action.icon} {action.label}
                  </motion.button>
                ))}
              </div>
            </motion.div>
          )}
        </div>
      </div>

      {/* 底部 AI 助手对话面板 */}
      {plan && (
        <div className="sticky bottom-0 z-10 bg-white border-t border-gray-200 shadow-[0_-4px_20px_rgba(0,0,0,0.06)]" style={{ paddingBottom: "env(safe-area-inset-bottom, 0px)" }}>
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
                      <div className="w-7 h-7 rounded-full bg-gradient-to-br from-emerald-400 to-teal-500 flex items-center justify-center text-white text-xs shrink-0 shadow-sm mt-0.5">
                        🌿
                      </div>
                    )}
                    <div
                      className={`max-w-[75%] px-4 py-2.5 text-sm leading-relaxed ${
                        msg.role === "user"
                          ? "bg-emerald-500 text-white rounded-2xl rounded-br-md shadow-sm"
                          : "bg-gray-50 text-gray-700 rounded-2xl rounded-bl-md border border-gray-100"
                      }`}
                    >
                      {msg.content}
                    </div>
                    {msg.role === "user" && (
                      <div className="w-7 h-7 rounded-full bg-emerald-100 flex items-center justify-center text-emerald-600 text-xs shrink-0 mt-0.5">
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
                  <div className="w-7 h-7 rounded-full bg-gradient-to-br from-emerald-400 to-teal-500 flex items-center justify-center text-white text-xs shrink-0 shadow-sm">
                    🌿
                  </div>
                  <div className="bg-gray-50 rounded-2xl rounded-bl-md border border-gray-100 px-4 py-3">
                    <div className="flex gap-1">
                      <span className="w-2 h-2 bg-emerald-400 rounded-full animate-bounce" style={{ animationDelay: "0ms" }} />
                      <span className="w-2 h-2 bg-emerald-400 rounded-full animate-bounce" style={{ animationDelay: "150ms" }} />
                      <span className="w-2 h-2 bg-emerald-400 rounded-full animate-bounce" style={{ animationDelay: "300ms" }} />
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
                  className="w-full px-3 sm:px-4 py-2.5 sm:py-3 rounded-xl bg-gray-50 text-gray-800 text-sm outline-none focus:ring-2 focus:ring-emerald-400 focus:bg-white border border-gray-100 transition-all disabled:opacity-40"
                />
              </div>
              <motion.button
                onClick={() => handleSend(chatInput)}
                disabled={loading || !chatInput.trim()}
                whileHover={!loading && chatInput.trim() ? { scale: 1.03 } : {}}
                whileTap={!loading && chatInput.trim() ? { scale: 0.97 } : {}}
                className="px-4 sm:px-5 py-2.5 sm:py-3 bg-gradient-to-r from-emerald-500 to-teal-500 hover:from-emerald-400 hover:to-teal-400 disabled:from-gray-300 disabled:to-gray-300 text-white text-sm font-medium rounded-xl transition-all shadow-lg shadow-emerald-200/30 disabled:shadow-none"
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
