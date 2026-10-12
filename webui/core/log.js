/**
 * 统一事件日志（兼容层）
 * ========================
 * 底层框架的 append-only 事件流（framework/log.js）是「单一真相源」。
 * 本文件把它适配成项目原有日志接口（log.info / write / on / recent / all），
 * 字段映射到外壳与概况页消费的结构，使旧调用方零改动即接入内核底座。
 *
 * 写即落-frame 底座；读即把底座记录映射回旧 schema。前后端可视化、
 * 审计消费的是同一份事件流。
 */
import { log as fLog } from '../framework/log.js';

/** 底座记录 -> 旧 schema（id / ts / tick / level / source / target / type / payload） */
const mapRec = (e) => ({
  id: e.seq,
  ts: e.ts,
  tick: e.ts,
  level: (e.data && e.data.level) || 'info',
  source: (e.data && e.data.source) != null ? e.data.source : null,
  target: (e.data && e.data.target) != null ? e.data.target : null,
  type: e.type,
  payload: (e.data && e.data.payload) != null ? e.data.payload : null,
});

function write(o) {
  return fLog.record(o.type, {
    level: o.level || 'info',
    source: o.source != null ? o.source : null,
    target: o.target != null ? o.target : null,
    payload: o.payload != null ? o.payload : null,
  });
}

export const log = {
  TICK_MS: 1,
  tick: () => Date.now(),
  quantize: (ms) => ms,

  write,
  on(fn) { return fLog.on((e) => { try { fn(mapRec(e)); } catch (_) { /* 忽略订阅方错误 */ } }); },
  recent(withinMs = 5000) {
    const cut = Date.now() - withinMs;
    return fLog.all().filter((e) => e.ts >= cut).map(mapRec);
  },
  all() { return fLog.all().map(mapRec); },
  clear() { fLog.all().length = 0; },

  info(o) { return write(o); },
  warn(o) { return write({ ...o, level: 'warn' }); },
  error(o) { return write({ ...o, level: 'error' }); },
};

if (typeof window !== 'undefined') window.__log = log;
