"use client";

import { useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { useAuth } from "@/lib/auth";

interface AuthModalProps {
  open: boolean;
  onClose: () => void;
  defaultTab?: "login" | "register";
}

export default function AuthModal({ open, onClose, defaultTab = "login" }: AuthModalProps) {
  const { login, register } = useAuth();
  const [tab, setTab] = useState<"login" | "register">(defaultTab);
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

  const resetForm = () => {
    setError("");
    setAccount("");
    setLoginPwd("");
    setNickname("");
    setPhone("");
    setEmail("");
    setRegPwd("");
  };

  const handleTab = (t: "login" | "register") => {
    setTab(t);
    setError("");
  };

  const handleLogin = async () => {
    if (!account.trim() || !loginPwd) {
      setError("请填写手机号/邮箱和密码");
      return;
    }
    setSubmitting(true);
    setError("");
    try {
      await login(account.trim(), loginPwd);
      resetForm();
      onClose();
    } catch (e: any) {
      setError(e.message || "登录失败");
    } finally {
      setSubmitting(false);
    }
  };

  const handleRegister = async () => {
    if (!nickname.trim() || !phone.trim() || !email.trim() || !regPwd) {
      setError("请填写所有字段");
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
      resetForm();
      onClose();
    } catch (e: any) {
      setError(e.message || "注册失败");
    } finally {
      setSubmitting(false);
    }
  };

  const handleOverlayClick = (e: React.MouseEvent) => {
    if (e.target === e.currentTarget) onClose();
  };

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.2 }}
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm"
          onClick={handleOverlayClick}
        >
          <motion.div
            initial={{ opacity: 0, scale: 0.9, y: 20 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.9, y: 20 }}
            transition={{ duration: 0.25 }}
            className="bg-white rounded-2xl shadow-2xl w-full max-w-md mx-4 overflow-hidden"
          >
            {/* Tabs */}
            <div className="flex border-b border-gray-100">
              <button
                onClick={() => handleTab("login")}
                className={`flex-1 py-3.5 text-sm font-semibold transition-colors ${
                  tab === "login"
                    ? "text-emerald-600 border-b-2 border-emerald-500"
                    : "text-gray-400 hover:text-gray-600"
                }`}
              >
                登录
              </button>
              <button
                onClick={() => handleTab("register")}
                className={`flex-1 py-3.5 text-sm font-semibold transition-colors ${
                  tab === "register"
                    ? "text-emerald-600 border-b-2 border-emerald-500"
                    : "text-gray-400 hover:text-gray-600"
                }`}
              >
                注册
              </button>
            </div>

            <div className="p-6">
              {error && (
                <div className="mb-4 px-3 py-2 rounded-lg bg-red-50 text-red-600 text-sm">
                  {error}
                </div>
              )}

              {tab === "login" ? (
                <div className="space-y-4">
                  <input
                    type="text"
                    placeholder="手机号 / 邮箱"
                    value={account}
                    onChange={(e) => setAccount(e.target.value)}
                    className="w-full px-4 py-3 rounded-xl border border-gray-200 focus:border-emerald-400 focus:ring-2 focus:ring-emerald-100 outline-none transition-all text-sm"
                  />
                  <input
                    type="password"
                    placeholder="密码"
                    value={loginPwd}
                    onChange={(e) => setLoginPwd(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && handleLogin()}
                    className="w-full px-4 py-3 rounded-xl border border-gray-200 focus:border-emerald-400 focus:ring-2 focus:ring-emerald-100 outline-none transition-all text-sm"
                  />
                  <button
                    onClick={handleLogin}
                    disabled={submitting}
                    className="w-full py-3 rounded-xl bg-gradient-to-r from-emerald-500 to-emerald-400 text-white font-semibold shadow-lg shadow-emerald-500/25 hover:shadow-emerald-400/40 hover:-translate-y-0.5 transition-all disabled:opacity-60 disabled:hover:translate-y-0"
                  >
                    {submitting ? "登录中..." : "登录"}
                  </button>
                </div>
              ) : (
                <div className="space-y-4">
                  <input
                    type="text"
                    placeholder="昵称"
                    value={nickname}
                    onChange={(e) => setNickname(e.target.value)}
                    className="w-full px-4 py-3 rounded-xl border border-gray-200 focus:border-emerald-400 focus:ring-2 focus:ring-emerald-100 outline-none transition-all text-sm"
                  />
                  <input
                    type="tel"
                    placeholder="手机号"
                    value={phone}
                    onChange={(e) => setPhone(e.target.value)}
                    className="w-full px-4 py-3 rounded-xl border border-gray-200 focus:border-emerald-400 focus:ring-2 focus:ring-emerald-100 outline-none transition-all text-sm"
                  />
                  <input
                    type="email"
                    placeholder="邮箱"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    className="w-full px-4 py-3 rounded-xl border border-gray-200 focus:border-emerald-400 focus:ring-2 focus:ring-emerald-100 outline-none transition-all text-sm"
                  />
                  <input
                    type="password"
                    placeholder="密码"
                    value={regPwd}
                    onChange={(e) => setRegPwd(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && handleRegister()}
                    className="w-full px-4 py-3 rounded-xl border border-gray-200 focus:border-emerald-400 focus:ring-2 focus:ring-emerald-100 outline-none transition-all text-sm"
                  />
                  <button
                    onClick={handleRegister}
                    disabled={submitting}
                    className="w-full py-3 rounded-xl bg-gradient-to-r from-emerald-500 to-emerald-400 text-white font-semibold shadow-lg shadow-emerald-500/25 hover:shadow-emerald-400/40 hover:-translate-y-0.5 transition-all disabled:opacity-60 disabled:hover:translate-y-0"
                  >
                    {submitting ? "注册中..." : "注册"}
                  </button>
                </div>
              )}
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
