/**
 * P.A.L.M · API Fallback 工具
 * ────────────────────────────
 * 提供 "先尝试真实后端 → 不可用则抛出异常" 的统一包装。
 */

import { getBaseUrl } from './apiConfig';

/** 带超时的 fetch */
export async function fetchWithTimeout(
  url: string, init?: RequestInit, timeoutMs = 10_000,
): Promise<Response> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { ...init, signal: controller.signal });
  } finally {
    clearTimeout(timer);
  }
}

/**
 * 尝试从真实后端获取 JSON 数据。
 * 后端不可用或请求失败时抛出异常（由调用方处理，通常显示 N/O）。
 */
export async function tryFetch<T>(
  serviceKey: string,
  path: string,
  init?: RequestInit,
  timeoutMs = 8_000,
): Promise<T> {
  const baseUrl = getBaseUrl(serviceKey);
  if (!baseUrl) throw new Error(`未知服务: ${serviceKey}`);

  const res = await fetchWithTimeout(`${baseUrl}${path}`, init, timeoutMs);
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`[${res.status}] ${res.statusText}${text ? ': ' + text : ''}`);
  }
  return res.json();
}

/**
 * 尝试从真实后端获取 Blob 数据。
 * 后端不可用或请求失败时抛出异常。
 */
export async function tryFetchBlob(
  serviceKey: string,
  path: string,
  init?: RequestInit,
  timeoutMs = 15_000,
): Promise<Blob> {
  const baseUrl = getBaseUrl(serviceKey);
  if (!baseUrl) throw new Error(`未知服务: ${serviceKey}`);

  const res = await fetchWithTimeout(`${baseUrl}${path}`, init, timeoutMs);
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`[${res.status}] ${res.statusText}${text ? ': ' + text : ''}`);
  }
  return res.blob();
}
