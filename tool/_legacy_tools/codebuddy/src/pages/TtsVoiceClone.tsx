/**
 * Qwen3-TTS · 语音克隆 (VoiceClone)
 *
 * Qwen3-TTS 语音克隆界面 — 参考音频 + 克隆模式 + 参数配置
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { Button, Card, Input, Select, Radio, Tag, Upload } from 'antd';
import {
  PlayCircleOutlined,
  PauseCircleOutlined,
  DownloadOutlined,
  UploadOutlined,
  InboxOutlined,
} from '@ant-design/icons';
import { useModuleConfig } from '../store/configStore';
import { type TtsConfig } from '../store/configSchema';

const { TextArea } = Input;
const { Dragger } = Upload;

const LANGUAGES = [
  { value: 'auto', label: '自动检测' },
  { value: 'chinese', label: '中文' },
  { value: 'english', label: '英文' },
  { value: 'japanese', label: '日语' },
  { value: 'korean', label: '韩语' },
];

export default function TtsVoiceClone() {
  const { config, update } = useModuleConfig<TtsConfig>('tts');
  const [refAudioPath, setRefAudioPath] = useState<string>('');
  const [refText, setRefText] = useState('');

  const [audioUrl] = useState<string | null>(null);
  const [playing, setPlaying] = useState(false);

  const audioRef = useRef<HTMLAudioElement>(null);

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

  const handleFileSelect = useCallback((file: File) => {
    setRefAudioPath(`local:${file.name}`);
    return false;
  }, []);

  const handlePlayPause = useCallback(() => {
    if (!audioRef.current || !audioUrl) return;
    if (playing) {
      audioRef.current.pause();
    } else {
      audioRef.current.play();
    }
  }, [playing, audioUrl]);

  const handleDownload = useCallback(() => {
    if (!audioUrl) return;
    const a = document.createElement('a');
    a.href = audioUrl;
    a.download = `qwen3-tts-clone-${Date.now()}.wav`;
    a.click();
  }, [audioUrl]);

  return (
    <div className="qwen-tts-subpage">
      <div className="qwen-tts-layout">
        <div className="qwen-tts-main">
          {/* 参考音频上传 */}
          <Card className="qwen-tts-card" size="small" title="参考音频">
            <Dragger
              accept="audio/*"
              showUploadList={false}
              beforeUpload={handleFileSelect}
            >
              <p className="ant-upload-drag-icon"><InboxOutlined /></p>
              <p className="ant-upload-text">点击或拖拽上传参考音频</p>
              <p className="ant-upload-hint">支持 WAV、MP3、FLAC 等格式</p>
            </Dragger>
            {refAudioPath && (
              <div style={{ marginTop: 8 }}>
                <Tag icon={<UploadOutlined />} color="processing">{refAudioPath}</Tag>
              </div>
            )}
          </Card>

          {/* 克隆模式 */}
          <Card className="qwen-tts-card" size="small" title="克隆模式">
            <Radio.Group
              value={config.voiceCloneMode}
              onChange={(e) => update({ voiceCloneMode: e.target.value })}
              optionType="button"
              buttonStyle="solid"
            >
              <Radio.Button value="x-vector">x-vector（仅音色）</Radio.Button>
              <Radio.Button value="icl">ICL（音色 + 语气/节奏）</Radio.Button>
            </Radio.Group>
          </Card>

          {/* 参考文本（ICL 模式） */}
          {config.voiceCloneMode === 'icl' && (
            <Card className="qwen-tts-card" size="small" title="参考文本（ICL 模式必需）">
              <TextArea
                value={refText}
                onChange={(e) => setRefText(e.target.value)}
                placeholder="输入参考音频对应的文本内容..."
                rows={3}
                className="qwen-tts-textarea"
              />
            </Card>
          )}

          {/* 语言 */}
          <Card className="qwen-tts-card" size="small" title="语言">
            <Select value={config.voiceCloneLanguage} onChange={(v) => update({ voiceCloneLanguage: v })} style={{ width: '100%' }} options={LANGUAGES} />
          </Card>

          {/* 音频播放器 */}
          {audioUrl && (
            <Card className="qwen-tts-card qwen-tts-player-card" size="small" title="播放" style={{ marginTop: 8 }}>
              <audio ref={audioRef} src={audioUrl} style={{ display: 'none' }} />
              <div className="qwen-tts-player">
                <Button type="text" size="large" icon={playing ? <PauseCircleOutlined /> : <PlayCircleOutlined />} onClick={handlePlayPause} className="qwen-tts-play-btn" />
                <div className="qwen-tts-player-wave">
                  <div className="qwen-tts-wave-bar" style={{ animationPlayState: playing ? 'running' : 'paused' }}>
                    {Array.from({ length: 32 }).map((_, i) => <span key={i} style={{ animationDelay: `${i * 0.05}s` }} />)}
                  </div>
                </div>
                <Button type="text" icon={<DownloadOutlined />} onClick={handleDownload} className="qwen-tts-download-btn">下载 WAV</Button>
              </div>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}
