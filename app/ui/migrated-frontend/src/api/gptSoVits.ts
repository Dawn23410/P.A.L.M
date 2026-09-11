/**
 * GPT-SoVITS API 封装
 * Base URL: 由 apiConfig 统一管理（默认 9880 / 5000）
 * 后端不可用时直接抛出异常，由调用方处理（显示 N/O 或错误提示）。
 */

import { getBaseUrl } from './apiConfig';
import { fetchWithTimeout } from './withFallback';

// ─── 服务 Key ─────────────────────────────────────────────────

const API_SERVICE = 'gptSoVits';
const RUNTIME_SERVICE = 'gptSoVitsRuntime';

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const url = `${getBaseUrl(API_SERVICE)}${path}`;
  const res = await fetchWithTimeout(url, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...init?.headers },
  });
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`[${res.status}] ${res.statusText}${text ? ': ' + text : ''}`);
  }
  return res.json();
}

async function requestAudio(path: string, body: unknown): Promise<Blob> {
  const url = `${getBaseUrl(API_SERVICE)}${path}`;
  const res = await fetchWithTimeout(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`[${res.status}] ${res.statusText}${text ? ': ' + text : ''}`);
  }
  return res.blob();
}

async function runtimeRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const url = `${getBaseUrl(RUNTIME_SERVICE)}${path}`;
  const res = await fetchWithTimeout(url, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...init?.headers },
  });
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`[${res.status}] ${res.statusText}${text ? ': ' + text : ''}`);
  }
  return res.json();
}

// ─── 类型定义 ──────────────────────────────────────────────────

export interface GptSoVitsHealth {
  status: string;
  version?: string;
}

export interface TtsPayload {
  text: string;
  text_lang?: string;
  ref_audio_path?: string;
  ref_text?: string;
  ref_lang?: string;
  prompt_mode?: string;
  text_split_method?: string;
  batch_size?: number;
  media_type?: 'wav' | 'mp3';
  streaming?: boolean;
}

export interface VoiceClonePayload {
  text: string;
  text_lang?: string;
  ref_audio_path?: string;
  ref_text?: string;
  ref_lang?: string;
}

export interface ModelInfo {
  name: string;
  version: string;
  loaded: boolean;
}

// ─── 健康检查 ─────────────────────────────────────────────────

export async function getHealth(): Promise<GptSoVitsHealth> {
  return request<GptSoVitsHealth>('/status');
}

// ─── 语音合成 ─────────────────────────────────────────────────

export async function generateTts(payload: TtsPayload): Promise<Blob> {
  return requestAudio('/tts', payload);
}

// ─── 语音克隆 ─────────────────────────────────────────────────

export async function generateVoiceClone(payload: VoiceClonePayload): Promise<Blob> {
  return requestAudio('/voice-clone', payload);
}

// ─── 模型管理 ─────────────────────────────────────────────────

export async function getModels(): Promise<ModelInfo[]> {
  return request<ModelInfo[]>('/models');
}

export async function setModel(name: string): Promise<{ success: boolean }> {
  return request('/models/set', {
    method: 'POST',
    body: JSON.stringify({ name }),
  });
}

// ─── 整合包管理 ─────────────────────────────────────────────

export interface PackageEntry {
  name: string;
  path: string;
  type?: string;
  refLang: string;
  modelVersion: string;
  cutMethod: string;
  audioCount?: number;
}

export interface ScanResult {
  ckpt: string[];
  pth: string[];
  wav: string[];
  ref_texts: string[];
  versions?: { ckpt: string | null; pth: string | null };
}

export async function getPackagePath(): Promise<{ path: string }> {
  return runtimeRequest('/packages/path');
}

export async function searchPackages(): Promise<PackageEntry[]> {
  return runtimeRequest('/packages/search');
}

export async function loadPackage(path: string): Promise<{ success: boolean; name: string; path: string }> {
  return runtimeRequest('/packages/load', {
    method: 'POST',
    body: JSON.stringify({ path }),
  });
}

export async function scanMatesDirectory(baseName: string, filePath?: string): Promise<ScanResult> {
  const body: any = { base_name: baseName };
  if (filePath) body.dir = filePath;
  const result = await runtimeRequest<{ success: boolean; matches: { ckpt: string[]; pth: string[]; wav: string[] }; ref_texts: string[]; versions?: { ckpt: string | null; pth: string | null } }>('/files/scan-mates', {
    method: 'POST',
    body: JSON.stringify(body),
  });
  return { ...result.matches, ref_texts: result.ref_texts || [], versions: result.versions };
}

export async function fetchFileFromBackend(filePath: string): Promise<File> {
  const resp = await fetch(`${getBaseUrl(RUNTIME_SERVICE)}/files/read`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path: filePath }),
  });
  if (!resp.ok) {
    const text = await resp.text().catch(() => '');
    throw new Error(`读取文件失败: ${text}`);
  }
  const blob = await resp.blob();
  const fileName = filePath.split(/[/\\]/).pop() || 'unknown';
  return new File([blob], fileName);
}

export async function downloadPackage(path: string): Promise<{ success: boolean; dest: string }> {
  return runtimeRequest('/packages/download', {
    method: 'POST',
    body: JSON.stringify({ path }),
  });
}
