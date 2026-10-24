"use client";

import { useState, useEffect } from "react";
import { motion } from "framer-motion";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";
import { fetchHistory, deletePlan, fetchPlan } from "@/lib/api";
import PlanCard from "@/components/PlanCard";
import UserNav from "@/components/UserNav";
import LanguageSwitcher from "@/components/LanguageSwitcher";

export default function HistoryPage() {
  const router = useRouter();
  const { isAuthenticated, loading: authLoading } = useAuth();
  const [plans, setPlans] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!authLoading && !isAuthenticated) {
      router.push("/");
      return;
    }
    if (isAuthenticated) loadPlans();
  }, [isAuthenticated, authLoading]);

  const loadPlans = async () => {
    setLoading(true);
    const data = await fetchHistory();
    setPlans(data);
    setLoading(false);
  };

  const handleDelete = async (id: number) => {
    if (!confirm("确定删除这条攻略？")) return;
    const ok = await deletePlan(id);
    if (ok) setPlans((prev) => prev.filter((p) => p.id !== id));
  };

  const handleLoad = async (id: number) => {
    const data = await fetchPlan(id);
    if (!data?.plan) return;
    const p = data.plan;
    // 恢复到 plan 页面
    if (p.spots) localStorage.setItem("yedu_selected_spots", JSON.stringify(p.spots));
    if (p.plan_text) localStorage.setItem("yedu_plan", p.plan_text);
    // 2026-10-10 修复：这里以前写的是 yedu_session_params，而 plan 页读的是
    // yedu_user_params —— key 不一致，导致"从历史打开后继续修改，改动再也回写不了"
    if (p.params) localStorage.setItem("yedu_user_params", JSON.stringify(p.params));
    // 记住这份攻略的 id：后续修改就地更新同一条，而不是又新增一条
    if (p.id) localStorage.setItem("yedu_plan_id", String(p.id));
    if (p.recommendation) localStorage.setItem("yedu_recommendation", p.recommendation);
    if (p.to_city) localStorage.setItem("yedu_to_city", p.to_city);
    router.push("/plan");
  };

  if (authLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-paper-2">
        <div className="w-8 h-8 border-3 border-brand-200 border-t-blue-500 rounded-full animate-spin" />
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gradient-to-b from-paper-2 to-brand-50/30">
      <nav className="sticky top-0 z-20 bg-surface/80 backdrop-blur-xl border-b border-line/50 px-4 py-3 flex items-center justify-between ">
        <button onClick={() => router.push("/")} className="text-brand-600 font-medium hover:text-blue-700 flex items-center gap-1">
          <span>←</span> 首页
        </button>
        <h1 className="text-lg font-bold text-ink-900">历史攻略</h1>
        <div className="flex items-center gap-2">
          <LanguageSwitcher />
          <UserNav />
        </div>
      </nav>

      <div className="max-w-2xl mx-auto px-4 py-6">
        {loading ? (
          <div className="flex flex-col items-center justify-center py-20">
            <div className="w-8 h-8 border-3 border-brand-200 border-t-blue-500 rounded-full animate-spin mb-3" />
            <p className="text-ink-400 text-sm">加载中...</p>
          </div>
        ) : plans.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-20 text-ink-400">
            <div className="text-5xl mb-4">📋</div>
            <p className="mb-2">还没有历史攻略</p>
            <button
              onClick={() => router.push("/recommend")}
              className="mt-4 px-6 py-2 bg-brand-700 hover:bg-brand-600 text-white text-sm font-medium rounded-full transition-all"
            >
              去生成一份
            </button>
          </div>
        ) : (
          <div className="grid gap-4">
            {plans.map((p) => (
              <PlanCard
                key={p.id}
                plan={p}
                onClick={() => handleLoad(p.id)}
                onDelete={() => handleDelete(p.id)}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
