"use client";

import Link from "next/link";
import { motion } from "framer-motion";
import { useTranslation } from "react-i18next";
import { ArrowRight, Map, Sparkles, FileText, Route } from "lucide-react";
import SiteHeader from "@/components/SiteHeader";

/**
 * 首页 —— P0 轻量改造（视觉换血，结构留待 P1 重构）
 *
 * P0 改了什么：
 *   1. **去掉登录门禁** —— 原来一进来就 redirect 到 /login，Demo 阶段游客直接可看
 *   2. **换掉"科技蓝 + 深色玻璃卡"** —— 这正是要避免的"黑色科技 AI 产品"观感；
 *      改为暖白纸底 + 墨绿 + 大图留白
 *   3. **emoji 全换成线性图标**（原来 🎯🎨🗺️📄 当图标用，是廉价感的主因）
 *   4. 用上设计 token 与 SiteHeader 组件
 *
 * P1 会继续把"4 张特色卡 + 3 步流程"换成真正的**热门目的地**（用户来这是找灵感的，
 * 不是看产品说明书的）。
 */

export default function Home() {
  const { t } = useTranslation();

  const features = [
    { Icon: Sparkles, title: t("home.feature1_title"), desc: t("home.feature1_desc") },
    { Icon: Map, title: t("home.feature2_title"), desc: t("home.feature2_desc") },
    { Icon: Route, title: t("home.feature3_title"), desc: t("home.feature3_desc") },
    { Icon: FileText, title: t("home.feature4_title"), desc: t("home.feature4_desc") },
  ];

  const steps = [t("home.step1"), t("home.step2"), t("home.step3")];

  return (
    <div className="min-h-screen bg-paper">
      {/* Hero：整屏大图 + 压底渐变（杂志封面感，靠留白不靠玻璃卡） */}
      <section className="relative min-h-[92vh] flex flex-col">
        <div
          className="absolute inset-0 bg-cover bg-center"
          style={{
            backgroundImage:
              "url('https://images.unsplash.com/photo-1563336832-316dd7cb7df6?w=2000&q=80&auto=format&fit=crop')",
          }}
        />
        {/* 暖调压底：原来是 to-brand-900/80 的蓝紫渐变，改为中性深色，不抢图片本色 */}
        <div className="absolute inset-0 bg-gradient-to-b from-black/55 via-black/30 to-black/70" />
        <div className="img-scrim absolute inset-x-0 bottom-0 h-2/3" />

        <SiteHeader variant="overlay" />

        <div className="relative z-10 flex-1 flex flex-col justify-end">
          <div className="max-w-[1400px] w-full mx-auto px-4 sm:px-6 pb-16 sm:pb-24">
            <motion.div
              initial={{ opacity: 0, y: 24 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.7, ease: [0.22, 1, 0.36, 1] }}
              className="max-w-3xl"
            >
              <p className="text-[11px] tracking-[0.22em] uppercase text-white/70 mb-4">
                AI 旅行攻略
              </p>
              <h1 className="font-[family-name:var(--font-display)] text-[38px] leading-[1.15] sm:text-[56px] sm:leading-[1.08] text-white">
                {t("home.title")}
              </h1>
              <p className="mt-5 text-[15px] sm:text-[17px] leading-relaxed text-white/85 max-w-xl">
                {t("home.subtitle")}
              </p>

              <div className="mt-9">
                <Link
                  href="/recommend"
                  className="inline-flex items-center gap-2 h-12 px-7 rounded-[var(--radius-control)] bg-accent-500 hover:bg-accent-400 text-white text-[15px] font-medium transition-colors"
                >
                  {t("home.cta")}
                  <ArrowRight className="w-4 h-4" strokeWidth={1.8} />
                </Link>
              </div>
            </motion.div>
          </div>
        </div>
      </section>

      {/* 特色：从"半透明玻璃卡"改为纸面卡片（描边分层，不用阴影） */}
      <section className="max-w-[1400px] mx-auto px-4 sm:px-6 py-16 sm:py-20">
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          {features.map(({ Icon, title, desc }, i) => (
            <motion.div
              key={title}
              initial={{ opacity: 0, y: 14 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true }}
              transition={{ delay: i * 0.06, duration: 0.45 }}
              className="bg-surface border border-line rounded-[var(--radius-card)] p-5"
            >
              <Icon className="w-[18px] h-[18px] text-brand-700" strokeWidth={1.6} />
              <p className="mt-3.5 text-[15px] font-medium text-ink-900">{title}</p>
              <p className="mt-1.5 text-[13px] leading-relaxed text-ink-600 whitespace-pre-line">
                {desc}
              </p>
            </motion.div>
          ))}
        </div>

        {/* 流程：去掉蓝色圆点，改为细线 + 序号 */}
        <div className="mt-14 flex flex-wrap items-center gap-x-3 gap-y-3">
          {steps.map((s, i) => (
            <div key={s} className="flex items-center gap-3">
              <span className="flex items-center gap-2.5">
                <span className="w-6 h-6 rounded-full border border-line-strong text-ink-600 text-[11px] flex items-center justify-center">
                  {i + 1}
                </span>
                <span className="text-[13.5px] text-ink-700">{s}</span>
              </span>
              {i < steps.length - 1 && <span className="w-8 h-px bg-line-strong" />}
            </div>
          ))}
        </div>
      </section>

      <footer className="border-t border-line">
        <div className="max-w-[1400px] mx-auto px-4 sm:px-6 py-8 text-[12px] text-ink-400">
          {t("home.poweredBy")}
        </div>
      </footer>
    </div>
  );
}