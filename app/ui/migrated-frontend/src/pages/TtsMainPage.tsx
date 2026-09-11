/**
 * P.A.L.M · 语音合成（GPT-SoVITS 引擎）
 *
 * GPT-SoVITS 配置容器 + 子界面路由（CosyVoice 已拆分至独立路由 /tts/cosyvoice）
 * 已移除 Qwen3-TTS；GSV 线已接上（/tts、/voice-clone、整合包管理）。
 */

import { useState, useEffect, useRef } from 'react';
import { App, Button, Modal, Progress, Select, Tag, Space, Switch } from 'antd';
import { FolderOpenOutlined, SettingOutlined } from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import { getHealth as gsHealth, searchPackages } from '../api/gptSoVits';
import { useModuleConfig } from '../store/configStore';
import { type TtsConfig } from '../store/configSchema';
import GsBasicVoice from './GsBasicVoice';
import GsVoiceClone from './GsVoiceClone';
import GsBasicConfig from './GsBasicConfig';

const MODEL = {
  value: 'gpt-sovits',
  label: 'GPT-SoVITS',
  versions: ['V1', 'V2', 'V3', 'V4', 'V2Pro', 'V2ProPlas'],
  features: ['语音克隆'],
  healthCheck: gsHealth,
};

const SECTIONS = [
  { key: 'voice', label: '语音合成', comp: GsBasicVoice },
  { key: 'design', label: '音色设计', comp: GsBasicVoice },
  { key: 'clone', label: '语音克隆', comp: GsVoiceClone },
];

const STATUS_COLORS: Record<string, string> = {
  '已连接': '#22c55e',
  '未连接': '#94a3b8',
};

// ── GPT-SoVITS 配置面板 ──

const LANG_OPTIONS = [
  { value: '中文', label: '中文' },
  { value: '英文', label: '英文' },
  { value: '日文', label: '日文' },
  { value: '粤语', label: '粤语' },
  { value: '韩语', label: '韩语' },
  { value: '中英混合', label: '中英混合' },
  { value: '日英混合', label: '日英混合' },
  { value: '多语种混合', label: '多语种混合' },
];

interface PackageInfo {
  name: string;
  refLang: string;
  cutMethod: string;
  modelVersion: string;
  audioCount: number;
  packageType?: string;
  emotionTags?: { name: string; tags: string[] }[];
  refText?: string;
  loading?: boolean;
  loadProgress?: number;
}

const RUNTIME_BASE = import.meta.env.VITE_GSV_RUNTIME_BASE || 'http://127.0.0.1:5000';

