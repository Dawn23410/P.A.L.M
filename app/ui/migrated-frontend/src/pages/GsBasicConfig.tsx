/**
 * GPT-SoVITS · 基础配置
 *
 * 模型路径、参考音频（多文件）、语种、切句等基础参数配置
 * 支持创建/选择整合包双模式
 */

import { useRef, useState, useEffect } from 'react';
import { App, Button, Input, Progress, Select } from 'antd';
import { FolderOpenOutlined, PlusOutlined } from '@ant-design/icons';
import { scanMatesDirectory, searchPackages } from '../api/gptSoVits';

const API_BASE = import.meta.env.VITE_GSV_API_BASE || 'http://127.0.0.1:5000';

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

interface AudioEntry {
  file: File | null;
  name: string;
  refText: string;
  refLang: string;        // 每个参考音频独立的语种
}

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

interface GsBasicConfigProps {
  onPackageCreated?: (name: string, meta: { refLang: string; cutMethod: string; modelVersion: string; audioCount: number; refLangs: string[] }) => void;
  cutMethod?: string;
  /** 视图模式：'create' 创建表单 / 'select' 选择列表 */
  mode?: 'create' | 'select';
  /** 外部传入的整合包列表（来自 GsConfigPanel） */
  packages?: PackageInfo[];
  /** 当前正在使用的整合包名 */
  activePkg?: string | null;
  /** 用户点击"使用该模型"时回调 */
  onSelectPackage?: (name: string, pkg: PackageInfo) => void;
  /** 用户点击"删除整合包"时回调 */
  onRemovePackage?: (name: string) => void;
  /** 用户添加整合包时回调（外部处理上传） */
  onExternalAddPackage?: (file: File) => Promise<void>;
  /** 点击"创建整合包"时回调（由父组件打开创建模态框） */
  onRequestCreate?: () => void;
  /** 点击"高级创建"时回调 */
  onRequestAdvancedCreate?: () => void;
}

