/**
 * 结构化事件日志（唯一真实数据源）
 * =================================
 * 概况页的数据包不再来自「模拟」或「临时事件总线」，而是来自这里 ——
 * 一条条真实发生、带完整上下文的记录。
 *
 * 记录结构（schema）：
 *   {
 *     id,          // 自增序号，用于消费端去重（实时 + 回放只消费一次）
 *     ts,          // 墙钟时间戳（整毫秒）
 *     tick,        // 单调时间刻（整毫秒，页面加载起算）—— 时间刻最小单位 1ms
 *                  // 所有时间戳与运行时长都量化到 TICK_MS=1ms，不允许亚毫秒
 *     level,       // info | warn | error
 *     source,      // 起点节点 id（cpu / fe / rnd）—— 决定数据包从哪个球出发
 *     target,      // 终点节点 id —— 与 source 共同决定走哪条管道、哪个方向
 *     type,        // 业务类型：control / render / state / event / heartbeat / error / warn
 *     payload      // 可选附加信息（如文本长度、错误信息）
 *   }
 *
 * 设计要点：
 *   - 追加写 + 环形缓冲（上限 MAX），不会无限增长
 *   - 写即广播（subscribe），消费方（概况页）实时拿记录
 *   - recent(withinMs) 供模块挂载时回放「最近的真实记录」
 *   - error / warn 同时镜像到 console，保留开发期可观测性
 *   - 以后接外部真实日志（文件 / API / WebSocket）只需往这里灌同样结构的记录，
 *     可视化层不用改
 */

const MAX = 500;

/**
 * 时间刻（tick）最小单位 = 1ms。
 * 所有时间戳与运行时长都必须量化到这个粒度（整毫秒），不允许出现亚毫秒。
 */
const TICK_MS = 1;

/** 把毫秒量化到时间刻粒度（整毫秒） */
const quantize = (ms) => Math.round(ms / TICK_MS) * TICK_MS;

/** 单调递增时间刻：页面加载起算，整毫秒 */
const tickNow = () => quantize(performance.now());

/** 本地时间 HH:MM:SS.mmm（毫秒保留 3 位，即时间刻粒度） */
function localTime(ts) {
  const d = new Date(ts);
  const p = (n, w = 2) => String(n).padStart(w, '0');
  return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}.${p(d.getMilliseconds(), 3)}`;
}

/** 全部记录（按时间顺序） */
const records = [];
/** 订阅者 */
const listeners = new Set();
/** 自增 id */
let seq = 0;

/**
 * 写一条真实记录。
 * @param {{level?:string,source?:string,target?:string,type:string,payload?:*}} o
 */
function write(o) {
  const rec = {
    id: ++seq,
    ts: quantize(Date.now()),   // 墙钟时间戳（整毫秒，时间刻粒度）
    tick: tickNow(),            // 单调时间刻（整毫秒，页面加载起算）
    level: o.level || 'info',
    source: o.source || null,
    target: o.target || null,
    type: o.type,
    payload: o.payload != null ? o.payload : null,
  };
  records.push(rec);
  if (records.length > MAX) records.shift();

  // 打印到 Web 控制台：所有级别都输出，便于实时观察真实日志流。
  // 格式：[log #id] tick=<单调时间刻>ms <本地 HH:MM:SS.mmm> <source>→<target> <type> [payload]
  const head = `[log #${rec.id}] tick=${rec.tick}ms ${localTime(rec.ts)} ${rec.source || '-'}→${rec.target || '-'} ${rec.type}`;
  const args = rec.payload != null ? [head, rec.payload] : [head];
  if (rec.level === 'error') console.error(...args);
  else if (rec.level === 'warn') console.warn(...args);
  else console.log(...args);

  listeners.forEach((fn) => { try { fn(rec); } catch (e) { console.error('[log] listener:', e); } });
  return rec;
}

export const log = {
  /** 时间刻最小单位（ms） */
  TICK_MS,
  /** 当前单调时间刻（整毫秒） */
  tick: tickNow,
  /** 把毫秒量化到时间刻粒度 */
  quantize,

  write,

  /** 订阅新记录，返回退订函数 */
  on(fn) {
    listeners.add(fn);
    return () => listeners.delete(fn);
  },

  /** 取最近 withinMs 毫秒内的真实记录 */
  recent(withinMs = 5000) {
    const cut = Date.now() - withinMs;
    return records.filter((r) => r.ts >= cut);
  },

  /** 全部记录（快照） */
  all() { return records.slice(); },

  /** 清空（一般不需要） */
  clear() { records.length = 0; },

  // 便捷写入
  info(o) { return write({ ...o, level: 'info' }); },
  warn(o) { return write({ ...o, level: 'warn' }); },
  error(o) { return write({ ...o, level: 'error' }); },
};

// 暴露到控制台，便于联调：window.__log.info({source:'fe',target:'cpu',type:'control'})
if (typeof window !== 'undefined') window.__log = log;