function GsConfigPanel() {
  const { message } = App.useApp();
  const navigate = useNavigate();
  const { config, update } = useModuleConfig<TtsConfig>('tts');
  const [packages, setPackages] = useState<PackageInfo[]>([]);
  const [selectModalOpen, setSelectModalOpen] = useState(false);
  const [createModalOpen, setCreateModalOpen] = useState(false);
  const mountedRef = useRef(true);
  useEffect(() => () => { mountedRef.current = false; }, []);

  // 监听子组件通过 CustomEvent 发来的路径导入事件，同步到父级 packages 状态
  useEffect(() => {
    const handler = (e: Event) => {
      const detail = (e as CustomEvent).detail;
      if (detail?.name && detail?.meta) {
        setPackages((prev) => (prev.some((p) => p.name === detail.name) ? prev : [...prev, { name: detail.name, ...detail.meta }]));
      }
    };
    window.addEventListener('pkg-imported', handler);
    return () => window.removeEventListener('pkg-imported', handler);
  }, []);

  // 初始化：扫描已有整合包
  useEffect(() => {
    searchPackages().then((entries) => {
      if (!mountedRef.current) return;
      const seen = new Set<string>();
      setPackages(entries.filter((e) => {
        if (seen.has(e.name)) return false;
        seen.add(e.name);
        return true;
      }).map((e) => ({
        name: e.name, refLang: e.refLang || '-',
        cutMethod: e.cutMethod || '-', modelVersion: e.modelVersion || '-',
        audioCount: (e as any).audioCount ?? 0, packageType: (e as any).packageType || 'standard',
        emotionTags: (e as any).emotionTags || [], refText: (e as any).refText || '',
      })));
    }).catch(() => {});
  }, []);

  // ─── 上传包并轮询解压 ─────────────────────────
  const loadAndPollPackage = async (file: File) => {
    const baseName = file.name.replace(/\.gsvp$/i, '');
    let uploadedName = baseName;
    try {
      const formData = new FormData();
      formData.append('file', file);
      const uploadResp = await fetch(`${RUNTIME_BASE}/packages/upload`, {
        method: 'POST', body: formData,
      });
      if (!uploadResp.ok) {
        const err = await uploadResp.json().catch(() => ({}));
        throw new Error(err.error || '上传失败');
      }
      const result = await uploadResp.json();
      const name = baseName || result.name;
      uploadedName = name;
      const meta = result.meta || {};

      setPackages((prev) => (prev.some((p) => p.name === name) ? prev : [...prev, {
        name, refLang: meta.refLang || '-', cutMethod: meta.cutMethod || '-',
        modelVersion: meta.modelVersion || '-', audioCount: meta.audioCount ?? 0,
        loading: true, loadProgress: 0,
      }]));
      message.success(`魔数验证通过，正在解压 ${name}...`);

      for (let attempt = 0; attempt < 600; attempt++) {
        await new Promise((r) => setTimeout(r, 200));
        if (!mountedRef.current) return;
        const pct = Math.min(99, Math.round(10 + (attempt / 600) * 89));
        setPackages((prev) => prev.map((p) => p.name === name ? { ...p, loadProgress: pct } : p));
        const entries = await searchPackages();
        const found = entries.find((entry) => entry.name === name);
        if (found) {
          setPackages((prev) => prev.map((p) => p.name === name ? {
            ...p, loadProgress: 100,
            refLang: found.refLang || '-', cutMethod: found.cutMethod || '-',
            modelVersion: found.modelVersion || '-', audioCount: found.audioCount ?? 0, loading: false,
          } : p));
          message.success(`整合包「${name}」已就绪`);
          return;
        }
      }
      setPackages((prev) => prev.map((p) => p.name === name ? { ...p, loading: false } : p));
      message.warning(`解压 ${name} 超时，请刷新后重试`);
    } catch (err: any) {
      // 清除卡在 0% 的加载状态
      setPackages((prev) => prev.map((p) => p.name === uploadedName ? { ...p, loading: false, loadProgress: 0 } : p));
      message.error(err?.message || '加载整合包失败');
    }
  };

  const handleRemovePackage = async (name: string) => {
    setPackages((prev) => prev.filter((p) => p.name !== name));
    if (config.gsvActivePkg === name) update({ gsvActivePkg: '' });
    try {
      await fetch(`${RUNTIME_BASE}/packages/delete`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name }),
      });
    } catch {}
  };

  const handleUsePackage = (name: string) => {
    update({ gsvActivePkg: name });
  };

  // 当前激活的包详情
  const activePkgDetail = packages.find((p) => p.name === config.gsvActivePkg) ?? null;

  // 高级包：refText 为空时从 config.json 补读
  const [extraRefText, setExtraRefText] = useState('');
  useEffect(() => {
    if (activePkgDetail?.packageType === 'advanced' && !activePkgDetail.refText) {
      fetch(`${RUNTIME_BASE}/packages/config?name=${encodeURIComponent(activePkgDetail.name)}`)
        .then((r) => r.json())
        .then((data) => {
          if (data.refText) setExtraRefText(data.refText);
        })
        .catch(() => {});
    } else {
      setExtraRefText('');
    }
  }, [activePkgDetail]);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8, width: '100%' }}>
      {/* 顶部配置行 */}
      <div className="gsv-tts-config-bar" style={{ width: '100%' }}>
        <div className="gsv-tts-config-item">
          <span className="gsv-tts-config-label">设备</span>
          <Select value={config.gsvDevice} onChange={(v) => update({ gsvDevice: v })} size="small" style={{ width: 100 }}
            options={[{ value: 'cuda:0', label: 'CUDA' }, { value: 'cpu', label: 'CPU' }]} />
        </div>
        <div className="gsv-tts-config-item">
          <span className="gsv-tts-config-label">半精度</span>
          <Switch checked={config.gsvHalfPrecision} onChange={(v) => update({ gsvHalfPrecision: v })} size="small" />
        </div>
        <div className="gsv-tts-config-item">
          <span className="gsv-tts-config-label">流式输出</span>
          <Switch checked={config.gsvStreaming} onChange={(v) => update({ gsvStreaming: v })} size="small" />
        </div>
        <div className="gsv-tts-config-item">
          <span className="gsv-tts-config-label">合成语种</span>
          <Select value={config.gsvSynthLang} onChange={(v) => update({ gsvSynthLang: v })} size="small" style={{ width: 100 }}
            options={LANG_OPTIONS} />
        </div>
        <div className="gsv-tts-config-item">
          <span className="gsv-tts-config-label">切句</span>
          <Select value={config.gsvCutMethod} onChange={(v) => update({ gsvCutMethod: v })} size="small" style={{ width: 100 }}
            options={[
              { value: '不切', label: '不切' },
              { value: '四句一切', label: '四句一切' },
              { value: '50字一切', label: '50字一切' },
              { value: '中文句号切', label: '中文句号切' },
              { value: '英文句号切', label: '英文句号切' },
              { value: '标点符号切', label: '标点符号切' },
            ]} />
        </div>
        <div style={{ flex: 1 }} />
        <Button type="text" size="small" icon={<FolderOpenOutlined />} onClick={() => setSelectModalOpen(true)}>选择整合包</Button>
      </div>

      {/* 确定性开关 */}
      <div className="gsv-tts-deterministic">
        <div className="gsv-tts-deterministic-inner">
          <SettingOutlined style={{ fontSize: 11, opacity: 0.6 }} />
          <span>直接对上次合成结果调整语速和音色，防止随机性</span>
        </div>
        <Switch checked={config.gsvDeterministic} onChange={(v) => update({ gsvDeterministic: v })} size="small" />
      </div>

      {/* 当前选中整合包详细配置 */}
      <div style={{
        border: '1px solid var(--palm-card-border, #e4e7ec)',
        borderRadius: 4, minHeight: 260,
        display: 'flex',
        flexDirection: 'column',
        alignItems: activePkgDetail ? 'stretch' : 'center',
        justifyContent: activePkgDetail ? 'flex-start' : 'center',
        fontSize: 11, color: 'var(--palm-text-low, #94a3b8)',
        padding: activePkgDetail ? '12px 14px' : '20px',
        background: 'transparent',
      }}>
        {activePkgDetail ? (
          <>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
              <FolderOpenOutlined style={{ fontSize: 15, opacity: 0.7 }} />
              <span style={{ fontSize: 14, fontWeight: 600, color: 'var(--palm-text-mid, #344054)', fontFamily: 'ui-monospace, monospace' }}>{activePkgDetail.name}</span>
              <span style={{ fontSize: 10, color: '#22c55e', fontWeight: 500, background: 'rgba(34,197,94,0.1)', padding: '2px 8px', borderRadius: 3, marginLeft: 4 }}>正在使用</span>
              {activePkgDetail.packageType === 'advanced' && (
                <span style={{ fontSize: 9, fontWeight: 600, color: '#8b5cf6', background: '#ede9fe', padding: '1px 5px', borderRadius: 3, marginLeft: 'auto' }}>高级</span>
              )}
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '6px 20px', fontSize: 11 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 11 }}>
                <span style={{ color: 'var(--palm-text-low, #475467)', flexShrink: 0 }}>参考语种：</span>
                {(activePkgDetail.refLang || '-').replace(/,/g, '、').split('、').filter(Boolean).map((lang, li) => (
                  <span key={li} style={{
                    fontSize: 10, fontWeight: 500, color: '#3b82f6',
                    background: 'rgba(59,130,246,0.1)',
                    padding: '1px 7px', borderRadius: 3, whiteSpace: 'nowrap',
                  }}>{lang}</span>
                ))}
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 11 }}>
                <span style={{ color: 'var(--palm-text-low, #475467)', flexShrink: 0 }}>模型版本：</span>
                <span style={{
                  fontSize: 10, fontWeight: 500, color: '#8b5cf6',
                  background: 'rgba(139,92,246,0.1)',
                  padding: '1px 7px', borderRadius: 3,
                }}>{activePkgDetail.modelVersion || '-'}</span>
              </div>
              <div><span style={{ color: 'var(--palm-text-low, #475467)' }}>参考音频：</span><strong style={{ color: 'var(--palm-text-mid, #344054)' }}>{activePkgDetail.audioCount ?? 0} 个</strong></div>
              {activePkgDetail.packageType === 'advanced' && activePkgDetail.emotionTags && activePkgDetail.emotionTags.length > 0 && (
                <div style={{ gridColumn: '1 / -1', display: 'flex', flexDirection: 'column', gap: 3, paddingTop: 2 }}>
                  {(activePkgDetail.emotionTags as { name: string; tags: string[] }[]).map((item, idx) => (
                    <div key={idx} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 10, lineHeight: '18px' }}>
                      <span style={{ color: 'var(--palm-text-low, #475467)', flexShrink: 0, whiteSpace: 'nowrap' }}>参考文本{idx + 1}:</span>
                      <span style={{ color: 'var(--palm-text-mid, #344054)', flex: 1, wordBreak: 'break-all' }}>「{(() => {
                        const texts = (activePkgDetail.refText || extraRefText || '');
                        return texts ? (texts.split('\n')[idx] || item.name || '') : (item.name || '');
                      })()}」</span>
                      <span style={{ color: '#8b5cf6', flexShrink: 0, marginLeft: 'auto' }}>[{item.tags.join(', ')}]</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </>
        ) : (
          <span>暂无选中整合包，请点击上方「选择整合包」按钮</span>
        )}
      </div>

      {/* 选择整合包弹窗 */}
      <Modal
        title="整合包管理"
        open={selectModalOpen}
        onCancel={() => setSelectModalOpen(false)}
        footer={null}
        width={800}
        destroyOnHidden
        className="gsv-tts-create-modal"
        styles={{ body: { padding: '16px 20px', background: 'transparent', minHeight: 470 }, mask: { backdropFilter: 'blur(4px)', background: 'rgba(0,0,0,0.3)' } }}
      >
        <GsBasicConfig
          mode="select"
          cutMethod={config.gsvCutMethod}
          packages={packages}
          activePkg={config.gsvActivePkg || null}
          onSelectPackage={(name) => {
            handleUsePackage(name);
            setSelectModalOpen(false);
          }}
          onRemovePackage={(name) => {
            handleRemovePackage(name);
          }}
          onExternalAddPackage={async (file) => {
            await loadAndPollPackage(file);
          }}
          onRequestCreate={() => {
            setCreateModalOpen(true);
            setSelectModalOpen(false);
          }}
          onRequestAdvancedCreate={() => {
            setCreateModalOpen(false);
            setSelectModalOpen(false);
            navigate('/tts/gs-advanced');
          }}
        />
      </Modal>

      {/* 创建整合包弹窗 */}
      <Modal
        title="创建整合包"
        open={createModalOpen}
        onCancel={() => { setCreateModalOpen(false); setSelectModalOpen(true); }}
        footer={null}
        width={800}
        destroyOnHidden
        className="gsv-tts-create-modal"
        styles={{ body: { padding: '16px 20px', background: 'transparent' }, mask: { backdropFilter: 'blur(4px)', background: 'rgba(0,0,0,0.3)' } }}
      >
        <GsBasicConfig
          mode="create"
          cutMethod={config.gsvCutMethod}
          packages={packages}
          activePkg={config.gsvActivePkg || null}
          onExternalAddPackage={async (file) => {
            await loadAndPollPackage(file);
          }}
          onRequestAdvancedCreate={() => {
            setCreateModalOpen(false);
            setSelectModalOpen(false);
            navigate('/tts/gs-advanced');
          }}
          onPackageCreated={(name, meta) => {
            setPackages((prev) => (prev.some((p) => p.name === name) ? prev : [...prev, { name, ...meta }]));
            setCreateModalOpen(false);
            setSelectModalOpen(true);
          }}
        />
      </Modal>
    </div>
  );
}

