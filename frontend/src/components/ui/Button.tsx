import type { ButtonHTMLAttributes, ReactNode } from "react";

/**
 * 按钮 —— 全站唯一的按钮实现
 *
 * 为什么要有它：改版前按钮样式散落在各页面（`bg-blue-500 hover:bg-blue-400`
 * 这类硬编码 14 处以上），且是"科技蓝 + 大阴影"，与高端旅行杂志感不符。
 * 这里统一成：主色墨绿、强调色赭石橙、描边式次按钮，阴影只保留极淡一层。
 *
 * variant:
 *   primary 深墨绿实心（主要动作）
 *   accent  赭石橙实心（页面唯一的主 CTA，慎用，一屏最多一个）
 *   outline 白底 + 描边（次动作）
 *   ghost   透明（弱动作、图标按钮）
 */

type Variant = "primary" | "accent" | "outline" | "ghost" | "danger";
type Size = "sm" | "md" | "lg";

const VARIANTS: Record<Variant, string> = {
  primary:
    "bg-brand-700 text-white hover:bg-brand-600 active:bg-brand-800 shadow-[0_1px_2px_rgb(0_0_0/0.06)]",
  accent:
    "bg-accent-500 text-white hover:bg-accent-400 active:bg-accent-600 shadow-[0_1px_2px_rgb(0_0_0/0.06)]",
  outline: "bg-surface text-ink-900 border border-line hover:border-line-strong hover:bg-paper-2",
  ghost: "bg-transparent text-ink-600 hover:bg-paper-2 hover:text-ink-900",
  danger: "bg-transparent text-danger-500 hover:bg-danger-500/8",
};

const SIZES: Record<Size, string> = {
  sm: "h-8 px-3 text-[13px] gap-1.5",
  md: "h-10 px-4 text-sm gap-2",
  lg: "h-12 px-6 text-[15px] gap-2",
};

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  icon?: ReactNode;
  block?: boolean;
}

export default function Button({
  variant = "primary",
  size = "md",
  icon,
  block,
  className = "",
  children,
  ...rest
}: ButtonProps) {
  return (
    <button
      {...rest}
      className={[
        "inline-flex items-center justify-center rounded-[var(--radius-control)]",
        "font-medium transition-colors duration-150 select-none",
        "disabled:opacity-40 disabled:pointer-events-none",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-400/50",
        VARIANTS[variant],
        SIZES[size],
        block ? "w-full" : "",
        className,
      ]
        .filter(Boolean)
        .join(" ")}
    >
      {icon && <span className="shrink-0 [&>svg]:w-4 [&>svg]:h-4">{icon}</span>}
      {children}
    </button>
  );
}