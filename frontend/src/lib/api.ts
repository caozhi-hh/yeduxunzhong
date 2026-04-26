const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000";

export async function streamChat(
  endpoint: string,
  body: Record<string, unknown>,
  onChunk: (text: string) => void,
  onDone: (data?: Record<string, unknown>) => void,
) {
  let receivedDone = false;

  try {
    const res = await fetch(`${API_BASE}${endpoint}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });

    if (!res.ok) {
      onChunk(`\n\n❌ 请求失败：${res.status} ${res.statusText}`);
      onDone();
      return;
    }

    const reader = res.body?.getReader();
    if (!reader) { onDone(); return; }

    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() || "";

      for (const line of lines) {
        if (line.startsWith("data: ")) {
          try {
            const data = JSON.parse(line.slice(6));
            if (data.type === "chunk") onChunk(data.content);
            else if (data.type === "done") { receivedDone = true; onDone(data); }
          } catch {}
        }
      }
    }
  } catch {
    onChunk("\n\n⚠️ 连接中断，请重试");
  }

  if (!receivedDone) onDone();
}

export async function fetchSpotPhoto(spotName: string, city: string): Promise<string> {
  try {
    const res = await fetch(`${API_BASE}/api/generate-image`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ spot_name: spotName, city }),
    });
    if (!res.ok) return "";
    const data = await res.json();
    if (data.status === "ok" && data.url) return data.url;
  } catch {}
  return "";
}
