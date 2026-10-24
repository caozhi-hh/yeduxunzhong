import type { Metadata } from "next";
import AppProviders from "@/components/AppProviders";
import "./globals.css";

/**
 * 根布局
 *
 * P0 改动：
 * 1. **去掉 next/font/google** —— 原来用 Inter + Geist Mono，构建时要从
 *    fonts.googleapis.com 取字体。实测这会让**构建直接失败**：
 *      Failed to fetch `Inter` from Google Fonts.
 *      Failed to fetch `Geist Mono` from Google Fonts.
 *    （Google 系在大陆不可达；之前能构建成功只是命中了缓存，属于隐藏的定时炸弹。）
 *    Demo 必须能稳定构建与部署，所以改为**系统字体栈**（定义在 globals.css）：
 *      --font-sans    PingFang SC / Microsoft YaHei 等系统字体
 *      --font-display Noto Serif SC / 宋体，做杂志感标题
 *    代价是各系统字体略有差异；收益是构建稳定、首屏零外部字体请求。
 *
 * 2. 预连接保留并补充地图瓦片域名（Leaflet 走栅格瓦片，省 DNS/TLS 往返）。
 */

export const metadata: Metadata = {
  title: "野渡寻踪 — AI 旅行攻略",
  description: "看灵感、选景点、生成一份能直接用的旅行攻略",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN" className="h-full antialiased">
      <head>
        {/* 景点照片（自托管，走本站 /api/images/，这里预连的是地图瓦片） */}
        <link rel="preconnect" href="https://basemaps.cartocdn.com" crossOrigin="anonymous" />
        <link rel="preconnect" href="https://webrd01.is.autonavi.com" crossOrigin="anonymous" />
        <link rel="dns-prefetch" href="https://images.unsplash.com" />
      </head>
      <body className="min-h-full flex flex-col">
        <AppProviders>{children}</AppProviders>
      </body>
    </html>
  );
}