/**
 * GPT-SoVITS · 语音克隆
 *
 * 高级参数配置：语速、句间停顿、Top-K等
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { Button, Card, Slider } from 'antd';
import {
  PlayCircleOutlined,
  PauseCircleOutlined,
  DownloadOutlined,
} from '@ant-design/icons';
import { useModuleConfig } from '../store/configStore';
import { type TtsConfig } from '../store/configSchema';

export default function GsVoiceClone() {
  const { config, update } = useModuleConfig<TtsConfig>('tts');
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
    a.download = `gsv-clone-${Date.now()}.wav`;
    a.click();
  }, [audioUrl]);

  return (
    <div className="qwen-tts-subpage">
      <div className="qwen-tts-layout">
        <div className="qwen-tts-main" style={{ display: 'flex', flexDirection: 'column', gap: 0 }}>
          {/* 高级设置（常驻） */}
          <div className="qwen-tts-advanced" style={{ padding: '6px 0 2px' }}>
            <div className="qwen-tts-param-row" style={{ alignItems: 'center' }}>
              <span className="qwen-tts-param-label">语速</span>
              <Slider value={config.gsCloneSpeed} onChange={(v) => update({ gsCloneSpeed: v })} min={0.6} max={1.65} step={0.05} style={{ flex: 1, margin: '0 8px' }} />
              <span className="qwen-tts-param-value">{config.gsCloneSpeed.toFixed(2)}</span>
            </div>
            <div className="qwen-tts-param-row" style={{ alignItems: 'center' }}>
              <span className="qwen-tts-param-label">句间停顿</span>
              <Slider value={config.gsClonePauseSec} onChange={(v) => update({ gsClonePauseSec: v })} min={0.1} max={0.5} step={0.05} style={{ flex: 1, margin: '0 8px' }} />
              <span className="qwen-tts-param-value">{config.gsClonePauseSec.toFixed(2)}s</span>
            </div>
            <div className="qwen-tts-param-row" style={{ alignItems: 'center' }}>
              <span className="qwen-tts-param-label">Top-K</span>
              <Slider value={config.gsCloneTopK} onChange={(v) => update({ gsCloneTopK: v })} min={1} max={100} step={1} style={{ flex: 1, margin: '0 8px' }} />
              <span className="qwen-tts-param-value">{config.gsCloneTopK}</span>
            </div>
            <div className="qwen-tts-param-row" style={{ alignItems: 'center' }}>
              <span className="qwen-tts-param-label">Top-P</span>
              <Slider value={config.gsCloneTopP} onChange={(v) => update({ gsCloneTopP: v })} min={0} max={1} step={0.05} style={{ flex: 1, margin: '0 8px' }} />
              <span className="qwen-tts-param-value">{config.gsCloneTopP.toFixed(2)}</span>
            </div>
            <div className="qwen-tts-param-row" style={{ alignItems: 'center' }}>
              <span className="qwen-tts-param-label">Temperature</span>
              <Slider value={config.gsCloneTemperature} onChange={(v) => update({ gsCloneTemperature: v })} min={0} max={1} step={0.05} style={{ flex: 1, margin: '0 8px' }} />
              <span className="qwen-tts-param-value">{config.gsCloneTemperature.toFixed(2)}</span>
            </div>
          </div>

          {/* 音频播放器 */}
          {audioUrl && (
            <Card className="qwen-tts-card qwen-tts-player-card" size="small" title="播放" style={{ marginTop: 10 }}>
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
