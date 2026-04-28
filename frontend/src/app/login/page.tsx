"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { motion } from "framer-motion";
import { useTranslation } from "react-i18next";
import { useAuth } from "@/lib/auth";
import LanguageSwitcher from "@/components/LanguageSwitcher";

export default function LoginPage() {
  const router = useRouter();
  const { isAuthenticated, loading: authLoading, login, register } = useAuth();
  const { t } = useTranslation();

  const [tab, setTab] = useState<"login" | "register">("login");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  // Login fields
  const [account, setAccount] = useState("");
  const [loginPwd, setLoginPwd] = useState("");

  // Register fields
  const [nickname, setNickname] = useState("");
  const [phone, setPhone] = useState("");
  const [email, setEmail] = useState("");
  const [regPwd, setRegPwd] = useState("");

  useEffect(() => {
    if (!authLoading && isAuthenticated) {
      router.replace("/");
    }
  }, [isAuthenticated, authLoading]);

  const handleLogin = async () => {
    if (!account.trim() || !loginPwd) {
      setError(t("auth.phone_email") + " / " + t("auth.password"));
      return;
    }
    setSubmitting(true);
    setError("");
    try {
      await login(account.trim(), loginPwd);
      router.replace("/");
    } catch (e: any) {
      setError(e.message || "Login failed");
    } finally {
      setSubmitting(false);
    }
  };

  const handleRegister = async () => {
    if (!nickname.trim() || !phone.trim() || !email.trim() || !regPwd) {
      setError("Please fill all fields");
      return;
    }
    setSubmitting(true);
    setError("");
    try {
      await register({
        nickname: nickname.trim(),
        phone: phone.trim(),
        email: email.trim(),
        password: regPwd,
      });
      router.replace("/");
    } catch (e: any) {
      setError(e.message || "Register failed");
    } finally {
      setSubmitting(false);
    }
  };

  if (authLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gradient-to-b from-gray-900 to-emerald-900">
        <div className="w-10 h-10 border-4 border-emerald-300/30 border-t-emerald-400 rounded-full animate-spin" />
      </div>
    );
  }

  if (isAuthenticated) return null;

  return (
    <div className="relative min-h-screen flex items-center justify-center overflow-hidden">
      {/* 背景 */}
      <div
        className="absolute inset-0 bg-cover bg-center bg-no-repeat"
        style={{
          backgroundImage:
            "url('https://images.unsplash.com/photo-1469854523086-cc02fe5d8800?w=1920&q=80')",
        }}
      />
      <div className="absolute inset-0 bg-gradient-to-br from-black/70 via-black/50 to-emerald-900/80" />

      {/* 语言切换 */}
      <div className="absolute top-4 right-4 z-10">
        <LanguageSwitcher />
      </div>

      {/* 登录卡片 */}
      <motion.div
        initial={{ opacity: 0, y: 30, scale: 0.95 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        transition={{ duration: 0.5 }}
        className="relative z-10 w-full max-w-md mx-4"
      >
        {/* 品牌 */}
        <div className="text-center mb-8">
          <h1 className="text-4xl font-extrabold text-white mb-2 drop-shadow-lg">🌿 野渡寻踪</h1>
          <p className="text-emerald-200/80 text-sm">AI 智能旅行攻略规划师</p>
        </div>

        {/* 卡片 */}
        <div className="bg-white/95 backdrop-blur-xl rounded-3xl shadow-2xl overflow-hidden">
          {/* Tabs */}
          <div className="flex border-b border-gray-100">
            <button
              onClick={() => { setTab("login"); setError(""); }}
              className={`flex-1 py-4 text-sm font-semibold transition-colors ${
                tab === "login"
                  ? "text-emerald-600 border-b-2 border-emerald-500 bg-emerald-50/50"
                  : "text-gray-400 hover:text-gray-600"
              }`}
            >
              {t("auth.login")}
            </button>
            <button
              onClick={() => { setTab("register"); setError(""); }}
              className={`flex-1 py-4 text-sm font-semibold transition-colors ${
                tab === "register"
                  ? "text-emerald-600 border-b-2 border-emerald-500 bg-emerald-50/50"
                  : "text-gray-400 hover:text-gray-600"
              }`}
            >
              {t("auth.register")}
            </button>
          </div>

          <div className="p-6 sm:p-8">
            {error && (
              <div className="mb-4 px-4 py-2.5 rounded-xl bg-red-50 text-red-600 text-sm border border-red-100">
                {error}
              </div>
            )}

            {tab === "login" ? (
              <div className="space-y-4">
                <input
                  type="text"
                  placeholder={t("auth.phone_email")}
                  value={account}
                  onChange={(e) => setAccount(e.target.value)}
                  className="w-full px-4 py-3.5 rounded-xl border border-gray-200 focus:border-emerald-400 focus:ring-2 focus:ring-emerald-100 outline-none transition-all text-sm bg-gray-50/50"
                />
                <input
                  type="password"
                  placeholder={t("auth.password")}
                  value={loginPwd}
                  onChange={(e) => setLoginPwd(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && handleLogin()}
                  className="w-full px-4 py-3.5 rounded-xl border border-gray-200 focus:border-emerald-400 focus:ring-2 focus:ring-emerald-100 outline-none transition-all text-sm bg-gray-50/50"
                />
                <button
                  onClick={handleLogin}
                  disabled={submitting}
                  className="w-full py-3.5 rounded-xl bg-gradient-to-r from-emerald-500 to-teal-500 text-white font-semibold shadow-lg shadow-emerald-500/25 hover:shadow-emerald-400/40 hover:-translate-y-0.5 transition-all disabled:opacity-60 disabled:hover:translate-y-0"
                >
                  {submitting ? t("auth.loggingIn") : t("auth.login")}
                </button>
              </div>
            ) : (
              <div className="space-y-3.5">
                <input
                  type="text"
                  placeholder={t("auth.nickname")}
                  value={nickname}
                  onChange={(e) => setNickname(e.target.value)}
                  className="w-full px-4 py-3 rounded-xl border border-gray-200 focus:border-emerald-400 focus:ring-2 focus:ring-emerald-100 outline-none transition-all text-sm bg-gray-50/50"
                />
                <input
                  type="tel"
                  placeholder={t("auth.phone")}
                  value={phone}
                  onChange={(e) => setPhone(e.target.value)}
                  className="w-full px-4 py-3 rounded-xl border border-gray-200 focus:border-emerald-400 focus:ring-2 focus:ring-emerald-100 outline-none transition-all text-sm bg-gray-50/50"
                />
                <input
                  type="email"
                  placeholder={t("auth.email")}
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  className="w-full px-4 py-3 rounded-xl border border-gray-200 focus:border-emerald-400 focus:ring-2 focus:ring-emerald-100 outline-none transition-all text-sm bg-gray-50/50"
                />
                <input
                  type="password"
                  placeholder={t("auth.password")}
                  value={regPwd}
                  onChange={(e) => setRegPwd(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && handleRegister()}
                  className="w-full px-4 py-3 rounded-xl border border-gray-200 focus:border-emerald-400 focus:ring-2 focus:ring-emerald-100 outline-none transition-all text-sm bg-gray-50/50"
                />
                <button
                  onClick={handleRegister}
                  disabled={submitting}
                  className="w-full py-3.5 rounded-xl bg-gradient-to-r from-emerald-500 to-teal-500 text-white font-semibold shadow-lg shadow-emerald-500/25 hover:shadow-emerald-400/40 hover:-translate-y-0.5 transition-all disabled:opacity-60 disabled:hover:translate-y-0"
                >
                  {submitting ? t("auth.registering") : t("auth.register")}
                </button>
              </div>
            )}
          </div>
        </div>

        <p className="text-center mt-6 text-xs text-white/30">Powered by LangGraph + 豆包</p>
      </motion.div>
    </div>
  );
}
