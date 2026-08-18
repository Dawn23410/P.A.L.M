/* 数据访问封装：全前端唯一的 fetch 出口（UiPort 契约的浏览器侧）。

- BASE 由 shell 注入（同源空串 / PyWebView 桥 / 独立后端地址）。
- 所有失败统一归一为抛出 ApiError（message 中文），界面只做展示降级。
- 契约约定：后端不可达/端点缺失时界面显示「后端未连接」而非白屏。
 */

export const BASE = window.PALM_API_BASE ?? "";

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

/** 统一请求：method + path + body，超时默认 10s。 */
export async function request(method, path, body, { timeout = 10000, signal } = {}) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeout);
  const onAbort = () => signal?.addEventListener("abort", () => ctrl.abort());
  onAbort();
  try {
    const resp = await fetch(BASE + path, {
      method,
      headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
      body: body !== undefined ? JSON.stringify(body) : undefined,
      signal: ctrl.signal,
    });
    if (!resp.ok) {
      let detail = `HTTP ${resp.status}`;
      try {
        const j = await resp.json();
        detail = j.detail || j.message || detail;
      } catch (_) { /* 非 JSON 响应保留状态码 */ }
      throw new ApiError(detail, resp.status);
    }
    const text = await resp.text();
    return text ? JSON.parse(text) : null;
  } catch (exc) {
    if (exc instanceof ApiError) throw exc;
    throw new ApiError(exc.name === "AbortError" ? "请求超时，请检查后端连接" : `后端未连接：${exc.message}`);
  } finally {
    clearTimeout(timer);
  }
}

export const get = (path) => request("GET", path);
export const post = (path, body) => request("POST", path, body);
export const del = (path) => request("DELETE", path);

/** SSE 流式读取（对话等）：onEvent 收到每个事件对象，返回 abort 函数。 */
export function stream(path, body, { onEvent, onDone, onError }) {
  const ctrl = new AbortController();
  (async () => {
    try {
      const resp = await fetch(BASE + path, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
        signal: ctrl.signal,
      });
      if (!resp.ok) {
        let detail = `HTTP ${resp.status}`;
        try { detail = (await resp.json()).detail || detail; } catch (_) {}
        throw new ApiError(detail, resp.status);
      }
      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buf = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const parts = buf.split("\n\n");
        buf = parts.pop();
        for (const part of parts) {
          const line = part.trim();
          if (!line.startsWith("data:")) continue;
          const payload = line.slice(5).trim();
          if (payload === "[DONE]") { onDone?.(); return; }
          try { onEvent?.(JSON.parse(payload)); } catch (_) { /* 忽略畸形事件 */ }
        }
      }
      onDone?.();
    } catch (exc) {
      onError?.(exc instanceof ApiError ? exc : new ApiError(`流中断：${exc.message}`));
    }
  })();
  return () => ctrl.abort();
}
