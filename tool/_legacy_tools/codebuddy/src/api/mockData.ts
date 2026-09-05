/**
 * P.A.L.M · Mock 数据层
 * ────────────────────────────
 * 所有后端服务的模拟数据，用于前端在无后端时正常展示。
 * 真实数据足够丰富，UI 能完整渲染，不会出现空白/报错。
 */

import type { PerfSnapshot } from '../hooks/usePerformance';
import type { ModuleEntry } from '../hooks/useModuleStatus';
import type {
  SystemHealth, SystemInfo, ModelInfo, CurrentModel,
  SpeakersResponse, SetupStatus,
} from './qwenTts';
import type { GptSoVitsHealth, PackageEntry, ScanResult } from './gptSoVits';

// ═══════════════════════════════════════════════════════════════════
//  1. 性能监控 (palm-backend · port 8080)
// ═══════════════════════════════════════════════════════════════════

export const MOCK_PERF_SNAPSHOT: PerfSnapshot = {
  cpu: {
    model: 'Intel(R) Core(TM) i7-13700H (模拟)',
    baseFreq: '2.40 GHz',
    currentFreq: '3.80 GHz',
    usage: 23.5,
    temperature: 58,
  },
  memory: {
    speed: 4800,
    total: 32,
    available: 18.5,
    usage: 42,
  },
  gpus: [
    { model: 'NVIDIA GeForce RTX 4060 Laptop (模拟)', usage: 15 },
  ],
  network: {
    uploadSpeed: 2.3,
    downloadSpeed: 8.7,
  },
  disks: [
    { mount: 'C:', total: 256, used: 120 },
    { mount: 'D:', total: 1024, used: 420 },
  ],
};

export const MOCK_MODULE_LIST: ModuleEntry[] = [
  { id: 'dashboard',  name: '仪表盘',   status: 'online',  description: '系统监控与概览 (模拟)' },
  { id: 'tts',        name: '语音播报', status: 'offline', description: 'TTS 语音合成服务 (未连接)' },
  { id: 'wallpaper',  name: '壁纸引擎', status: 'online',  description: '动态壁纸管理 (模拟)' },
  { id: 'dock',       name: 'Dock 栏',  status: 'warning', description: '应用启动器 (模拟)' },
  { id: 'agent',      name: 'Agent',    status: 'offline', description: 'AI 助手 (未连接)' },
  { id: 'asr',        name: '语音识别', status: 'offline', description: '语音转文字 (未连接)' },
];

// ═══════════════════════════════════════════════════════════════════
//  2. Qwen3-TTS (port 8000)
// ═══════════════════════════════════════════════════════════════════

export const MOCK_QWEN_HEALTH: SystemHealth = {
  status: 'healthy',
  timestamp: Date.now(),
};

export const MOCK_QWEN_SYSTEM_INFO: SystemInfo = {
  platform: 'Windows (模拟)',
  cuda_available: true,
  cuda_version: '12.1',
  gpu_count: 1,
  gpus: [{
    index: 0,
    name: 'NVIDIA GeForce RTX 4060 Laptop (模拟)',
    vram_total_gb: 8,
    vram_free_gb: 3.2,
    compute_capability: '8.9',
    is_integrated: false,
    is_discrete: true,
  }],
  flash_attn_available: true,
  suggested_device: 'cuda:0',
  model_loaded: false,
};

export const MOCK_QWEN_MODELS: ModelInfo[] = [
  { repo_id: 'Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice',   cached: false, model_size: '1.2 GB' },
  { repo_id: 'Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice',   cached: false, model_size: '3.4 GB' },
  { repo_id: 'Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign',   cached: false, model_size: '3.4 GB' },
  { repo_id: 'Qwen/Qwen3-TTS-12Hz-1.7B-Base',           cached: false, model_size: '3.4 GB' },
];

export const MOCK_QWEN_CURRENT_MODEL: import('./qwenTts').CurrentModel = {
  loaded: false,
  model_type: undefined,
};

export const MOCK_QWEN_SPEAKERS: SpeakersResponse = {
  speakers: ['default', 'female_1', 'female_2', 'male_1', 'male_2'],
  count: 5,
};

