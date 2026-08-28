/**
 * Qwen3-TTS · 语音合成 (CustomVoice)
 *
 * API: POST /custom-voice/generate
 *      GET  /custom-voice/speakers
 *      GET  /custom-voice/languages
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import {
  Button,
  Card,
  Collapse,
  Input,
  InputNumber,
  Select,
  Slider,
  Space,
  Typography,
} from 'antd';
import {
  PlayCircleOutlined,
  PauseCircleOutlined,
  DownloadOutlined,
  SettingOutlined,
} from '@ant-design/icons';
import {
  generateCustomVoice,
  getSpeakers,
  type CustomVoicePayload,
} from '../api/qwenTts';
import { useModuleConfig } from '../store/configStore';
import { type TtsConfig } from '../store/configSchema';

const { TextArea } = Input;
const { Text } = Typography;

const LANGUAGES = [
  { value: 'auto', label: '自动检测' },
  { value: 'chinese', label: '中文' },
  { value: 'english', label: '英文' },
  { value: 'french', label: '法语' },
  { value: 'german', label: '德语' },
  { value: 'italian', label: '意大利语' },
  { value: 'japanese', label: '日语' },
  { value: 'korean', label: '韩语' },
  { value: 'portuguese', label: '葡萄牙语' },
  { value: 'russian', label: '俄语' },
  { value: 'spanish', label: '西班牙语' },
];

export default function TtsCustomVoice() {
  const { config, update } = useModuleConfig<TtsConfig>('tts');
  const [text, setText] = useState('');
  const [speakerList, setSpeakerList] = useState<string[]>([]);
  const [generating, setGenerating] = useState(false);
  const [audioUrl, setAudioUrl] = useState<string | null>(null);
  const [playing, setPlaying] = useState(false);

  const audioRef = useRef<HTMLAudioElement>(null);

  // 加载说话人列表
  useEffect(() => {
    getSpeakers()
      .then((res) => {
        const list = res.speakers ?? [];
        setSpeakerList(list);
        if (list.length > 0 && list[0] !== config.customVoiceSpeaker) {
          update({ customVoiceSpeaker: list[0] });
        }
      })
      .catch(() => {
        setSpeakerList([
          'aiden', 'dylan', 'eric', 'ono_anna',
          'ryan', 'serena', 'sohee', 'uncle_fu', 'vivian',
        ]);
      });
  }, []);

  // 监听播放状态
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
    if (!text.trim()) return;
    setGenerating(true);
    setAudioUrl(null);

    try {
      const payload: CustomVoicePayload = {
        text: text.trim(),
        speaker: config.customVoiceSpeaker,
        language: config.customVoiceLanguage,
        instruct: config.customVoiceInstruct || null,
        non_streaming_mode: true,
      };
      if (config.customVoiceTemperature != null) payload.temperature = config.customVoiceTemperature;
      if (config.customVoiceTopK != null) payload.top_k = config.customVoiceTopK;
      if (config.customVoiceTopP != null) payload.top_p = config.customVoiceTopP;
      if (config.customVoiceMaxNewTokens != null) payload.max_new_tokens = config.customVoiceMaxNewTokens;

      const blob = await generateCustomVoice(payload);
      const url = URL.createObjectURL(blob);
      setAudioUrl(url);
    } catch (err: any) {
      console.error('Generate failed:', err);
    } finally {
      setGenerating(false);
    }
  }, [text, config.customVoiceSpeaker, config.customVoiceLanguage, config.customVoiceInstruct, config.customVoiceTemperature, config.customVoiceTopK, config.customVoiceTopP, config.customVoiceMaxNewTokens]);

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
    a.download = `qwen3-tts-${Date.now()}.wav`;
    a.click();
  }, [audioUrl]);

  return (
    <div className="qwen-tts-subpage">
      <div className="qwen-tts-layout">
        {/* 主区域 */}
        <div className="qwen-tts-main">
          {/* 文本输入 */}
          
          {/* 参数行 */}
          <div className="qwen-tts-param-row">
            <Card className="qwen-tts-card" size="small" title="说话人" style={{ flex: 1 }}>
              <Select
                value={config.customVoiceSpeaker}
                onChange={(v) => update({ customVoiceSpeaker: v })}
                style={{ width: '100%' }}
                options={speakerList.map((s) => ({
                  value: s,
                  label: s.charAt(0).toUpperCase() + s.slice(1),
                }))}
              />
            </Card>

            <Card className="qwen-tts-card" size="small" title="语言" style={{ flex: 1 }}>
              <Select
                value={config.customVoiceLanguage}
                onChange={(v) => update({ customVoiceLanguage: v })}
                style={{ width: '100%' }}
                options={LANGUAGES}
              />
            </Card>
          </div>

          {/* 情感指令 */}
          <Card className="qwen-tts-card" size="small" title="情感/风格指令（可选，仅 1.7B 模型支持）">
            <TextArea
              value={config.customVoiceInstruct}
              onChange={(e) => update({ customVoiceInstruct: e.target.value })}
              placeholder="例如：温柔知性的中年女声，说话从容不迫..."
              rows={2}
              className="qwen-tts-textarea"
            />
          </Card>

          {/* 高级参数 */}
          <Collapse
            ghost
            expandIconPosition="end"
            defaultActiveKey={[]}
            items={[
              {
                key: 'advanced',
                label: (
                  <Space>
                    <SettingOutlined />
                    <span>高级参数</span>
                  </Space>
                ),
                children: (
                  <div className="qwen-tts-advanced">
                    <div className="qwen-tts-param-item">
                      <Text className="qwen-tts-param-label">Temperature</Text>
                      <Space>
                        <Slider
                          min={0}
                          max={2}
                          step={0.05}
                          value={config.customVoiceTemperature}
                          onChange={(v) => update({ customVoiceTemperature: v })}
                          style={{ width: 160 }}
                        />
                        <InputNumber
                          size="small"
                          value={config.customVoiceTemperature}
                          onChange={(v) => update({ customVoiceTemperature: v ?? 1.0 })}
                          min={0}
                          max={2}
                          step={0.05}
                          style={{ width: 70 }}
                        />
                      </Space>
                    </div>
                    <div className="qwen-tts-param-item">
                      <Text className="qwen-tts-param-label">Top-K</Text>
                      <InputNumber
                        size="small"
                        value={config.customVoiceTopK}
                        onChange={(v) => update({ customVoiceTopK: v ?? 50 })}
                        min={1}
                        max={100}
                        style={{ width: 120 }}
                      />
                    </div>
                    <div className="qwen-tts-param-item">
                      <Text className="qwen-tts-param-label">Top-P</Text>
                      <Space>
                        <Slider
                          min={0}
                          max={1}
                          step={0.05}
                          value={config.customVoiceTopP}
                          onChange={(v) => update({ customVoiceTopP: v })}
                          style={{ width: 160 }}
                        />
                        <InputNumber
                          size="small"
                          value={config.customVoiceTopP}
                          onChange={(v) => update({ customVoiceTopP: v ?? 0.9 })}
                          min={0}
                          max={1}
                          step={0.05}
                          style={{ width: 70 }}
                        />
                      </Space>
                    </div>
                    <div className="qwen-tts-param-item">
                      <Text className="qwen-tts-param-label">Max Tokens</Text>
                      <InputNumber
                        size="small"
                        value={config.customVoiceMaxNewTokens}
                        onChange={(v) => update({ customVoiceMaxNewTokens: v ?? 2048 })}
                        min={64}
                        max={8192}
                        step={64}
                        style={{ width: 120 }}
                      />
                    </div>
                  </div>
                ),
              },
            ]}
          />

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