// ── 主页面 ──

export default function TtsMainPage() {
  const mountedRef = useRef(true);
  useEffect(() => () => { mountedRef.current = false; }, []);
  const { config, update } = useModuleConfig<TtsConfig>('tts');
  const section = config.selectedSection;
  const [statuses, setStatuses] = useState<Record<string, '未连接' | '已连接'>>({});

  useEffect(() => {
    MODEL.healthCheck()
      .then(() => { if (mountedRef.current) setStatuses((prev) => ({ ...prev, [MODEL.value]: '已连接' })); })
      .catch(() => { if (mountedRef.current) setStatuses((prev) => ({ ...prev, [MODEL.value]: '未连接' })); });
  }, []);

  const getStatus = (value: string) => statuses[value] ?? '未连接';

  const currentModel = MODEL;
  const availableSections = SECTIONS.filter((s) => currentModel.features.includes(s.label));

  useEffect(() => {
    const first = availableSections[0];
    if (first && !availableSections.some((s) => s.key === section)) {
      update({ selectedSection: first.key });
    }
  }, []);

  const resolveComponent = (key: string) => {
    return SECTIONS.find((s) => s.key === key)?.comp ?? GsBasicVoice;
  };

  const ActiveComp = resolveComponent(section);

  return (
    <>
      <div className="palm-page__title-row palm-page__title-row--compact">
        <div>
          <div className="palm-page__subtitle">GPT-SoVITS 引擎</div>
          <h2 className="palm-page__title">TTS</h2>
        </div>
      </div>

      {/* 模型信息（连接状态） */}
      <div className="gsv-tts-card gsv-tts-card--row" style={{ marginBottom: 10, padding: 0 }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 0 }}>
          <div style={{ padding: '6px 16px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 4 }}>
              <span className="gsv-tts-label" style={{ fontSize: 13 }}>{currentModel.label}</span>
              <div style={{ flex: 1 }} />
              <span style={{ display: 'inline-block', width: 6, height: 6, borderRadius: '50%', background: STATUS_COLORS[getStatus(currentModel.value)], marginRight: 4 }} />
              <span style={{ fontSize: 10, color: 'var(--palm-text-low, #475467)' }}>{getStatus(currentModel.value)}</span>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, flex: 1 }}>
                <span style={{ fontSize: 10, color: 'var(--palm-text-low, #475467)', flexShrink: 0, width: 30 }}>版本</span>
                <Space size={4} wrap>
                  {currentModel.versions.map((v) => (
                    <span key={v} style={{ fontSize: 10, color: 'var(--palm-text-mid, #667085)', fontFamily: 'ui-monospace, "SF Mono", "JetBrains Mono", Menlo, monospace' }}>{v}</span>
                  ))}
                </Space>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexShrink: 0 }}>
                <span style={{ fontSize: 10, color: 'var(--palm-text-low, #475467)', flexShrink: 0, width: 30, textAlign: 'right' }}>支持</span>
                <Space size={4} wrap>
                  {currentModel.features.map((f) => (
                    <Tag key={f} color="cyan" style={{ fontSize: 10, lineHeight: '18px', margin: 0 }}>{f}</Tag>
                  ))}
                </Space>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* 配置容器 */}
      <div className="gsv-tts-card" style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
        <div style={{ padding: '8px 16px' }}>
          <span className="gsv-tts-label">模型配置</span>
        </div>
        <div style={{ padding: '10px 16px' }}>
          <GsConfigPanel />
        </div>

        {availableSections.length > 1 && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '8px 16px' }}>
          <span className="gsv-tts-label">功能选择</span>
          <div style={{ flex: 1 }} />
          <Select value={section} onChange={(v) => update({ selectedSection: v })} className="gsv-tts-model-select" style={{ width: 200 }} size="small"
            options={availableSections.map((s) => ({ value: s.key, label: s.label }))} />
        </div>
        )}

        <div className="gsv-tts-page-content" style={{ padding: '0 16px 10px' }} key={section}>
          <ActiveComp />
        </div>
      </div>
    </>
  );
}
