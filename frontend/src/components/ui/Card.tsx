import type { HTMLAttributes, ReactNode } from "react";

/**
 * 卡片 —— 用**描边**分层，不用阴影
 *
 * 这是本次视觉方向的关键决定：改版前靠 `shadow-sm`（22 处）+ `rounded-2xl`（31 处）
 * 堆层次，观感偏"后台管理系统"。高端杂志的做法是**细描边 + 留白**，
 * 阴影只在需要"浮起来"的元素（浮层、悬停）上出现。
 */

export interface CardProps extends HTMLAttributes<HTMLDivElement> {
  /** 无内边距（图片铺满型卡片用） */
  flush?: boolean;
  /** 悬停时轻微抬起（可点击的卡片用） */
  interactive?: boolean;
  children: ReactNode;
}

export default function Card({
  flush,
  interactive,
  className = "",
  children,
  ...rest
}: CardProps) {
  return (
    <div
      {...rest}
      className={[
        "bg-surface border border-line rounded-[var(--radius-card)] overflow-hidden",
        flush ? "" : "p-4 sm:p-5",
        interactive
          ? "transition-[border-color,transform,box-shadow] duration-200 hover:border-line-strong hover:-translate-y-0.5 hover:shadow-[0_6px_24px_-12px_rgb(0_0_0/0.18)] cursor-pointer"
          : "",
        className,
      ]
        .filter(Boolean)
        .join(" ")}
    >
      {children}
    </div>
  );
}