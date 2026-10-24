import type { ReactNode } from "react";

/**
 * 分节标题 —— 杂志式排版的基本单元
 *
 * 结构：小号英文/点缀标签（eyebrow）→ 衬线大标题 → 可选说明与右侧动作。
 * 改版前各页面的小标题都是 `text-sm font-bold text-gray-700`，层级拉不开，
 * 整页看上去"平"。这里把层级固定下来：标题用衬线、字号明显大于正文。
 */
export default function SectionHeader({
  eyebrow,
  title,
  desc,
  action,
  className = "",
}: {
  eyebrow?: ReactNode;
  title: ReactNode;
  desc?: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div className={`flex items-end justify-between gap-4 ${className}`}>
      <div className="min-w-0">
        {eyebrow && (
          <p className="text-[11px] tracking-[0.14em] uppercase text-ink-400 mb-1.5">{eyebrow}</p>
        )}
        <h2 className="text-[22px] sm:text-[26px] leading-tight text-ink-900">{title}</h2>
        {desc && <p className="mt-2 text-[13.5px] text-ink-600 leading-relaxed max-w-2xl">{desc}</p>}
      </div>
      {action && <div className="shrink-0">{action}</div>}
    </div>
  );
}