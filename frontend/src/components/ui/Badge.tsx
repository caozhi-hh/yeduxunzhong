import type { ReactNode } from "react";

/**
 * 徽标 / 标签 —— 统一"小胶囊"的观感
 *
 * 改版前每处都手写 `text-xs px-2 py-0.5 bg-blue-50 text-blue-700 rounded-full`，
 * 颜色与圆角各不相同。这里固定 4 种语义色调。
 */

type Tone = "brand" | "accent" | "neutral" | "outline";

const TONES: Record<Tone, string> = {
  brand: "bg-brand-50 text-brand-700 border-brand-100",
  accent: "bg-accent-50 text-accent-700 border-accent-100",
  neutral: "bg-paper-2 text-ink-600 border-line",
  outline: "bg-transparent text-ink-600 border-line-strong",
};

export default function Badge({
  tone = "neutral",
  children,
  className = "",
}: {
  tone?: Tone;
  children: ReactNode;
  className?: string;
}) {
  return (
    <span
      className={[
        "inline-flex items-center gap-1 rounded-full border px-2 py-0.5",
        "text-[11px] leading-5 font-medium whitespace-nowrap",
        TONES[tone],
        className,
      ]
        .filter(Boolean)
        .join(" ")}
    >
      {children}
    </span>
  );
}