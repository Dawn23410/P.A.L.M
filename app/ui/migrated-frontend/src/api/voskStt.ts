/**
 * VOSK 本地离线 STT 客户端
 * ────────────────────────────
 * 通过 WebSocket 把浏览器麦克风采集到的音频（转为 16kHz 单声道 16-bit PCM）
 * 实时上传到本地 VOSK 服务（speech/vosk/server.py，默认 ws://localhost:2700）做离线识别。
 *
 * 与浏览器原生 Web Speech API 的区别：
 * - 完全离线，不依赖浏览器识别服务、不联网、不上传云端。
 * - 使用项目自带的 vosk-model-small-cn-0.22 中文模型。
 *
 * 若本地 VOSK 服务未启动 / 连不上，调用方应回退到 Web Speech API（见 Chat.tsx）。
 */

export type VoskStatus = 'idle' | 'connecting' | 'listening' | 'stopped' | 'error';

export interface VoskSttCallbacks {
  /** 实时中间结果（未定稿） */
  onPartial?: (text: string) => void;
  /** 一句话的最终识别结果 */
  onFinal?: (fullText: string) => void;
  /** 状态变化 */
  onStatus?: (status: VoskStatus) => void;
  /** 错误（含无法连接服务、麦克风权限被拒） */
  onError?: (msg: string) => void;
}

/** 简单线性重采样器：把任意采样率转成目标采样率（单声道 float） */
class LinearResampler {
  private ratio: number;
  private last: number | null = null;
  constructor(private fromRate: number, private toRate: number) {
    this.ratio = toRate / fromRate;
  }
  process(input: Float32Array): Float32Array {
    const outLen = Math.ceil(input.length * this.ratio);
    const out = new Float32Array(outLen);
    for (let i = 0; i < outLen; i++) {
      const srcPos = i / this.ratio;
      const i0 = Math.floor(srcPos);
      const i1 = Math.min(i0 + 1, input.length - 1);
      const frac = srcPos - i0;
      const a = input[i0] ?? 0;
      const b = input[i1] ?? 0;
      out[i] = a + (b - a) * frac;
    }
    return out;
  }
}

export class VoskStt {
  private ws: WebSocket | null = null;
  private audioCtx: AudioContext | null = null;
  private stream: MediaStream | null = null;
  private processor: ScriptProcessorNode | null = null;
  private source: MediaStreamAudioSourceNode | null = null;
  private resampler: LinearResampler | null = null;
  private finalSegments: string[] = [];
  private readonly url: string;
  private readonly cb: VoskSttCallbacks;
  private connectTimer: number | null = null;

  /** 连接超时（毫秒）：超时即视为服务不可用，触发 onError 供调用方回退 */
  static readonly CONNECT_TIMEOUT = 2500;

  constructor(url: string, cb: VoskSttCallbacks) {
    this.url = url;
    this.cb = cb;
  }

  /** 是否已连接并正在聆听 */
  get active(): boolean {
    return this.ws?.readyState === WebSocket.OPEN && !!this.processor;
  }

  async start(): Promise<void> {
    this.finalSegments = [];
    this.cb.onStatus?.('connecting');

    // 1) 先建立 WebSocket；连不上则快速失败
    try {
      this.ws = new WebSocket(this.url);
    } catch (e: any) {
      this.cb.onError?.(`无法连接本地 VOSK 服务（${this.url}）`);
      this.cb.onStatus?.('error');
      return;
    }
    this.ws.binaryType = 'arraybuffer';

    const connectPromise = new Promise<void>((resolve, reject) => {
      if (!this.ws) return reject(new Error('ws null'));
      this.ws.onopen = () => resolve();
      this.ws.onerror = () => reject(new Error('ws error'));
      this.connectTimer = window.setTimeout(
        () => reject(new Error('timeout')),
        VoskStt.CONNECT_TIMEOUT,
      );
    });

    try {
      await connectPromise;
    } catch {
      if (this.connectTimer) window.clearTimeout(this.connectTimer);
      this.connectTimer = null;
      try {
        this.ws.close();
      } catch {
        /* ignore */
      }
      this.ws = null;
      this.cb.onError?.(`无法连接本地 VOSK 服务（${this.url}），已回退浏览器语音识别`);
      this.cb.onStatus?.('error');
      return;
    }
    if (this.connectTimer) window.clearTimeout(this.connectTimer);
    this.connectTimer = null;

    // 通知服务端采样率
    try {
      this.ws.send(JSON.stringify({ sample_rate: 16000 }));
    } catch {
      /* ignore */
    }

    // 2) 采集麦克风并转码
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
    } catch (e: any) {
      this.cb.onError?.('麦克风权限被拒绝或设备不可用');
      this.stop();
      return;
    }

