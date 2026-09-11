/**
 * LLM 聊天客户端
 * ───────────────────────────────────────────────────────────
 * 默认走「织语层 · 本地 Mock」：由 src/api/weaveLayer.ts 纯前端产出语料风格模块，
 * 零后端依赖、离线可用，织语层始终生效（不再出现「mock 绕过织语层」的异常）。
 *
 * 仅当织语模式切到 bridge 且后端可达（:7799 织语服务 / :7788 心智魔方桥接）时，
 * 才走完整六面流水线（含 MockLLM / 真实 LLM、好感度、内心独白）。接真实 LLM 时
 * 在桥接侧把 MENTALCORE_MODE 置 live 即可，前端无需改动。
 *
 * 兼容导出 getMentalCoreUrl / pingMentalCore（mentalcore.ts / MentalCore.tsx 仍在用）。
 */
import { isForceMock } from './apiConfig';
import {
  getMentalCoreUrl,
  pingMentalCore,
  getWeaveMode,
  produceWeave,
  produceWeaveBridge,
  fetchWeaveModuleFromService,
} from './weaveLayer';
import { makeMockReply } from './mockLlm';

export { getMentalCoreUrl, pingMentalCore };

export interface ChatMessage {
  role: 'user' | 'assistant' | 'system';
  content: string;
}

export interface ReplyMeta {
  /** weave-mock=本地织语层 Mock；mentalcore=桥接完整流水线；local-mock=兜底（不应再出现） */
  source: 'weave-mock' | 'mentalcore';
  degraded?: boolean;
  persona?: string;
  emotion?: string;
  affinityDelta?: number;
  innerNote?: string;
  /** 织语层产出的语料风格模块（mock 模式也会注入，便于透明展示） */
  styleModule?: string;
}

export interface MentalReply {
  content: string;
  meta: ReplyMeta;
}

/** 本地 Mock 回复：优先使用原装语料/模板，仅保留 GPT-SoVITS 说明作为特殊分支。 */
export function mockReply(prompt: string): string {
  const p = prompt.trim();
  if (/gpt[-\s]?sovits|gsv|语音合成/i.test(p)) {
    return [
      '（歪了歪头）<内心>他在问语音合成的事，先给说明。</内心>',
      '### GPT-SoVITS 语音合成',
      '',
      '当前已接入以下能力：',
      '',
      '| 能力 | 端点 | 说明 |',
      '| --- | --- | --- |',
      '| 合成 | `/tts` | 文本转语音 |',
      '| 复刻 | `/voice-clone` | 音色克隆 |',
      '| 状态 | `/status` | 服务健康 |',
      '',
      '在「语音播报」页选择模型 `gpt-sovits` 后即可使用。',
    ].join('\n');
  }
  return makeMockReply(p);
}

const delay = (ms: number) => new Promise((r) => setTimeout(r, ms));

/**
 * 发送一条用户消息，返回助手回复与回传元数据。
 * 默认本地 Mock 织语层；bridge 模式下尝试完整流水线，失败降级本地 Mock。
 */
export async function sendChat(_history: ChatMessage[], prompt: string): Promise<MentalReply> {
  // bridge 模式：优先完整六面流水线（织语服务 :7799 或 心智魔方桥接 :7788）
  if (!isForceMock() && getWeaveMode() === 'bridge') {
    const bridged = await produceWeaveBridge(prompt);
    if (bridged) {
      const fields = (bridged.fields || {}) as Record<string, any>;
      return {
        content: bridged.content,
        meta: {
          source: bridged.mode === 'bridge' ? 'mentalcore' : 'weave-mock',
          persona: bridged.persona,
          emotion: bridged.emotion,
          affinityDelta: bridged.affinityDelta,
          innerNote: fields.inner_note,
        },
      };
    }
  }
  // 默认：本地 Mock 织语层。优先调用原装 :7799 服务获取风格模块，离线/失败则前端兜底。
  await delay(420);
  const serviceWeave = await fetchWeaveModuleFromService(prompt);
  const weave = serviceWeave ?? produceWeave();
  return {
    content: mockReply(prompt),
    meta: {
      source: 'weave-mock',
      persona: weave.persona,
      styleModule: weave.content,
    },
  };
}
