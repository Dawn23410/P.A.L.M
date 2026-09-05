/**
 * P.A.L.M · Dashboard (Compact + Status + Console)
 * ────────────────────────────────────────────────
 * 概览卡内嵌详情 + 模块状态 + 控制台输出
 */

import { useRef, useEffect, useCallback } from 'react';
import { Progress } from 'antd';
import { useModuleConfig } from '../store/configStore';
import {
  usePerformance,
  tempColor,
  fmtSpeed,
} from '../hooks/usePerformance';
import { useModuleStatus, STATUS_COLORS, STATUS_LABELS } from '../hooks/useModuleStatus';
import { useConsole, LEVEL_COLORS } from '../hooks/useConsole';

// ─── 颜色 ───────────────────────────────────────────────────────

function barColor(val: number): string {
  if (val >= 85) return '#e24b4a';
  if (val >= 65) return '#d4a017';
  return 'var(--palm-cyan, #0d6b8a)';
}

// ─── 微型进度条 ──────────────────────────────────────────────────

function MiniBar({ value, color }: { value: number; color?: string }) {
  const c = color ?? barColor(value);
  return (
    <div style={{ height: 3, borderRadius: 2, overflow: 'hidden', background: 'var(--palm-track, #d0d5dd)', marginTop: 2, marginBottom: 4 }}>
      <div style={{ width: `${Math.min(100, Math.max(1, value))}%`, background: c, height: 3, borderRadius: 2, transition: 'width 0.4s cubic-bezier(0.16,1,0.3,1)' }} />
    </div>
  );
}

// ─── 内联信息行 ──────────────────────────────────────────────────

function InlineRow({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: 9, lineHeight: '1.6' }}>
      <span style={{ color: 'var(--palm-text-low, #667085)', letterSpacing: '0.04em' }}>{label}</span>
      <span style={{ color: color ?? 'var(--palm-text-high, #101828)', fontFamily: 'ui-monospace, "SF Mono", "JetBrains Mono", Menlo, monospace', fontWeight: 500, fontSize: 9 }}>{value}</span>
    </div>
  );
}

// ─── CSS 注入 ───────────────────────────────────────────────────

