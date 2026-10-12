/**
 * webui DevServer 守护进程（后台常驻 + 子进程自动重启）
 * 用法：node devserver-daemon.mjs [端口]   （默认 5173）
 *
 * 行为：
 *   - 拉起 core/devserver.js 子进程（WebUI 唯一静态服务入口）
 *   - 子进程异常退出 → 指数退避自动重启（1s 起，上限 10s）
 *   - 收到 SIGINT / SIGTERM → 先停子进程再退出（优雅）
 *   - 心跳日志追加写 devserver-daemon.log
 */
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = __dirname;
const PORT = Number(process.argv[2] || 5173);
const LOG = path.join(ROOT, 'devserver-daemon.log');

const ts = () => new Date().toISOString();
const log = (m) => {
  const line = `[${ts()}] ${m}`;
  try { fs.appendFileSync(LOG, line + '\n'); } catch { /* 日志盘满也不崩守护 */ }
  console.log(line);
};

let child = null;
let delay = 1000;
let stopping = false;

function start() {
  if (stopping) return;
  log(`拉起 devserver (port ${PORT})...`);
  child = spawn(process.execPath, ['--experimental-default-type=module', 'core/devserver.js', String(PORT)], {
    cwd: ROOT,
    stdio: ['ignore', 'pipe', 'pipe'],
    windowsHide: true,
  });
  child.stdout.on('data', (d) => process.stdout.write(`[devserver] ${d}`));
  child.stderr.on('data', (d) => process.stderr.write(`[devserver:err] ${d}`));
  child.on('exit', (code, signal) => {
    if (stopping) return;
    log(`devserver 退出 code=${code} signal=${signal}；${delay}ms 后重启`);
    child = null;
    setTimeout(start, delay);
    delay = Math.min(delay * 2, 10000); // 退避，避免崩溃抖动打满 CPU
  });
}

function stop() {
  stopping = true;
  log('守护进程收到停止信号，退出');
  if (child) child.kill('SIGTERM');
  setTimeout(() => process.exit(0), 800);
}
process.on('SIGINT', stop);
process.on('SIGTERM', stop);

log(`守护进程启动 pid=${process.pid}，监控端口 ${PORT}`);
start();
setInterval(() => log('heartbeat alive'), 30000).unref?.();
