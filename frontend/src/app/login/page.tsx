"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { motion } from "framer-motion";
import { useForm } from "react-hook-form";
import { useAuth } from "@/lib/auth";
import LanguageSwitcher from "@/components/LanguageSwitcher";

interface LoginFormData {
  username: string;
  password: string;
}

export default function LoginPage() {
  const router = useRouter();
  const { isAuthenticated, loading: authLoading, login, register } = useAuth();

  const [tab, setTab] = useState<"login" | "register">("login");
  const [serverError, setServerError] = useState("");

  const {
    register: regField,
    handleSubmit,
    formState: { errors, isSubmitting },
    reset,
  } = useForm<LoginFormData>({
    mode: "onBlur",
    defaultValues: { username: "", password: "" },
  });

  useEffect(() => {
    if (!authLoading && isAuthenticated) {
      router.replace("/");
    }
  }, [isAuthenticated, authLoading]);

  const onSubmit = async (data: LoginFormData) => {
    setServerError("");
    try {
      if (tab === "login") {
        await login(data.username.trim(), data.password);
      } else {
        await register({ username: data.username.trim(), password: data.password });
      }
      router.replace("/");
    } catch (e: any) {
      setServerError(e.message || (tab === "login" ? "登录失败" : "注册失败"));
    }
  };

  const switchTab = (newTab: "login" | "register") => {
    setTab(newTab);
    setServerError("");
    reset({ username: "", password: "" });
  };

  if (authLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-blue-100 via-blue-200 to-indigo-300">
        <div className="flex flex-col items-center gap-4">
          <div className="relative w-14 h-14">
            <div className="absolute inset-0 rounded-full border-4 border-blue-200" />
            <div className="absolute inset-0 rounded-full border-4 border-transparent border-t-blue-500 animate-spin" />
          </div>
          <p className="text-blue-600/60 text-sm font-medium">加载中...</p>
        </div>
      </div>
    );
  }

  if (isAuthenticated) return null;

  return (
    <div className="relative min-h-screen flex items-center justify-center overflow-hidden">
      {/* 绝美风景背景图 */}
      <div
        className="absolute inset-0 bg-cover bg-center bg-no-repeat scale-105"
        style={{
          backgroundImage:
            "url('https://images.unsplash.com/photo-1563336832-316dd7cb7df6?w=1400&q=80&auto=format&fit=crop')",
        }}
      />
      {/* 渐变遮罩：确保文字可读 */}
      <div className="absolute inset-0 bg-gradient-to-br from-black/60 via-blue-900/40 to-indigo-900/60" />
      {/* 底部光晕 */}
      <div className="absolute bottom-0 left-0 right-0 h-1/3 bg-gradient-to-t from-blue-900/50 to-transparent pointer-events-none" />

      <div className="absolute top-4 right-4 z-10">
        <LanguageSwitcher />
      </div>

      <motion.div
        initial={{ opacity: 0, y: 30, scale: 0.95 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        transition={{ duration: 0.6, ease: [0.25, 0.46, 0.45, 0.94] }}
        className="relative z-10 w-full max-w-md mx-4"
      >
        {/* 品牌区 */}
        <div className="text-center mb-8">
          <motion.div
            initial={{ scale: 0.5, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            transition={{ type: "spring", stiffness: 200, delay: 0.1 }}
            className="inline-flex items-center justify-center w-16 h-16 rounded-2xl bg-gradient-to-br from-blue-500 to-indigo-600 shadow-xl shadow-blue-400/40 mb-4 backdrop-blur-sm"
          >
            <span className="text-3xl">🧭</span>
          </motion.div>
          <h1 className="text-4xl font-extrabold text-white mb-2 drop-shadow-lg">野渡寻踪</h1>
          <p className="text-blue-100/80 text-sm font-medium drop-shadow">AI 智能旅行攻略规划师</p>
        </div>

        {/* 表单卡片 */}
        <div className="bg-white/90 backdrop-blur-xl rounded-3xl shadow-2xl shadow-blue-200/40 overflow-hidden">
          <div className="flex border-b border-blue-50">
            <button
              onClick={() => switchTab("login")}
              className={`flex-1 py-4 text-sm font-semibold transition-all ${
                tab === "login"
                  ? "text-blue-600 border-b-2 border-blue-500 bg-blue-50/60"
                  : "text-gray-400 hover:text-blue-500"
              }`}
            >
              登录
            </button>
            <button
              onClick={() => switchTab("register")}
              className={`flex-1 py-4 text-sm font-semibold transition-all ${
                tab === "register"
                  ? "text-blue-600 border-b-2 border-blue-500 bg-blue-50/60"
                  : "text-gray-400 hover:text-blue-500"
              }`}
            >
              注册
            </button>
          </div>

          <form onSubmit={handleSubmit(onSubmit)} noValidate className="p-6 sm:p-8">
            {serverError && (
              <motion.div
                initial={{ opacity: 0, y: -5 }}
                animate={{ opacity: 1, y: 0 }}
                className="mb-4 px-4 py-2.5 rounded-xl bg-red-50 text-red-600 text-sm border border-red-100"
              >
                {serverError}
              </motion.div>
            )}

            <div className="space-y-4">
              <div>
                <div className="relative">
                  <span className="absolute left-3.5 top-1/2 -translate-y-1/2 text-gray-400 text-sm">👤</span>
                  <input
                    type="text"
                    placeholder="用户名"
                    {...regField("username", {
                      required: "请输入用户名",
                      minLength: { value: 2, message: "用户名至少2个字符" },
                      maxLength: { value: 20, message: "用户名最多20个字符" },
                    })}
                    className={`w-full pl-10 pr-4 py-3.5 rounded-xl border outline-none transition-all text-sm bg-white/80 ${
                      errors.username
                        ? "border-red-300 focus:border-red-400 focus:ring-2 focus:ring-red-100"
                        : "border-gray-200 focus:border-blue-400 focus:ring-2 focus:ring-blue-100"
                    }`}
                  />
                </div>
                {errors.username && (
                  <p className="mt-1.5 text-xs text-red-500 pl-1">{errors.username.message}</p>
                )}
              </div>

              <div>
                <div className="relative">
                  <span className="absolute left-3.5 top-1/2 -translate-y-1/2 text-gray-400 text-sm">🔒</span>
                  <input
                    type="password"
                    placeholder="密码"
                    {...regField("password", {
                      required: "请输入密码",
                      minLength: tab === "register"
                        ? { value: 6, message: "密码至少6位" }
                        : undefined,
                    })}
                    className={`w-full pl-10 pr-4 py-3.5 rounded-xl border outline-none transition-all text-sm bg-white/80 ${
                      errors.password
                        ? "border-red-300 focus:border-red-400 focus:ring-2 focus:ring-red-100"
                        : "border-gray-200 focus:border-blue-400 focus:ring-2 focus:ring-blue-100"
                    }`}
                  />
                </div>
                {errors.password && (
                  <p className="mt-1.5 text-xs text-red-500 pl-1">{errors.password.message}</p>
                )}
              </div>

              <motion.button
                type="submit"
                whileHover={{ scale: 1.01 }}
                whileTap={{ scale: 0.98 }}
                disabled={isSubmitting}
                className="w-full py-3.5 rounded-xl bg-gradient-to-r from-blue-500 to-indigo-500 text-white font-semibold shadow-lg shadow-blue-500/25 hover:shadow-blue-400/40 transition-all disabled:opacity-60 disabled:hover:scale-100"
              >
                {isSubmitting ? (
                  <span className="flex items-center justify-center gap-2">
                    <span className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                    请稍候...
                  </span>
                ) : tab === "login" ? "登录" : "注册"}
              </motion.button>
            </div>

            {tab === "login" && (
              <p className="text-center text-xs text-gray-400 mt-4">没有账号？点上方「注册」</p>
            )}
          </form>
        </div>

        <p className="text-center mt-6 text-xs text-white/30">Powered by LangChain + Qwen</p>
      </motion.div>
    </div>
  );
}
