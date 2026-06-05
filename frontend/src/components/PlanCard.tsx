"use client";

import { motion } from "framer-motion";

interface PlanCardProps {
  plan: {
    id: number;
    title: string;
    from_city: string;
    to_city: string;
    days: number;
    budget: number;
    dep_date: string;
    ret_date: string;
    spots: string[];
    created_at: string;
  };
  onClick: () => void;
  onDelete: () => void;
}

export default function PlanCard({ plan, onClick, onDelete }: PlanCardProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      className="bg-white rounded-2xl border border-gray-100 shadow-sm hover:shadow-md hover:-translate-y-0.5 transition-all overflow-hidden"
    >
      <div onClick={onClick} className="cursor-pointer p-4 sm:p-5">
        <div className="flex items-start justify-between gap-2 mb-3">
          <h3 className="font-bold text-gray-800 text-base truncate">
            {plan.title || `${plan.to_city} ${plan.days}日游`}
          </h3>
          <span className="text-xs text-gray-400 whitespace-nowrap">
            {plan.created_at?.slice(0, 10)}
          </span>
        </div>

        <div className="flex flex-wrap gap-2 text-xs text-gray-500 mb-3">
          <span className="px-2 py-0.5 bg-blue-50 text-blue-700 rounded-full">
            {plan.from_city} → {plan.to_city}
          </span>
          <span className="px-2 py-0.5 bg-blue-50 text-blue-700 rounded-full">
            {plan.days} 天
          </span>
          <span className="px-2 py-0.5 bg-amber-50 text-amber-700 rounded-full">
            ¥{plan.budget}
          </span>
          {plan.dep_date && (
            <span className="px-2 py-0.5 bg-gray-50 text-gray-600 rounded-full">
              {plan.dep_date}
            </span>
          )}
        </div>

        {plan.spots && plan.spots.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {plan.spots.slice(0, 5).map((s: string) => (
              <span key={s} className="text-xs text-gray-400 bg-gray-50 px-2 py-0.5 rounded">
                {s}
              </span>
            ))}
            {plan.spots.length > 5 && (
              <span className="text-xs text-gray-300">+{plan.spots.length - 5}</span>
            )}
          </div>
        )}
      </div>

      <div className="border-t border-gray-50 px-4 py-2 flex justify-end">
        <button
          onClick={(e) => {
            e.stopPropagation();
            onDelete();
          }}
          className="text-xs text-gray-400 hover:text-red-500 transition-colors"
        >
          删除
        </button>
      </div>
    </motion.div>
  );
}
