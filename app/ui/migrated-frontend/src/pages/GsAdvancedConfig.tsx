/**
 * GPT-SoVITS · 高级创建
 *
 * 独立子界面（专属路由 /tts/gs-advanced）
 */

import { useState, useRef, useEffect } from 'react';
import { Button, Input, Divider, App, Select, Tooltip, Progress } from 'antd';
import { ArrowLeftOutlined, PlusOutlined, DeleteOutlined, FolderOpenOutlined } from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import { scanMatesDirectory } from '../api/gptSoVits';

interface AudioEntry {
  name: string;
  file: File | null;
  refText: string;
  refLang: string;
  emotionTags: string[];
}

const EMOTION_TAGS = [
  { label: '高兴' },
  { label: '悲伤' },
  { label: '愤怒' },
  { label: '恐惧' },
  { label: '惊讶' },
  { label: '平静' },
  { label: '温柔' },
  { label: '冷漠' },
  { label: '紧张' },
  { label: '自信' },
  { label: '疲惫' },
  { label: '无奈' },
  { label: '兴奋' },
  { label: '疑惑' },
  { label: '讽刺' },
];

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

export default function GsAdvancedConfig() {
  const navigate = useNavigate();
  const { message } = App.useApp();
  const [packageName, setPackageName] = useState('');
  const [gptPath, setGptPath] = useState('');
  const [sovitsPath, setSovitsPath] = useState('');
  const [gptFile, setGptFile] = useState<File | null>(null);
  const [sovitsFile, setSovitsFile] = useState<File | null>(null);
  const [gptVer, setGptVer] = useState<string | null>(null);
  const [sovitsVer, setSovitsVer] = useState<string | null>(null);
  const [modelVersion, setModelVersion] = useState('');
  const [detectedVer, setDetectedVer] = useState<string | null>(null);
  const gptInputRef = useRef<HTMLInputElement>(null);
  const sovitsInputRef = useRef<HTMLInputElement>(null);
  const [audioEntries, setAudioEntries] = useState<AudioEntry[]>([
    { name: '', file: null, refText: '', refLang: '中文', emotionTags: [] },
  ]);
  const audioInputRefs = useRef<(HTMLInputElement | null)[]>([]);
  const [online, setOnline] = useState(false);
  const [checking, setChecking] = useState(true);
  const [creating, setCreating] = useState(false);
  const [createProgress, setCreateProgress] = useState<{
    taskId: string; progress: number; status: string;
    totalBytes?: number; processedBytes?: number; speedBps?: number;
    etaSecs?: number; currentFile?: string;
  } | null>(null);

  const API_BASE = import.meta.env.VITE_GSV_API_BASE || 'http://127.0.0.1:5000';

  const handleCreate = async () => {
    if (!packageName.trim()) return void message.warning('请输入包名');
    if (!gptPath.trim()) return void message.warning('请选择 GPT 模型文件');
    if (!sovitsPath.trim()) return void message.warning('请选择 SoVITS 模型文件');

    const filledAudios = audioEntries.filter((a) => a.name.trim());
    if (filledAudios.length === 0) return void message.warning('请至少填写一个参考音频路径');

    // 校验每条参考音频：路径、文本、情感标签缺一不可
    for (let i = 0; i < filledAudios.length; i++) {
      const a = filledAudios[i];
      if (!a.name.trim()) return void message.warning(`第 ${i + 1} 个参考音频：请输入路径`);
      if (!a.refText.trim()) return void message.warning(`第 ${i + 1} 个参考音频：请输入参考文本`);
      if (a.emotionTags.length === 0) return void message.warning(`第 ${i + 1} 个参考音频：请至少选择一个情感标签`);
    }

    if (!modelVersion) return void message.warning('模型版本未识别，请手动选择');
    if (detectedVer?.includes('不一致')) return void message.warning('GPT 与 SoVITS 模型版本不一致，请检查模型文件');

    setCreating(true);
    setCreateProgress(null);
    await new Promise((r) => setTimeout(r, 50));

    try {
      let task_id: string;
      const hasAudioFiles = filledAudios.some((a) => a.file);

      if (hasAudioFiles) {
        // 文件已选中 → 上传模式
        const fd = new FormData();
        fd.append('meta', JSON.stringify({
          refLang: [...new Set(filledAudios.map((a) => a.refLang))].join('、'),
          refText: filledAudios.map((a) => a.refText).join('\n'),
          cutMethod: '不切',
          modelVersion: modelVersion || '',
          packageName: packageName.trim(),
          packageType: 'advanced',
          emotionTags: filledAudios.map((a) => ({
            name: (a.file?.name || a.name).split(/[\\/]/).pop() || a.name,
            tags: a.emotionTags,
          })),
        }));
        fd.append('gpt', gptFile!);
        fd.append('sovits', sovitsFile!);
        filledAudios.forEach((a) => { if (a.file) fd.append('audios', a.file); });
        const resp = await fetch(`${API_BASE}/packages/create`, { method: 'POST', body: fd });
        if (!resp.ok) { const err = await resp.json().catch(() => ({})); throw new Error(err.error || '创建失败'); }
        const result = await resp.json();
        task_id = result.task_id;
      } else {
        // 自动路径模式 → 传文件路径到后端
        const resp = await fetch(`${API_BASE}/packages/create-from-paths`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            meta: {
              refLang: [...new Set(filledAudios.map((a) => a.refLang))].join('、'),
              refText: filledAudios.map((a) => a.refText).join('\n'),
              cutMethod: '不切',
              modelVersion: modelVersion || '',
              packageName: packageName.trim(),
              packageType: 'advanced',
              emotionTags: filledAudios.map((a) => ({
                name: a.name.split(/[\\/]/).pop() || a.name,
                tags: a.emotionTags,
              })),
            },
            gpt_path: gptPath,
            sovits_path: sovitsPath,
            audio_paths: filledAudios.map((a) => a.name),
          }),
        });
        if (!resp.ok) { const err = await resp.json().catch(() => ({})); throw new Error(err.error || '创建失败'); }
        const result = await resp.json();
        task_id = result.task_id;
      }

      setCreateProgress({ taskId: task_id, progress: 0, status: 'processing' });

      // 轮询进度
      await new Promise<void>((resolve, reject) => {
        const poll = async () => {
          try {
            const pr = await fetch(`${API_BASE}/packages/progress?task_id=${task_id}`);
            const st = await pr.json();
            setCreateProgress({
              taskId: task_id, progress: st.progress, status: st.status,
              totalBytes: st.totalBytes, processedBytes: st.processedBytes,
              speedBps: st.speedBps, etaSecs: st.etaSecs, currentFile: st.currentFile,
            });
            if (st.status === 'done') {
              const fileName = st.fileName || `${packageName.trim() || 'gsv-package'}.gsvp`;
              message.success(`创建成功: ${fileName}`);
              navigate('/tts');
              resolve(); return;
            }
            if (st.status === 'error') {
              reject(new Error(st.error || '创建失败'));
              return;
            }
            setTimeout(poll, 600);
          } catch (err) {
            reject(err as Error);
          }
        };
        poll();
      });
    } catch (e: any) {
      setCreateProgress((prev) => prev ? { ...prev, status: 'error' } : null);
      message.error(`创建失败: ${e.message}`);
    } finally {
      setCreating(false);
    }
  };

  useEffect(() => {
    const check = async () => {
      try {
        const resp = await fetch(`${API_BASE}/health`);
        setOnline(resp.ok);
      } catch {
        setOnline(false);
      }
      setChecking(false);
    };
    check();
    const timer = setInterval(check, 10000);
    return () => clearInterval(timer);
  }, []);

  const handleAddAudio = () => {
    setAudioEntries((prev) => [...prev, { name: '', file: null, refText: '', refLang: '中文', emotionTags: [] }]);
  };

  const handleRemoveAudio = (idx: number) => {
    if (audioEntries.length <= 1) return;
    setAudioEntries((prev) => prev.filter((_, i) => i !== idx));
  };

  const handleAudioFileChange = (index: number) => (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    if (f) {
      setAudioEntries((prev) => {
        const next = [...prev];
        next[index] = { ...next[index], file: f, name: next[index].name || f.name };
        return next;
      });
      e.target.value = '';
    }
  };

  const updateAudio = (idx: number, field: keyof AudioEntry, value: string) => {
    setAudioEntries((prev) => {
      const n = [...prev];
      n[idx] = { ...n[idx], [field]: value };
      return n;
    });
  };

  const toggleEmotionTag = (audioIdx: number, tagLabel: string) => {
    setAudioEntries((prev) => {
      const n = [...prev];
      const entry = n[audioIdx];
      const tags = entry.emotionTags;
      if (tags.includes(tagLabel)) {
        n[audioIdx] = { ...entry, emotionTags: tags.filter((t) => t !== tagLabel) };
      } else if (tags.length < 5) {
        n[audioIdx] = { ...entry, emotionTags: [...tags, tagLabel] };
      }
      return n;
    });
  };

  // ─── 模型版本检测 ──────────────────────────────
  const scanVersion = async (file: File): Promise<string | null> => {
    try {
      const buf = await file.slice(0, 100 * 1024).arrayBuffer();
      const text = new TextDecoder('utf-8', { fatal: false }).decode(buf);
      const checks: [RegExp, string][] = [
        // 训练路径标记
        [/logs_s[12]_v2proplas/i, 'V2ProPlas'],
        [/logs_s[12]_v2pro/i, 'V2Pro'],
        [/logs_s[12]_v4/i, 'V4'],
        [/logs_s[12]_v3/i, 'V3'],
        [/logs_s[12]_v2/i, 'V2'],
        // JSON version 声明
        [/"version":\s*"v2proplas"/i, 'V2ProPlas'],
        [/"version":\s*"v2pro"/i, 'V2Pro'],
        [/"version":\s*"v4"/i, 'V4'],
        [/"version":\s*"v3"/i, 'V3'],
        [/"version":\s*"v2"/i, 'V2'],
        [/"version":\s*"v1"/i, 'V1'],
        // 版本标记
        [/gsv-v2proplas-pretrained/i, 'V2ProPlas'],
        [/gsv-v2pro-pretrained/i, 'V2Pro'],
        [/gsv-v4-pretrained/i, 'V4'],
        [/gsv-v3-pretrained/i, 'V3'],
        [/gsv-v2-pretrained/i, 'V2'],
        [/gsv-v1-pretrained/i, 'V1'],
        [/weights_v2proplas/i, 'V2ProPlas'],
        [/weights_v2pro/i, 'V2Pro'],
        [/SoVITS_weights_v4/i, 'V4'], [/SoVITS_weights_v3/i, 'V3'], [/SoVITS_weights_v2/i, 'V2'],
        [/GPT_weights_v4/i, 'V4'], [/GPT_weights_v3/i, 'V3'], [/GPT_weights_v2/i, 'V2'],
      ];
      for (const [regex, ver] of checks) {
        if (regex.test(text)) return ver;
      }
      return null;
    } catch {
      return null;
    }
  };

  const reconcileVersions = (g: string | null, s: string | null) => {
    if (g && s) {
      if (g === s) { setModelVersion(g); setDetectedVer(g); }
      else { setModelVersion(''); setDetectedVer(`版本不一致 — GPT(${g}) SoVITS(${s})`); }
    } else if (g && !s) { setModelVersion(g); setDetectedVer(g); }
    else if (!g && s) { setModelVersion(s); setDetectedVer(s); }
    else { setModelVersion(''); setDetectedVer('无法识别'); }
  };

  // ─── 文件名版本检测（精确，不受二进制内容干扰）───
  const detectVersionFromFilename = (filePath: string): string | null => {
    const name = filePath.replace(/[\\/]/g, '/').split('/').pop()?.toLowerCase() || '';
    if (/v2proplas/i.test(name)) return 'V2ProPlas';
    if (/v2pro/i.test(name)) return 'V2Pro';
    if (/v4/i.test(name)) return 'V4';
    if (/v3/i.test(name)) return 'V3';
    if (/v2/i.test(name)) return 'V2';
    if (/v1/i.test(name)) return 'V1';
    return null;
  };

  // ─── 模型文件选择 + 自动检测 ─────────────────
  const pickModelFile = async (type: 'gpt' | 'sovits') => {
    try {
      const ext = type === 'gpt' ? 'ckpt' : 'pth';
      const resp = await fetch(`${API_BASE}/packages/file-picker?ext=${ext}`);
      const result = await resp.json();
      if (!result.success || !result.path) return;
      if (type === 'gpt') {
        setGptPath(result.path); setGptFile(null);
      } else {
        setSovitsPath(result.path); setSovitsFile(null);
      }
      // 用后端返回的完整路径提取目录进行扫描
      const dirPath = result.path.replace(/[\\/][^\\/]+$/, '');
      const scanResult = await scanMatesDirectory('', dirPath);

      // 文件名版本检测（最高优先级）
      const fileVer = detectVersionFromFilename(result.path);

      if (scanResult) {
        // 扫描对端文件并检测版本（文件名 > 内容）
        const otherFiles = type === 'gpt' ? scanResult.pth : scanResult.ckpt;
        let otherVer: string | null = null;
        if (otherFiles.length > 0) {
          otherVer = detectVersionFromFilename(otherFiles[0]);
          const vs: any = scanResult.versions || {};
          const contentVer = type === 'gpt' ? vs.pth : vs.ckpt;
          if (!otherVer) otherVer = contentVer;
        }

        // 版本优先级：选中文件文件名 > 对端文件名 > 内容检测
        const bestVer = fileVer || otherVer;
        setGptVer(type === 'gpt' ? bestVer : otherVer);
        setSovitsVer(type === 'sovits' ? bestVer : otherVer);
        if (bestVer) {
          setModelVersion(bestVer);
          setDetectedVer(bestVer);
        } else {
          setDetectedVer('无法识别');
        }
        // 配套文件填充
        if (type === 'gpt') {
          if (scanResult.pth.length === 1) { setSovitsPath(scanResult.pth[0]); message.success('自动检测到匹配的 SoVITS 文件'); }
          else if (scanResult.pth.length > 1) { message.warning(`检测到 ${scanResult.pth.length} 个 SoVITS 文件，请手动选择`, 5); }
        } else {
          if (scanResult.ckpt.length === 1) { setGptPath(scanResult.ckpt[0]); message.success('自动检测到匹配的 GPT 文件'); }
          else if (scanResult.ckpt.length > 1) { message.warning(`检测到 ${scanResult.ckpt.length} 个 GPT 文件，请手动选择`, 5); }
        }
        if (scanResult.wav.length > 0) {
          setAudioEntries(scanResult.wav.map((p: string, i: number) => ({
            name: p, file: null, refText: scanResult.ref_texts[i] || '', refLang: '中文', emotionTags: [],
          })));
          message.success(`自动检测到 ${scanResult.wav.length} 个参考音频`);
        }
      }
    } catch (e) {
      console.warn('后端文件选择失败:', e);
    }
  };
  const autoFillMates = async (sourceFile: File, sourceType: 'gpt' | 'sovits') => {
    // 仅通过扩展名匹配目录下的所有同类文件
    // 若有文件完整路径，以其所在目录为根；否则由后端使用 MODELS_ROOT
    const filePath = (sourceFile as any).path;
    const dirPath = filePath ? filePath.replace(/[\\/][^\\/]+$/, '') : undefined;
    try {
      const result = dirPath
        ? await scanMatesDirectory('', dirPath)
        : await scanMatesDirectory('');
      if (result) {
        if (sourceType === 'gpt') {
          if (result.pth.length === 1) {
            setSovitsPath(result.pth[0]);
            message.success('自动检测到匹配的 SoVITS 文件');
          } else if (result.pth.length > 1) {
            const names = result.pth.map((p: string) => p.split(/[\\/]/).pop()).join('、');
            message.warning(`检测到 ${result.pth.length} 个 SoVITS 文件: ${names}，请手动选择`, 5);
          }
        } else if (sourceType === 'sovits') {
          if (result.ckpt.length === 1) {
            setGptPath(result.ckpt[0]);
            message.success('自动检测到匹配的 GPT 文件');
          } else if (result.ckpt.length > 1) {
            const names = result.ckpt.map((p: string) => p.split(/[\\/]/).pop()).join('、');
            message.warning(`检测到 ${result.ckpt.length} 个 GPT 文件: ${names}，请手动选择`, 5);
          }
        }
        if (result.wav.length > 0) {
          setAudioEntries(result.wav.map((p: string, i: number) => ({
            name: p, file: null,
            refText: result.ref_texts[i] || '',
            refLang: '中文',
            emotionTags: [],
          })));
          message.success(`自动检测到 ${result.wav.length} 个参考音频`);
        }
      }
    } catch (e: any) {
      console.warn('自动检测失败:', e?.message || e);
    }
  };

  const handleGptChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    if (f) {
      setGptFile(f); setGptPath(f.name);
      // 文件名检测优先于内容检测
      const fileVer = detectVersionFromFilename(f.name);
      const contentVer = await scanVersion(f);
      const ver = fileVer || contentVer;
      setGptVer(ver);
      reconcileVersions(ver, sovitsVer);
      await autoFillMates(f, 'gpt');
      e.target.value = '';
    }
  };

  const handleSovitsChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    if (f) {
      setSovitsFile(f); setSovitsPath(f.name);
      const fileVer = detectVersionFromFilename(f.name);
      const contentVer = await scanVersion(f);
      const ver = fileVer || contentVer;
      setSovitsVer(ver);
      reconcileVersions(gptVer, ver);
      await autoFillMates(f, 'sovits');
      e.target.value = '';
    }
  };

  return (
    <>
      <div className="palm-page__title-row palm-page__title-row--compact">
        <div>
          <div className="palm-page__subtitle">GPT-SoVITS</div>
          <h2 className="palm-page__title">高级创建</h2>
        </div>
        <div style={{ flex: 1 }} />
        <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/tts')} size="small">
          返回
        </Button>
      </div>

      <div className="qwen-tts-card" style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column', overflow: 'hidden', background: 'transparent' }}>
        <div style={{ padding: '16px 20px', display: 'flex', gap: 24, alignItems: 'flex-start' }}>
          <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 10 }}>
            <div className="qwen-tts-path-row">
              <span className="qwen-tts-path-label">包名</span>
              <Input
                value={packageName}
                onChange={(e) => setPackageName(e.target.value)}
                placeholder="输入整合包名称（不含扩展名）"
                className="qwen-tts-path-input"
                style={{ width: '40%' }}
              />
            </div>
            <div className="qwen-tts-path-row">
              <span className="qwen-tts-path-label">GPT 模型路径</span>
              <input type="file" ref={gptInputRef} style={{ display: 'none' }} accept=".ckpt" onChange={handleGptChange} />
              <Input
                value={gptPath}
                onChange={(e) => setGptPath(e.target.value)}
                placeholder="选择或输入 GPT 模型文件路径..."
                className="qwen-tts-path-input"
              />
              <Button size="small" icon={<FolderOpenOutlined />} onClick={() => pickModelFile('gpt')}>选择</Button>
            </div>
            <div className="qwen-tts-path-row">
              <span className="qwen-tts-path-label">SoVITS 模型路径</span>
              <input type="file" ref={sovitsInputRef} style={{ display: 'none' }} accept=".pth" onChange={handleSovitsChange} />
              <Input
                value={sovitsPath}
                onChange={(e) => setSovitsPath(e.target.value)}
                placeholder="选择或输入 SoVITS 模型文件路径..."
                className="qwen-tts-path-input"
              />
              <Button size="small" icon={<FolderOpenOutlined />} onClick={() => pickModelFile('sovits')}>选择</Button>
            </div>

            {/* ── 模型版本 ── */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <span className="qwen-tts-path-label">模型版本</span>
              <Select value={modelVersion} onChange={setModelVersion} size="small" style={{ width: 120 }}
                placeholder="选择模型版本"
                options={[
                  { value: 'V1', label: 'V1' }, { value: 'V2', label: 'V2' },
                  { value: 'V3', label: 'V3' }, { value: 'V4', label: 'V4' },
                  { value: 'V2Pro', label: 'V2Pro' }, { value: 'V2ProPlas', label: 'V2ProPlas' },
                ]}
              />
              {detectedVer && (
                <span style={{ fontSize: 10, color: 'var(--palm-text-low, #475467)', marginLeft: 8 }}>
                  自动识别: <strong style={{ color: detectedVer.includes('不一致') ? '#d4a017' : 'var(--palm-primary, #3b82f6)' }}>{detectedVer}</strong>
                </span>
              )}
            </div>

            {/* 参考音频 */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginTop: 4 }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <span style={{ fontSize: 11, fontWeight: 600, color: 'var(--palm-text-mid, #344054)' }}>参考音频</span>
                <Button size="small" icon={<PlusOutlined />} onClick={handleAddAudio}>添加音频</Button>
              </div>
              <div data-hide-scrollbar style={{ maxHeight: 480, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 6,
                scrollbarWidth: 'none', msOverflowStyle: 'none',
              }}>
                <style>{`[data-hide-scrollbar]::-webkit-scrollbar { display: none }`}</style>
                {audioEntries.map((entry, i) => (
                  <div key={i} style={{ display: 'flex', flexDirection: 'column', gap: 4, padding: 8, border: '1px solid var(--palm-card-border, #e4e7ec)', borderRadius: 4, position: 'relative' }}>
                    <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                      <input type="file" ref={(el) => { audioInputRefs.current[i] = el; }} style={{ display: 'none' }} accept=".wav,.mp3,.flac,.ogg,.m4a" onChange={handleAudioFileChange(i)} />
                      <Input
                        size="small"
                        value={entry.name}
                        onChange={(e) => updateAudio(i, 'name', e.target.value)}
                        placeholder="音频文件路径或名称..."
                        style={{ fontSize: 11, flex: 1 }}
                      />
                      <Button size="small" icon={<FolderOpenOutlined />} onClick={() => audioInputRefs.current[i]?.click()}>选择</Button>
                      <Button size="small" icon={<DeleteOutlined />} onClick={() => handleRemoveAudio(i)} danger />
                    </div>
                    <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                      <Input
                        size="small"
                        value={entry.refText}
                        onChange={(e) => updateAudio(i, 'refText', e.target.value)}
                        placeholder="输入该音频对应的参考文本..."
                        style={{ fontSize: 11, flex: 1 }}
                      />
                      <Select
                        size="small"
                        value={entry.refLang || '中文'}
                        onChange={(val) => updateAudio(i, 'refLang', val)}
                        options={LANG_OPTIONS}
                        style={{ width: 90, fontSize: 11 }}
                      />
                    </div>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                        <span style={{ fontSize: 10, color: 'var(--palm-text-low, #475467)', flexShrink: 0 }}>情感标签</span>
                        <Tooltip title="建议选择越少越好，最多 5 种">
                          <span style={{ fontSize: 9, color: 'var(--palm-text-low, #94a3b8)' }}>
                            ({entry.emotionTags.length}/5 · 越少越好)
                          </span>
                        </Tooltip>
                      </div>
                      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                        {EMOTION_TAGS.map((tag) => {
                          const selected = entry.emotionTags.includes(tag.label);
                          return (
                            <span
                              key={tag.label}
                              onClick={() => toggleEmotionTag(i, tag.label)}
                              style={{
                                display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                                width: 36, height: 24, fontSize: 10, cursor: 'pointer', borderRadius: 3,
                                border: `1px solid ${selected ? '#3b82f6' : 'var(--palm-card-border, #e4e7ec)'}`,
                                background: selected ? '#dbeafe' : 'transparent',
                                color: selected ? '#3b82f6' : 'var(--palm-text-low, #94a3b8)',
                                fontWeight: selected ? 600 : 400,
                                transition: 'all 0.15s',
                                opacity: !selected && entry.emotionTags.length >= 5 ? 0.4 : 1,
                                userSelect: 'none',
                              }}
                            >{tag.label}</span>
                          );
                        })}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>

          <Divider type="vertical" style={{ height: 'auto', alignSelf: 'stretch', borderColor: 'var(--palm-card-border, #e4e7ec)' }} />

          <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 10 }}>
            {/* 音频可视化 */}
            <div style={{
              flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', position: 'relative',
              borderRadius: 6, border: '1px solid var(--palm-card-border, #e4e7ec)',
              minHeight: 200, overflow: 'hidden',
            }}>
              <div style={{
                position: 'absolute', left: 16, right: 16, top: '50%', height: 1,
                background: 'var(--palm-card-border, #e4e7ec)',
              }} />
              <div style={{
                width: 8, height: 8, borderRadius: '50%',
                background: '#3b82f6',
                zIndex: 1,
              }} />
            </div>

            {/* 终端输出 */}
            <div style={{
              height: 120, overflowY: 'auto', borderRadius: 6,
              border: '1px solid var(--palm-card-border, #e4e7ec)',
              padding: '8px 10px', fontFamily: 'Consolas, Monaco, monospace', fontSize: 10,
              lineHeight: '18px',
            }} />

            {/* 状态栏 */}
            {!checking && (
              <div style={{ padding: '4px 0', display: 'flex', alignItems: 'center', gap: 6 }}>
                <span style={{
                  width: 7, height: 7, borderRadius: '50%', flexShrink: 0,
                  background: online ? '#10b981' : '#ef4444',
                  boxShadow: online ? '0 0 4px #10b981' : '0 0 4px #ef4444',
                }} />
                <span style={{ fontSize: 10, color: online ? '#10b981' : '#ef4444', fontWeight: 500 }}>
                  {online ? '在线' : '离线'}
                </span>
                <div style={{ flex: 1 }} />
                <Button size="small" type="primary" onClick={() => message.info('合成测试功能开发中')}>合成测试</Button>
                <Button size="small" type="primary" loading={creating} onClick={handleCreate}>创建整合包</Button>
              </div>
            )}
            {createProgress && createProgress.progress >= 0 && (
              <div style={{ paddingTop: 4 }}>
                <Progress percent={Math.max(0, Math.min(100, createProgress.progress))} size="small"
                  strokeColor={createProgress.status === 'error' ? '#ff4d4f' : undefined}
                  format={(p) => {
                    if (createProgress.status === 'error') return '失败';
                    if (createProgress.status === 'done') return '已完成';
                    const labels: Record<string, string> = { 'reading': '读取文件', 'hashing': '计算MD5', 'compressing': '打包中', 'saving': '保存文件', 'extracting': '解压中' };
                    return `${p ?? 0}% ${labels[createProgress.status] || ''}`;
                  }}
                />
                {createProgress.totalBytes && (
                  <div style={{ fontSize: 11, color: '#666', paddingTop: 2, fontFamily: 'monospace' }}>
                    {(() => {
                      const total = createProgress.totalBytes ?? 1;
                      const done = createProgress.processedBytes ?? 0;
                      const speed = createProgress.speedBps ?? 0;
                      const eta = createProgress.etaSecs ?? 0;
                      const file = createProgress.currentFile || '';
                      const fmt = (b: number) => b >= 1048576 ? (b / 1048576).toFixed(1) + 'MB' : b >= 1024 ? (b / 1024).toFixed(0) + 'KB' : b + 'B';
                      const speedStr = speed >= 1048576 ? (speed / 1048576).toFixed(1) + 'MB/s' : speed >= 1024 ? (speed / 1024).toFixed(0) + 'KB/s' : speed + 'B/s';
                      const etaStr = eta > 3600 ? `${(eta / 3600).toFixed(1)}h` : eta > 60 ? `${Math.ceil(eta / 60)}m` : `${Math.max(1, eta)}s`;
                      return `文件: ${file.split(/[/\\]/).pop() || file}  |  已处理: ${fmt(done)} / ${fmt(total)}  |  速度: ${speedStr}  |  预计: ${etaStr}`;
                    })()}
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      </div>
    </>
  );
}