function injectStyles() {
  ['palm-dashboard-style-v2', 'palm-dashboard-compact'].forEach((oldId) => {
    const old = document.getElementById(oldId);
    if (old) old.remove();
  });

  const id = 'palm-dashboard-v4';
  if (typeof document === 'undefined' || document.getElementById(id)) return;
  const s = document.createElement('style');
  s.id = id;
  s.textContent = `
    :root {
      --palm-card-border: #b0b7c3;
      --palm-text-high: #0b0f19;
      --palm-text-mid: #344054;
      --palm-text-low: #475467;
      --palm-track: #b0b7c3;
      --palm-cell-bg: #eaecf0;
    }
    :root[data-theme='dark'] {
      --palm-card-border: rgba(255,255,255,0.08);
      --palm-text-high: #f0f2f5;
      --palm-text-mid: #9aa5b1;
      --palm-text-low: #64748b;
      --palm-track: rgba(255,255,255,0.06);
      --palm-cell-bg: rgba(255,255,255,0.03);
    }

    html, body { overflow: hidden; }

    .palm-dashboard-wrap {
      display: flex;
      flex-direction: column;
      flex: 1;
      overflow: hidden;
      min-height: 0;
    }

    .palm-stats-row {
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 8px;
      margin-bottom: 12px;
    }
    @media (max-width: 900px) { .palm-stats-row { grid-template-columns: repeat(2, 1fr); } }
    @media (max-width: 500px) { .palm-stats-row { grid-template-columns: 1fr; } }

    /* ── 通用卡片 ── */
    .palm-card {
      background: var(--palm-surface, #fff);
      border: 1px solid var(--palm-card-border, #b0b7c3);
      border-radius: 10px;
      padding: 12px 14px;
      box-shadow: 0 4px 12px rgba(0,0,0,0.08), 0 1px 2px rgba(0,0,0,0.04);
      transition: all 0.2s ease;
    }
    :root[data-theme='dark'] .palm-card { box-shadow: 0 1px 3px rgba(0,0,0,0.15); }

    .palm-card__title {
      font-size: 10px; font-weight: 600;
      letter-spacing: 0.12em; text-transform: uppercase;
      color: var(--palm-text-mid, #475467);
      margin-bottom: 10px;
    }

    /* ── 概览卡 ── */
    .palm-stat-card {
      background: var(--palm-surface, #fff);
      border: 1px solid var(--palm-card-border, #b0b7c3);
      border-radius: 10px;
      padding: 10px 12px;
      transition: all 0.2s ease;
      display: flex;
      flex-direction: column;
      height: 115px;
      box-shadow: 0 4px 12px rgba(0,0,0,0.08), 0 1px 2px rgba(0,0,0,0.04);
    }
    .palm-stat-card:hover {
      border-color: var(--palm-cyan, #0d6b8a);
      box-shadow: 0 6px 16px rgba(13,107,138,0.15), 0 2px 4px rgba(0,0,0,0.06);
    }
    :root[data-theme='dark'] .palm-stat-card { box-shadow: 0 1px 3px rgba(0,0,0,0.15); }
    :root[data-theme='dark'] .palm-stat-card:hover { box-shadow: 0 2px 8px rgba(0,229,255,0.06), 0 1px 3px rgba(0,0,0,0.15); }

    .palm-stat-card__spacer { flex: 1; min-height: 0; }
    .palm-stat-card__head {
      display: flex; align-items: center; gap: 4px; margin-bottom: 3px;
    }
    .palm-stat-card__icon { font-size: 11px; line-height: 1; }
    .palm-stat-card__label {
      font-size: 9px; letter-spacing: 0.12em;
      text-transform: uppercase; font-weight: 600;
      color: var(--palm-text-mid, #475467);
    }
    .palm-stat-card__model-row {
      display: flex; justify-content: space-between;
      align-items: center; margin-bottom: 2px;
    }
    .palm-stat-card__model {
      font-size: 9px; font-weight: 600;
      font-family: ui-monospace,monospace;
      color: var(--palm-text-mid, #475467);
      white-space: nowrap; overflow: hidden;
      text-overflow: ellipsis; max-width: 65%; letter-spacing: -0.01em;
    }
    .palm-stat-card__usage {
      font-size: 14px; font-weight: 700;
      font-family: ui-monospace,"SF Mono","JetBrains Mono",Menlo,monospace;
      font-variant-numeric: tabular-nums;
      text-align: right; margin-left: auto; flex-shrink: 0; letter-spacing: -0.02em;
    }

    /* ── 模块状态 ── */
    .palm-status-grid {
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 8px;
    }
    @media (max-width: 900px) { .palm-status-grid { grid-template-columns: repeat(2, 1fr); } }
    @media (max-width: 500px) { .palm-status-grid { grid-template-columns: 1fr; } }

    .palm-status-cell {
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 8px 10px;
      background: var(--palm-cell-bg, #eaecf0);
      border-radius: 6px;
      transition: background 0.2s ease;
    }
    .palm-status-dot {
      width: 8px; height: 8px; border-radius: 50%;
      flex-shrink: 0;
      transition: background 0.3s ease;
    }
    .palm-status-info {
      display: flex; flex-direction: column; gap: 1px;
      min-width: 0;
    }
    .palm-status-name {
      font-size: 10px; font-weight: 600;
      color: var(--palm-text-high, #0b0f19);
      white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
    }
    .palm-status-desc {
      font-size: 8px;
      color: var(--palm-text-low, #475467);
      white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
    }
    .palm-status-tag {
      margin-left: auto;
      font-size: 8px; font-weight: 600;
      font-family: ui-monospace,monospace;
      flex-shrink: 0;
    }

    .palm-status-summary {
      display: flex;
      gap: 12px;
      margin-bottom: 10px;
      flex-wrap: wrap;
    }
    .palm-status-summary-item {
      display: flex;
      align-items: center;
      gap: 4px;
      font-size: 9px;
      font-family: ui-monospace,monospace;
      color: var(--palm-text-mid, #475467);
    }
    .palm-status-summary-dot {
      width: 6px; height: 6px; border-radius: 50%;
    }

    /* ── 控制台 ── */
    .palm-console {
      flex: 1;
      min-height: 0;
      background: #f0f2f5;
      border-radius: 6px 6px 0 0;
      padding: 10px 12px 4px;
      overflow-y: auto;
      font-family: ui-monospace,"SF Mono","JetBrains Mono",Menlo,monospace;
      font-size: 10px;
      line-height: 1.7;
    }
    :root[data-theme='dark'] .palm-console {
      background: #0d1b2a;
    }
    :root {
      --console-input-color: #334155;
    }
    :root[data-theme='dark'] {
      --console-input-color: #e2e8f0;
    }
    .palm-console::-webkit-scrollbar { width: 4px; }
    .palm-console::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.15); border-radius: 2px; }

    .palm-console-line {
      display: flex;
      gap: 6px;
      opacity: 0.9;
      white-space: pre-wrap;
      word-break: break-all;
    }

    .palm-console-input-line {
      display: flex;
      align-items: center;
      gap: 6px;
      padding: 6px 12px 8px;
      background: #f0f2f5;
      border-radius: 0 0 6px 6px;
    }
    :root[data-theme='dark'] .palm-console-input-line {
      background: #0d1b2a;
    }
    .palm-console-prompt {
      font-weight: 700;
      flex-shrink: 0;
      user-select: none;
    }
    .palm-console-input {
      flex: 1;
      background: transparent;
      border: none;
      outline: none;
      color: var(--palm-text-mid, #344054);
      font-family: inherit;
      font-size: 10px;
      caret-color: #22c55e;
      padding: 0;
    }

    /* ── 存储大卡 ── */
    .palm-storage-card {
      background: var(--palm-surface, #fff);
      border: 1px solid var(--palm-card-border, #b0b7c3);
      border-radius: 10px;
      padding: 14px 16px 16px;
      transition: all 0.2s ease;
      box-shadow: 0 4px 12px rgba(0,0,0,0.08), 0 1px 2px rgba(0,0,0,0.04);
    }
    .palm-storage-card:hover {
      border-color: var(--palm-cyan, #0d6b8a);
      box-shadow: 0 6px 16px rgba(13,107,138,0.15), 0 2px 4px rgba(0,0,0,0.06);
    }
    :root[data-theme='dark'] .palm-storage-card { box-shadow: 0 1px 3px rgba(0,0,0,0.15); }
    :root[data-theme='dark'] .palm-storage-card:hover { box-shadow: 0 2px 8px rgba(0,229,255,0.06), 0 1px 3px rgba(0,0,0,0.15); }

    .palm-storage-card__title {
      font-size: 10px; font-weight: 600;
      letter-spacing: 0.12em; text-transform: uppercase;
      color: var(--palm-text-mid, #475467); margin-bottom: 10px;
    }
    .palm-storage-card__overview {
      display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px;
    }
    .palm-storage-card__olabel {
      font-size: 9px; letter-spacing: 0.08em; text-transform: uppercase;
      color: var(--palm-text-low, #475467);
    }
    .palm-storage-card__ovalue {
      font-size: 13px; font-weight: 700; font-family: ui-monospace,monospace;
    }
    .palm-storage-partitions {
      display: grid; grid-template-columns: repeat(3, 1fr);
      gap: 10px; margin-top: 10px;
    }
    .palm-partition-cell {
      display: flex; flex-direction: column; gap: 3px;
      background: var(--palm-cell-bg, #eaecf0);
      border-radius: 6px; padding: 8px 10px;
    }
    .palm-partition-header {
      display: flex; align-items: center; justify-content: space-between;
    }
    .palm-partition-mount {
      font-size: 10px; font-weight: 600; font-family: ui-monospace,monospace;
      color: var(--palm-text-high, #101828);
    }
    .palm-partition-size {
      font-size: 8px; color: var(--palm-text-low, #475467);
      font-family: ui-monospace,monospace;
    }

    /* ── GPU ── */
    .palm-gpu-preview-sep {
      height: 1px; background: var(--palm-card-border, #d0d5dd); margin: 4px 0;
    }
    .palm-gpu-content {
      flex: 1; overflow-y: auto; scrollbar-width: none; min-height: 0;
      margin: 0 -2px; padding: 0 2px;
    }
    .palm-gpu-content::-webkit-scrollbar { display: none; }
    .palm-gpu-card { user-select: none; }
  `;
  document.head.appendChild(s);
}

