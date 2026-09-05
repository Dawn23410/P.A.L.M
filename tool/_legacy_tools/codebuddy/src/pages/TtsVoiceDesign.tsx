/**
 * Qwen3-TTS · 音色设计 (VoiceDesign)
 *
 * API: POST /voice-design/generate
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { Button, Card, Input, Select } from 'antd';
import {
  PlayCircleOutlined,
  PauseCircleOutlined,
  DownloadOutlined,
} from '@ant-design/icons';
import { generateVoiceDesign } from '../api/qwenTts';
import { useModuleConfig } from '../store/configStore';
import { type TtsConfig } from '../store/configSchema';

const { TextArea } = Input;

const LANGUAGES = [
  { value: 'auto', label: '自动检测' },
  { value: 'chinese', label: '中文' },
  { value: 'english', label: '英文' },
  { value: 'japanese', label: '日语' },
  { value: 'korean', label: '韩语' },
  { value: 'french', label: '法语' },
  { value: 'spanish', label: '西班牙语' },
];

export default function TtsVoiceDesign() {
  const { config, update } = useModuleConfig<TtsConfig>('tts');
  const [text, setText] = useState('');
  const [generating, setGenerating] = useState(false);
  const [audioUrl, setAudioUrl] = useState<string | null>(null);
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

  const handleGenerate = useCallback(async () => {
    if (!text.trim() || !config.voiceDesignInstruct.trim()) return;
    setGenerating(true);
    setAudioUrl(null);

    try {
      const blob = await generateVoiceDesign({
        text: text.trim(),
        instruct: config.voiceDesignInstruct.trim(),
        language: config.voiceDesignLanguage,
      });
      const url = URL.createObjectURL(blob);
      setAudioUrl(url);
    } catch (err: any) {
      console.error('Voice design generate failed:', err);
    } finally {
      setGenerating(false);
    }
  }, [text, config.voiceDesignInstruct, config.voiceDesignLanguage]);

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
    a.download = `qwen3-tts-voicedesign-${Date.now()}.wav`;
    a.click();
  }, [audioUrl]);

  return (
    <div className="qwen-tts-subpage">
      <div className="qwen-tts-layout">
        {/* 主区域 */}
        <div className="qwen-tts-main">
          
          {/* 语言选择 */}
          <Card className="qwen-tts-card" size="small" title="语言">
            <Select
              value={config.voiceDesignLanguage}
              onChange={(v) => update({ voiceDesignLanguage: v })}
              style={{ width: '100%' }}
              options={LANGUAGES}
            />
          </Card>

          {/* 音色描述 */}
          <Card className="qwen-tts-card" size="small" title="音色描述">
            <TextArea
              value={config.voiceDesignInstruct}
              onChange={(e) => update({ voiceDesignInstruct: e.target.value })}
              placeholder="用文字描述您想要的音色特征..."
              rows={4}
              className="qwen-tts-textarea"
            />
          </Card>

          {/* 音频播放器 */}
          {audioUrl && (
            <Card className="qwen-tts-card qwen-tts-player-card" size="small" title="播放">
              <audio ref={audioRef} src={audioUrl} style={{ display: 'none' }} />
              <div className="qwen-tts-player">
                <Button
                  type="text"
                  size="large"
                  icon={playing ? <PauseCircleOutlined /> : <PlayCircleOutlined />}
                  onClick={handlePlayPause}
                  className="qwen-tts-play-btn"
                />
                <div className="qwen-tts-player-wave">
                  <div className="qwen-tts-wave-bar" style={{ animationPlayState: playing ? 'running' : 'paused' }}>
                    {Array.from({ length: 32 }).map((_, i) => (
                      <span key={i} style={{ animationDelay: `${i * 0.05}s` }} />
                    ))}
                  </div>
                </div>
                <Button
                  type="text"
                  icon={<DownloadOutlined />}
                  onClick={handleDownload}
                  className="qwen-tts-download-btn"
                >
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
