import type {
  InputHTMLAttributes,
  ReactNode,
  SelectHTMLAttributes,
  TextareaHTMLAttributes,
} from "react";

/**
 * 表单控件 —— 统一输入框 / 文本域 / 下拉
 *
 * 改版前每个输入框都手写一长串 `w-full px-3 py-2 rounded-xl border border-gray-200
 * text-sm focus:outline-none focus:ring-2 focus:ring-blue-400`，且聚焦环是蓝色。
 * 这里统一：暖白底、细描边、聚焦时墨绿细环（克制，不用粗蓝环）。
 */

const BASE =
  "w-full bg-surface text-ink-900 placeholder:text-ink-400 border border-line " +
  "rounded-[var(--radius-control)] transition-colors duration-150 " +
  "focus:outline-none focus:border-brand-400 focus:ring-2 focus:ring-brand-400/25 " +
  "disabled:opacity-50";

export function Input({ className = "", ...rest }: InputHTMLAttributes<HTMLInputElement>) {
  return <input {...rest} className={`${BASE} h-10 px-3 text-sm ${className}`} />;
}

export function Textarea({
  className = "",
  ...rest
}: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea {...rest} className={`${BASE} px-3 py-2.5 text-sm resize-y ${className}`} />;
}

export function Select({
  className = "",
  children,
  ...rest
}: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select {...rest} className={`${BASE} h-10 px-3 pr-8 text-sm cursor-pointer ${className}`}>
      {children}
    </select>
  );
}

/** 表单字段包装：标签 + 说明 + 错误提示，保证全站间距一致 */
export function Field({
  label,
  hint,
  error,
  children,
  className = "",
}: {
  label?: ReactNode;
  hint?: ReactNode;
  error?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={`space-y-1.5 ${className}`}>
      {label && <label className="block text-[13px] font-medium text-ink-700">{label}</label>}
      {children}
      {error ? (
        <p className="text-[12px] text-danger-500">{error}</p>
      ) : (
        hint && <p className="text-[12px] text-ink-400">{hint}</p>
      )}
    </div>
  );
}