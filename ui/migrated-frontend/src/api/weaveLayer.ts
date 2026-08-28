/**
 * 织语层（WeaveLayer）独立客户端 —— 从聊天逻辑中拆出。
 * ───────────────────────────────────────────────────────────
 * 织语层只负责产出「语料风格模块」注入 LLM（口吻 / 格式约束 / 内心独白规范），
 * 与完整心智魔方（六面 + MockLLM + 记忆 + 存储）解耦。
 *
 * 模式（默认本地 Mock）：
 *  - 'mock'（默认）：纯前端计算，零后端依赖。镜像 mentalcore/weave_layer.py
 *    的 WeaveFace.produce_module，使用内置默认角色卡（梦瑶），离线即可产出风格模块。
 *  - 'bridge'：转发到独立织语层服务（默认 :7799）或心智魔方桥接（默认 :7788），
 *    走完整六面流水线（含真实/ MockLLM 回复 + 好感度 / 内心独白）。
 *
 * 默认即本地 Mock：无需启动任何后端，聊天页开箱即用且织语层始终生效。
 */
import { isForceMock } from './apiConfig';

export type WeaveMode = 'mock' | 'bridge';

export interface WeaveModule {
  source: 'weave';
  /** 织语层产出的「语料风格模块」文本 */
  content: string;
  persona: string;
  mode: WeaveMode;
}

/** bridge 模式返回的扩展结果（含六面流水线回传的元数据）。 */
export interface WeaveBridgeResult extends WeaveModule {
  fields?: Record<string, unknown>;
  emotion?: string;
  affinityDelta?: number;
  manifest?: unknown;
}

export interface WeaveStatus {
  mode: WeaveMode;
  /** 是否有可桥接的后端（7799 织语层服务 或 7788 心智魔方桥接）在线 */
  online: boolean;
  persona: string;
  /** 实际生效的织语来源：local-mock / weave-service / mentalcore */
  source: 'local-mock' | 'weave-service' | 'mentalcore' | 'offline';
}

/** 内置默认角色卡（与 mentalcore/mentalcore/persona_card.py::default_persona 保持一致） */
const DEFAULT_PERSONA = {
  name: '梦瑶',
  formatSpec: '[动作](神态)<内心>正文',
  tone: '温柔轻快',
};

/** 初始模式：VITE_WEAVE_MODE 可覆盖，默认 'mock'（本地 Mock） */
let weaveMode: WeaveMode =
  (import.meta as any).env?.VITE_WEAVE_MODE === 'bridge' ? 'bridge' : 'mock';

export function getWeaveMode(): WeaveMode {
  return weaveMode;
}

export function setWeaveMode(mode: WeaveMode): void {
  weaveMode = mode;
}

/** 独立织语层服务地址（可被 VITE_WEAVE_URL 覆盖），默认 :7799 */
export function getWeaveUrl(): string {
  const env = (import.meta as any).env?.VITE_WEAVE_URL as string | undefined;
  if (env) return env.replace(/\/$/, '');
  return 'http://127.0.0.1:7799';
}

/** 心智魔方桥接地址（可被 VITE_MENTALCORE_URL 覆盖），默认 :7788 */
export function getMentalCoreUrl(): string {
  const env = (import.meta as any).env?.VITE_MENTALCORE_URL as string | undefined;
  if (env) return env.replace(/\/$/, '');
  return 'http://127.0.0.1:7788';
}

/**
 * 本地 Mock 风格模块：与 mentalcore/mentalcore/faces/weave.py 中
 * WeaveFace.produce_module 的产出逐字对齐，保证离线态与桥接态行为一致。
 */
export function buildStyleModule(persona = DEFAULT_PERSONA): string {
  return (
    `【表达风格】按格式「${persona.formatSpec}」组织语言，` +
    `保持${persona.name}的口吻，与示例对话的语感一致。` +
    `<内心>是本句未说出口的真实想法；正文须用自然口语把这份想法` +
    `对用户说出来，与<内心>同一主题、情绪一致，不得逐字复读内心` +
    `或另起无关话题。`
  );
}

/** 默认本地 Mock：纯前端计算织语层风格模块（零网络）。 */
export function produceWeave(): WeaveModule {
  return {
    source: 'weave',
    content: buildStyleModule(),
    persona: DEFAULT_PERSONA.name,
    mode: 'mock',
  };
}

