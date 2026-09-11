import { useEffect, useMemo, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeHighlight from 'rehype-highlight';
import { SendOutlined, UserOutlined, RobotOutlined, AudioOutlined, AudioMutedOutlined } from '@ant-design/icons';
import { message } from 'antd';
import { useThemeStore } from '../store/themeStore';
import { sendChat } from '../api/chat';
import type { ReplyMeta } from '../api/chat';
import { getWeaveStatus, setWeaveMode } from '../api/weaveLayer';
import type { WeaveStatus } from '../api/weaveLayer';
import { VoskStt, getVoskWsUrl } from '../api/voskStt';
import 'highlight.js/styles/github-dark.css';

type Role = 'user' | 'assistant';

interface Message {
  id: string;
  role: Role;
  content: string;
  pending?: boolean;
  meta?: ReplyMeta;
}

// Web Speech API 在不同浏览器下有前缀，统一类型别名
type SpeechRecognition = any;
type SpeechRecognitionEvent = any;

const SEED: Message[] = [
  {
    id: 'seed-1',
    role: 'assistant',
    content:
      '你好，我是 **P.A.L.M** 助手。\n\n我可以回答关于控制台配置、语音合成（GPT-SoVITS）等问题，并支持 **Markdown** 渲染：\n\n- 列表项一\n- 列表项二\n\n```ts\nfunction greet(name: string) {\n  return `Hello, ${name}`;\n}\n```',
  },
];

// 聊天应答由 src/api/chat.ts 的 sendChat() 提供（默认 mock，可切真实 LLM）。

function uid() {
  return `m-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
}

export default function Chat() {
  const [messages, setMessages] = useState<Message[]>(SEED);
  const [input, setInput] = useState('');
  const [busy, setBusy] = useState(false);
  const [listening, setListening] = useState(false);
  const [sttStatus, setSttStatus] = useState<'idle' | 'starting' | 'listening' | 'stopping'>('idle');
  const recognitionRef = useRef<SpeechRecognition | null>(null);
  const listenTimerRef = useRef<number | null>(null);
  const lastInterimRef = useRef('');
  const sttSupported = useMemo(
    () => !!(window as any).SpeechRecognition || !!(window as any).webkitSpeechRecognition,
    [],
  );
  const resolved = useThemeStore((s) => s.resolved);
  const [weave, setWeave] = useState<WeaveStatus>({
    mode: 'mock',
    online: false,
    persona: '梦瑶',
    source: 'local-mock',
  });
  useEffect(() => {
    getWeaveStatus().then(setWeave);
  }, []);

  const switchWeaveMode = (mode: 'mock' | 'bridge') => {
    if (mode === weave.mode) return;
    setWeaveMode(mode);
    getWeaveStatus().then(setWeave);
  };
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = listRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages]);

  // 组件卸载时强制终止语音识别，避免状态泄漏
  useEffect(() => {
    return () => {
      if (listenTimerRef.current) window.clearTimeout(listenTimerRef.current);
      try {
        recognitionRef.current?.abort();
      } catch {
        // ignore
      }
      try {
        voskRef.current?.stop();
      } catch {
        // ignore
      }
    };
  }, []);

  const send = async (overrideText?: string) => {
    const text = (overrideText ?? input).trim();
    if (!text || busy) return;
    const userMsg: Message = { id: uid(), role: 'user', content: text };
    const botMsg: Message = { id: uid(), role: 'assistant', content: '', pending: true };
    setMessages((m) => [...m, userMsg, botMsg]);
    setInput('');
    setBusy(true);
    try {
      const reply = await sendChat(messages, text);
      setMessages((m) =>
        m.map((msg) =>
          msg.id === botMsg.id
            ? { ...msg, content: reply.content, meta: reply.meta, pending: false }
            : msg,
        ),
      );
    } catch (e: any) {
      setMessages((m) =>
        m.map((msg) =>
          msg.id === botMsg.id
            ? { ...msg, content: '⚠️ ' + (e?.message || '请求失败'), pending: false }
            : msg,
        ),
      );
    } finally {
      setBusy(false);
    }
  };

  // 用 ref 在语音识别事件回调里读取最新状态/输入，避免闭包过期
  const sttStatusRef = useRef(sttStatus);
  const inputRef = useRef(input);
  // 当前使用的 STT 引擎：vosk（本地离线）/ webspeech（浏览器兜底）/ null
  const sttEngineRef = useRef<'vosk' | 'webspeech' | null>(null);
  const voskRef = useRef<VoskStt | null>(null);
  useEffect(() => {
    sttStatusRef.current = sttStatus;
  }, [sttStatus]);
  useEffect(() => {
    inputRef.current = input;
  }, [input]);

  // 浏览器原生语音识别（Web Speech API）——前端直连 STT，无需后端。
  const resetListening = (next = false) => {
    if (listenTimerRef.current) {
      window.clearTimeout(listenTimerRef.current);
      listenTimerRef.current = null;
    }
    recognitionRef.current = null;
    lastInterimRef.current = '';
    setSttStatus('idle');
    setListening(next);
  };

  const stopListening = () => {
    if (!recognitionRef.current) {
      resetListening(false);
      return;
    }
    setSttStatus('stopping');
    try {
      recognitionRef.current.stop();
    } catch {
      try {
        recognitionRef.current.abort();
      } catch {
        resetListening(false);
      }
    }
    // 保险：若 3 秒内仍未触发 onend/onerror，强制重置状态
    listenTimerRef.current = window.setTimeout(() => {
      resetListening(false);
    }, 3000);
  };

  const startListening = () => {
    const SR = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    if (!SR) {
      message.error('当前浏览器不支持 Web Speech API，无法使用语音输入');
      return;
    }

    // 若已有实例在运行，先安全停止
    if (recognitionRef.current) {
      stopListening();
      return;
    }

    setSttStatus('starting');
    sttEngineRef.current = 'webspeech';
    const rec: SpeechRecognition = new SR();
    rec.lang = 'zh-CN';
    rec.interimResults = true;
    rec.continuous = false;
    rec.maxAlternatives = 1;

    rec.onstart = () => {
      setSttStatus('listening');
      setListening(true);
    };

    rec.onresult = (e: SpeechRecognitionEvent) => {
      let interim = '';
      let final = '';
      for (let i = 0; i < e.results.length; i++) {
        const t = e.results[i][0].transcript;
        if (e.results[i].isFinal) {
          final += t;
        } else {
          interim += t;
        }
      }

      setInput((prev) => {
        // 去掉上一次的 interim 片段，避免重复追加
        const base = prev.endsWith(lastInterimRef.current)
          ? prev.slice(0, -lastInterimRef.current.length).trim()
          : prev.trim();
        const live = final || interim;
        lastInterimRef.current = live;
        const next = base ? `${base} ${live}` : live;
        inputRef.current = next; // 同步 ref，确保 onend 能读到最新值
        return next;
      });
    };

    rec.onerror = (e: any) => {
      const err = e.error as string;
      if (err === 'not-allowed') {
        message.error('麦克风权限被拒绝，请在浏览器设置中允许麦克风访问');
      } else if (err === 'no-speech') {
        message.warning('未检测到语音，请重试');
      } else if (err === 'audio-capture') {
        message.error('未检测到麦克风设备');
      } else if (err === 'network') {
        message.error('语音识别网络错误，请检查网络');
      } else if (err !== 'aborted') {
        message.error(`语音识别失败：${err || '未知错误'}`);
      }
      resetListening(false);
    };

    rec.onend = () => {
      // 识别自然结束，若输入框有内容且用户未手动停止，可自动发送
      const finalText = inputRef.current.trim();
      const shouldAutoSend = sttStatusRef.current !== 'stopping' && finalText;
      resetListening(false);
      if (shouldAutoSend) {
        send(finalText);
      }
    };

    recognitionRef.current = rec;
    try {
      rec.start();
    } catch (e: any) {
      message.error(`无法启动语音识别：${e?.message || '未知错误'}`);
      resetListening(false);
    }
  };

  // ── 本地 VOSK 离线 STT（优先）─────────────────────────────
  const stopVosk = () => {
    voskRef.current?.stop();
    voskRef.current = null;
  };

  const startVosk = () => {
    setSttStatus('starting');
    sttEngineRef.current = 'vosk';
    const vosk = new VoskStt(getVoskWsUrl(), {
      onStatus: (s) => {
        if (s === 'listening') {
          setListening(true);
        } else if (s === 'stopped' || s === 'idle' || s === 'error') {
          setListening(false);
          setSttStatus('idle');
        }
      },
      onPartial: (t) => {
        setInput(() => {
          const committed = voskRef.current?.getText() ?? '';
          const next = committed ? `${committed} ${t}`.trim() : t;
          inputRef.current = next;
          return next;
        });
      },
      onFinal: (full) => {
        inputRef.current = full;
        setInput(full);
      },
      onError: (msg) => {
        // VOSK 不可用 → 自动回退到浏览器 Web Speech API
        message.warning(`${msg}（已回退到浏览器语音识别）`);
        stopVosk();
        sttEngineRef.current = null;
        setListening(false);
        setSttStatus('idle');
        startListening();
      },
    });
    voskRef.current = vosk;
    vosk.start();
  };

  // ── 统一开关 ───────────────────────────────────────────────
  const stopAll = () => {
    if (sttEngineRef.current === 'vosk') stopVosk();
    else if (sttEngineRef.current === 'webspeech') stopListening();
    sttEngineRef.current = null;
    setListening(false);
    setSttStatus('idle');
  };

  const toggleListen = () => {
    if (listening || sttEngineRef.current) {
      stopAll();
      return;
    }
    // 优先本地 VOSK 离线识别；连不上时由 onError 自动回退浏览器 Web Speech
    startVosk();
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter') {
      // Shift + Enter：保留默认行为，换行
      if (e.shiftKey) return;
      // 输入法组合中（中文候选未确认）不发送，避免误触
      if (e.nativeEvent.isComposing) return;
      e.preventDefault();
      send();
    }
  };

  return (
    <div className="palm-chat">
      <div className="palm-chat__head">
        <span className="palm-chat__title">聊天</span>
        <span
          className={[
            'palm-chat__status',
            weave.mode === 'mock'
              ? 'palm-chat__status--mock'
              : weave.online
                ? 'palm-chat__status--on'
                : 'palm-chat__status--mock',
          ].join(' ')}
        >
          {weave.mode === 'mock'
            ? '织语层 · 本地 Mock（默认）'
            : weave.online
              ? `织语层 · 桥接在线（${weave.persona}）`
              : '织语层 · 桥接未连接（已降级本地 Mock）'}
        </span>
        <div className="palm-segmented palm-chat__mode" role="group" aria-label="织语层模式">
          <button
            type="button"
            className={weave.mode === 'mock' ? 'active' : ''}
            onClick={() => switchWeaveMode('mock')}
          >
            本地 Mock
          </button>
          <button
            type="button"
            className={weave.mode === 'bridge' ? 'active' : ''}
            onClick={() => switchWeaveMode('bridge')}
          >
            桥接
          </button>
        </div>
        <span className="palm-chat__hint">Markdown 已启用 · 回车发送 · Shift + 回车换行</span>
      </div>

      <div className="palm-chat__list" ref={listRef}>
        {messages.map((msg) => (
          <div key={msg.id} className={`palm-chat__row palm-chat__row--${msg.role}`}>
            <div className="palm-chat__avatar">
              {msg.role === 'user' ? <UserOutlined /> : <RobotOutlined />}
            </div>
            <div className="palm-chat__bubble">
              {msg.pending ? (
                <span className="palm-chat__typing">思考中…</span>
              ) : (
                <div className={`palm-md palm-md--${resolved}`}>
                  <ReactMarkdown
                    remarkPlugins={[remarkGfm]}
                    rehypePlugins={[rehypeHighlight]}
                  >
                    {msg.content}
                  </ReactMarkdown>
                  {msg.role === 'assistant' && msg.meta && (
                    <div className="palm-chat__meta">
                      {msg.meta.styleModule ? (
                        <span className="palm-chat__meta-style" title={msg.meta.styleModule}>
                          织语风格模块已注入
                        </span>
                      ) : null}
                      {msg.meta.source === 'weave-mock' && <span>· 本地 Mock（织语层生效）</span>}
                      {msg.meta.source === 'mentalcore' && msg.meta.persona && (
                        <span>· {msg.meta.persona}</span>
                      )}
                      {msg.meta.innerNote && <span> · {msg.meta.innerNote}</span>}
                      {typeof msg.meta.affinityDelta === 'number' && (
                        <span>
                          {' · 好感度 '}
                          {msg.meta.affinityDelta >= 0 ? '+' : ''}
                          {msg.meta.affinityDelta}
                        </span>
                      )}
                      {msg.meta.emotion && <span> · {msg.meta.emotion}</span>}
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        ))}
      </div>

      <div className="palm-chat__input">
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder={
            listening
              ? sttEngineRef.current === 'vosk'
                ? '正在聆听…（本地离线 VOSK 识别）'
                : '正在聆听… 说完后自动识别'
              : '输入消息… 支持 Markdown（或点麦克风语音输入）'
          }
          rows={3}
          disabled={sttStatus === 'starting'}
        />
        <button
          type="button"
          className={`palm-chat__mic${listening ? ' palm-chat__mic--on' : ''}`}
          onClick={toggleListen}
          disabled={sttStatus === 'starting'}
          title={
            listening
              ? sttEngineRef.current === 'vosk'
                ? '停止聆听（本地离线 VOSK）'
                : '停止聆听'
              : sttStatus === 'starting'
                ? '启动中…'
                : '语音输入（本地 VOSK 离线 / 浏览器兜底）'
          }
        >
          {listening ? <AudioOutlined /> : <AudioMutedOutlined />}
        </button>
        <button
          type="button"
          className="palm-chat__send"
          onClick={() => send()}
          disabled={busy || !input.trim()}
        >
          <SendOutlined />
          <span>发送</span>
        </button>
      </div>
      {listening && sttEngineRef.current === 'vosk' && (
        <div className="palm-chat__stt-hint">本地离线识别 · VOSK (中文)</div>
      )}
    </div>
  );
}
