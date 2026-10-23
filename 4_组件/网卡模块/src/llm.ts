// llm.ts — LLM 内核砖块（智谱 GLM，OpenAI 兼容协议）
// 注册链路：LifecycleController.register → manifest 进注册表 → 能力进容器 → Fiber 管生命周期
// 出网链路：LLM 砖块绝不直接 fetch —— 一律经 net 门面（fail-closed），网卡砖注入执行器
// 安全：API key 只从环境变量/.env 读取，绝不硬编码、绝不进版本库
// 参考：P.A.L.M 原版 adapters/model/provider.py（流式 + 模型路由）；智谱开放平台 v4 API（OpenAI 兼容）

import { readFileSync, existsSync } from 'node:fs';
import { join } from 'node:path';
import { net } from './net.ts';

// ── 配置（从 .env / 环境变量加载） ──
export interface LlmConfig {
  apiKey: string;
  baseUrl: string;
  model: string;
}

/** 加载智谱配置：环境变量优先，其次 palm-core/.env */
export function loadLlmConfig(): LlmConfig {
  const envFile = join(process.cwd(), '.env');
  const fileVars: Record<string, string> = {};
  if (existsSync(envFile)) {
    for (const line of readFileSync(envFile, 'utf-8').split('\n')) {
      const t = line.trim();
      if (!t || t.startsWith('#')) continue;
      const i = t.indexOf('=');
      if (i > 0) fileVars[t.slice(0, i).trim()] = t.slice(i + 1).trim();
    }
  }
  const env = (k: string) => process.env[k] ?? fileVars[k];
  const apiKey = env('ZHIPU_API_KEY');
  if (!apiKey) throw new Error('缺少 ZHIPU_API_KEY（环境变量或 .env）');
  return {
    apiKey,
    baseUrl: env('ZHIPU_BASE_URL') ?? 'https://open.bigmodel.cn/api/paas/v4',
    model: env('ZHIPU_MODEL') ?? 'glm-4-flash',
  };
}

// ── OpenAI 兼容消息与响应 ──
export interface ChatMessage {
  role: 'system' | 'user' | 'assistant';
  content: string;
}

export interface ChatOptions {
  model?: string;
  temperature?: number;
  maxTokens?: number;
}

export interface ChatResult {
  content: string;
  model: string;
  usage: { promptTokens: number; completionTokens: number; totalTokens: number } | null;
}

// ── 砖块实现 ──
export class LlmBrick {
  private readonly cfg: LlmConfig;

  constructor(cfg?: LlmConfig) {
    this.cfg = cfg ?? loadLlmConfig();
  }

  get name(): string { return 'llm'; }
  get model(): string { return this.cfg.model; }

  /**
   * 对话补全（非流式）。经网卡门面出网（唯一出网出口，fail-closed）。
   * @param messages 消息数组
   */
  async chat(messages: ChatMessage[], opts: ChatOptions = {}): Promise<ChatResult> {
    const body = {
      model: opts.model ?? this.cfg.model,
      messages,
      stream: false,
      ...(opts.temperature !== undefined ? { temperature: opts.temperature } : {}),
      ...(opts.maxTokens !== undefined ? { max_tokens: opts.maxTokens } : {}),
    };
    const resp = await net.request('POST', `${this.cfg.baseUrl}/chat/completions`, {
      headers: {
        'Authorization': `Bearer ${this.cfg.apiKey}`,
        'Content-Type': 'application/json',
      },
      body,
      timeoutMs: 60_000,
    }) as { choices?: { message?: { content?: string } }[]; model?: string; usage?: Record<string, number> };


    const content = resp?.choices?.[0]?.message?.content ?? '';
    const u = resp?.usage;
    return {
      content,
      model: resp?.model ?? body.model,
      usage: u ? { promptTokens: u.prompt_tokens ?? 0, completionTokens: u.completion_tokens ?? 0, totalTokens: u.total_tokens ?? 0 } : null,
    };
  }
}