/** 探测是否有可桥接的后端（7799 优先，7788 兜底）。 */
export async function pingWeave(): Promise<{
  online: boolean;
  source: 'weave-service' | 'mentalcore' | 'offline';
}> {
  if (isForceMock()) return { online: false, source: 'offline' };
  // 1) 独立织语层服务（默认 :7799）
  try {
    const res = await fetch(`${getWeaveUrl()}/api/weave/health`, { method: 'GET' });
    if (res.ok) {
      const d = await res.json();
      if (d.ok) return { online: true, source: 'weave-service' };
    }
  } catch {
    /* 织语层服务未起 */
  }
  // 2) 心智魔方桥接（默认 :7788）
  try {
    const res = await fetch(`${getMentalCoreUrl()}/api/health`, { method: 'GET' });
    if (res.ok) {
      const d = await res.json();
      if (d.ok) return { online: true, source: 'mentalcore' };
    }
  } catch {
    /* 心智魔方桥接未起 */
  }
  return { online: false, source: 'offline' };
}

/** 聚合当前织语层状态（供 UI 状态条使用）。 */
export async function getWeaveStatus(): Promise<WeaveStatus> {
  const { online, source } = await pingWeave();
  const effectiveSource: WeaveStatus['source'] =
    weaveMode === 'mock' ? 'local-mock' : source === 'offline' ? 'offline' : source;
  return {
    mode: weaveMode,
    online,
    persona: DEFAULT_PERSONA.name,
    source: effectiveSource,
  };
}

/**
 * bridge 模式发往后端：优先独立织语层服务（:7799，其再决定 mock/bridge），
 * 失败回退直接心智魔方桥接（:7788）。返回完整流水线结果（含元数据）或 null。
 */
export async function produceWeaveBridge(text: string): Promise<WeaveBridgeResult | null> {
  if (isForceMock()) return null;
  // 1) 独立织语层服务
  try {
    const res = await fetch(`${getWeaveUrl()}/api/weave`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text }),
    });
    if (res.ok) {
      const d = await res.json();
      if (d.ok && d.content != null) {
        return {
          source: 'weave',
          content: d.content as string,
          persona: (d.persona as string) ?? DEFAULT_PERSONA.name,
          mode: (d.mode as WeaveMode) ?? 'bridge',
          fields: d.fields,
          emotion: d.emotion,
          affinityDelta:
            typeof d.affinity_delta === 'number' ? d.affinity_delta : undefined,
          manifest: d.manifest,
        };
      }
    }
  } catch {
    /* 织语层服务未起 */
  }
  // 2) 心智魔方桥接（完整六面流水线）
  try {
    const res = await fetch(`${getMentalCoreUrl()}/api/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text }),
    });
    if (res.ok) {
      const d = await res.json();
      if (d.ok && d.body != null) {
        return {
          source: 'weave',
          content: d.body as string,
          persona: (d.persona as string) ?? DEFAULT_PERSONA.name,
          mode: 'bridge',
          fields: d.fields,
          emotion: d.emotion,
          affinityDelta:
            typeof d.affinity_delta === 'number' ? d.affinity_delta : undefined,
          manifest: d.manifest,
        };
      }
    }
  } catch {
    /* 桥接未起 */
  }
  return null;
}

/**
 * 从原装织语层服务（:7799）获取风格模块。
 * 仅当服务在线且自身运行在 mock 模式时才返回，避免误拿 bridge 转发结果。
 */
export async function fetchWeaveModuleFromService(text: string): Promise<WeaveModule | null> {
  if (isForceMock()) return null;
  try {
    const health = await fetch(`${getWeaveUrl()}/api/weave/health`, { method: 'GET' });
    if (!health.ok) return null;
    const hd = await health.json();
    if (!hd.ok || hd.mode !== 'mock') return null;

    const res = await fetch(`${getWeaveUrl()}/api/weave`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text }),
    });
    if (!res.ok) return null;
    const d = await res.json();
    if (!d.ok || d.content == null) return null;
    return {
      source: 'weave',
      content: d.content as string,
      persona: (d.persona as string) ?? DEFAULT_PERSONA.name,
      mode: 'mock',
    };
  } catch {
    return null;
  }
}

/** 探测心智魔方桥接（:7788）是否在线（供「心智魔方」页使用）。 */
export async function pingMentalCore(): Promise<{
  online: boolean;
  mode?: string;
  persona?: string;
}> {
  try {
    const res = await fetch(`${getMentalCoreUrl()}/api/health`, { method: 'GET' });
    if (res.ok) {
      const d = await res.json();
      if (d.ok) return { online: true, mode: d.mode, persona: d.persona };
    }
  } catch {
    /* 桥接不可用 */
  }
  return { online: false };
}
