/**
 * GPT-SoVITS · 语音合成（基础语音合成 / 音色设计）
 *
 * API: POST /tts   (gptSoVits.generateTts)
 * 对接已接上的 GSV 后端。语音合成与音色设计复用本界面：
 *  - voice  : 文本 + 当前激活整合包参考音频 → 合成
 *  - design : 同上，仅面向"音色设计"标签页（GSV 暂无独立音色设计接口，复用合成）
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { Button, Card, Input, Select, Space, Tag, message as antdMessage } from 'antd';
import {
  PlayCircleOutlined,
  PauseCircleOutlined,
  DownloadOutlined,
} from '@ant-design/icons';
import { generateTts, searchPackages } from '../api/gptSoVits';
import { useModuleConfig } from '../store/configStore';
import { type TtsConfig } from '../store/configSchema';

const { TextArea } = Input;

const LANG_OPTIONS = [
  { value: '中文', label: '中文' },
  { value: '英文', label: '英文' },
  { value: '日文', label: '日文' },
  { value: '粤语', label: '粤语' },
  { value: '韩文', label: '韩文' },
  { value: '中英混合', label: '中英混合' },
];

interface ActivePkg {
  name: string;
  path?: string;
}

export default function GsBasicVoice() {
  const { config, update } = useModuleConfig<TtsConfig>('tts');
  const [text, setText] = useState('');
  const [generating, setGenerating] = useState(false);
  const [audioUrl, setAudioUrl] = useState<string | null>(null);
  const [playing, setPlaying] = useState(false);
  const [activePkg, setActivePkg] = useState<ActivePkg | null>(null);

  const audioRef = useRef<HTMLAudioElement>(null);

  // 读取当前激活整合包（用于参考音频路径）
  useEffect(() => {
    if (config.gsvActivePkg) {
      searchPackages()
        .then((entries) => {
          const found = entries.find((e) => e.name === config.gsvActivePkg);
          if (found) setActivePkg({ name: found.name, path: (found as any).path });
          else setActivePkg({ name: config.gsvActivePkg });
        })
        .catch(() => setActivePkg({ name: config.gsvActivePkg }));
    } else {
      setActivePkg(null);
    }
  }, [config.gsvActivePkg]);

  useEffect(() => {
    const el = audioRef.current;
    if (!el) return;
    const onPlay = () => setPlaying(true);
    const onPause = () => setPlaying(false);
    const onEnded = () => setPlaying(false);
    el.addEventListener('play', onPlay);
    el.addEventListener('pause', onPause);
    el.addEventListener('ended', onEnded);
    return () => {
      el.removeEventListener('play', onPlay);
      el.removeEventListener('pause', onPause);
      el.removeEventListener('ended', onEnded);
    };
  }, []);

  const handleGenerate = useCallback(async () => {
    if (!text.trim()) {
      antdMessage.warning('请输入要合成的文本');
      return;
    }
    if (!config.gsvActivePkg) {
      antdMessage.warning('请先在「选择整合包」中指定参考音色');
      return;
    }
    setGenerating(true);
    setAudioUrl(null);
    try {
      const blob = await generateTts({
        text: text.trim(),
        text_lang: langToGs(config.gsvSynthLang),
        ref_lang: langToGs(config.gsvSynthLang),
        text_split_method: cutMethodToGs(config.gsvCutMethod),
        streaming: config.gsvStreaming,
      });
      const url = URL.createObjectURL(blob);
      setAudioUrl(url);
    } catch (err: any) {
      antdMessage.error(err?.message || '合成失败');
    } finally {
      setGenerating(false);
    }
  }, [text, config.gsvActivePkg, config.gsvSynthLang, config.gsvCutMethod, config.gsvStreaming]);

  const handlePlayPause = useCallback(() => {
    if (!audioRef.current || !audioUrl) return;
    if (playing) audioRef.current.pause();
    else audioRef.current.play();
  }, [playing, audioUrl]);

  const handleDownload = useCallback(() => {
    if (!audioUrl) return;
    const a = document.createElement('a');
    a.href = audioUrl;
    a.download = `gsv-${Date.now()}.wav`;
    a.click();
  }, [audioUrl]);

  return (
    <div className="gsv-tts-subpage">
      <div className="gsv-tts-layout">
        <div className="gsv-tts-main">
          {/* 参考音色提示 */}
          <Card className="gsv-tts-card" size="small" title="参考音色" style={{ marginBottom: 10 }}>
            {activePkg ? (
              <Space>
                <Tag color="green">{activePkg.name}</Tag>
                <span style={{ fontSize: 11, color: 'var(--palm-text-low, #475467)' }}>已作为参考音频参与合成</span>
              </Space>
            ) : (
              <span style={{ fontSize: 12, color: '#e24b4a' }}>尚未选择整合包，请回到上方「选择整合包」指定参考音色</span>
            )}
          </Card>

          {/* 文本输入 */}
          <Card className="gsv-tts-card" size="small" title="合成文本" style={{ marginBottom: 10 }}>
            <TextArea
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder="输入要合成的文本…"
              rows={4}
              className="gsv-tts-textarea"
            />
          </Card>

          {/* 语言选择 */}
          <Card className="gsv-tts-card" size="small" title="合成语种" style={{ marginBottom: 10 }}>
            <Select value={config.gsvSynthLang} onChange={(v) => update({ gsvSynthLang: v })} style={{ width: '100%' }} options={LANG_OPTIONS} />
          </Card>

          {/* 生成按钮 */}
          <div style={{ display: 'flex', gap: 8, marginBottom: 10 }}>
            <Button type="primary" icon={<PlayCircleOutlined />} loading={generating} onClick={handleGenerate}>
              开始合成
            </Button>
          </div>

          {/* 播放器 */}
          {audioUrl && (
            <Card className="gsv-tts-card gsv-tts-player-card" size="small" title="播放">
              <audio ref={audioRef} src={audioUrl} style={{ display: 'none' }} />
              <div className="gsv-tts-player">
                <Button type="text" size="large" icon={playing ? <PauseCircleOutlined /> : <PlayCircleOutlined />} onClick={handlePlayPause} className="gsv-tts-play-btn" />
                <div className="gsv-tts-player-wave">
                  <div className="gsv-tts-wave-bar" style={{ animationPlayState: playing ? 'running' : 'paused' }}>
                    {Array.from({ length: 32 }).map((_, i) => (
                      <span key={i} style={{ animationDelay: `${i * 0.05}s` }} />
                    ))}
                  </div>
                </div>
                <Button type="text" icon={<DownloadOutlined />} onClick={handleDownload} className="gsv-tts-download-btn">
                  下载 WAV
                </Button>
              </div>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}

// ─── 语言/切句映射（前端展示值 → GSV API 值） ───

function langToGs(lang: string): string {
  const map: Record<string, string> = {
    '中文': 'zh',
    '英文': 'en',
    '日文': 'ja',
    '粤语': 'yue',
    '韩文': 'ko',
    '中英混合': 'zh',
  };
  return map[lang] ?? 'zh';
}

function cutMethodToGs(method: string): string {
  const map: Record<string, string> = {
    '不切': 'none',
    '四句一切': '4sentence',
    '50字一切': '50chars',
    '中文句号切': 'zh_period',
    '英文句号切': 'en_period',
    '标点符号切': 'punctuation',
  };
  return map[method] ?? 'none';
}
