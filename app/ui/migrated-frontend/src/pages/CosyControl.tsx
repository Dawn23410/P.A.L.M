/**
 * P.A.L.M · CosyVoice 自然语言控制（原生面板）
 *
 * 完全沿用 GPT-SoVITS 原生面板的视觉语言与结构：
 *   gsv-tts-subpage > gsv-tts-layout > gsv-tts-main
 *   各区块统一用 antd Card(size="small", title=...) 承载
 * 聚焦 CosyVoice2 的「自然语言控制 + 跨语种合成」：
 *   - 说话人管理：列表 / 设为默认常驻 / 删除
 *   - 说话人热注册：子窗口（Modal）表单，参考音频 + 文本 + ID，即时持久化
 *   - 自然语言控制合成：合成文本 + instruct（风格/方言/跨语种指令）+ 说话人
 *   - 重启载入：热重载 spk2info 到内存，无需重启进程
 *
 * 后端：speech/cosyvoice/api_server.py（FastAPI @7861）
 */

import { useEffect, useRef, useState, useCallback } from 'react';
import { App, Button, Card, Select, Slider, Switch, Input, InputNumber, Upload, List, Tag, Space, Modal } from 'antd';
import {
  ReloadOutlined,
  PlusOutlined,
  DeleteOutlined,
  StarOutlined,
  SoundOutlined,
  ThunderboltOutlined,
  UploadOutlined,
} from '@ant-design/icons';
import { useModuleConfig } from '../store/configStore';
import { type TtsConfig } from '../store/configSchema';
import {
  getHealth,
  listSpeakers,
  registerSpeaker,
  deleteSpeaker,
  setDefaultSpeaker,
  reloadSpeakers,
  generateTts,
  getSettings,
  saveSettings,
  type CosySpeaker,
  type CosySettings,
} from '../api/cosyVoice';

const { TextArea } = Input;
const INSTRUCT_EXAMPLES = '用兴奋的语气 / 用四川话说 / 用英语说这句话 / 用机器人风格';

type ConnStatus = 'loading' | 'ok' | 'down';

