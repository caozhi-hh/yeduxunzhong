"use client";

import { motion } from "framer-motion";
import Link from "next/link";

const features = [
  { icon: "🎯", title: "AI 智能推荐", desc: "根据你的预算和风格\n精准推荐必去景点" },
  { icon: "🎨", title: "AI 生成景点图", desc: "每个景点自动生成\n沉浸式预览图片" },
  { icon: "🗺️", title: "智能路线规划", desc: "不走回头路\n每天行程最优安排" },
  { icon: "📄", title: "一键导出攻略", desc: "详细攻略导出 Word\n离线也能随时查看" },
];

const steps = [
  { num: 1, text: "填写旅行参数" },
  { num: 2, text: "勾选心仪景点" },
  { num: 3, text: "获取详细攻略" },
];

export default function Home() {
  return (
    <div className="relative min-h-screen flex flex-col items-center justify-center overflow-hidden">
      {/* 背景图层 */}
      <div
        className="absolute inset-0 bg-cover bg-center bg-no-repeat"
        style={{
          backgroundImage:
            "url('https://images.unsplash.com/photo-1469854523086-cc02fe5d8800?w=1920&q=80')",
        }}
      />
      {/* 渐变遮罩 */}
      <div className="absolute inset-0 bg-gradient-to-b from-black/60 via-black/40 to-emerald-900/80" />

      {/* 内容层 */}
      <div className="relative z-10 flex flex-col items-center justify-center px-4 py-16 w-full">
        {/* 品牌区 */}
        <motion.div
          initial={{ opacity: 0, y: 30 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6 }}
          className="text-center mb-14"
        >
          <h1 className="text-4xl sm:text-5xl md:text-6xl font-extrabold text-white mb-4 drop-shadow-lg tracking-wide">
            🌿 野渡寻踪
          </h1>
          <p className="text-base sm:text-xl text-emerald-200 max-w-2xl mx-auto leading-relaxed drop-shadow">
            AI 智能旅行攻略规划师 — 从景点推荐到详细行程，一站搞定
          </p>
        </motion.div>

        {/* 特色卡片 */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 sm:gap-4 max-w-4xl w-full mb-10 sm:mb-14 px-2">
          {features.map((f, i) => (
            <motion.div
              key={f.title}
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.2 + i * 0.1, duration: 0.5 }}
              className="bg-white/10 backdrop-blur-md rounded-2xl p-5 text-center border border-white/20 hover:bg-white/20 hover:-translate-y-1 transition-all"
            >
              <div className="text-4xl mb-2">{f.icon}</div>
              <div className="font-bold text-white text-base mb-1">{f.title}</div>
              <div className="text-xs text-emerald-100/80 whitespace-pre-line leading-relaxed">
                {f.desc}
              </div>
            </motion.div>
          ))}
        </div>

        {/* 流程步骤 */}
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.6 }}
          className="flex flex-wrap items-center justify-center gap-3 sm:gap-4 mb-10 sm:mb-14"
        >
          {steps.map((s, i) => (
            <div key={s.num} className="flex items-center gap-3">
              <div className="flex items-center gap-2">
                <div className="w-10 h-10 rounded-full bg-emerald-500 text-white flex items-center justify-center font-bold text-lg shadow-lg">
                  {s.num}
                </div>
                <span className="text-sm text-white font-medium drop-shadow">{s.text}</span>
              </div>
              {i < steps.length - 1 && (
                <span className="text-emerald-300/60 text-2xl mx-1">→</span>
              )}
            </div>
          ))}
        </motion.div>

        {/* CTA 按钮 */}
        <motion.div
          initial={{ opacity: 0, scale: 0.9 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ delay: 0.8, duration: 0.4 }}
        >
          <Link
            href="/recommend"
            className="inline-block bg-emerald-500 hover:bg-emerald-400 text-white font-bold text-lg sm:text-xl px-8 sm:px-14 py-4 sm:py-5 rounded-full shadow-2xl shadow-emerald-500/30 hover:shadow-emerald-400/40 transition-all hover:-translate-y-1"
          >
            🚀 开始生成攻略
          </Link>
        </motion.div>

        {/* 底部 */}
        <p className="mt-20 text-xs text-white/40">Powered by LangGraph + 豆包</p>
      </div>
    </div>
  );
}
