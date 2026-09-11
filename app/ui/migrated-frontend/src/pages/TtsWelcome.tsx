/**
 * P.A.L.M · 语音播报（TTS）欢迎页
 *
 * 侧边栏「语音播报」入口页；在此选择具体引擎进入配置界面。
 */

import { useNavigate } from 'react-router-dom';
import { SoundOutlined, CustomerServiceOutlined } from '@ant-design/icons';
import { Card } from 'antd';

export default function TtsWelcome() {
  const navigate = useNavigate();

  const engines = [
    {
      key: '/tts/gpt-sovits',
      title: 'GPT-SoVITS',
      desc: '本地语音克隆与语音合成引擎，支持离线运行。',
      icon: <SoundOutlined style={{ fontSize: 18, color: 'var(--palm-cyan)' }} />,
      tag: '本地 · 离线',
    },
    {
      key: '/tts/cosyvoice',
      title: 'CosyVoice',
      desc: '阿里自定义音色引擎，需先启动服务（默认 7860 端口）。',
      icon: <CustomerServiceOutlined style={{ fontSize: 18, color: 'var(--palm-cyan)' }} />,
      tag: '自定义音色',
    },
  ];

  return (
    <div>
      <div className="palm-page__title-row palm-page__title-row--compact">
        <div>
          <div className="palm-page__subtitle">语音合成引擎</div>
          <h2 className="palm-page__title">TTS</h2>
        </div>
      </div>

      <div style={{ maxWidth: 760, padding: '12px 4px' }}>
        <p style={{ color: 'var(--palm-text-mid, #475467)', fontSize: 13, lineHeight: 1.7, marginBottom: 20 }}>
          欢迎使用 P.A.L.M 语音合成控制台。请从下方选择引擎，进入对应的配置界面。
        </p>

        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))',
            gap: 14,
          }}
        >
          {engines.map((e) => (
            <Card
              key={e.key}
              hoverable
              onClick={() => navigate(e.key)}
              style={{ background: 'var(--palm-surface)', borderColor: 'var(--palm-line)', borderRadius: 6 }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 10 }}>
                <span
                  style={{
                    width: 34,
                    height: 34,
                    borderRadius: 8,
                    display: 'inline-flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    background: 'rgba(0, 229, 255, 0.08)',
                    border: '1px solid var(--palm-line)',
                    flexShrink: 0,
                  }}
                >
                  {e.icon}
                </span>
                <span style={{ fontSize: 14, fontWeight: 600, color: 'var(--palm-text)' }}>{e.title}</span>
                <span
                  style={{
                    marginLeft: 'auto',
                    fontSize: 10,
                    color: 'var(--palm-text-low, #64748b)',
                    border: '1px solid var(--palm-line)',
                    padding: '1px 8px',
                    borderRadius: 999,
                    whiteSpace: 'nowrap',
                  }}
                >
                  {e.tag}
                </span>
              </div>
              <div style={{ fontSize: 12, color: 'var(--palm-text-low, #64748b)', lineHeight: 1.6 }}>{e.desc}</div>
            </Card>
          ))}
        </div>
      </div>
    </div>
  );
}
