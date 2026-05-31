"use client";

import { useTranslation } from "react-i18next";

export default function LanguageSwitcher() {
  const { i18n } = useTranslation();
  const isZh = i18n.language === "zh";

  return (
    <button
      onClick={() => i18n.changeLanguage(isZh ? "en" : "zh")}
      className="px-3 py-1.5 text-xs font-medium rounded-full bg-white/10 backdrop-blur-md border border-white/20 hover:bg-white/20 text-white transition-all"
    >
      {isZh ? "EN" : "中文"}
    </button>
  );
}
