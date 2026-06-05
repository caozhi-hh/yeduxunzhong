const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000";

export function getLang(): string {
  if (typeof window === "undefined") return "zh";
  return localStorage.getItem("yedu_lang") || "zh";
}

function getAuthHeaders(): Record<string, string> {
  const token = typeof window !== "undefined" ? localStorage.getItem("yedu_auth_token") : null;
  return token ? { Authorization: `Bearer ${token}` } : {};
}

/** XSS 防护：转义 HTML 特殊字符 */
function sanitize(input: string): string {
  return input
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#x27;");
}

/** 统一错误类 */
export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number = 500) {
    super(message);
    this.status = status;
  }
}

/** 统一 JSON 请求封装 */
async function request<T>(
  endpoint: string,
  options: RequestInit = {},
): Promise<T> {
  const res = await fetch(`${API_BASE}${endpoint}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...getAuthHeaders(),
      ...options.headers,
    },
  });

  const data = await res.json().catch(() => ({}));

  if (!res.ok || data.status === "error") {
    throw new ApiError(
      data.message || data.detail || `请求失败 (${res.status})`,
      res.status,
    );
  }

  return data as T;
}

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
      headers: { "Content-Type": "application/json", ...getAuthHeaders() },
      body: JSON.stringify({ ...body, language: getLang() }),
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

// History API
export async function fetchHistory(): Promise<any[]> {
  try {
    const data = await request<{ plans?: any[] }>("/api/history");
    return data.plans || [];
  } catch { return []; }
}

export async function fetchPlan(id: number): Promise<any> {
  try {
    return await request(`/api/history/${id}`);
  } catch { return null; }
}

export async function deletePlan(id: number): Promise<boolean> {
  try {
    await request(`/api/history/${id}`, { method: "DELETE" });
    return true;
  } catch { return false; }
}

export async function savePlanToHistory(data: Record<string, unknown>): Promise<any> {
  try {
    return await request("/api/history", {
      method: "POST",
      body: JSON.stringify(data),
    });
  } catch { return null; }
}

export { sanitize };
