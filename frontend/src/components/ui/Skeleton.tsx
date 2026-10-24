import type { ReactNode } from "react";

/**
 * 骨架屏 —— 内容未到时用**柔和 shimmer**，而不是灰块
 *
 * 这是"图片优先"体验的基本功：改版前照片未到就是一块 `bg-gray-100`，
 * 观感像坏掉了；现在统一用带微光的占位，让等待看起来是"正在来"。
 */

export function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`skeleton rounded-[var(--radius-image)] ${className}`} />;
}

/** 图片位骨架：固定宽高比，避免加载完成时页面跳动（CLS） */
export function ImageSkeleton({
  ratio = "16 / 10",
  className = "",
}: {
  ratio?: string;
  className?: string;
}) {
  return <div className={`skeleton w-full ${className}`} style={{ aspectRatio: ratio }} />;
}

/** 文本行骨架 */
export function LineSkeleton({ w = "100%" }: { w?: string }) {
  return <div className="skeleton h-3 rounded-full" style={{ width: w }} />;
}

/** 卡片骨架（图 + 两行字） */
export function CardSkeleton({ ratio = "16 / 10" }: { ratio?: string }) {
  return (
    <div className="bg-surface border border-line rounded-[var(--radius-card)] overflow-hidden">
      <ImageSkeleton ratio={ratio} className="rounded-none" />
      <div className="p-4 space-y-2.5">
        <LineSkeleton w="70%" />
        <LineSkeleton w="45%" />
      </div>
    </div>
  );
}

export function SkeletonGrid({ count = 6, ratio }: { count?: number; ratio?: string }) {
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
      {Array.from({ length: count }).map((_, i) => (
        <CardSkeleton key={i} ratio={ratio} />
      ))}
    </div>
  );
}

/**
 * 空态 —— 统一"没内容"的表达
 * 改版前各处只有一句 `text-gray-400` 文字，没有引导也没有视觉。
 */
export function EmptyState({
  icon,
  title,
  desc,
  action,
  className = "",
}: {
  icon?: ReactNode;
  title: string;
  desc?: string;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={`flex flex-col items-center justify-center text-center py-14 px-6 ${className}`}
    >
      {icon && <div className="text-ink-300 mb-3 [&>svg]:w-7 [&>svg]:h-7">{icon}</div>}
      <p className="text-[15px] font-medium text-ink-700">{title}</p>
      {desc && <p className="mt-1.5 text-[13px] text-ink-400 max-w-sm leading-relaxed">{desc}</p>}
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}