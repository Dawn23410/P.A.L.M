/**
 * P.A.L.M · useModuleStatus
 * ───────────────────────────
 * 模块运行状态 Hook。
 * 通过后端 HTTP API 获取实时模块状态，后端不可用时返回离线状态。
 */

import { useState, useEffect } from 'react';
import { tryFetch } from '../api/withFallback';

// ─── 类型 ───────────────────────────────────────────────────────

export type ModuleStatus = 'online' | 'warning' | 'error' | 'offline';

export interface ModuleEntry {
  id: string;
  name: string;
  status: ModuleStatus;
  description: string;
}

export interface ModuleStatusData {
  modules: ModuleEntry[];
  summary: {
    online: number;
    warning: number;
    error: number;
    offline: number;
    total: number;
  };
}

// ─── 颜色常量 ────────────────────────────────────────────────────

export const STATUS_COLORS: Record<ModuleStatus, string> = {
  online:  '#22c55e',
  warning: '#d4a017',
  error:   '#e24b4a',
  offline: '#9aa5b1',
};

export const STATUS_LABELS: Record<ModuleStatus, string> = {
  online:  '在线',
  warning: '异常',
  error:   '错误',
  offline: '离线',
};

// ─── 辅助函数 ────────────────────────────────────────────────────

function calcSummary(modules: ModuleEntry[]): ModuleStatusData['summary'] {
  return {
    online:  modules.filter(m => m.status === 'online').length,
    warning: modules.filter(m => m.status === 'warning').length,
    error:   modules.filter(m => m.status === 'error').length,
    offline: modules.filter(m => m.status === 'offline').length,
    total:   modules.length,
  };
}

// ─── 离线默认值 ──────────────────────────────────────────────────

const FALLBACK_MODULES: ModuleEntry[] = [
  { id: 'dashboard', name: '仪表盘',   status: 'offline', description: 'N/O' },
  { id: 'wallpaper', name: '壁纸引擎', status: 'offline', description: 'N/O' },
  { id: 'dock',      name: 'Dock 栏',  status: 'offline', description: 'N/O' },
  { id: 'agent',     name: 'Agent',    status: 'offline', description: 'N/O' },
  { id: 'asr',       name: '语音识别', status: 'offline', description: 'N/O' },
  { id: 'tts',       name: '语音播报', status: 'offline', description: 'N/O' },
];

// ─── Hook ────────────────────────────────────────────────────────

export function useModuleStatus(): ModuleStatusData {
  const [modules, setModules] = useState<ModuleEntry[]>(FALLBACK_MODULES);

  useEffect(() => {
    let mounted = true;
    let timer: ReturnType<typeof setInterval> | null = null;

    const fetchModules = async () => {
      try {
        const data = await tryFetch<ModuleEntry[]>('performance', '/api/modules');
        if (mounted) setModules(data);
      } catch {
        // 后端不可用 → 保持离线状态
      }
    };

    const onVisibilityChange = () => {
      if (document.visibilityState === 'visible') fetchModules();
    };
    document.addEventListener('visibilitychange', onVisibilityChange);

    fetchModules();
    timer = setInterval(fetchModules, 4000);
    return () => {
      mounted = false;
      if (timer) clearInterval(timer);
      document.removeEventListener('visibilitychange', onVisibilityChange);
    };
  }, []);

  return { modules, summary: calcSummary(modules) };
}
