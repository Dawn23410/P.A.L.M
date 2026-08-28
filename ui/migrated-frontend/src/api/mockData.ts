/**
 * P.A.L.M · Mock 数据层
 * ────────────────────────────
 * 所有后端服务的模拟数据，用于前端在无后端时正常展示。
 * 真实数据足够丰富，UI 能完整渲染，不会出现空白/报错。
 *
 * 注：Qwen3-TTS 已移除，仅保留 GPT-SoVITS 与性能监控模拟数据。
 */

import type { PerfSnapshot } from '../hooks/usePerformance';
import type { ModuleEntry } from '../hooks/useModuleStatus';
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
  { id: 'tts',        name: '语音播报', status: 'offline', description: 'GPT-SoVITS 语音合成服务 (未连接)' },
];

// ═══════════════════════════════════════════════════════════════════
//  2. GPT-SoVITS (port 9880 / 5000)
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
