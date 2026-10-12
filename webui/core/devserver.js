/**
 * 开发服务器（仅开发期使用，生产环境可删）
 *
 * - 静态托管 webui 目录（ES Module 需要 http 协议，不能 file:// 直开）
 * - 提供 /__hmr 接口：返回 pages/ 下各模块文件的 mtime
 *   前端轮询该接口，发现 mtime 变化即热重载对应模块
 *
 * 启动：node core/devserver.js [端口]
 */
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, '..');
// 端口必须是合法数字；传了非法参数（如 --help）时回退默认值，
// 否则 Number('--x') 得到 NaN，server.listen 会直接抛 RangeError 崩掉。
const argPort = Number(process.argv[2]);
const PORT = Number.isInteger(argPort) && argPort > 0 && argPort < 65536 ? argPort : 5173;
const PAGES_DIR = path.join(ROOT, 'pages');

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.mjs': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.ico': 'image/x-icon',
  '.woff2': 'font/woff2',
  '.woff': 'font/woff',
  '.ttf': 'font/ttf',
};

/** 收集 pages/ 下所有模块文件 + index.html 的修改时间 */
function collectMtimes() {
  const out = {};
  let files = [];
  try {
    files = fs.readdirSync(PAGES_DIR);
  } catch {
    return out;
  }
  for (const f of files) {
    if (!/\.(js|mjs|css)$/.test(f)) continue;
    try {
      const full = path.join(PAGES_DIR, f);
      out[path.basename(f, path.extname(f))] = fs.statSync(full).mtimeMs;
    } catch {
      /* 忽略读取失败 */
    }
  }
  // index.html 变更无法按模块热重载（外壳本身在变），通知客户端整页刷新
  try {
    out['index.html'] = fs.statSync(path.join(ROOT, 'index.html')).mtimeMs;
  } catch {
    /* 忽略读取失败 */
  }
  return out;
}

const server = http.createServer((req, res) => {
  const url = new URL(req.url, `http://${req.headers.host}`);

  // ---- HMR 接口 ----
  if (url.pathname === '/__hmr') {
    res.writeHead(200, {
      'Content-Type': 'application/json; charset=utf-8',
      'Cache-Control': 'no-store',
    });
    res.end(JSON.stringify({ modules: collectMtimes(), ts: Date.now() }));
    return;
  }

  // ---- 静态文件 ----
  let rel = decodeURIComponent(url.pathname);
  if (rel === '/' || rel === '') rel = '/index.html';

  // 防目录穿越
  const target = path.join(ROOT, rel);
  if (!target.startsWith(ROOT)) {
    res.writeHead(403).end('Forbidden');
    return;
  }

  fs.readFile(target, (err, buf) => {
    if (err) {
      res.writeHead(404, { 'Content-Type': 'text/plain; charset=utf-8' });
      res.end('404 Not Found: ' + rel);
      return;
    }
    const ext = path.extname(target).toLowerCase();
    res.writeHead(200, {
      'Content-Type': MIME[ext] || 'application/octet-stream',
      'Cache-Control': 'no-store',
    });
    res.end(buf);
  });
});

server.listen(PORT, () => {
  console.log(`\n  WebUI dev server 已启动`);
  console.log(`  http://localhost:${PORT}\n`);
  console.log(`  热重载监控目录: pages/`);
  console.log(`  改完模块文件保存，页面会自动重载该模块。\n`);
});
