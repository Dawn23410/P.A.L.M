/**
 * 架构清单 —— 概况页可视化球的数据源 + 导航项探测
 * =================================================
 * 概况页内容**固定**（不绑定模块注册表）：下面 OVERVIEW_NODES 就是概况要显示的全部球。
 * 每个球的状态由探测决定：
 *   detected  脚本文件是否存在（fetch HEAD）
 *   beat()    能否把模块**拉起来**（动态 import；页面模块还要导出 mount）
 * 显示规则：
 *   检测到 + 心跳通   → 实心球
 *   检测到 + 心跳不通 → 半透明虚线
 *   未检测到          → 半透明虚线（内容仍显示，不再隐藏）
 *
 * 解耦保证：只用 HEAD 探测、用 import 做心跳；失败被吞掉，删文件不影响外壳与其他模块。
 */

import { list } from './loader.js';

/**
 * 概况页固定内容（页面模块 + 前端基础设施）。
 * 改概况显示什么，只改这里 —— 与 core/modules.js 的注册表无关。
 */
export const OVERVIEW_NODES = [
  { id: 'home',     title: '主页',   path: '/pages/home.js',           r: 10, kind: 'page' },
  { id: 'overview', title: '概况',   path: '/pages/overview.js',       r: 13, kind: 'page' },
  { id: 'chat',     title: '聊天',   path: '/pages/chat.js',           r: 13, kind: 'page' },
  { id: 'settings', title: '设置',   path: '/pages/settings.js',       r: 11, kind: 'page' },
  { id: 'renderer', title: '渲染器', path: '/core/renderers/index.js', r: 14, kind: 'biz' },
  { id: 'log',      title: '日志',   path: '/core/log.js',             r: 12, kind: 'biz' },
  { id: 'theme',    title: '主题',   path: '/core/theme/index.js',     r: 11, kind: 'biz' },
  { id: 'router',   title: '路由',   path: '/core/router.js',          r: 11, kind: 'biz' },
  { id: 'loader',   title: '加载器', path: '/core/loader.js',          r: 10, kind: 'biz' },
];

/* ---------- 探测 ---------- */

/** 探测结果缓存：同一路径只请求一次 */
const probeCache = new Map();

/** 「检测到」：脚本文件是否存在（一次 HEAD） */
export function probe(path) {
  if (!probeCache.has(path)) {
    probeCache.set(
      path,
      fetch(path, { method: 'HEAD', cache: 'no-store' })
        .then((res) => res.ok)
        .catch(() => false)
    );
  }
  return probeCache.get(path);
}

/** 心跳（页面模块）：能 import 且导出可用的 mount/default → 通 */
export async function heartbeat(url) {
  try {
    const m = await import(/* @vite-ignore */ url);
    return !!(m && (m.default || m.mount));
  } catch {
    return false;
  }
}

/** 心跳（基础设施）：能 import 即算「在」 */
async function importOk(url) {
  try { await import(/* @vite-ignore */ url); return true; } catch { return false; }
}

/** 导航用：注册表里的页面模块 + 存在性探测（未检测到则不显示导航项） */
export async function detectPages() {
  return Promise.all(
    list().map(async (m) => ({
      id: m.id,
      title: m.title,
      detected: await probe(`/pages/${m.id}.js`),
    }))
  );
}

/**
 * 组装概况模型：**固定的** OVERVIEW_NODES，每个带 detected 与 beat()。
 * @returns {{nodes:Array}}
 */
export async function buildModel() {
  const nodes = await Promise.all(
    OVERVIEW_NODES.map(async (n) => ({
      ...n,
      detected: await probe(n.path),
      beat: n.kind === 'page' ? () => heartbeat(n.path) : () => importOk(n.path),
    }))
  );
  return { nodes };
}
