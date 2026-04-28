"use client";

import { useEffect, useRef, useState } from "react";

interface SpotCoord {
  name: string;
  lng: number;
  lat: number;
}

interface RouteMapProps {
  spots: string[];
  city: string;
  coords?: SpotCoord[];
}

const ROUTE_COLORS = ["#E65100", "#1565C0", "#2E7D32", "#7B1FA2", "#C62828", "#00838F"];

let amapLoadPromise: Promise<any> | null = null;

function loadAMapSDK(): Promise<any> {
  if ((window as any).AMap) return Promise.resolve((window as any).AMap);
  if (amapLoadPromise) return amapLoadPromise;

  const key = process.env.NEXT_PUBLIC_AMAP_KEY;
  const secret = process.env.NEXT_PUBLIC_AMAP_SECRET || "";

  if (!key) return Promise.reject(new Error("未配置高德地图 Key"));

  if (secret) {
    (window as any)._AMapSecurityConfig = { securityJsCode: secret };
  }

  amapLoadPromise = new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = `https://webapi.amap.com/maps?v=2.0&key=${key}`;
    script.onload = () => {
      const AMap = (window as any).AMap;
      if (AMap) {
        console.log("[AMap] SDK loaded OK");
        resolve(AMap);
      } else {
        amapLoadPromise = null;
        reject(new Error("AMap not found after load"));
      }
    };
    script.onerror = () => {
      amapLoadPromise = null;
      reject(new Error("AMap script load failed"));
    };
    document.head.appendChild(script);
  });

  return amapLoadPromise;
}

export default function RouteMap({ spots, city, coords }: RouteMapProps) {
  const mapRef = useRef<HTMLDivElement>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!coords?.length || !city) return;

    let cancelled = false;

    (async () => {
      try {
        const AMap = await Promise.race([
          loadAMapSDK(),
          new Promise<never>((_, reject) => setTimeout(() => reject(new Error("SDK 超时")), 10000)),
        ]);
        if (cancelled || !mapRef.current) return;

        // 直接用后端传来的坐标，不需要浏览器端地理编码
        const locs = coords.filter((c) => c.lng && c.lat);

        const avgLng = locs.reduce((s, l) => s + l.lng, 0) / locs.length;
        const avgLat = locs.reduce((s, l) => s + l.lat, 0) / locs.length;

        const map = new AMap.Map(mapRef.current, {
          center: [avgLng, avgLat],
          zoom: 11,
          viewMode: "2D",
        });

        const markers: any[] = [];
        locs.forEach((loc, idx) => {
          const color = ROUTE_COLORS[idx % ROUTE_COLORS.length];
          const marker = new AMap.Marker({
            position: [loc.lng, loc.lat],
            title: loc.name,
            label: {
              content: `<div style="background:${color};color:#fff;padding:2px 8px;border-radius:12px;font-size:12px;font-weight:bold;white-space:nowrap;">${idx + 1}. ${loc.name}</div>`,
              direction: "top",
              offset: new AMap.Pixel(0, -8),
            },
          });
          map.add(marker);
          markers.push(marker);
        });

        if (locs.length >= 2) {
          const path = locs.map((l) => [l.lng, l.lat]);
          map.add(new AMap.Polyline({
            path,
            strokeColor: "#2E7D32",
            strokeWeight: 4,
            strokeOpacity: 0.8,
            lineJoin: "round",
            showDir: true,
          }));
        }

        map.setFitView(markers, false, [60, 60, 60, 60]);
        setLoading(false);
      } catch (e) {
        console.error("[RouteMap]", e);
        if (!cancelled) {
          setError("地图加载失败");
          setLoading(false);
        }
      }
    })();

    return () => { cancelled = true; };
  }, [coords, city]);

  if (error) {
    return (
      <div className="bg-white rounded-2xl p-6 shadow-sm border border-gray-100 mb-6">
        <div className="text-center text-gray-400 py-6">
          <span className="text-3xl">🗺️</span>
          <p className="mt-2 text-sm">{error}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="bg-white rounded-2xl p-4 shadow-sm border border-gray-100 mb-6">
      <h3 className="text-sm font-bold text-emerald-700 mb-3">🗺️ 景点路线图</h3>
      <div className="relative rounded-xl overflow-hidden" style={{ height: "360px" }}>
        {loading && (
          <div className="absolute inset-0 flex items-center justify-center bg-gray-50 z-10">
            <div className="text-center">
              <div className="w-8 h-8 border-3 border-emerald-200 border-t-emerald-500 rounded-full animate-spin mx-auto mb-2" />
              <p className="text-gray-400 text-sm">加载地图中...</p>
            </div>
          </div>
        )}
        <div ref={mapRef} style={{ width: "100%", height: "100%" }} />
      </div>
      {coords && coords.length > 0 && (
        <div className="flex flex-wrap gap-2 mt-3">
          {coords.filter((c) => c.lng && c.lat).map((loc, idx) => (
            <span
              key={loc.name}
              className="text-xs px-2 py-1 rounded-full text-white font-medium"
              style={{ backgroundColor: ROUTE_COLORS[idx % ROUTE_COLORS.length] }}
            >
              {idx + 1}. {loc.name}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
