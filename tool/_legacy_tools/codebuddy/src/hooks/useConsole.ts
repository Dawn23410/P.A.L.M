/**
 * P.A.L.M · useConsole
 * ──────────────────────
 * 正式交互式控制台 Hook。
 * 支持命令输入与响应，无模拟数据。
 */

import { useState, useCallback, useRef } from 'react';

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

// ─── 欢迎信息 ────────────────────────────────────────────────────

const WELCOME_LINES: ConsoleLine[] = [];

// ─── ID 生成器 ──────────────────────────────────────────────────
// 必须放在 HELP_TEXT 之前，避免 let TDZ
let nextId = 100;

function makeId() { return nextId++; }

// ─── 命令处理器 ──────────────────────────────────────────────────

const HELP_TEXT: ConsoleLine[] = [
  { id: makeId(), level: 'info', text: '可用命令:' },
  { id: makeId(), level: 'info', text: '  help     — 显示此帮助' },
  { id: makeId(), level: 'info', text: '  clear    — 清屏' },
  { id: makeId(), level: 'info', text: '  status   — 显示系统状态' },
  { id: makeId(), level: 'info', text: '  modules  — 列出所有模块' },
  { id: makeId(), level: 'info', text: '  echo ... — 回显输入' },
  { id: makeId(), level: 'info', text: '  date     — 显示当前时间' },
  { id: makeId(), level: 'info', text: '  whoami   — 显示当前用户' },
  { id: makeId(), level: 'info', text: '  ver      — 系统版本' },
];

function sysLine(level: ConsoleLevel, text: string): ConsoleLine {
  return { id: makeId(), level, text };
}

function executeCommand(input: string, modules: { name: string; status: string }[]): ConsoleLine[] {
  const trimmed = input.trim().toLowerCase();
  const parts = trimmed.split(/\s+/);
  const cmd = parts[0];

  switch (cmd) {
    case 'help':
      return HELP_TEXT;

    case 'clear':
      return []; // 特殊标记由外部处理

    case 'status': {
      const results: ConsoleLine[] = [
        sysLine('info', '系统状态:'),
        sysLine('info', `  运行时间: 在线`),
        sysLine('info', `  模块总数: ${modules.length}`),
        sysLine('info', `  在线模块: ${modules.filter(m => m.status === 'online').length}`),
        sysLine('info', `  异常模块: ${modules.filter(m => m.status === 'warning').length}`),
        sysLine('info', `  错误模块: ${modules.filter(m => m.status === 'error').length}`),
        sysLine('info', `  离线模块: ${modules.filter(m => m.status === 'offline').length}`),
      ];
      return results;
    }

    case 'modules':
      if (modules.length === 0) return [sysLine('warn', '暂无模块数据')];
      return [
        sysLine('info', '已注册模块:'),
        ...modules.map(m => sysLine(
          m.status === 'online' ? 'success' : m.status === 'warning' ? 'warn' : m.status === 'error' ? 'error' : 'debug',
          `  [${m.status === 'online' ? '●' : m.status === 'warning' ? '◉' : m.status === 'error' ? '✕' : '○'}] ${m.name}`
        )),
      ];

    case 'echo':
      return [sysLine('info', input.slice(4).trim() || '')];

    case 'date': {
      const now = new Date();
      return [sysLine('info', now.toLocaleString('zh-CN'))];
    }

    case 'whoami':
      return [sysLine('info', 'P.A.L.M System User')];

    case 'ver':
      return [sysLine('info', 'P.A.L.M 系统 v1.0.0 (Build 2026.06)')];

    case '':
      return [];

    default:
      return [sysLine('error', `未知命令: ${cmd}。输入 help 查看可用命令`)];
  }
}

// ─── Hook ────────────────────────────────────────────────────────

export function useConsole() {
  const [lines, setLines] = useState<ConsoleLine[]>(WELCOME_LINES);
  const [input, setInput] = useState('');
  const maxLines = useRef(200);

  const submitCommand = useCallback((cmd: string, modules?: { name: string; status: string }[]) => {
    const inputLine: ConsoleLine = { id: makeId(), level: 'input', text: `$ ${cmd}` };
    const result = executeCommand(cmd, modules ?? []);

    if (cmd.trim().toLowerCase() === 'clear') {
      setLines([]);
      return;
    }

    setLines(prev => {
      const combined = [...prev, inputLine, ...result];
      return combined.length > maxLines.current
        ? combined.slice(combined.length - maxLines.current)
        : combined;
    });
  }, []);

  const clearConsole = useCallback(() => {
    setLines([]);
  }, []);

  return { lines, input, setInput, submitCommand, clearConsole };
}