export default function CosyControl() {
  const { message } = App.useApp();
  const { config, update } = useModuleConfig<TtsConfig>('tts');

  const [status, setStatus] = useState<ConnStatus>('loading');
  const [speakers, setSpeakers] = useState<CosySpeaker[]>([]);
  const [defaultSpk, setDefaultSpk] = useState<string | null>(null);

  const [audioUrl, setAudioUrl] = useState<string | null>(null);
  const [generating, setGenerating] = useState(false);

  // 运行设置（设备 / 半精度）
  const [device, setDevice] = useState<string>(config.cosyDevice);
  const [halfPrecision, setHalfPrecision] = useState<boolean>(config.cosyHalfPrecision);
  const [settingsBusy, setSettingsBusy] = useState(false);

  // 注册子窗口
  const [regOpen, setRegOpen] = useState(false);
  const [regText, setRegText] = useState('');
  const [regId, setRegId] = useState('');
  const [regFile, setRegFile] = useState<File | null>(null);
  const [registering, setRegistering] = useState(false);

  const audioRef = useRef<HTMLAudioElement>(null);
  const mountedRef = useRef(true);
  useEffect(() => () => {
    mountedRef.current = false;
    if (audioUrl) URL.revokeObjectURL(audioUrl);
  }, [audioUrl]);

  // 解析当前选中说话人：已选 > 默认常驻 > 列表首项
  const resolveSelected = useCallback(
    (list: CosySpeaker[], sel: string, def: string | null) => {
      if (sel && list.some((s) => s.id === sel)) return sel;
      if (def && list.some((s) => s.id === def)) return def;
      return list.length ? list[0].id : '';
    },
    [],
  );

  const refreshSpeakers = useCallback(async () => {
    try {
      const data = await listSpeakers();
      if (!mountedRef.current) return;
      setSpeakers(data.speakers);
      setDefaultSpk(data.default);
      const cur = resolveSelected(data.speakers, config.cosySelectedSpeaker, data.default);
      if (cur !== config.cosySelectedSpeaker) update({ cosySelectedSpeaker: cur });
    } catch {
      if (mountedRef.current) setSpeakers([]);
    }
  }, [config.cosySelectedSpeaker, update, resolveSelected]);

  // 首次加载：健康检查 + 说话人列表 + 运行设置同步
  useEffect(() => {
    let alive = true;
    getHealth()
      .then(() => alive && setStatus('ok'))
      .catch(() => alive && setStatus('down'));
    refreshSpeakers();
    initSettings();
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ─── 操作 ──────────────────────────────────────────────────
  const handleSetDefault = async (spkId: string) => {
    try {
      const data = await setDefaultSpeaker(spkId);
      setSpeakers(data.speakers);
      setDefaultSpk(data.default);
      update({ cosyDefaultSpeaker: data.default || '' });
      message.success(`已设「${spkId}」为默认常驻说话人`);
    } catch (e: any) {
      message.error(e?.message || '设置默认失败');
    }
  };

  const handleDelete = async (spkId: string) => {
    try {
      const data = await deleteSpeaker(spkId);
      setSpeakers(data.speakers);
      setDefaultSpk(data.default);
      const cur = resolveSelected(data.speakers, config.cosySelectedSpeaker, data.default);
      update({ cosySelectedSpeaker: cur });
      message.success(`已删除「${spkId}」`);
    } catch (e: any) {
      message.error(e?.message || '删除失败');
    }
  };

  const openRegister = () => {
    setRegText('');
    setRegId('');
    setRegFile(null);
    setRegOpen(true);
  };

  const handleRegister = async () => {
    if (!regFile) return message.warning('请先上传参考音频');
    if (!regText.trim()) return message.warning('请填写参考音频文本');
    if (!regId.trim()) return message.warning('请填写说话人ID');
    setRegistering(true);
    try {
      const data = await registerSpeaker(regText.trim(), regId.trim(), regFile);
      if (!mountedRef.current) return;
      setSpeakers(data.speakers);
      setDefaultSpk(data.default);
      update({ cosySelectedSpeaker: regId.trim() });
      setRegOpen(false);
      setRegText('');
      setRegId('');
      setRegFile(null);
      message.success(`「${regId.trim()}」注册成功`);
    } catch (e: any) {
      message.error(e?.message || '注册失败');
    } finally {
      if (mountedRef.current) setRegistering(false);
    }
  };

  const handleReload = async () => {
    try {
      const data = await reloadSpeakers();
      setSpeakers(data.speakers);
      setDefaultSpk(data.default);
      const cur = resolveSelected(data.speakers, config.cosySelectedSpeaker, data.default);
      update({ cosySelectedSpeaker: cur });
      message.success('已重启载入说话人');
    } catch (e: any) {
      message.error(e?.message || '重载失败');
    }
  };

  // ─── 运行设置（设备 / 半精度） ──────────────────────────────
  const initSettings = useCallback(async () => {
    try {
      const s: CosySettings = await getSettings();
      setDevice(s.device);
      setHalfPrecision(s.fp16);
      if (mountedRef.current) update({ cosyDevice: s.device, cosyHalfPrecision: s.fp16 });
    } catch {
      // 后端不可用时回退到本地存储值
      setDevice(config.cosyDevice);
      setHalfPrecision(config.cosyHalfPrecision);
    }
  }, [config.cosyDevice, config.cosyHalfPrecision, update]);

  const waitForRestart = useCallback(
    async (targetDevice: string, targetFp16: boolean) => {
      const deadline = Date.now() + 30000;
      while (Date.now() < deadline) {
        await new Promise((r) => setTimeout(r, 1500));
        if (!mountedRef.current) return;
        try {
          const s: CosySettings = await getSettings();
          if (s.device === targetDevice && s.fp16 === targetFp16) {
            setDevice(s.device);
            setHalfPrecision(s.fp16);
            update({ cosyDevice: s.device, cosyHalfPrecision: s.fp16 });
            setStatus('ok');
            message.success('服务已重启，新设备已生效');
            refreshSpeakers();
            return;
          }
        } catch {
          // 服务重启中，继续轮询
        }
      }
      message.warning('服务重启超时，请检查后台日志（%TEMP%\\palm_cosy.log）');
    },
    [message, refreshSpeakers, update],
  );

  const applySettings = useCallback(
    async (newDevice: string, newFp16: boolean) => {
      setSettingsBusy(true);
      try {
        const res = await saveSettings(newDevice, newFp16);
        update({ cosyDevice: res.device, cosyHalfPrecision: res.fp16 });
        if (res.needs_restart) {
          message.info('设置已保存，服务正在重启以应用新设备…');
          await waitForRestart(res.device, res.fp16);
        } else {
          setDevice(res.device);
          setHalfPrecision(res.fp16);
          message.success('运行设置已保存');
        }
      } catch (e: any) {
        message.error(e?.message || '保存运行设置失败');
      } finally {
        setSettingsBusy(false);
      }
    },
    [message, update, waitForRestart],
  );

  const handleDeviceChange = (v: string) => {
    setDevice(v);
    applySettings(v, v === 'cpu' ? false : halfPrecision);
  };

  const handleHalfChange = (v: boolean) => {
    setHalfPrecision(v);
    applySettings(device, v);
  };

  const handleGenerate = async () => {
    const spk = resolveSelected(speakers, config.cosySelectedSpeaker, defaultSpk);
    if (!spk) return message.warning('没有可用说话人，请先注册');
    if (!config.cosyText.trim()) return message.warning('请填写合成文本');
    if (!config.cosyInstruct.trim()) return message.warning('请填写 instruct 文本（风格/方言/跨语种指令）');
    setGenerating(true);
    try {
      const blob = await generateTts({
        tts_text: config.cosyText,
        instruct_text: config.cosyInstruct,
        spk_id: spk,
        speed: config.cosySpeed,
        seed: config.cosySeed,
        stream: config.cosyStream,
      });
      if (!mountedRef.current) return;
      const url = URL.createObjectURL(blob);
      if (audioUrl) URL.revokeObjectURL(audioUrl);
      setAudioUrl(url);
    } catch (e: any) {
      message.error(e?.message || '合成失败');
    } finally {
      if (mountedRef.current) setGenerating(false);
    }
  };

  const randomSeed = () => update({ cosySeed: Math.floor(Math.random() * 1_000_000) });

  const selectedNow = resolveSelected(speakers, config.cosySelectedSpeaker, defaultSpk);
  const STATUS_COLOR = status === 'ok' ? '#22c55e' : status === 'down' ? '#ef4444' : '#94a3b8';

  return (
    <div className="gsv-tts-subpage">
      <div className="gsv-tts-layout">
        <div className="gsv-tts-main">
          {/* 服务状态 */}
          <Card className="gsv-tts-card" size="small" title="服务状态">
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <span style={{ display: 'inline-block', width: 7, height: 7, borderRadius: '50%', background: STATUS_COLOR }} />
              <span style={{ fontSize: 12, color: 'var(--palm-text-mid, #475467)' }}>
                {status === 'loading' ? '连接中…' : status === 'ok' ? 'CosyVoice 已连接' : '未连接（请在后台启动 Cosy API :7861）'}
              </span>
              <Tag color="cyan" style={{ fontSize: 10, lineHeight: '18px', margin: 0 }}>自然语言控制</Tag>
              <Tag color="cyan" style={{ fontSize: 10, lineHeight: '18px', margin: 0 }}>跨语种合成</Tag>
              <Tag color="cyan" style={{ fontSize: 10, lineHeight: '18px', margin: 0 }}>说话人热注册</Tag>
              <div style={{ flex: 1 }} />
              <Button size="small" icon={<ReloadOutlined />} onClick={handleReload} disabled={status !== 'ok'}>
                重启载入
              </Button>
            </div>
          </Card>

          {/* 合成参数配置条 */}
          <div className="gsv-tts-config-bar" style={{ paddingLeft: 4 }}>
            <div className="gsv-tts-config-item">
              <span className="gsv-tts-config-label">速度</span>
              <Slider value={config.cosySpeed} onChange={(v) => update({ cosySpeed: v })} min={0.5} max={2} step={0.1} style={{ width: 120 }} />
              <span style={{ fontSize: 11, color: 'var(--palm-text-mid, #475467)', width: 32 }}>{config.cosySpeed.toFixed(1)}</span>
            </div>
            <div className="gsv-tts-config-item">
              <span className="gsv-tts-config-label">随机种子</span>
              <InputNumber value={config.cosySeed} onChange={(v) => update({ cosySeed: v ?? 0 })} size="small" style={{ width: 90 }} />
              <Button size="small" icon={<ThunderboltOutlined />} onClick={randomSeed} />
            </div>
            <div className="gsv-tts-config-item">
              <span className="gsv-tts-config-label">流式输出</span>
              <Switch checked={config.cosyStream} onChange={(v) => update({ cosyStream: v })} size="small" />
            </div>
            <div className="gsv-tts-config-item">
              <span className="gsv-tts-config-label">运行设备</span>
              <Select
                size="small"
                style={{ width: 92 }}
                value={device}
                onChange={handleDeviceChange}
                disabled={settingsBusy || status !== 'ok'}
                options={[
                  { value: 'cuda:0', label: 'CUDA' },
                  { value: 'cpu', label: 'CPU' },
                ]}
              />
            </div>
            <div className="gsv-tts-config-item">
              <span className="gsv-tts-config-label">半精度</span>
              <Switch
                checked={halfPrecision}
                onChange={handleHalfChange}
                size="small"
                disabled={device === 'cpu' || settingsBusy || status !== 'ok'}
              />
            </div>
          </div>

          {/* 说话人管理 */}
          <Card className="gsv-tts-card" size="small" title="说话人管理">
            <List
              size="small"
              dataSource={speakers}
              locale={{ emptyText: '暂无说话人，请点击「注册说话人」' }}
              renderItem={(s) => (
                <List.Item
                  style={{ padding: '6px 0', alignItems: 'center' }}
                  actions={[
                    <Button
                      key="def"
                      type={s.is_default ? 'default' : 'link'}
                      size="small"
                      icon={<StarOutlined />}
                      disabled={s.is_default}
                      onClick={() => handleSetDefault(s.id)}
                    >
                      {s.is_default ? '默认' : '设默认'}
                    </Button>,
                    <Button
                      key="del"
                      type="link"
                      size="small"
                      danger
                      icon={<DeleteOutlined />}
                      onClick={() => handleDelete(s.id)}
                    >
                      删除
                    </Button>,
                  ]}
                >
                  <List.Item.Meta
                    avatar={<SoundOutlined style={{ fontSize: 16, opacity: 0.7 }} />}
                    title={<span style={{ fontSize: 13 }}>{s.id}{s.is_default && <Tag color="gold" style={{ marginLeft: 6, fontSize: 9 }}>常驻</Tag>}</span>}
                    description={<span style={{ fontSize: 10, color: 'var(--palm-text-low, #475467)' }}>{s.prompt_text || '声纹已注册'}</span>}
                  />
                </List.Item>
              )}
            />
            <div style={{ borderTop: '1px solid var(--palm-line, #e4e7ec)', marginTop: 4, paddingTop: 10, textAlign: 'right' }}>
              <Button type="primary" size="small" icon={<PlusOutlined />} onClick={openRegister} disabled={status !== 'ok'}>
                注册说话人
              </Button>
            </div>
          </Card>

          {/* 自然语言控制合成 */}
          <Card className="gsv-tts-card" size="small" title="自然语言控制合成">
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                <span className="gsv-tts-config-label" style={{ width: 64, flexShrink: 0 }}>说话人</span>
                <Select
                  size="small"
                  style={{ flex: 1 }}
                  placeholder="选择说话人"
                  value={selectedNow || undefined}
                  onChange={(v) => update({ cosySelectedSpeaker: v })}
                  options={speakers.map((s) => ({ value: s.id, label: s.id + (s.is_default ? '（默认）' : '') }))}
                />
              </div>

              <div>
                <div className="gsv-tts-config-label" style={{ marginBottom: 4 }}>instruct 文本（风格 / 方言 / 跨语种指令）</div>
                <Input
                  placeholder={INSTRUCT_EXAMPLES}
                  value={config.cosyInstruct}
                  onChange={(e) => update({ cosyInstruct: e.target.value })}
                  disabled={!speakers.length}
                />
              </div>

              <div>
                <div className="gsv-tts-config-label" style={{ marginBottom: 4 }}>合成文本（可为任意语言）</div>
                <TextArea
                  rows={3}
                  value={config.cosyText}
                  onChange={(e) => update({ cosyText: e.target.value })}
                  disabled={!speakers.length}
                />
              </div>

              <Button
                type="primary"
                icon={<SoundOutlined />}
                loading={generating}
                onClick={handleGenerate}
                disabled={!speakers.length || status !== 'ok'}
              >
                生成音频
              </Button>

              {audioUrl && (
                <audio ref={audioRef} src={audioUrl} controls style={{ width: '100%', marginTop: 4 }} />
              )}
            </div>
          </Card>
        </div>
      </div>

      {/* 注册子窗口 */}
      <Modal
        title="注册说话人"
        open={regOpen}
        onCancel={() => !registering && setRegOpen(false)}
        footer={[
          <Button key="cancel" onClick={() => setRegOpen(false)} disabled={registering}>取消</Button>,
          <Button key="ok" type="primary" icon={<PlusOutlined />} loading={registering} onClick={handleRegister}>
            注册
          </Button>,
        ]}
        destroyOnHidden
      >
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12, paddingTop: 4 }}>
          <div>
            <div className="gsv-tts-config-label" style={{ marginBottom: 6 }}>参考音频（3–6 秒・单说话人）</div>
            <Upload
              beforeUpload={(f) => { setRegFile(f); return false; }}
              maxCount={1}
              showUploadList={{ showPreviewIcon: false, showRemoveIcon: true }}
              onRemove={() => setRegFile(null)}
            >
              <Button size="small" icon={<UploadOutlined />}>
                {regFile ? regFile.name : '选择参考音频'}
              </Button>
            </Upload>
          </div>
          <div>
            <div className="gsv-tts-config-label" style={{ marginBottom: 6 }}>说话人 ID（如 anko）</div>
            <Input
              size="small"
              placeholder="说话人ID，如 anko"
              value={regId}
              onChange={(e) => setRegId(e.target.value)}
            />
          </div>
          <div>
            <div className="gsv-tts-config-label" style={{ marginBottom: 6 }}>参考音频所念内容的转写</div>
            <TextArea
              size="small"
              rows={2}
              placeholder="参考音频所念内容的转写"
              value={regText}
              onChange={(e) => setRegText(e.target.value)}
            />
          </div>
        </div>
      </Modal>
    </div>
  );
}
