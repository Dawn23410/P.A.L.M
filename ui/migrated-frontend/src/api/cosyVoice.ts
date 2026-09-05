/**
 * CosyVoice API 封装
 * Base URL: 由 apiConfig 统一管理（默认 7861）
 * 后端不可用时直接抛异常，由调用方处理（显示 N/O 或错误提示）。
 *
 * 端点与 GPT-SoVITS 风格对齐：/health、/speakers、/tts 等。
 */

import { getBaseUrl } from './apiConfig';
import { fetchWithTimeout } from './withFallback';

const API_SERVICE = 'cosyVoice';

// ─── 类型定义 ──────────────────────────────────────────────────

export interface CosySpeaker {
  id: string;
  is_default: boolean;
  prompt_text: string;
}

export interface SpeakersPayload {
  speakers: CosySpeaker[];
  default: string | null;
}

export interface CosyHealth {
  status: string;
  model_loaded: boolean;
  sample_rate: number | null;
  device?: string;
  fp16?: boolean;
}

export interface CosySettings {
  device: string;
  fp16: boolean;
  model_loaded?: boolean;
}

export interface SaveSettingsResult {
  saved: boolean;
  device: string;
  fp16: boolean;
  needs_restart: boolean;
}

export interface TtsRequest {
  tts_text: string;
  instruct_text: string;
  spk_id: string;
  speed?: number;
  seed?: number;
  stream?: boolean;
}

// ─── 健康检查 ─────────────────────────────────────────────────

export async function getHealth(): Promise<CosyHealth> {
  const res = await fetchWithTimeout(`${getBaseUrl(API_SERVICE)}/health`, { method: 'GET' }, 5000);
  if (!res.ok) throw new Error(`[${res.status}] 健康检查失败`);
  return res.json();
}

// ─── 运行设置（设备 / 半精度） ───────────────────────────────

export async function getSettings(): Promise<CosySettings> {
  const res = await fetchWithTimeout(`${getBaseUrl(API_SERVICE)}/settings`, { method: 'GET' }, 5000);
  if (!res.ok) throw new Error(`[${res.status}] 获取运行设置失败`);
  return res.json();
}

export async function saveSettings(device: string, fp16: boolean): Promise<SaveSettingsResult> {
  const res = await fetchWithTimeout(`${getBaseUrl(API_SERVICE)}/settings`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ device, fp16, restart: true }),
  }, 15000);
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(text || `[${res.status}] 保存运行设置失败`);
  }
  return res.json();
}

// ─── 说话人管理 ───────────────────────────────────────────────

export async function listSpeakers(): Promise<SpeakersPayload> {
  const res = await fetchWithTimeout(`${getBaseUrl(API_SERVICE)}/speakers`, { method: 'GET' }, 8000);
  if (!res.ok) throw new Error(`[${res.status}] 获取说话人列表失败`);
  return res.json();
}

export async function registerSpeaker(
  promptText: string,
  spkId: string,
  promptWav: File,
): Promise<SpeakersPayload> {
  const form = new FormData();
  form.append('prompt_text', promptText);
  form.append('spk_id', spkId);
  form.append('prompt_wav', promptWav);

  const res = await fetchWithTimeout(`${getBaseUrl(API_SERVICE)}/speakers/register`, {
    method: 'POST',
    body: form,
  }, 60000);
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(text || `[${res.status}] 注册说话人失败`);
  }
  return res.json();
}

export async function deleteSpeaker(spkId: string): Promise<SpeakersPayload> {
  const res = await fetchWithTimeout(`${getBaseUrl(API_SERVICE)}/speakers/delete`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ spk_id: spkId }),
  }, 15000);
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(text || `[${res.status}] 删除说话人失败`);
  }
  return res.json();
}

export async function setDefaultSpeaker(spkId: string): Promise<SpeakersPayload> {
  const res = await fetchWithTimeout(`${getBaseUrl(API_SERVICE)}/speakers/default`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ spk_id: spkId }),
  }, 15000);
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(text || `[${res.status}] 设置默认说话人失败`);
  }
  return res.json();
}

export async function reloadSpeakers(): Promise<SpeakersPayload> {
  const res = await fetchWithTimeout(`${getBaseUrl(API_SERVICE)}/reload`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
  }, 15000);
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(text || `[${res.status}] 重载说话人失败`);
  }
  return res.json();
}

// ─── 语音合成（自然语言控制） ──────────────────────────────────

export async function generateTts(req: TtsRequest): Promise<Blob> {
  const res = await fetchWithTimeout(`${getBaseUrl(API_SERVICE)}/tts`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      tts_text: req.tts_text,
      instruct_text: req.instruct_text,
      spk_id: req.spk_id,
      speed: req.speed ?? 1.0,
      seed: req.seed ?? 0,
      stream: req.stream ?? false,
    }),
  }, 60000);
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(text || `[${res.status}] 合成失败`);
  }
  return res.blob();
}
