/**
 * P.A.L.M · CosyView
 * CosyVoice（阿里自定义音色引擎）Web UI 内嵌视图。
 * 直接加载 CosyVoice 自带的 Gradio webui（speech/cosyvoice/webui.py），
 * 默认地址 http://127.0.0.1:7860，可用 VITE_COSYVOICE_BASE 覆盖。
 */
import { useEffect, useState } from 'react';

const COSY_BASE = import.meta.env.VITE_COSYVOICE_BASE || 'http://127.0.0.1:7860';

export default function CosyView() {
  const [status, setStatus] = useState<'loading' | 'ok' | 'down'>('loading');

  useEffect(() => {
    let alive = true;
    const ctrl = new AbortController();
    fetch(COSY_BASE, { method: 'GET', signal: ctrl.signal })
      .then((r) => { if (alive) setStatus(r.ok || r.status === 405 ? 'ok' : 'down'); })
      .catch(() => { if (alive) setStatus('down'); });
    return () => { alive = false; ctrl.abort(); };
  }, []);

  return (
    <div className="cosy-view">
      <div className="cosy-view__bar">
        <span className="cosy-view__title">CosyVoice · 自然语言控制（跨语种合成）</span>
        <span className={`cosy-view__status cosy-view__status--${status}`}>
          {status === 'loading' ? '连接中…' : status === 'ok' ? '已连接' : '未连接'}
        </span>
        <div style={{ flex: 1 }} />
        <a className="cosy-view__link" href={COSY_BASE} target="_blank" rel="noreferrer">新标签页打开 ↗</a>
      </div>
      <div className="cosy-view__frame-wrap">
        {status === 'down' ? (
          <div className="cosy-view__hint">
            <p>未检测到 CosyVoice 服务。</p>
            <p>请先启动：<code>python speech/cosyvoice/webui.py --port 7860</code></p>
            <p>启动后刷新本页即可加载控制台。</p>
          </div>
        ) : (
          <iframe className="cosy-view__frame" src={COSY_BASE} title="CosyVoice Web UI" />
        )}
      </div>
    </div>
  );
}
