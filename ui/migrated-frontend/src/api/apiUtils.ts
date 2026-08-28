/**
 * API 工具函数
 * 提供带超时的 fetch 封装和统一错误处理
 */

const DEFAULT_TIMEOUT = 30000; // 30s

/** 带超时的 fetch */
export async function fetchWithTimeout(url: string, init?: RequestInit, timeoutMs = DEFAULT_TIMEOUT): Promise<Response> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(url, { ...init, signal: controller.signal });
    return res;
  } finally {
    clearTimeout(timer);
  }
}

/** 统一 API 请求（JSON 响应） */
export async function apiRequest<T>(baseUrl: string, path: string, init?: RequestInit): Promise<T> {
  try {
    const res = await fetchWithTimeout(`${baseUrl}${path}`, {
      ...init,
      headers: { 'Content-Type': 'application/json', ...init?.headers },
    });
    if (!res.ok) {
      const text = await res.text().catch(() => '');
      throw new Error(`[${res.status}] ${res.statusText}${text ? ': ' + text : ''}`);
    }
    return res.json();
  } catch (err: any) {
    if (err.name === 'AbortError') {
      throw new Error('请求超时，请检查后端服务是否运行');
    }
    if (err.message?.includes('Failed to fetch') || err.message?.includes('NetworkError')) {
      throw new Error(`无法连接到后端服务 (${baseUrl})`);
    }
    throw err;
  }
}

/** 统一 API 请求（Blob 响应，用于音频） */
export async function apiRequestAudio(baseUrl: string, path: string, body: unknown): Promise<Blob> {
  try {
    const res = await fetchWithTimeout(`${baseUrl}${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      const text = await res.text().catch(() => '');
      throw new Error(`[${res.status}] ${res.statusText}${text ? ': ' + text : ''}`);
    }
    return res.blob();
  } catch (err: any) {
    if (err.name === 'AbortError') {
      throw new Error('请求超时，请检查后端服务是否运行');
    }
    if (err.message?.includes('Failed to fetch') || err.message?.includes('NetworkError')) {
      throw new Error(`无法连接到后端服务 (${baseUrl})`);
    }
    throw err;
  }
}
