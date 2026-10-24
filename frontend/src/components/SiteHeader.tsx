"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Compass } from "lucide-react";
import LanguageSwitcher from "@/components/LanguageSwitcher";
import UserNav from "@/components/UserNav";

/**
 * 全站头部 —— 5 个页面原本各写一遍同样的头部标记，这里统一
 *
 * variant:
 *   solid   暖白底 + 细描边（内页用）
 *   overlay 透明浮在大图上、白字（首页 Hero 用）
 *
 * 注意：Demo 阶段不强制登录，未登录时 UserNav 自身返回 null（它已这样实现），
 * 所以头部不会出现"登录/注册"这类拦人的元素。
 */

// 注意：/explore（目的地探索页）属于 P2，尚未创建 —— 这里先不放，
// 避免 Demo 里出现点进去 404 的死链。P2 建好后再补上。
const NAV = [
  { href: "/", label: "首页" },
  { href: "/recommend", label: "开始规划" },
];

export default function SiteHeader({
  variant = "solid",
  className = "",
}: {
  variant?: "solid" | "overlay";
  className?: string;
}) {
  const pathname = usePathname();
  const overlay = variant === "overlay";

  return (
    <header
      className={[
        "z-30 w-full",
        overlay
          ? "absolute top-0 left-0 right-0 bg-transparent"
          : "sticky top-0 bg-paper/85 backdrop-blur-md border-b border-line",
        className,
      ]
        .filter(Boolean)
        .join(" ")}
    >
      <div className="max-w-[1400px] mx-auto h-14 px-4 sm:px-6 flex items-center gap-6">
        {/* 品牌 */}
        <Link
          href="/"
          className={`flex items-center gap-2 shrink-0 ${overlay ? "text-white" : "text-ink-900"}`}
        >
          <Compass
            className={`w-[18px] h-[18px] ${overlay ? "text-white" : "text-brand-700"}`}
            strokeWidth={1.6}
          />
          <span className="font-[family-name:var(--font-display)] text-[17px] tracking-tight">
            野渡寻踪
          </span>
        </Link>

        {/* 导航 */}
        <nav className="hidden sm:flex items-center gap-1">
          {NAV.map((n) => {
            const active = pathname === n.href;
            return (
              <Link
                key={n.href}
                href={n.href}
                className={[
                  "px-3 py-1.5 rounded-[var(--radius-control)] text-[13.5px] transition-colors",
                  overlay
                    ? active
                      ? "text-white bg-white/15"
                      : "text-white/75 hover:text-white hover:bg-white/10"
                    : active
                      ? "text-ink-900 bg-paper-2 font-medium"
                      : "text-ink-600 hover:text-ink-900 hover:bg-paper-2",
                ].join(" ")}
              >
                {n.label}
              </Link>
            );
          })}
        </nav>

        <div className="ml-auto flex items-center gap-2">
          <LanguageSwitcher />
          <UserNav />
        </div>
      </div>
    </header>
  );
}