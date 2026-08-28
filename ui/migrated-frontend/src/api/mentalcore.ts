/**
 * 心智魔方（MentalCore / Boss 大脑）可视化客户端
 * ──────────────────────────
 * 仅读取 Boss 侧已完整实现并可运行的部分：
 *  - 六面（人格 / 情感好感度 / 织语 / 律动 / 记忆）实时状态
 *  - guardrail 护栏档位配置（执行引擎 Worker 源码在本仓库缺失，仅展示配置）
 *  - 意图路由判定（IntentRouter 为纯函数，可独立展示 Boss/Worker 双链路由逻辑）
 *
 * 注意：Worker 执行引擎源码缺失，本客户端不发起任何任务执行调用。
 */
import { getMentalCoreUrl } from './chat';

export interface FaceInfo {
  name: string;
  label: string;
  description: string;
  state: Record<string, unknown>;
}

export interface GuardrailInfo {
  profile: string;
  rules_yaml: string;
  emotion_via_llm: boolean;
  mode: string;
  crypto_enabled: boolean;
  tiers: string[];
  note: string;
}

export interface RouteResult {
  intent: string;
  task_goal: string;
  intervention_action: string;
  redirect_instruction: string;
  confidence: number;
  note: string;
}

const base = () => getMentalCoreUrl();

export async function getFaces(): Promise<FaceInfo[]> {
  const res = await fetch(`${base()}/api/faces`);
  if (!res.ok) throw new Error(`faces 请求失败 (${res.status})`);
  const d = await res.json();
  return d.faces || [];
}

export async function getGuardrail(): Promise<GuardrailInfo> {
  const res = await fetch(`${base()}/api/guardrail`);
  if (!res.ok) throw new Error(`guardrail 请求失败 (${res.status})`);
  return res.json();
}

export async function routeIntent(text: string): Promise<RouteResult> {
  const res = await fetch(`${base()}/api/route?text=${encodeURIComponent(text)}`);
  if (!res.ok) throw new Error(`route 请求失败 (${res.status})`);
  return res.json();
}

export const INTENT_LABELS: Record<string, string> = {
  chat: '闲聊 / 直接回复',
  task: '任务（启动 Worker 执行）',
  intervention: '干预（取消/暂停/恢复/重定向）',
  query: '查询（Worker 进展）',
};
