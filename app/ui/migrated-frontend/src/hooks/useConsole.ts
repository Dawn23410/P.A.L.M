/**
 * P.A.L.M · useConsole
 * ──────────────────────
 * 交互式控制台 Hook —— 纯本地内置命令终端（不连接后端执行引擎，不执行代码）。
 *  - help / clear / ver   本地处理
 *  - status / modules     只读 GET 读取 P.A.L.M 引擎真实状态（非代码执行）
 *  - 不支持 Python / Bash / Node 等任意代码执行
 * 终端只服务于 P.A.L.M 项目本身的运维查看。
 */

import { useState, useCallback, useRef } from 'react';
import { tryFetch } from '../api/withFallback';

// ─── 类型 ───────────────────────────────────────────────────────

export type ConsoleLevel = 'info' | 'success' | 'warn' | 'error' | 'debug' | 'system' | 'input';

export interface ConsoleLine {
  id: number;
  level: ConsoleLevel;
  text: string;
}

export const LEVEL_COLORS: Record<ConsoleLevel, string> = {
  info:    '#0891b2',
  success: '#22c55e',
  warn:    '#d4a017',
  error:   '#e24b4a',
  debug:   '#64748b',
  system:  '#a78bfa',
  input:   'var(--console-input-color, #475569)',
};

// ─── ID 生成器 ──────────────────────────────────────────────────

let nextId = 100;
function makeId() { return nextId++; }
function sysLine(level: ConsoleLevel, text: string): ConsoleLine {
  return { id: makeId(), level, text };
}

// ─── 真实状态读取（只读 GET，非代码执行） ────────────────────────

async function fetchProjectStatus(): Promise<ConsoleLine[]> {
  try {
    const [mods, metrics] = await Promise.all([
      tryFetch<any>('performance', '/api/modules').catch(() => null),
      tryFetch<any>('performance', '/api/metrics').catch(() => null),
    ]);
    const lines: ConsoleLine[] = [sysLine('system', '── P.A.L.M 系统状态 ──')];
    if (Array.isArray(mods)) {
      const online = mods.filter((m: any) => m.status === 'online').length;
      lines.push(sysLine('info', `模块: 共 ${mods.length} 个 · 在线 ${online}`));
      mods.slice(0, 12).forEach((m: any) =>
        lines.push(sysLine('debug', `  [${m.status === 'online' ? '●' : m.status === 'error' ? '✕' : m.status === 'warning' ? '◉' : '○'}] ${m.name}`)));
      if (mods.length > 12) lines.push(sysLine('debug', `  … 其余 ${mods.length - 12} 个`));
    } else {
      lines.push(sysLine('warn', '模块数据不可用'));
    }
    if (metrics && typeof metrics === 'object') {
      const parts = Object.entries(metrics)
        .slice(0, 8)
        .map(([k, v]) => `  ${k}: ${typeof v === 'object' ? JSON.stringify(v) : String(v)}`);
      lines.push(sysLine('info', '指标:'));
      parts.forEach((p) => lines.push(sysLine('debug', p)));
    }
    return lines;
  } catch (e) {
    return [sysLine('error', `获取状态失败: ${String(e)}`)];
  }
}

async function fetchModules(): Promise<ConsoleLine[]> {
  try {
    const mods = await tryFetch<any>('performance', '/api/modules');
    if (!Array.isArray(mods) || mods.length === 0) return [sysLine('warn', '暂无模块数据')];
    return [
      sysLine('system', `已注册模块 (${mods.length}):`),
      ...mods.map((m: any) => sysLine(
        m.status === 'online' ? 'success' : m.status === 'warning' ? 'warn' : m.status === 'error' ? 'error' : 'debug',
        `  [${m.status === 'online' ? '●' : m.status === 'warning' ? '◉' : m.status === 'error' ? '✕' : '○'}] ${m.name}${m.description ? ' — ' + m.description : ''}`)),
    ];
  } catch (e) {
    return [sysLine('error', `获取模块失败: ${String(e)}`)];
  }
}

// ─── 帮助 / 欢迎 ─────────────────────────────────────────────────

const HELP_TEXT: ConsoleLine[] = [
  sysLine('system', 'P.A.L.M 控制台 — 内置命令终端'),
  sysLine('info', '  help             显示此帮助'),
  sysLine('info', '  status           显示 P.A.L.M 系统状态'),
  sysLine('info', '  modules          列出已注册模块'),
  sysLine('info', '  clear            清屏'),
  sysLine('info', '  ver              系统版本'),
];

const WELCOME_LINES: ConsoleLine[] = [
  sysLine('system', 'P.A.L.M 控制台已就绪 · 输入 help 查看命令'),
];

// ─── Hook ────────────────────────────────────────────────────────

export function useConsole() {
  const [lines, setLines] = useState<ConsoleLine[]>(WELCOME_LINES);
  const [input, setInput] = useState('');
  const [executing, setExecuting] = useState(false);
  const maxLines = useRef(200);

  const append = useCallback((newLines: ConsoleLine[]) => {
    setLines((prev) => {
      const combined = [...prev, ...newLines];
      return combined.length > maxLines.current
        ? combined.slice(combined.length - maxLines.current)
        : combined;
    });
  }, []);

  const submitCommand = useCallback(async (raw: string) => {
    const cmd = raw.trim();
    append([sysLine('input', `$ ${raw}`)]);
    if (cmd === '') return;
    const lower = cmd.toLowerCase();

    if (lower === 'clear') { setLines([]); return; }
    if (lower === 'help') { append(HELP_TEXT); return; }
    if (lower === 'ver') { append([sysLine('info', 'P.A.L.M 系统 v1.0.0 (Build 2026.06)')]); return; }

    if (lower === 'status' || lower === 'modules') {
      setExecuting(true);
      try {
        append(await (lower === 'status' ? fetchProjectStatus() : fetchModules()));
      } finally {
        setExecuting(false);
      }
      return;
    }

    append([sysLine('error', `未知命令: ${cmd}（输入 help 查看可用命令）`)]);
  }, [append]);

  const clearConsole = useCallback(() => setLines([]), []);

  return { lines, input, setInput, submitCommand, clearConsole, executing };
}