    const Ctx: typeof AudioContext =
      window.AudioContext || (window as any).webkitAudioContext;
    this.audioCtx = new Ctx({ sampleRate: 16000 });
    const ctxRate = this.audioCtx.sampleRate; // 浏览器可能不精确给 16000
    this.resampler = ctxRate === 16000 ? null : new LinearResampler(ctxRate, 16000);

    this.source = this.audioCtx.createMediaStreamSource(this.stream);
    this.processor = this.audioCtx.createScriptProcessor(4096, 1, 1);

    this.processor.onaudioprocess = (e: AudioProcessingEvent) => {
      const samples = e.inputBuffer.getChannelData(0); // 已单声道
      const out = this.resampler ? this.resampler.process(samples) : samples;
      const buf = new ArrayBuffer(out.length * 2);
      const view = new DataView(buf);
      for (let i = 0; i < out.length; i++) {
        let s = out[i];
        if (s > 1) s = 1;
        else if (s < -1) s = -1;
        view.setInt16(i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true);
      }
      if (this.ws && this.ws.readyState === WebSocket.OPEN) {
        this.ws.send(buf);
      }
    };

    this.source.connect(this.processor);
    this.processor.connect(this.audioCtx.destination);

    // 3) 接收识别结果
    this.ws.onmessage = (ev: MessageEvent) => {
      let data: any;
      try {
        data = JSON.parse(ev.data as string);
      } catch {
        return;
      }
      if (typeof data.partial === 'string') {
        this.cb.onPartial?.(data.partial);
      } else if (typeof data.text === 'string' && data.text.trim()) {
        this.finalSegments.push(data.text.trim());
        this.cb.onFinal?.(this.finalSegments.join(' '));
      }
    };
    this.ws.onerror = () => {
      /* 由 close 兜底 */
    };
    this.ws.onclose = () => {
      /* 由 stop()/外部处理 */
    };

    this.cb.onStatus?.('listening');
  }

  /** 停止采集并关闭连接 */
  stop(): void {
    if (this.connectTimer) {
      window.clearTimeout(this.connectTimer);
      this.connectTimer = null;
    }
    try {
      this.processor?.disconnect();
    } catch {
      /* ignore */
    }
    try {
      this.source?.disconnect();
    } catch {
      /* ignore */
    }
    try {
      this.stream?.getTracks().forEach((t) => t.stop());
    } catch {
      /* ignore */
    }
    try {
      this.audioCtx?.close();
    } catch {
      /* ignore */
    }
    if (this.ws) {
      try {
        this.ws.close();
      } catch {
        /* ignore */
      }
    }
    this.processor = null;
    this.source = null;
    this.audioCtx = null;
    this.stream = null;
    this.ws = null;
    if (this.cb.onStatus) {
      // 仅当不是错误态时标记为 stopped
      this.cb.onStatus('stopped');
    }
  }

  /** 已累积的最终文本 */
  getText(): string {
    return this.finalSegments.join(' ');
  }
}

/** 解析 VOSK WebSocket 地址（可被 VITE_VOSK_WS_URL 覆盖） */
export function getVoskWsUrl(): string {
  const env = (import.meta as any).env?.VITE_VOSK_WS_URL as string | undefined;
  if (env) return env;
  // 用 127.0.0.1 强制 IPv4 回环，避免 localhost 解析到 ::1(IPv6) 导致连不上
  return `ws://127.0.0.1:2700`;
}
