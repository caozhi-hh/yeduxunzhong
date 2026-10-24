"use client";

import type { ReactNode } from "react";

/**
 * 分段切换 —— 用下划线指示，不用"实心黑胶囊"
 *
 * 改版前 trip 页用的是 `bg-gray-800 text-white` 的实心切换，观感偏工具/后台。
 * 杂志感的做法是细下划线 + 字重变化，安静但有明确指示。
 */

export interface TabItem {
  key: string;
  label: ReactNode;
  hint?: string;
}

export default function Tabs({
  items,
  value,
  onChange,
  className = "",
}: {
  items: TabItem[];
  value: string;
  onChange: (key: string) => void;
  className?: string;
}) {
  return (
    <div className={`flex items-center gap-5 border-b border-line ${className}`}>
      {items.map((it) => {
        const active = it.key === value;
        return (
          <button
            key={it.key}
            type="button"
            title={it.hint}
            onClick={() => onChange(it.key)}
            className={[
              "relative -mb-px pb-2 pt-1 text-sm transition-colors",
              active
                ? "text-ink-900 font-semibold"
                : "text-ink-600 hover:text-ink-900 font-normal",
            ].join(" ")}
          >
            {it.label}
            <span
              className={[
                "absolute left-0 right-0 -bottom-px h-[2px] rounded-full transition-opacity",
                active ? "bg-brand-700 opacity-100" : "opacity-0",
              ].join(" ")}
            />
          </button>
        );
      })}
    </div>
  );
}