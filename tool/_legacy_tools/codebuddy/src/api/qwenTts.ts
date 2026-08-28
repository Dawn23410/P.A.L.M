/**
 * Qwen3-TTS API 封装
 * Base URL: 由 apiConfig 统一管理（默认 http://127.0.0.1:8000/api/v1）
 * 后端不可用时直接抛出异常，由调用方处理（显示 N/O 或错误提示）。
 */

import { getBaseUrl } from './apiConfig';
import { fetchWithTimeout } from './withFallback';

// ─── 服务 Key ─────────────────────────────────────────────────

const SERVICE_KEY = 'qwenTts';

function baseUrl(): string {
  return getBaseUrl(SERVICE_KEY);
}

// ─── 工具函数 ─────────────────────────────────────────────────

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const url = `${baseUrl()}${path}`;
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
  const url = `${baseUrl()}${path}`;
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

// ─── 类型定义 ──────────────────────────────────────────────────

export interface SystemHealth {
  status: string;
  timestamp: number;
}

export interface GpuInfo {
  index: number;
  name: string;
  vram_total_gb: number;
  vram_free_gb: number;
  compute_capability: string;
  is_integrated: boolean;
  is_discrete: boolean;
}

export interface SystemInfo {
  platform: string;
  cuda_available: boolean;
  cuda_version: string;
  gpu_count: number;
  gpus: GpuInfo[];
  flash_attn_available: boolean;
  suggested_device: string;
  model_loaded: boolean;
}

export interface ModelInfo {
  repo_id: string;
  cached: boolean;
  model_size: string;
}

export interface CurrentModel {
  loaded: boolean;
  checkpoint?: string;
  model_type?: string;
  model_size?: string;
  supported_speakers?: string[];
  supported_languages?: string[];
}

export interface LoadModelPayload {
  checkpoint: string;
  device?: string;
  dtype?: string;
  flash_attn?: boolean;
}

export interface DownloadTask {
  task_id: string;
  status: string;
  progress?: number;
  speed_mbps?: number;
}

export interface DownloadableModel {
  repo_id: string;
}

export interface SpeakersResponse {
  speakers: string[];
  count: number;
}

export interface CustomVoicePayload {
  text: string;
  speaker?: string;
  language?: string;
  instruct?: string | null;
  non_streaming_mode?: boolean;
  temperature?: number | null;
  top_k?: number | null;
  top_p?: number | null;
  max_new_tokens?: number | null;
}

export interface VoiceDesignPayload {
  text: string;
  instruct: string;
  language?: string;
}

export interface VoiceClonePayload {
  text: string;
  language?: string;
  ref_audio: string;
  gpt_path?: string;
  sovits_path?: string;
  x_vector_only_mode?: boolean;
  ref_text?: string;
}

export interface VoiceClonePromptPayload {
  ref_audio: string;
  ref_text: string;
  x_vector_only_mode?: boolean;
}

export interface VoiceCloneFromPromptPayload {
  text: string;
  language?: string;
  prompt_file_path: string;
}

export interface GenerateResult {
  success: boolean;
  duration_sec: number;
  sample_rate: number;
  audio_length_sec: number;
  audio_b64: string;
}

export interface SetupStatus {
  all_installed: boolean;
  installed_count: number;
  total_count: number;
  categories: Record<string, { name: string; installed: boolean; version?: string; required: boolean; note?: string }[]>;
  pypi_mirrors: Record<string, string>;
}

// ─── 系统管理 ──────────────────────────────────────────────────

export async function getHealth(): Promise<SystemHealth> {
  return request<SystemHealth>('/health');
}

export async function getSystemInfo(): Promise<SystemInfo> {
  return request<SystemInfo>('/system/info');
}

// ─── 模型管理 ──────────────────────────────────────────────────

export async function listModels(): Promise<ModelInfo[]> {
  return request<ModelInfo[]>('/models');
}

export async function getCurrentModel(): Promise<CurrentModel> {
  return request<CurrentModel>('/models/current');
}

export async function loadModel(payload: LoadModelPayload): Promise<CurrentModel> {
  return request<CurrentModel>('/models/load', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function unloadModel(): Promise<{ status: string; message: string }> {
  return request('/models/current', { method: 'DELETE' });
}

// ─── 模型下载 ──────────────────────────────────────────────────

export async function listDownloadableModels(): Promise<DownloadableModel[]> {
  return request<DownloadableModel[]>('/models/download');
}

export async function startDownload(repoId: string): Promise<{ task_id: string; already_cached: boolean }> {
  return request('/models/download', {
    method: 'POST',
    body: JSON.stringify({ repo_id: repoId }),
  });
}

export async function getDownloadTask(taskId: string): Promise<DownloadTask> {
  return request<DownloadTask>(`/models/download/${taskId}`);
}

export async function cancelDownload(taskId: string): Promise<void> {
  await request(`/models/download/${taskId}`, { method: 'DELETE' });
}

// ─── 设置管理 ──────────────────────────────────────────────────

export async function getSetupStatus(): Promise<SetupStatus> {
  return request<SetupStatus>('/setup/status');
}

export async function installDeps(categories?: string, pypiMirror?: string): Promise<{ task_id: string }> {
  const params = new URLSearchParams();
  if (categories) params.set('categories', categories);
  if (pypiMirror) params.set('pypi_mirror', pypiMirror);
  const qs = params.toString();
  return request(`/setup/install-deps${qs ? '?' + qs : ''}`, { method: 'POST' });
}

// ─── CustomVoice 语音合成 ──────────────────────────────────────

export async function getSpeakers(): Promise<SpeakersResponse> {
  return request<SpeakersResponse>('/custom-voice/speakers');
}

export async function getLanguages(): Promise<string[]> {
  return request<string[]>('/custom-voice/languages');
}

export async function generateCustomVoice(payload: CustomVoicePayload): Promise<Blob> {
  return requestAudio('/custom-voice/generate', payload);
}

// ─── VoiceDesign 音色设计 ────────────────────────────────────

export async function generateVoiceDesign(payload: VoiceDesignPayload): Promise<Blob> {
  return requestAudio('/voice-design/generate', payload);
}

// ─── VoiceClone 语音克隆 ──────────────────────────────────────

export async function generateVoiceClone(payload: VoiceClonePayload): Promise<Blob> {
  return requestAudio('/voice-clone/generate', payload);
}

export async function generateVoiceCloneWithFile(formData: FormData): Promise<Blob> {
  const url = `${baseUrl()}/voice-clone/generate-with-file`;
  const res = await fetch(url, {
    method: 'POST',
    body: formData,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`[${res.status}] ${res.statusText}${text ? ': ' + text : ''}`);
  }
  return res.blob();
}

export async function createVoiceClonePrompt(payload: VoiceClonePromptPayload): Promise<{
  success: boolean;
  prompt_file_path: string;
  items_count: number;
}> {
  return request('/voice-clone/prompt', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function generateFromPrompt(payload: VoiceCloneFromPromptPayload): Promise<Blob> {
  return requestAudio('/voice-clone/generate-from-prompt', payload);
}
