/**
 * P.A.L.M · Config Store
 * ────────────────────────
 * 统一的模块配置持久化层。
 *
 * 特性：
 *  - zustand 统一状态管理
 *  - 500ms 防抖自动保存到 localStorage
 *  - 深度合并默认值（向后兼容新字段）
 *  - 全量导出 / 导入 JSON（含版本与时间戳）
 *  - 单模块重置 / 全量重置
 *  - useModuleConfig hook（模块页面的标准消费方式）
 *
 * 存储 key：palm.config.v1
 */

import { useCallback } from 'react';
import { create } from 'zustand';
import type { ModuleId } from './configSchema';
import { DEFAULT_CONFIGS } from './configSchema';

// ─── 常量 ───────────────────────────────────────────────────────

const STORAGE_KEY = 'palm.config.v1';
const SAVE_DELAY = 500; // ms

// ─── 工具 ───────────────────────────────────────────────────────

function deepClone<T>(obj: T): T {
  return JSON.parse(JSON.stringify(obj));
}

/** 深度合并：用 defaults 做模板，overrides 覆盖（支持嵌套对象） */
function deepMerge(
  defaults: Record<string, unknown>,
  overrides: Record<string, unknown>,
): Record<string, unknown> {
  const result: Record<string, unknown> = {};
  for (const key of Object.keys(defaults)) {
    const dv = defaults[key];
    const ov = overrides[key];
    if (
      dv !== null &&
      typeof dv === 'object' &&
      !Array.isArray(dv) &&
      ov !== null &&
      typeof ov === 'object' &&
      !Array.isArray(ov)
    ) {
      result[key] = deepMerge(
        dv as Record<string, unknown>,
        ov as Record<string, unknown>,
      );
    } else {
      // 当 overrides 有值时用 overrides，否则保留 default
      result[key] = ov !== undefined ? ov : dv;
    }
  }
  return result;
}

/** 将保存的配置与默认值合并，确保新加的字段也有默认值 */
function mergeWithDefaults(
  saved: Record<string, unknown>,
): Record<string, Record<string, unknown>> {
  const result: Record<string, Record<string, unknown>> = {};
  const ids = Object.keys(DEFAULT_CONFIGS) as ModuleId[];
  for (const id of ids) {
    const savedModule = saved[id] as Record<string, unknown> | undefined;
    result[id] = savedModule
      ? deepMerge(DEFAULT_CONFIGS[id] as Record<string, unknown>, savedModule)
      : deepClone(DEFAULT_CONFIGS[id]);
  }
  return result as Record<string, Record<string, unknown>>;
}

// ─── 持久化读写 ─────────────────────────────────────────────────

function readStorage(): Record<string, Record<string, unknown>> {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw);
      if (parsed && typeof parsed === 'object') {
        return mergeWithDefaults(parsed);
      }
    }
  } catch (e) {
    console.warn('[ConfigStore] Failed to read localStorage, using defaults:', e);
  }
  return deepClone(DEFAULT_CONFIGS) as Record<string, Record<string, unknown>>;
}

function writeStorage(configs: Record<string, Record<string, unknown>>) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(configs));
  } catch (e) {
    console.error('[ConfigStore] Failed to save to localStorage:', e);
  }
}

// ─── 防抖调度 ───────────────────────────────────────────────────

let saveTimer: ReturnType<typeof setTimeout> | null = null;

function scheduleSave() {
  if (saveTimer) clearTimeout(saveTimer);
  saveTimer = setTimeout(() => {
    const { configs } = useConfigStore.getState();
    writeStorage(configs);
    saveTimer = null;
  }, SAVE_DELAY);
}

function flushSave() {
  if (saveTimer) {
    clearTimeout(saveTimer);
    saveTimer = null;
  }
  const { configs } = useConfigStore.getState();
  writeStorage(configs);
}

// ─── Store 类型 ─────────────────────────────────────────────────

export interface ConfigStore {
  /** 所有模块的当前配置 */
  configs: Record<string, Record<string, unknown>>;

  /** 读取某模块配置（泛型，调用方提供类型） */
  getConfig: <T = Record<string, unknown>>(moduleId: ModuleId) => T;

  /** 更新某模块的部分配置 */
  updateConfig: (moduleId: ModuleId, partial: Record<string, unknown>) => void;

  /** 重置某模块到默认值 */
  resetConfig: (moduleId: ModuleId) => void;

  /** 重置所有模块到默认值 */
  resetAll: () => void;

  /** 导出全量配置为 JSON 字符串 */
  exportAll: () => string;

  /**
   * 导入全量配置（从 JSON 字符串）
   * 格式兼容 exportAll 的产出，也兼容纯 configs 对象
   */
  importAll: (json: string) => { success: boolean; error?: string };

  /** 立即持久化（通常无需手动调用，导出/导入会自动触发） */
  persistNow: () => void;
}

// ─── Store ──────────────────────────────────────────────────────

export const useConfigStore = create<ConfigStore>((set, get) => ({
  configs: readStorage(),

  getConfig: (moduleId) => get().configs[moduleId] as never,

  updateConfig: (moduleId, partial) => {
    set((state) => ({
      configs: {
        ...state.configs,
        [moduleId]: { ...(state.configs[moduleId] as object), ...partial } as Record<
          string,
          unknown
        >,
      },
    }));
    scheduleSave();
  },

  resetConfig: (moduleId) => {
    set((state) => ({
      configs: {
        ...state.configs,
        [moduleId]: { ...DEFAULT_CONFIGS[moduleId] },
      },
    }));
    scheduleSave();
  },

  resetAll: () => {
    set({ configs: deepClone(DEFAULT_CONFIGS) as Record<string, Record<string, unknown>> });
    flushSave();
  },

  exportAll: () =>
    JSON.stringify(
      {
        version: 1,
        exportedAt: new Date().toISOString(),
        configs: get().configs,
      },
      null,
      2,
    ),

  importAll: (json) => {
    try {
      const data = JSON.parse(json);
      if (!data || typeof data !== 'object') {
        return { success: false, error: '无效的 JSON 格式' };
      }

      // 兼容 exportAll 的包装格式和纯 configs 对象
      const imported: Record<string, unknown> =
        data.configs && typeof data.configs === 'object' ? data.configs : data;

      // 与默认值合并，确保结构完整
      const merged = mergeWithDefaults(imported);
      set({ configs: merged });
      flushSave();
      return { success: true };
    } catch (e) {
      return {
        success: false,
        error: e instanceof Error ? e.message : '解析失败',
      };
    }
  },

  persistNow: () => flushSave(),
}));

// ─── Hook（模块页面的标准消费方式） ────────────────────────────

/**
 * 为指定模块提供响应式配置 + 更新/重置方法。
 *
 * @example
 * ```tsx
 * const { config, update, reset } = useModuleConfig('wallpaper');
 * // config.scaleMode       → 'fill'
 * // update({ scaleMode: 'fit' })
 * // reset()
 * ```
 */
export function useModuleConfig<T = Record<string, unknown>>(moduleId: ModuleId) {
  const config = useConfigStore((s) => s.configs[moduleId]) as T;
  const updateConfig = useConfigStore((s) => s.updateConfig);
  const resetConfig = useConfigStore((s) => s.resetConfig);

  const update = useCallback(
    (partial: Partial<T>) => updateConfig(moduleId, partial as Record<string, unknown>),
    [moduleId, updateConfig],
  );

  const reset = useCallback(() => resetConfig(moduleId), [moduleId, resetConfig]);

  return { config, update, reset };
}