export default function GsBasicConfig({
  onPackageCreated, cutMethod, mode = 'create',
  packages: externalPackages, activePkg: externalActivePkg,
  onSelectPackage, onRemovePackage, onExternalAddPackage,
  onRequestCreate,
  onRequestAdvancedCreate,
}: GsBasicConfigProps) {
  const { message } = App.useApp();

  // ── 模型文件 ──
  const [gptFile, setGptFile] = useState<File | null>(null);
  const [sovitsFile, setSovitsFile] = useState<File | null>(null);
  const [gptName, setGptName] = useState('');
  const [sovitsName, setSovitsName] = useState('');

  // ── 参考音频（多文件） ──
  const [audioEntries, setAudioEntries] = useState<AudioEntry[]>([]);
  const [activeAudioIdx, setActiveAudioIdx] = useState<number | null>(null);
  const audioInputRef = useRef<HTMLInputElement>(null);
  useEffect(() => { if (audioEntries.length === 0) setAudioEntries([{ file: null, name: '', refText: '', refLang: '中文' }]); }, []);
  useEffect(() => () => { cancelledRef.current = true; }, []);

  // ── 参数 ──
  const [packageName, setPackageName] = useState('');
  const [modelVersion, setModelVersion] = useState('');
  const [gptVer, setGptVer] = useState<string | null>(null);
  const [sovitsVer, setSovitsVer] = useState<string | null>(null);
  const [detectedVer, setDetectedVer] = useState('');
  const [creating, setCreating] = useState(false);
  const cancelledRef = useRef(false);

  // ── 文件路径 ──
  const [gptPath, setGptPath] = useState('');
  const [sovitsPath, setSovitsPath] = useState('');
  const [audioPaths, setAudioPaths] = useState<string[]>([]);
  const [createProgress, setCreateProgress] = useState<{
    taskId: string; progress: number; status: string;
    totalBytes?: number; processedBytes?: number; speedBps?: number;
    etaSecs?: number; currentFile?: string;
  } | null>(null);
  const gptInputRef = useRef<HTMLInputElement>(null);
  const sovitsInputRef = useRef<HTMLInputElement>(null);

  // ── 本地包管理 ──
  const [localPackages, setLocalPackages] = useState<PackageInfo[]>([]);
  const [localActivePkg, setLocalActivePkg] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const pkgInputRef = useRef<HTMLInputElement>(null);
  const mountedRef = useRef(true);
  useEffect(() => () => { mountedRef.current = false; }, []);

  // 优先使用外部状态，无外部状态时使用本地状态
  const packages = externalPackages ?? localPackages;
  const activePkg = externalActivePkg ?? localActivePkg;

  // 加载已有整合包（本地模式）
  useEffect(() => {
    if (externalPackages) return; // 外部管理时不重复加载
    searchPackages().then((entries) => {
      if (!mountedRef.current) return;
      const seen = new Set<string>();
      setLocalPackages(entries.filter((e) => {
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

  // ─── 包管理：上传 ────────────────────────────
  const handleAddPackage = async () => {
    message.info('正在打开文件选择对话框...', 2);
    // 优先使用后端原生文件对话框（跳过 HTTP 上传，直接读盘）
    try {
      const pickerResp = await fetch(`${API_BASE}/packages/file-picker`);
      const pickerResult = await pickerResp.json();
      if (pickerResult.success && pickerResult.path) {
        await importFromPath(pickerResult.path);
        return;
      }
      // 用户取消了后端对话框 → 静默退出，不再弹出浏览器文件框
      if (pickerResult.error === '用户取消了选择') return;
    } catch (e) {
      // 网络错误或后端未运行 → 回退到浏览器文件选择器
      console.warn('[GsBasicConfig] Backend file picker failed, falling back to browser picker:', e);
    }
    // 回退到浏览器文件选择器
    pkgInputRef.current?.click();
  };

  // ─── 从后端路径导入 .gsvp ─────────────────────
  const importFromPath = async (filePath: string) => {
    try {
      const resp = await fetch(`${API_BASE}/packages/import`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: filePath }),
      });
      const result = await resp.json();
      if (!result.success) throw new Error(result.error || '导入失败');
      const name = result.name;
      const meta = result.meta || {};
      const newPkg: PackageInfo = { name, refLang: meta.refLang || '-',
        cutMethod: meta.cutMethod || '-', modelVersion: meta.modelVersion || '-',
        audioCount: meta.audioCount ?? 0, loading: true, loadProgress: 0 };
      if (onExternalAddPackage) {
        window.dispatchEvent(new CustomEvent('pkg-imported', { detail: { name, meta } }));
      }
      setLocalPackages((prev) => (prev.some((p) => p.name === name) ? prev : [...prev, newPkg]));
      message.success(`已从磁盘导入 ${name}，正在解压...`);
      // 立即检查一次搜索结果（文件已复制到 packages 目录，应能立即查到）
      const immediateEntries = await fetch(`${API_BASE}/packages/search`).then(r => r.json()).catch(() => []);
      const immediateList = Array.isArray(immediateEntries) ? immediateEntries : (immediateEntries.entries || []);
      const immediateFound = immediateList.find((entry: any) => entry.name === name);
      if (immediateFound) {
        setLocalPackages((prev) => prev.map((p) => p.name === name ? {
          ...p, loadProgress: 100, refLang: immediateFound.refLang || '-',
          cutMethod: immediateFound.cutMethod || '-', modelVersion: immediateFound.modelVersion || '-',
          audioCount: immediateFound.audioCount ?? 0, loading: false,
        } : p));
        message.success(`整合包「${name}」已就绪`);
        return;
      }
      // 轮询等待解压（进度前置：快速到 80%，给后端足够时间完成）
      for (let attempt = 0; attempt < 600; attempt++) {
        await new Promise((r) => setTimeout(r, 200));
        if (!mountedRef.current) return;
        const pct = Math.min(99, Math.round(10 + (attempt / 600) * 89));
        setLocalPackages((prev) => prev.map((p) => p.name === name ? { ...p, loadProgress: pct } : p));
        const entries = await fetch(`${API_BASE}/packages/search`).then(r => r.json()).catch(() => []);
        const list = Array.isArray(entries) ? entries : (entries.entries || []);
        const found = list.find((entry: any) => entry.name === name);
        if (found) {
          setLocalPackages((prev) => prev.map((p) => p.name === name ? {
            ...p, loadProgress: 100, refLang: found.refLang || '-',
            cutMethod: found.cutMethod || '-', modelVersion: found.modelVersion || '-',
            audioCount: found.audioCount ?? 0, loading: false,
          } : p));
          message.success(`整合包「${name}」已就绪`);
          return;
        }
      }
      setLocalPackages((prev) => prev.map((p) => p.name === name ? { ...p, loading: false } : p));
      message.warning(`解压 ${name} 超时，请刷新后重试`);
    } catch (err: any) {
      const nameFromPath = filePath.replace(/\.gsvp$/i, '').split(/[/\\]/).pop() || '';
      setLocalPackages((prev) => prev.map((p) => p.name === nameFromPath ? { ...p, loading: false, loadProgress: 0 } : p));
      message.error(err?.message || '导入失败');
    }
  };

  const handlePkgChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    e.target.value = '';
    // 尝试获取 file.path（Electron / 环境支持）
    const filePath = (file as any).path;
    if (filePath && typeof filePath === 'string') {
      await importFromPath(filePath);
      return;
    }
    // 回退到 HTTP 上传
    if (onExternalAddPackage) {
      await onExternalAddPackage(file);
    } else {
      await loadAndPollPackage(file);
    }
  };

  const loadAndPollPackage = async (file: File) => {
    const baseName = file.name.replace(/\.gsvp$/i, '');
    let uploadedName = baseName;
    try {
      const formData = new FormData();
      formData.append('file', file);
      const uploadResp = await fetch(`${API_BASE}/packages/upload`, {
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

      setLocalPackages((prev) => (prev.some((p) => p.name === name) ? prev : [...prev, {
        name, refLang: meta.refLang || '-', cutMethod: meta.cutMethod || '-',
        modelVersion: meta.modelVersion || '-', audioCount: meta.audioCount ?? 0,
        loading: true, loadProgress: 0,
      }]));
      message.success(`魔数验证通过，正在解压 ${name}...`);

      for (let attempt = 0; attempt < 720; attempt++) {
        await new Promise((r) => setTimeout(r, 200));
        if (!mountedRef.current) return;
        const pct = Math.min(99, Math.round((attempt / 720) * 99));
        setLocalPackages((prev) => prev.map((p) => p.name === name ? { ...p, loadProgress: pct } : p));
        const entries = await searchPackages();
        const found = entries.find((entry) => entry.name === name);
        if (found) {
          setLocalPackages((prev) => prev.map((p) => p.name === name ? {
            ...p, loadProgress: 100,
            refLang: found.refLang || '-', cutMethod: found.cutMethod || '-',
            modelVersion: found.modelVersion || '-', audioCount: found.audioCount ?? 0, loading: false,
          } : p));
          message.success(`整合包「${name}」已就绪`);
          return;
        }
      }
      setLocalPackages((prev) => prev.map((p) => p.name === name ? { ...p, loading: false } : p));
      message.warning(`解压 ${name} 超时，请刷新后重试`);
    } catch (err: any) {
      // 清除卡在 0% 的加载状态
      setLocalPackages((prev) => prev.map((p) => p.name === uploadedName ? { ...p, loading: false, loadProgress: 0 } : p));
      message.error(err?.message || '加载整合包失败');
    }
  };

  const handleRemovePkg = (name: string) => {
    if (onRemovePackage) {
      onRemovePackage(name);
    } else {
      setLocalPackages((prev) => prev.filter((p) => p.name !== name));
      if (localActivePkg === name) setLocalActivePkg(null);
    }
    try {
      fetch(`${API_BASE}/packages/delete`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name }),
      });
    } catch {}
  };

  const handleUsePkg = (name: string, pkg: PackageInfo) => {
    if (onSelectPackage) {
      onSelectPackage(name, pkg);
    } else {
      setLocalActivePkg(name);
    }
  };

  // ─── 拖入上传 ──────────────────────────────
  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault(); e.stopPropagation(); setDragOver(true);
  };
  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault(); e.stopPropagation(); setDragOver(false);
  };
  const handleDrop = async (e: React.DragEvent) => {
    e.preventDefault(); e.stopPropagation(); setDragOver(false);
    const files = Array.from(e.dataTransfer.files).filter((f) => f.name.endsWith('.gsvp'));
    if (files.length === 0) { message.warning('请拖入 .gsvp 格式的整合包文件'); return; }
    for (const file of files) {
      if (onExternalAddPackage) await onExternalAddPackage(file);
      else await loadAndPollPackage(file);
    }
  };

  const handleFileSelect = (ref: React.RefObject<HTMLInputElement | null>) => {
    if (ref.current) { ref.current.value = ''; ref.current.click(); }
  };

  // ─── 从文件名提取基底名称 ──────────────────────
  const extractBaseName = (fileName: string): string => {
    const name = fileName.replace(/\.(ckpt|pth|wav)$/i, '');
    return name.replace(/[-_]?e\d+(_s\d+)?(_l\d+)?$/, '').trim();
  };

  // ─── 后端扫描目录查找匹配文件 ──────────────────
  const doBackendScan = async (baseName: string, sourcePath?: string) => {
    try {
      const result = await scanMatesDirectory(baseName, sourcePath);
      return result;
    } catch (err: any) {
      const msg = err.message || '';
      if (msg.includes('无法连接')) {
        message.warning('后端服务未运行，无法自动检测配套文件。请启动 runtime server。');
      } else {
        message.warning(`自动检测失败: ${msg}`);
      }
      return null;
    }
  };

  // ─── 处理后端扫描结果 ──────────────────────────
  const processScanResult = (
    result: { ckpt: string[]; pth: string[]; wav: string[]; ref_texts?: string[] },
    sourceType: 'gpt' | 'sovits',
  ) => {
    const targetExt = sourceType === 'gpt' ? 'pth' : 'ckpt';
    const sourceExt = sourceType === 'gpt' ? 'ckpt' : 'pth';
    const otherType = sourceType === 'gpt' ? 'SoVITS' : 'GPT';
    const matches = result[targetExt as 'ckpt' | 'pth'] || [];
    const isOtherFilled = sourceType === 'gpt' ? !!sovitsFile : !!gptFile;

    const srcMatches = result[sourceExt as 'ckpt' | 'pth'] || [];
    if (srcMatches.length >= 1) {
      const setSrcPath = sourceType === 'gpt' ? setGptPath : setSovitsPath;
      setSrcPath(srcMatches[0]);
    }

    if (!isOtherFilled && matches.length > 0) {
      if (matches.length === 1) {
        const shortName = matches[0].split(/[/\\]/).pop() || matches[0];
        const setOtherName = sourceType === 'gpt' ? setSovitsName : setGptName;
        const setOtherPath = sourceType === 'gpt' ? setSovitsPath : setGptPath;
        setOtherName(shortName);
        setOtherPath(matches[0]);
        message.success(`自动检测到匹配的 ${otherType} 文件：${shortName}`);
      } else {
        const names = matches.map((p) => p.split(/[/\\]/).pop() || p).join('、');
        message.info(`检测到 ${matches.length} 个匹配的 ${otherType} 文件：${names}，请手动选择`);
      }
    }

    const wavMatches = result.wav || [];
    const refTexts = result.ref_texts || [];
    if (wavMatches.length > 0) {
      const allNames = wavMatches.map((p) => p.split(/[/\\]/).pop() || p);
      setAudioEntries(allNames.map((n, idx) => ({
        file: null, name: n, refText: (refTexts[idx] || '').trim(), refLang: '中文',
      })));
      setAudioPaths(wavMatches);
      const textFound = refTexts.some((t) => t && t.trim());
      message.success(`已自动添加 ${wavMatches.length} 个参考音频${textFound ? '，并关联参考文本' : ''}`);
    }
  };

  // ─── 自动填充匹配文件 ──────────────────────────
  const autoFillMates = async (sourceFile: File, sourceType: 'gpt' | 'sovits' | 'audio') => {
    const baseName = extractBaseName(sourceFile.name);
    if (!baseName) return;
    const result = await doBackendScan(baseName);
    if (!result) return;
    processScanResult(result, sourceType === 'audio' ? 'gpt' : sourceType);
  };

  // ─── 模型文件选择 + 自动检测 ─────────────────
  const handleGptChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    if (f) {
      setGptFile(f); setGptName(f.name);
      const ver = await scanVersion(f);
      setGptVer(ver);
      reconcileVersions(ver, sovitsVer);
      await autoFillMates(f, 'gpt');
    }
  };

  const handleSovitsChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    if (f) {
      setSovitsFile(f); setSovitsName(f.name);
      const ver = await scanVersion(f);
      setSovitsVer(ver);
      reconcileVersions(gptVer, ver);
      await autoFillMates(f, 'sovits');
    }
  };

  // ─── 参考音频管理 ────────────────────────────
  const handleAudioChange = (index: number) => (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    if (f) {
      setAudioEntries((prev) => {
        const next = [...prev];
        next[index] = { ...next[index], file: f, name: f.name };
        return next;
      });
    }
  };

  const addAudioEntry = () => {
    setAudioEntries((prev) => [...prev, { file: null, name: '', refText: '', refLang: '中文' }]);
  };

  // ─── 版本检测 ────────────────────────────────
  const scanVersion = async (file: File): Promise<string | null> => {
    try {
      const buf = await file.slice(0, 100 * 1024).arrayBuffer();
      const text = new TextDecoder('utf-8', { fatal: false }).decode(buf);
      const checks: [RegExp, string][] = [
        [/"version":\s*"v2proplas"/i, 'V2ProPlas'],
        [/"version":\s*"v2pro"/i, 'V2Pro'],
        [/"version":\s*"v4"/i, 'V4'],
        [/"version":\s*"v3"/i, 'V3'],
        [/"version":\s*"v2"/i, 'V2'],
        [/"version":\s*"v1"/i, 'V1'],
        [/gsv-v2proplas-pretrained/i, 'V2ProPlas'],
        [/gsv-v2pro-pretrained/i, 'V2Pro'],
        [/gsv-v4-pretrained/i, 'V4'],
        [/gsv-v3-pretrained/i, 'V3'],
        [/gsv-v2-pretrained/i, 'V2'],
        [/gsv-v1-pretrained/i, 'V1'],
        [/weights_v2proplas/i, 'V2ProPlas'],
        [/weights_v2pro/i, 'V2Pro'],
        [/SoVITS_weights_v4/i, 'V4'],
        [/SoVITS_weights_v3/i, 'V3'],
        [/SoVITS_weights_v2/i, 'V2'],
        [/GPT_weights_v4/i, 'V4'],
        [/GPT_weights_v3/i, 'V3'],
        [/GPT_weights_v2/i, 'V2'],
        [/logs_s1_v2proplas/i, 'V2ProPlas'],
        [/logs_s1_v2pro/i, 'V2Pro'],
        [/logs_s2_v2proplas/i, 'V2ProPlas'],
        [/logs_s2_v2pro/i, 'V2Pro'],
        [/logs_s1_v4/i, 'V4'],
        [/logs_s1_v3/i, 'V3'],
        [/logs_s1_v2/i, 'V2'],
        [/logs_s2_v4/i, 'V4'],
        [/logs_s2_v3/i, 'V3'],
        [/logs_s2_v2/i, 'V2'],
        [/s2Gv4\.pth/i, 'V4'],
        [/s2Gv3\.pth/i, 'V3'],
        [/s2Gv2\.pth/i, 'V2'],
        [/s1v3\.ckpt/i, 'V4'],
        [/s1v2\.ckpt/i, 'V2'],
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

  // ─── 创建整合包 ──────────────────────────────
  const handleCreate = async () => {
    const validAudios = audioEntries.filter((a) => a.file || a.name);
    if (!gptFile && !gptPath) return void message.warning('请选择 GPT 模型文件');
    if (!sovitsFile && !sovitsPath) return void message.warning('请选择 SoVITS 模型文件');
    if (validAudios.length === 0) return void message.warning('请选择至少一个参考音频文件');
    const refTexts = audioEntries.map((a) => a.refText.trim()).filter(Boolean);
    if (refTexts.length === 0) return void message.warning('请为参考音频输入参考文本');
    if (!modelVersion) return void message.warning('请选择模型版本');

    const entryRefLangs = audioEntries.map((a) => a.refLang || '中文');
    const uniqueLangs = [...new Set(entryRefLangs)];
    const effectiveRefLang = uniqueLangs.length === 1 ? uniqueLangs[0] : uniqueLangs.join('、');

    const hasAllPaths = !!(gptPath && sovitsPath && audioPaths.length > 0);
    const hasAllFiles = !!(gptFile && sovitsFile && audioEntries.some((a) => a.file));
    if (!hasAllPaths && !hasAllFiles) {
      if (!gptPath && !gptFile) return void message.warning('未获取到 GPT 模型，请手动输入路径或通过选择按钮选取文件');
      if (!sovitsPath && !sovitsFile) return void message.warning('未获取到 SoVITS 模型，请手动输入路径或通过选择按钮选取文件');
    }
    if (!hasAllPaths && audioPaths.length === 0 && !audioEntries.some((a) => a.file)) {
      return void message.warning('未获取到参考音频，请手动输入路径或通过选择按钮选取文件');
    }

    try {
      setCreating(true);
      setCreateProgress({ taskId: '', progress: 0, status: 'starting' });
      await new Promise((r) => setTimeout(r, 50));

      let task_id: string;
      const joinedRefText = refTexts.join('\n');

      if (hasAllPaths) {
        const body: Record<string, any> = {
          meta: { refLang: effectiveRefLang, refText: joinedRefText, cutMethod: cutMethod ?? '不切', modelVersion, packageName, refLangs: entryRefLangs },
          gpt_path: gptPath,
          sovits_path: sovitsPath,
          audio_paths: audioPaths,
        };
        const resp = await fetch(`${API_BASE}/packages/create-from-paths`, {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        });
        if (!resp.ok) { const err = await resp.json().catch(() => ({})); throw new Error(err.error || '创建失败'); }
        ({ task_id } = await resp.json());
      } else {
        const fd = new FormData();
        fd.append('meta', JSON.stringify({ refLang: effectiveRefLang, refText: joinedRefText, cutMethod: cutMethod ?? '不切', modelVersion, packageName, refLangs: entryRefLangs }));
        fd.append('gpt', gptFile!);
        fd.append('sovits', sovitsFile!);
        const fileAudios = validAudios.filter((a): a is AudioEntry & { file: File } => a.file !== null);
        fileAudios.forEach((a) => fd.append('audios', a.file));
        const resp = await fetch(`${API_BASE}/packages/create`, {
          method: 'POST', body: fd,
        });
        if (!resp.ok) { const err = await resp.json().catch(() => ({})); throw new Error(err.error || '创建失败'); }
        const result = await resp.json();
        const meta = result.meta || {};
        const name = result.name || packageName.trim() || 'gsv-package';
        message.success(`✅ 整合包「${name}」已创建${result.downloadPath ? `，已保存到下载文件夹` : ''}`);
        onPackageCreated?.(name, { refLang: meta.refLang || effectiveRefLang, cutMethod: cutMethod ?? '不切', modelVersion, audioCount: validAudios.length, refLangs: entryRefLangs });
        return;
      }

      setCreateProgress({ taskId: task_id, progress: 0, status: 'processing' });

      await new Promise<void>((resolve, reject) => {
        cancelledRef.current = false;
        const poll = async () => {
          if (cancelledRef.current) { resolve(); return; }
          try {
            const pr = await fetch(`${API_BASE}/packages/progress?task_id=${task_id}`);
            const st = await pr.json();
            if (cancelledRef.current) { resolve(); return; }
            setCreateProgress({ taskId: task_id, progress: st.progress, status: st.status,
              totalBytes: st.totalBytes, processedBytes: st.processedBytes,
              speedBps: st.speedBps, etaSecs: st.etaSecs, currentFile: st.currentFile });
            if (st.status === 'done') {
              const fileName = st.fileName || `${packageName.trim() || 'gsv-package'}.gsvp`;
              const filePath = st.filePath || '';
              const name = fileName.replace(/\.gsvp$/i, '');
              message.success(`创建成功: ${fileName}`);
              if (filePath) message.info(`文件路径: ${filePath}`);
              onPackageCreated?.(name, { refLang: effectiveRefLang, cutMethod: cutMethod ?? '不切', modelVersion, audioCount: validAudios.length, refLangs: entryRefLangs });
              // 创建成功后由父组件关闭模态框
              resolve(); return;
            }
            if (st.status === 'error') {
              reject(new Error(st.error || '创建失败'));
              return;
            }
            if (!cancelledRef.current) setTimeout(poll, 600);
          } catch (err) {
            if (!cancelledRef.current) reject(err as Error);
          }
        };
        poll();
      });
    } catch (err: any) {
      console.error('[GsBasicConfig] 创建整合包失败:', err);
      message.error(err?.message || '创建失败，请重试');
      setCreateProgress({ taskId: '', progress: -1, status: 'error' });
    } finally {
      cancelledRef.current = true;
      setCreating(false);
      setCreateProgress(null);
    }
  };

  // ─────────────────────────────────────────────
  // 选择视图：整合包列表 + 选择/创建按钮
  // ─────────────────────────────────────────────
  const renderSelectView = () => (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      {/* 顶部行：标题 + 添加 */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, justifyContent: 'space-between' }}>
        <span style={{ fontSize: 10, fontWeight: 600, color: 'var(--palm-text-mid, #344054)' }}>整合包列表</span>
        <div style={{ display: 'flex', gap: 6 }}>
          <input type="file" ref={pkgInputRef} style={{ display: 'none' }} accept=".gsvp" onChange={handlePkgChange} />
          <Button size="small" icon={<FolderOpenOutlined />} onClick={handleAddPackage}>添加整合包</Button>
          <Button size="small" icon={<FolderOpenOutlined />} onClick={onRequestCreate}>创建整合包</Button>
        </div>
      </div>

      {/* 整合包卡片列表 — 可滑动容器 */}
      <div style={{
        height: 480, overflowY: 'auto',
        border: `1px solid ${dragOver ? 'var(--palm-primary, #3b82f6)' : 'var(--palm-card-border, #e4e7ec)'}`,
        borderRadius: 4, padding: '8px 14px', display: 'flex', flexDirection: 'column', gap: 6,
        background: dragOver ? 'rgba(59,130,246,0.04)' : 'transparent',
        transition: 'border-color 0.15s, background 0.15s',
      }}
        onDragOver={handleDragOver} onDragLeave={handleDragLeave} onDrop={handleDrop}
      >
        {packages.length > 0 ? [...packages].sort((a, b) => {
          // 正在使用的置顶
          if (a.name === activePkg) return -1;
          if (b.name === activePkg) return 1;
          return 0;
        }).map((pkg) => {
          const isActive = activePkg === pkg.name;
          return (
            <div key={pkg.name} className="qwen-tts-card" style={{ padding: '10px 14px', display: 'flex', alignItems: 'center', gap: 12, flexShrink: 0 }}>
              <FolderOpenOutlined style={{ fontSize: 13, opacity: 0.6 }} />
              <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--palm-text-mid, #344054)', fontFamily: 'ui-monospace, monospace', flexShrink: 0, maxWidth: '40%', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{pkg.name.replace(/\.gsvp$/i, '')}</span>
              {pkg.packageType === 'advanced' && (
                <span style={{ fontSize: 9, fontWeight: 600, color: '#8b5cf6', background: '#ede9fe', padding: '1px 5px', borderRadius: 3, flexShrink: 0 }}>高级</span>
              )}
              {pkg.loading ? (
                <div style={{ flex: 1, minWidth: 0 }}>
                  <Progress percent={pkg.loadProgress ?? 0} size="small" strokeColor="#3b82f6" format={(p) => `${p}% 解压中`} />
                </div>
              ) : (<>
                <div style={{ display: 'flex', gap: 12, fontSize: 10, color: 'var(--palm-text-low, #475467)', flex: 1, alignItems: 'center' }}>
                  <span style={{ flexShrink: 0 }}>参考语种:</span>
                  {(pkg.refLang || '-').replace(/,/g, '、').split('、').filter(Boolean).map((lang, li) => (
                    <span key={li} style={{
                      fontSize: 10, fontWeight: 500, color: '#3b82f6',
                      background: 'rgba(59,130,246,0.1)',
                      padding: '1px 7px', borderRadius: 3, whiteSpace: 'nowrap',
                    }}>{lang}</span>
                  ))}
                  <span style={{ flexShrink: 0 }}>模型版本:</span>
                  <span style={{
                    fontSize: 10, fontWeight: 500, color: '#8b5cf6',
                    background: 'rgba(139,92,246,0.1)',
                    padding: '1px 7px', borderRadius: 3, whiteSpace: 'nowrap',
                  }}>{pkg.modelVersion || '-'}</span>
                  <span>参考音频: <strong style={{ color: 'var(--palm-text-mid, #344054)' }}>{pkg.audioCount ?? 0} 个</strong></span>
                </div>
                {isActive && <span style={{ fontSize: 10, color: '#22c55e', fontWeight: 500, background: 'rgba(34,197,94,0.1)', padding: '1px 6px', borderRadius: 3 }}>正在使用</span>}
                {!isActive && (
                  <Button size="small" type="primary" ghost style={{ fontSize: 10, lineHeight: '16px', height: 22 }} onClick={() => handleUsePkg(pkg.name, pkg)}>使用该模型</Button>
                )}
                <Button size="small" danger type="text" style={{ fontSize: 10, lineHeight: '16px', height: 22 }} onClick={() => handleRemovePkg(pkg.name)}>删除</Button>
              </>)}
            </div>
          );
        }) : (
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 11, color: 'var(--palm-text-low, #94a3b8)', padding: '180px 0' }}>
            {dragOver ? (
              <span style={{ color: 'var(--palm-primary, #3b82f6)' }}>释放以上传整合包</span>
            ) : (
              <span>暂无整合包，点击上方「添加整合包」按钮或拖入整合包文件</span>
            )}
          </div>
        )}
      </div>
    </div>
  );

  // ─────────────────────────────────────────────
  // 创建视图：配置表单
  // ─────────────────────────────────────────────
  const renderCreateView = () => (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      {/* 标题行：创建整合包 + 高级创建 */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, justifyContent: 'space-between' }}>
        <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--palm-text-mid, #344054)' }}>创建整合包</span>
        <Button size="small" danger onClick={onRequestAdvancedCreate || onRequestCreate}>高级创建</Button>
      </div>
      {/* ── 包名 ── */}
      <div className="qwen-tts-path-row">
        <span className="qwen-tts-path-label">包名</span>
        <Input value={packageName} onChange={(e) => setPackageName(e.target.value)} placeholder="输入整合包名称（不含扩展名）" className="qwen-tts-path-input" />
      </div>

      {/* ── 路径输入区 ── */}
      <div className="qwen-tts-form-group" style={{ gap: 4 }}>
        <div className="qwen-tts-path-row">
          <span className="qwen-tts-path-label">GPT 模型路径</span>
          <Input value={gptName} onChange={(e) => { setGptName(e.target.value); setGptPath(e.target.value); }} placeholder="选择或输入 GPT 模型文件路径..." className="qwen-tts-path-input" />
          <input type="file" ref={gptInputRef} style={{ display: 'none' }} accept=".ckpt" onChange={handleGptChange} />
          <Button size="small" onClick={() => handleFileSelect(gptInputRef)}>选择</Button>
        </div>
        <div className="qwen-tts-path-row">
          <span className="qwen-tts-path-label">SoVITS 模型路径</span>
          <Input value={sovitsName} onChange={(e) => { setSovitsName(e.target.value); setSovitsPath(e.target.value); }} placeholder="选择或输入 SoVITS 模型文件路径..." className="qwen-tts-path-input" />
          <input type="file" ref={sovitsInputRef} style={{ display: 'none' }} accept=".pth" onChange={handleSovitsChange} />
          <Button size="small" onClick={() => handleFileSelect(sovitsInputRef)}>选择</Button>
        </div>

        {/* 参考音频（多文件） */}
        <input type="file" ref={audioInputRef} style={{ display: 'none' }} accept=".wav" onChange={(e) => {
          if (activeAudioIdx !== null) handleAudioChange(activeAudioIdx)(e);
        }} />
        <div style={{ width: '100%', display: 'flex', flexDirection: 'column', gap: 2 }}>
        {audioEntries.map((entry, i) => (
          <div key={i} style={{ display: 'flex', flexDirection: 'column', gap: 2, paddingBottom: i < audioEntries.length - 1 ? 6 : 0 }}>
            <div className="qwen-tts-path-row" style={{ marginBottom: 0 }}>
              <span className="qwen-tts-path-label">参考音频{i + 1}路径</span>
              <Input value={entry.name} onChange={(e) => {
                const val = e.target.value;
                setAudioEntries((prev) => { const n = [...prev]; n[i] = { ...n[i], name: val }; return n; });
                setAudioPaths((prev) => { const n = [...prev]; n[i] = val; return n; });
              }} placeholder="选择或输入参考音频文件路径..." className="qwen-tts-path-input" />
              <Button size="small" onClick={() => { setActiveAudioIdx(i); audioInputRef.current?.click(); }}>选择</Button>
              {i === audioEntries.length - 1 && (
                <Button size="small" type="dashed" icon={<PlusOutlined />} onClick={addAudioEntry} style={{ marginLeft: 2 }} />
              )}
            </div>
            <div className="qwen-tts-path-row" style={{ marginBottom: 0, paddingLeft: 0 }}>
              <span className="qwen-tts-path-label">参考文本{i + 1}</span>
              <Input value={entry.refText} onChange={(e) => {
                setAudioEntries((prev) => { const n = [...prev]; n[i] = { ...n[i], refText: e.target.value }; return n; });
              }} placeholder="输入该音频对应的参考文本..." className="qwen-tts-path-input" />
              <Select value={entry.refLang || '中文'} onChange={(val) => {
                setAudioEntries((prev) => { const n = [...prev]; n[i] = { ...n[i], refLang: val }; return n; });
              }} size="small" style={{ width: 90, minWidth: 90 }} options={LANG_OPTIONS} />
            </div>
          </div>
        ))}
        </div>
      </div>

      {/* ── 模型版本 ── */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
        <div style={{ display: 'flex', gap: 6 }}>
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
        </div>
      </div>

      {/* ── 按钮行 ── */}
      <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, paddingTop: 4 }}>
        <Button type="primary" loading={creating} onClick={handleCreate} style={{ fontSize: 12 }}>
          {creating ? '创建中...' : '确认创建'}
        </Button>
      </div>
      {createProgress && createProgress.progress >= 0 && (
        <div style={{ paddingTop: 8 }}>
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
            <div style={{ fontSize: 11, color: '#666', paddingTop: 4, fontFamily: 'monospace' }}>
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
  );

  return mode === 'select' ? renderSelectView() : renderCreateView();
}