// ─── 页面 ───────────────────────────────────────────────────────

export default function Dashboard() {
  injectStyles();
  const { config } = useModuleConfig('dashboard');
  const refreshInterval = (config as any)?.refreshInterval ?? 1;
  const { snapshot } = usePerformance(1000);
  const { cpu, memory, gpus, network, disks } = snapshot;
  const moduleStatus = useModuleStatus();
  const { lines: consoleLines, input: consoleInput, setInput: setConsoleInput, submitCommand } = useConsole();

  const consoleRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // 自动滚动到底部
  useEffect(() => {
    if (consoleRef.current) {
      consoleRef.current.scrollTop = consoleRef.current.scrollHeight;
    }
  }, [consoleLines]);

  const handleConsoleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      submitCommand(consoleInput, moduleStatus.modules);
      setConsoleInput('');
    }
  }, [consoleInput, submitCommand, moduleStatus.modules, setConsoleInput]);

  // 点击控制台区域自动聚焦输入框
  const focusInput = useCallback(() => {
    inputRef.current?.focus();
  }, []);

  const totalUsed = disks.reduce((a, d) => a + d.used, 0);
  const totalSize = disks.reduce((a, d) => a + d.total, 0);
  const storageOverall = Math.round((totalUsed / totalSize) * 100);

  const sortedGpus = [...gpus].sort((a, b) => {
    const aIsIntegrated = /iris|uhd|hd graphics|xe|integrated/i.test(a.model);
    const bIsIntegrated = /iris|uhd|hd graphics|xe|integrated/i.test(b.model);
    if (aIsIntegrated && !bIsIntegrated) return -1;
    if (!aIsIntegrated && bIsIntegrated) return 1;
    return 0;
  });

  return (
    <div className="palm-dashboard-wrap">
      {/* ── 标题 ── */}
      <div className="palm-page__title-row palm-page__title-row--compact">
        <div>
          <div className="palm-page__subtitle">系统仪表盘</div>
          <h2 className="palm-page__title">仪表盘</h2>
        </div>
        <div style={{ marginLeft: 'auto', fontSize: 9, letterSpacing: '0.1em', color: 'var(--palm-text-low, #667085)', fontFamily: 'ui-monospace,monospace', display: 'flex', alignItems: 'center', gap: 5 }}>
          <span style={{ width: 4, height: 4, borderRadius: '50%', background: '#22c55e', display: 'inline-block', animation: 'palm-pulse 2s ease-in-out infinite' }} />
          <span style={{ opacity: 0.7 }}>{refreshInterval}s</span>
        </div>
      </div>

      {/* ── 概览卡行 ── */}
      <div className="palm-stats-row">
        <div className="palm-stat-card">
          <div className="palm-stat-card__head">
            <span className="palm-stat-card__icon">⬡</span>
            <span className="palm-stat-card__label">CPU</span>
          </div>
          <div className="palm-stat-card__model-row">
            <span className="palm-stat-card__model" title={cpu.model}>{cpu.model}</span>
            <span className="palm-stat-card__usage" style={{ color: barColor(cpu.usage) }}>{cpu.usage}%</span>
          </div>
          <MiniBar value={cpu.usage} />
          <InlineRow label="温度" value={`${cpu.temperature}°C`} color={tempColor(cpu.temperature)} />
          <InlineRow label="当前频率" value={cpu.currentFreq} />
          <div className="palm-stat-card__spacer" />
        </div>

        <div className="palm-stat-card">
          <div className="palm-stat-card__head">
            <span className="palm-stat-card__icon">⬢</span>
            <span className="palm-stat-card__label">内存</span>
          </div>
          <div className="palm-stat-card__model-row">
            <span className="palm-stat-card__usage" style={{ color: barColor(memory.usage) }}>{memory.usage}%</span>
          </div>
          <MiniBar value={memory.usage} />
          <InlineRow label="已用" value={`${(memory.total - memory.available).toFixed(1)} / ${memory.total} GB`} />
          <InlineRow label="速度" value={`${memory.speed} MT/s`} />
          <div className="palm-stat-card__spacer" />
        </div>

        <div className="palm-stat-card palm-gpu-card">
          <div className="palm-stat-card__head">
            <span className="palm-stat-card__icon">◆</span>
            <span className="palm-stat-card__label">GPU{sortedGpus.length > 1 ? ` · ${sortedGpus.length} 张` : ''}</span>
          </div>
          <div className="palm-gpu-content">
            {sortedGpus.map((gpu, i) => (
              <div key={i}>
                {i > 0 && <div className="palm-gpu-preview-sep" />}
                <div className="palm-stat-card__model-row">
                  <span className="palm-stat-card__model" title={gpu.model}>{gpu.model}</span>
                  <span className="palm-stat-card__usage" style={{ color: barColor(gpu.usage) }}>{gpu.usage}%</span>
                </div>
                <MiniBar value={gpu.usage} />
                <InlineRow label="利用率" value={`${gpu.usage}%`} />
              </div>
            ))}
          </div>
        </div>

        <div className="palm-stat-card">
          <div className="palm-stat-card__head">
            <span className="palm-stat-card__icon">⤮</span>
            <span className="palm-stat-card__label">网络</span>
          </div>
          <div className="palm-stat-card__model-row">
            <span className="palm-stat-card__model" style={{ maxWidth: 'none' }}>当前速率</span>
            <span className="palm-stat-card__usage" style={{ color: network.downloadSpeed > 5 ? '#0d6b8a' : barColor(Math.round((network.downloadSpeed / 50) * 100)) }}>{fmtSpeed(network.downloadSpeed)}</span>
          </div>
          <MiniBar value={Math.min(100, Math.round((network.downloadSpeed / 50) * 100))} />
          <div style={{ display: 'flex', alignItems: 'center', gap: 2, fontSize: 9, lineHeight: '1.6', marginTop: 1 }}>
            <span style={{ color: network.downloadSpeed > 5 ? '#0d6b8a' : 'var(--palm-text-low, #667085)', fontWeight: 700, fontFamily: 'ui-monospace,monospace' }}>↓</span>
            <span style={{ color: 'var(--palm-text-low, #667085)', letterSpacing: '0.04em' }}>下载</span>
            <span style={{ marginLeft: 'auto', fontFamily: 'ui-monospace,monospace', fontWeight: 500, color: 'var(--palm-text-high, #0b0f19)' }}>{fmtSpeed(network.downloadSpeed)}</span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 2, fontSize: 9, lineHeight: '1.6' }}>
            <span style={{ color: network.uploadSpeed > 1 ? '#22c55e' : 'var(--palm-text-low, #667085)', fontWeight: 700, fontFamily: 'ui-monospace,monospace' }}>↑</span>
            <span style={{ color: 'var(--palm-text-low, #667085)', letterSpacing: '0.04em' }}>上传</span>
            <span style={{ marginLeft: 'auto', fontFamily: 'ui-monospace,monospace', fontWeight: 500, color: 'var(--palm-text-high, #0b0f19)' }}>{fmtSpeed(network.uploadSpeed)}</span>
          </div>
          <div className="palm-stat-card__spacer" />
        </div>
      </div>

      {/* ── 存储大卡 ── */}
      <div className="palm-storage-card" style={{ marginBottom: 12 }}>
        <div className="palm-storage-card__title">存储</div>
        <div className="palm-storage-card__overview">
          <span className="palm-storage-card__olabel">总使用</span>
          <span className="palm-storage-card__ovalue" style={{ color: barColor(storageOverall) }}>
            {totalUsed.toLocaleString()} / {totalSize.toLocaleString()} GB
          </span>
        </div>
        <Progress percent={storageOverall} showInfo={false} strokeColor={barColor(storageOverall)} trailColor="var(--palm-track, #b0b7c3)" size="small" />
        <div className="palm-storage-partitions">
          {disks.map((d) => {
            const usage = Math.round((d.used / d.total) * 100);
            return (
              <div key={d.mount} className="palm-partition-cell">
                <div className="palm-partition-header">
                  <span className="palm-partition-mount">{d.mount}\</span>
                  <span className="palm-partition-size">{d.used.toLocaleString()} / {d.total.toLocaleString()} GB</span>
                </div>
                <Progress percent={usage} showInfo={false} strokeColor={barColor(usage)} trailColor="var(--palm-track, #b0b7c3)" size="small" />
              </div>
            );
          })}
        </div>
      </div>

      {/* ── 模块状态 ── */}
      <div className="palm-card" style={{ marginBottom: 12 }}>
        <div className="palm-card__title">模块状态</div>
        <div className="palm-status-summary">
          <div className="palm-status-summary-item">
            <span className="palm-status-summary-dot" style={{ background: STATUS_COLORS.online }} />
            {moduleStatus.summary.online} 在线
          </div>
          <div className="palm-status-summary-item">
            <span className="palm-status-summary-dot" style={{ background: STATUS_COLORS.warning }} />
            {moduleStatus.summary.warning} 异常
          </div>
          <div className="palm-status-summary-item">
            <span className="palm-status-summary-dot" style={{ background: STATUS_COLORS.error }} />
            {moduleStatus.summary.error} 错误
          </div>
          <div className="palm-status-summary-item">
            <span className="palm-status-summary-dot" style={{ background: STATUS_COLORS.offline }} />
            {moduleStatus.summary.offline} 离线
          </div>
        </div>
        <div className="palm-status-grid">
          {moduleStatus.modules.map(mod => (
            <div key={mod.id} className="palm-status-cell">
              <span className="palm-status-dot" style={{ background: STATUS_COLORS[mod.status] }} />
              <div className="palm-status-info">
                <span className="palm-status-name">{mod.name}</span>
                <span className="palm-status-desc">{mod.description}</span>
              </div>
              <span className="palm-status-tag" style={{ color: STATUS_COLORS[mod.status] }}>
                {STATUS_LABELS[mod.status]}
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* ── 控制台 ── */}
      <div className="palm-card" style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
        <div className="palm-card__title" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <span>控制台</span>
          <span style={{ fontSize: 9, color: 'var(--palm-text-low, #667085)', fontWeight: 400, letterSpacing: '0.02em' }}>输入 help 查看可用命令</span>
        </div>
        <div style={{ position: 'relative', flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', minHeight: 0 }}>
          <div className="palm-console" ref={consoleRef} onClick={focusInput}>
            {consoleLines.map(line => (
              <div key={line.id} className="palm-console-line" style={{ color: LEVEL_COLORS[line.level] }}>
                {line.level !== 'input' && line.level !== 'system' && (
                  <span className="palm-console-tag" style={{ color: LEVEL_COLORS[line.level] }}>
                    [{line.level.toUpperCase().slice(0, 4)}]
                  </span>
                )}
                <span>{line.text}</span>
              </div>
            ))}
          </div>
          <div className="palm-console-input-line">
            <span className="palm-console-prompt" style={{ color: '#22c55e' }}>$</span>
            <input
              ref={inputRef}
              className="palm-console-input"
              type="text"
              value={consoleInput}
              onChange={e => setConsoleInput(e.target.value)}
              onKeyDown={handleConsoleKeyDown}
              spellCheck={false}
              autoComplete="off"
            />
          </div>
        </div>
      </div>
    </div>
  );
}
