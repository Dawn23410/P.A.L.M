/**
 * P.A.L.M · Module Management
 * ────────────────────────────
 * 模块管理面板：识别到的模块卡片列表 + 上传模块弹窗。
 * 后端不可用时自动展示模拟数据。
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { App, Button, Modal, Progress, Spin, Tag } from 'antd';
import {
  UploadOutlined, AppstoreOutlined, InboxOutlined,
  CloseCircleOutlined, CheckCircleFilled, CloseCircleFilled,
} from '@ant-design/icons';

const API_BASE = import.meta.env.VITE_MODULE_API_BASE || 'http://127.0.0.1:9090';

// ─── 类型 ───────────────────────────────────────────────────────

interface ModuleCard {
  name: string;
  version: string;
  type: string;
  description: string;
  author: string;
  status: '未安装' | '已安装' | '损坏';
  integrity: { status: string; expected?: string; actual?: string; error?: string; warning?: string };
  port: number | null;
  path: string;
  running: boolean;
}

type ValidateState =
  | { type: 'idle' }
  | { type: 'validating' }
  | { type: 'valid'; module: string; version: string; description: string; entry: string; port: number | null; file: File }
  | { type: 'invalid'; reason: string; details?: string[] };

// ─── 颜色映射 ───────────────────────────────────────────────────

const STATUS_TAG: Record<string, { color: string; text: string }> = {
  '未安装': { color: 'default', text: '未安装' },
  '已安装': { color: 'success', text: '已安装' },
  '损坏':   { color: 'error',   text: '损坏' },
};

const TYPE_TAG: Record<string, string> = {
  backend:  'cyan',
  frontend: 'geekblue',
  service:  'purple',
  tool:     'orange',
};

// ─── 组件 ───────────────────────────────────────────────────────

export default function ModuleManagement() {
  const { message } = App.useApp();
  const [modules, setModules] = useState<ModuleCard[]>([]);
  const [loading, setLoading] = useState(true);
  const [apiError, setApiError] = useState(false);
  const [operating, setOperating] = useState<string | null>(null);
  const [progress, setProgress] = useState<{ name: string; percent: number; step: string } | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [validateState, setValidateState] = useState<ValidateState>({ type: 'idle' });
  const fileInputRef = useRef<HTMLInputElement>(null);
  const dirInputRef = useRef<HTMLInputElement>(null);
  const mountedRef = useRef(true);
  useEffect(() => () => { mountedRef.current = false; }, []);

  // ── 获取模块列表（含重试） ────────────────────────────────────

  const fetchModules = useCallback(async (retries = 5, silent = false) => {
    if (!silent) setLoading(true);
    setApiError(false);
    for (let i = 0; i < retries; i++) {
      try {
        const res = await fetch(`${API_BASE}/api/modules/with-status`);
        if (res.ok) {
          const data = await res.json();
          if (mountedRef.current) {
            setModules(data.modules || []);
            if (!silent) setLoading(false);
          }
          return;
        }
      } catch {
        // 后端未就绪
      }
      if (i < retries - 1) {
        await new Promise(r => setTimeout(r, 1000));
      }
    }
    if (!silent) { setApiError(true); setLoading(false); }
  }, []);

  useEffect(() => {
    fetchModules();
    const timer = setInterval(() => fetchModules(1, true), 5000);
    return () => clearInterval(timer);
  }, [fetchModules]);

  // ── 带进度条的 API 操作 ─────────────────────────────────────

  const advanceProgress = useCallback((name: string, steps: [number, string][], done: () => Promise<void>) => {
    let i = 0;
    const tick = () => {
      if (i >= steps.length) {
        done().finally(() => { if (mountedRef.current) { setOperating(null); setProgress(null); } });
        return;
      }
      const [pct, label] = steps[i];
      i++;
      if (mountedRef.current) setProgress({ name, percent: pct, step: label });
      if (pct < 100) {
        setTimeout(tick, 80);
      } else {
        done().finally(() => { if (mountedRef.current) { setOperating(null); setProgress(null); } });
      }
    };
    tick();
  }, []);

  const handleInstall = useCallback(async (name: string, version: string) => {
    setOperating(name);
    advanceProgress(name, [
      [8, '准备中…'],
      [25, '解压模块包…'],
      [45, '验证 MANIFEST…'],
      [65, '写入配置…'],
      [80, '注册模块…'],
      [100, ''],
    ], async () => {
      const res = await fetch(`${API_BASE}/api/module/install`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ filename: `${name}-v${version}.7z` }),
      });
      if (res.ok) message.success(`「${name}」安装成功`);
      else { const err = await res.json(); message.error((err.detail || err)?.error || '安装失败'); }
      fetchModules();
    });
  }, [fetchModules, advanceProgress]);

  const handleUninstall = useCallback(async (name: string) => {
    setOperating(name);
    advanceProgress(name, [
      [10, '停止模块…'],
      [40, '执行卸载钩子…'],
      [70, '清理目录…'],
      [90, '移除注册…'],
      [100, ''],
    ], async () => {
      const res = await fetch(`${API_BASE}/api/module/uninstall`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name }),
      });
      if (res.ok) message.success(`「${name}」已卸载`);
      else { const err = await res.json(); message.error((err.detail || err)?.error || '卸载失败'); }
      fetchModules();
    });
  }, [fetchModules, advanceProgress]);

  // ── 上传验证 ─────────────────────────────────────────────────

  const validateOnBackend = useCallback(async (file: File) => {
    if (!file.name.endsWith('.7z')) {
      setValidateState({ type: 'invalid', reason: '仅支持 .7z 格式的模块包' });
      return;
    }
    setValidateState({ type: 'validating' });
    const fd = new FormData();
    fd.append('file', file);
    try {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 20000);
      const res = await fetch(`${API_BASE}/api/module/validate`, {
        method: 'POST', body: fd, signal: controller.signal,
      });
      clearTimeout(timeoutId);
      if (res.ok) {
        const d = await res.json();
        setValidateState({
          type: 'valid',
          module: d.info.module,
          version: d.info.version,
          description: d.info.description || '',
          entry: d.info.entry,
          port: d.info.port,
          file,
        });
      } else {
        const err = await res.json();
        const detail = err.detail || err;
        setValidateState({ type: 'invalid', reason: detail.error || '验证失败', details: detail.details });
      }
    } catch (err: any) {
      if (err?.name === 'AbortError') {
        setValidateState({ type: 'invalid', reason: '验证超时（20 秒），请检查模块包是否损坏' });
      } else {
        setValidateState({ type: 'invalid', reason: '无法连接到模块管理服务（端口 9090）' });
      }
    }
  }, []);

  const acceptFile = useCallback((file: File) => {
    setSelectedFile(file);
    setValidateState({ type: 'idle' });
    validateOnBackend(file);
  }, [validateOnBackend]);

  const handleDragEnter = (e: React.DragEvent) => { e.preventDefault(); setDragOver(true); };
  const handleDragLeave = (e: React.DragEvent) => { e.preventDefault(); setDragOver(false); };
  const handleDrop = (e: React.DragEvent) => { e.preventDefault(); setDragOver(false); const f = e.dataTransfer.files[0]; if (f) acceptFile(f); };
  const handleFilePick = (e: React.ChangeEvent<HTMLInputElement>) => { const f = e.target.files?.[0]; if (f) acceptFile(f); };
  const handleDirPick = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (files && files.length > 0) {
      const zips = Array.from(files).filter(f => f.name.endsWith('.7z'));
      if (zips.length > 0) acceptFile(zips[0]);
    }
  };
  const handleClear = () => { setSelectedFile(null); setValidateState({ type: 'idle' }); if (fileInputRef.current) fileInputRef.current.value = ''; };
  const handleClose = () => { setModalOpen(false); setSelectedFile(null); setValidateState({ type: 'idle' }); setDragOver(false); };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16, height: '100%', overflow: 'hidden' }}>
      {/* ── 标题行 ── */}
      <div className="palm-page__title-row palm-page__title-row--compact"
           style={{ display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between', flexShrink: 0 }}>
        <div>
          <div className="palm-page__subtitle">模块管理</div>
          <h2 className="palm-page__title">模块管理</h2>
        </div>
        <div style={{ display: 'flex', gap: 8, marginBottom: 8 }}>
          <Button type="primary" icon={<UploadOutlined />} onClick={() => setModalOpen(true)}>上传模块</Button>
        </div>
      </div>

      {/* ── 已识别到的模块 ── */}
      <div className="palm-card" style={{
        flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column', minHeight: 0,
      }}>
        <div className="palm-card__title" style={{
          flexShrink: 0, display: 'flex', alignItems: 'center', gap: 6,
          borderBottom: '1px solid var(--palm-line)', paddingBottom: 8, marginBottom: 0,
        }}>
          <AppstoreOutlined />
          已识别到的模块
          <span style={{ marginLeft: 'auto', fontSize: 9, color: 'var(--palm-text-faint)', fontWeight: 400, fontFamily: 'ui-monospace,monospace' }}>D:\Desktop\Codebuddy\modules\</span>
        </div>

        {/* ── 模块列表 ── */}
        <div style={{
          flex: 1, overflowY: 'auto', minHeight: 0, padding: '8px 0',
          display: 'flex', flexDirection: 'column', gap: 8,
        }}>
          {!loading && apiError && (
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', minHeight: 200, color: 'var(--palm-text-faint)', fontSize: 12, gap: 8 }}>
              <CloseCircleFilled style={{ fontSize: 36, opacity: 0.35, color: '#e24b4a' }} />
              <span style={{ color: '#e24b4a' }}>无法连接到模块管理服务（端口 9090）</span>
              <Button size="small" onClick={() => fetchModules()}>重试</Button>
            </div>
          )}

          {!loading && !apiError && modules.length === 0 && (
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', minHeight: 200, color: 'var(--palm-text-faint)', fontSize: 12, gap: 8 }}>
              <AppstoreOutlined style={{ fontSize: 36, opacity: 0.25 }} />
              <span>暂未识别到任何模块</span>
              <span style={{ fontSize: 10, opacity: 0.6 }}>尚无模块，点击「上传模块」安装</span>
            </div>
          )}

          {modules.map((m) => (
            <div key={m.name} className="palm-card"
              style={{
                display: 'flex', alignItems: 'center', gap: 14,
                padding: '10px 14px', cursor: 'default',
              }}>
              {/* 模块名 + 标签 + 版本（左侧信息区） */}
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 3, flexWrap: 'wrap' }}>
                  <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--palm-text)' }}>{m.name}</span>
                  <Tag color={STATUS_TAG[m.status]?.color} style={{ fontSize: 9, lineHeight: '16px', padding: '0 5px', margin: 0 }}>
                    {STATUS_TAG[m.status]?.text}
                  </Tag>
                  <Tag color={TYPE_TAG[m.type] || 'default'} style={{ fontSize: 9, lineHeight: '16px', padding: '0 4px', margin: 0 }}>{m.type || '模块'}</Tag>
                  <span style={{ fontSize: 10, color: 'var(--palm-text-faint)', fontFamily: 'ui-monospace,monospace' }}>v{m.version}</span>
                </div>
                <div style={{ fontSize: 10, color: 'var(--palm-text-dim)', marginBottom: 2, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {m.description || '暂无描述'}
                </div>
                {m.author && (
                  <div style={{ fontSize: 9, color: 'var(--palm-text-faint)' }}>作者: {m.author}</div>
                )}
                {progress?.name === m.name && (
                  <div style={{ marginTop: 6 }}>
                    <Progress percent={progress.percent} size="small" showInfo={false}
                      strokeColor="var(--palm-cyan)" trailColor="var(--palm-track, #b0b7c3)" />
                    <div style={{ fontSize: 9, color: 'var(--palm-text-faint)', marginTop: 2 }}>
                      {progress.step}{progress.percent}%
                    </div>
                  </div>
                )}
              </div>

              {/* 操作按钮 */}
              <div style={{ flexShrink: 0 }}>
                {m.status === '未安装' && (
                  <Button type="primary" size="small" style={{ height: 28, fontSize: 11, width: 70 }}
                    loading={operating === m.name} onClick={() => handleInstall(m.name, m.version)}>
                    安装
                  </Button>
                )}
                {m.status === '已安装' && (
                  <Button size="small" style={{ height: 28, fontSize: 11, width: 56, color: '#e24b4a', borderColor: '#e24b4a' }}
                    loading={operating === m.name} onClick={() => handleUninstall(m.name)}>
                    卸载
                  </Button>
                )}
                {m.status === '损坏' && (
                  <Button size="small" style={{ height: 28, fontSize: 11, width: 100, color: '#e24b4a', borderColor: '#e24b4a' }}
                    loading={operating === m.name} onClick={() => handleUninstall(m.name)}>
                    卸载并删除
                  </Button>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* ── 上传弹窗 ── */}
      <Modal title="上传模块" open={modalOpen} onCancel={handleClose} footer={null} width={480} centered
        maskStyle={{ backdropFilter: 'blur(4px)', background: 'rgba(0,0,0,0.45)' }}
        styles={{ header: { marginBottom: 12, background: 'transparent' }, body: { padding: '0 24px 24px' }, content: { background: 'var(--palm-bg)', borderRadius: 10 } }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          <input ref={fileInputRef} type="file" accept=".7z" style={{ display: 'none' }} onChange={handleFilePick} />
          <input ref={dirInputRef} type="file" {...{ webkitdirectory: '' } as any} style={{ display: 'none' }} onChange={handleDirPick} />
          <div onDragEnter={handleDragEnter} onDragOver={handleDragEnter} onDragLeave={handleDragLeave} onDrop={handleDrop}
            onClick={() => fileInputRef.current?.click()}
            style={{ border: `2px dashed ${dragOver ? 'var(--palm-cyan)' : 'var(--palm-line-strong)'}`, borderRadius: 8, padding: '52px 16px', textAlign: 'center', cursor: 'pointer', transition: 'all 0.2s',
              background: dragOver ? 'color-mix(in srgb, var(--palm-cyan) 6%, transparent)' : 'transparent' }}>
            <InboxOutlined style={{ fontSize: 40, display: 'block', marginBottom: 10, opacity: 0.3 }} />
            <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--palm-text)' }}>{dragOver ? '松开以上传' : '拖拽模块包到此处'}</div>
            <div style={{ fontSize: 11, color: 'var(--palm-text-faint)', marginTop: 4 }}>或点击选择文件</div>
          </div>
          {selectedFile && (
            <div style={{ borderRadius: 6, border: `1px solid ${validateState.type === 'valid' ? 'var(--palm-ok)' : validateState.type === 'invalid' ? '#e24b4a' : 'var(--palm-line)'}`,
              background: validateState.type === 'valid' ? 'color-mix(in srgb, var(--palm-ok) 6%, transparent)' : validateState.type === 'invalid' ? 'color-mix(in srgb, #e24b4a 6%, transparent)' : 'transparent', padding: '12px 14px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
                {validateState.type === 'valid' && <CheckCircleFilled style={{ color: 'var(--palm-ok)', fontSize: 16 }} />}
                {validateState.type === 'invalid' && <CloseCircleFilled style={{ color: '#e24b4a', fontSize: 16 }} />}
                {validateState.type === 'validating' && <Spin size="small" />}
                <span style={{ flex: 1, fontSize: 12, fontWeight: 600, color: 'var(--palm-text)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{selectedFile.name}</span>
                <CloseCircleOutlined onClick={handleClear} style={{ color: 'var(--palm-text-faint)', cursor: 'pointer', flexShrink: 0 }} />
              </div>
              {validateState.type === 'validating' && (
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <Spin size="small" />
                  <span style={{ fontSize: 11, color: 'var(--palm-text-dim)' }}>正在验证模块包合法性</span>
                </div>
              )}
              {validateState.type === 'valid' && (
                <div>
                  <div style={{ fontSize: 11, color: 'var(--palm-ok)', fontWeight: 600, marginBottom: 4 }}>✓ 模块合法 — {validateState.module} v{validateState.version}</div>
                  {validateState.description && <div style={{ fontSize: 10, color: 'var(--palm-text-dim)', marginBottom: 2 }}>{validateState.description}</div>}
                  <div style={{ fontSize: 10, color: 'var(--palm-text-faint)', marginBottom: 10 }}>入口: {validateState.entry}{validateState.port ? ` | 端口: ${validateState.port}` : ''}</div>
                  <div style={{ fontSize: 11, color: 'var(--palm-text-dim)', marginBottom: 10 }}>是否立即加载并安装此模块？</div>
                  <div style={{ display: 'flex', gap: 8 }}>
                    <Button type="primary" size="small" style={{ height: 30, fontSize: 12 }}
                      loading={operating === validateState.module}
                      onClick={async () => {
                        await handleInstall(validateState.module, validateState.version);
                        handleClose();
                      }}>
                      立即加载
                    </Button>
                    <Button size="small" style={{ height: 30, fontSize: 12 }} onClick={handleClear}>取消</Button>
                  </div>
                </div>
              )}
              {validateState.type === 'invalid' && (
                <div>
                  <div style={{ fontSize: 11, color: '#e24b4a', fontWeight: 600 }}>✕ {validateState.reason}</div>
                  {validateState.details?.map((d, i) => <div key={i} style={{ fontSize: 10, color: '#e24b4a', marginTop: 2 }}>· {d}</div>)}
                </div>
              )}
            </div>
          )}
        </div>
      </Modal>
    </div>
  );
}
