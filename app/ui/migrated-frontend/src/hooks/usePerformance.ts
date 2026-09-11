/**
 * P.A.L.M · usePerformance
 * ─────────────────────────
 * 实时性能数据 Hook。
 * 通过后端 HTTP API 获取数据，后端不可用时显示 N/O。
 */

import { useState, useEffect } from 'react';
import { tryFetch } from '../api/withFallback';

// ─── 类型 ───────────────────────────────────────────────────────

export interface CpuInfo {
  model: string;
  baseFreq: string;
  currentFreq: string;
  usage: number;
  temperature: number;
}

export interface MemoryInfo {
  speed: number;
  total: number;
  available: number;
  usage: number;
}

export interface GpuInfo {
  model: string;
  usage: number;
}

export interface NetworkInfo {
  uploadSpeed: number;
  downloadSpeed: number;
}

export interface DiskPartition {
  mount: string;
  total: number;
  used: number;
}

export interface PerfSnapshot {
  cpu: CpuInfo;
  memory: MemoryInfo;
  gpus: GpuInfo[];
  network: NetworkInfo;
  disks: DiskPartition[];
}

export interface PerfData {
  snapshot: PerfSnapshot;
  error: string | null;
}

// ─── N/O 初始状态 ────────────────────────────────────────────────

const NA = 'N/O';

const INITIAL_SNAPSHOT: PerfSnapshot = {
  cpu: { model: NA, baseFreq: NA, currentFreq: NA, usage: 0, temperature: 0 },
  memory: { speed: 0, total: 0, available: 0, usage: 0 },
  gpus: [{ model: NA, usage: 0 }],
  network: { uploadSpeed: 0, downloadSpeed: 0 },
  disks: [{ mount: NA, total: 0, used: 0 }],
};

// ─── 工具函数 ────────────────────────────────────────────────────

export function tempColor(temp: number): string {
  if (temp >= 85) return '#e24b4a';
  if (temp >= 70) return '#d4a017';
  return '#0d6b8a';
}

export function fmtSpeed(mbs: number): string {
  if (isNaN(mbs) || mbs < 0) return '0 KB/s';
  if (mbs >= 1000) return `${(mbs / 1000).toFixed(1)} GB/s`;
  if (mbs >= 1) return `${mbs.toFixed(1)} MB/s`;
  return `${(mbs * 1000).toFixed(0)} KB/s`;
}

// ─── 空磁盘分区补丁（后端暂未就绪时展示结构） ─────────────────────

const FALLBACK_DISKS: DiskPartition[] = [
  { mount: 'C:', total: 0, used: 0 },
  { mount: 'D:', total: 0, used: 0 },
  { mount: 'E:', total: 0, used: 0 },
];

// ─── Hook ────────────────────────────────────────────────────────

export function usePerformance(refreshMs = 2000): PerfData {
  const [snapshot, setSnapshot] = useState<PerfSnapshot>(INITIAL_SNAPSHOT);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let mounted = true;
    let timer: ReturnType<typeof setInterval> | null = null;

    const fetchData = async () => {
      try {
        const data = await tryFetch<PerfSnapshot>('performance', '/api/metrics', undefined, 8_000);
        if (!mounted) return;
        setSnapshot(data);
        setError(null);
      } catch (err: any) {
        if (err.name === 'AbortError') return;
        if (!mounted) return;
        // 后端不可用 → 保持 N/O 状态
        setError(err.message ?? '连接失败');
      }
    };

    const onVisibilityChange = () => {
      if (document.visibilityState === 'visible') fetchData();
    };
    document.addEventListener('visibilitychange', onVisibilityChange);

    fetchData();
    timer = setInterval(fetchData, refreshMs);
    return () => {
      mounted = false;
      if (timer) clearInterval(timer);
      document.removeEventListener('visibilitychange', onVisibilityChange);
    };
  }, [refreshMs]);

  // 后端未返回 disks 时使用占位分区
  const safeSnapshot: PerfSnapshot = {
    ...snapshot,
    disks: snapshot.disks?.length ? snapshot.disks : FALLBACK_DISKS,
  };

  return { snapshot: safeSnapshot, error };
}
