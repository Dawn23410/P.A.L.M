/**
 * L0 底座 · 日志（append-only 事件流）
 * ==================================
 * 只追加、不回改历史；作为系统"单一真相源"。
 * 前端"可视化"与后端"审计"消费的是同一份事件流。
 */

const CAP = 2000;
const events = [];
let seq = 0;
const subs = new Set();

export const log = {
  /** 记一条事件（只追加） */
  record(type, data = null) {
    const ev = { seq: ++seq, ts: Date.now(), type, data };
    events.push(ev);
    if (events.length > CAP) events.shift();   // 环形上限（不是回改历史）
    subs.forEach((fn) => { try { fn(ev); } catch (_) { /* 订阅方出错不影响主流程 */ } });
    return ev;
  },
  /** 订阅（用于可视化/审计） */
  on(fn) { subs.add(fn); return () => subs.delete(fn); },
  /** 全量快照 */
  all() { return events.slice(); },
  /** 最近 n 条 */
  recent(n = 50) { return events.slice(-n); },
};