export const MOCK_QWEN_LANGUAGES: string[] = ['zh', 'en', 'ja', 'ko'];

export const MOCK_QWEN_SETUP_STATUS: SetupStatus = {
  all_installed: false,
  installed_count: 0,
  total_count: 4,
  categories: {
    system: [{ name: 'PyTorch', installed: false, required: true }],
    model: [
      { name: 'Qwen3-TTS-0.6B-CustomVoice', installed: false, required: false },
      { name: 'Qwen3-TTS-1.7B-CustomVoice', installed: false, required: false },
      { name: 'Qwen3-TTS-1.7B-VoiceDesign', installed: false, required: false },
      { name: 'Qwen3-TTS-1.7B-Base',        installed: false, required: false },
    ],
  },
  pypi_mirrors: {},
};

/** 模拟 TTS 返回一段静音 WAV（44.1kHz, 16-bit, 1秒无声） */
export function createMockAudioBlob(): Blob {
  const sampleRate = 44100;
  const durationSec = 1;
  const numSamples = sampleRate * durationSec;
  const buffer = new ArrayBuffer(44 + numSamples * 2);
  const view = new DataView(buffer);

  // WAV header
  const writeStr = (off: number, str: string) => {
    for (let i = 0; i < str.length; i++) view.setUint8(off + i, str.charCodeAt(i));
  };
  writeStr(0, 'RIFF');
  view.setUint32(4, 36 + numSamples * 2, true);
  writeStr(8, 'WAVE');
  writeStr(12, 'fmt ');
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);           // PCM
  view.setUint16(22, 1, true);           // mono
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  writeStr(36, 'data');
  view.setUint32(40, numSamples * 2, true);
  // 无声 PCM 数据（全部为 0）

  return new Blob([buffer], { type: 'audio/wav' });
}

// ═══════════════════════════════════════════════════════════════════
//  3. GPT-SoVITS (port 9880 / 5000)
// ═══════════════════════════════════════════════════════════════════

export const MOCK_GSV_HEALTH: GptSoVitsHealth = {
  status: 'ok',
  version: 'mock-0.0.1',
};

export const MOCK_GSV_MODELS = [
  { name: 'Mock Model v1', version: '1.0.0', loaded: false },
  { name: 'Mock Model v2', version: '2.0.0', loaded: false },
];

export const MOCK_GSV_PACKAGES: PackageEntry[] = [
  { name: '示例整合包_ZH',  path: '/mock/path/示例整合包',  refLang: 'ZH', modelVersion: 'v2', cutMethod: '按标点切分', audioCount: 5 },
  { name: '示例整合包_EN',  path: '/mock/path/示例整合包_EN', refLang: 'EN', modelVersion: 'v1', cutMethod: '按标点切分', audioCount: 3 },
];

export const MOCK_GSV_SCAN_RESULT: ScanResult = {
  ckpt: ['mock_speaker.ckpt'],
  pth:  ['mock_speaker.pth'],
  wav:  ['mock_ref_audio.wav'],
  ref_texts: ['这是模拟的参考文本。'],
};

// ═══════════════════════════════════════════════════════════════════
//  4. 模块管理 (port 9090)
// ═══════════════════════════════════════════════════════════════════

export interface MockModuleItem {
  name: string;
  version: string;
  type: string;
  description: string;
  status: string;
  integrity: { status: string };
  port: number | null;
  path: string;
  running: boolean;
}

export const MOCK_MODULE_MANAGER_MODULES: MockModuleItem[] = [
  {
    name: 'palm-backend',
    version: '0.3.0',
    type: 'backend',
    description: '系统性能监控 (模拟 — 未安装)',
    status: '未安装',
    integrity: { status: 'none' },
    port: 8080,
    path: '',
    running: false,
  },
  {
    name: 'qwen3-tts',
    version: '0.1.1',
    type: 'backend',
    description: 'Qwen3-TTS 语音合成 (模拟 — 未安装)',
    status: '未安装',
    integrity: { status: 'none' },
    port: 8000,
    path: '',
    running: false,
  },
];

export const MOCK_MODULE_CONFIG_RESPONSE = {
  modules_dir: '/mock/modules',
  packages_dir: '/mock/packages',
};
