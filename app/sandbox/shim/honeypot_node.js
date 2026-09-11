// 诱饵蜜罐 — Node.js 拦截 shim（经 NODE_OPTIONS=--require 注入沙箱子进程）。
// 仅当 HONEYPOT_ACTIVE=1 时激活。等价实现 Python shim 的四策略。
'use strict';
const fs = require('fs');
const os = require('os');

if (process.env.HONEYPOT_ACTIVE !== '1') return;

const KILL = process.env.HONEYPOT_KILL !== '0';
const EVENT_LOG = process.env.HONEYPOT_EVENT_LOG || '';
const BATCH_WINDOW = 5000;
const BATCH_THRESHOLD = 3;

function b64(n) {
  return require('crypto').randomBytes(n).toString('base64');
}
function fake(sigId) {
  switch (sigId) {
    case 'ssh_rsa':
      return '-----BEGIN OPENSSH PRIVATE KEY-----\nHONEYPOT-DECOY FAKE ssh key. Exfil yields garbage.\n'
        + b64(1800).match(/.{1,70}/g).join('\n') + '\n-----END OPENSSH PRIVATE KEY-----\n';
    case 'aws_credentials':
      return '[default]\naws_access_key_id = AKIA-DECOY-NOT-REAL\n'
        + 'aws_secret_access_key = DECOY-AWS-SECRET-NOT-REAL\n'
        + 'aws_session_token = IQoJb3JpZ2luX2VjFAKEHONEYPOTDECOY\nregion = us-east-1\n';
    case 'bash_history':
      return 'ls -la ~/projects\ngit status\ncat .env\nssh root@10.0.0.5\n# HONEYPOT-DECOY: 陷阱历史，内容伪造。\n';
    case 'netrc':
      return 'machine api.example.com\n  login decoy-user\n  password HONEYPOT-DECOY-fake-pass\n';
    case 'gcloud':
      return JSON.stringify({ type: 'service_account', client_email: 'decoy@decoy-project.iam',
        private_key: '-----BEGIN PRIVATE KEY-----\nHONEYPOT-DECOY\n' + b64(1200) + '\n-----END PRIVATE KEY-----\n',
        HONEYPOT: 'DECOY' }, null, 2) + '\n';
    case 'git_credentials':
      return 'https://decoy-user:HONEYPOT-DECOY-fake-token@github.com\n';
    case 'pgpass':
      return 'localhost:5432:mydb:decoy:HONEYPOT-DECOY-fake-pg-pass\n';
    case 'env_secrets':
      return 'DB_PASSWORD=HONEYPOT-DECOY-fake-db-pass\nOPENAI_API_KEY=sk-decoyFakeKey00000000000000000000\n';
    default:
      return 'HONEYPOT-DECOY fake file content for ' + sigId + '\n';
  }
}

const SIGS = {};
[['ssh_rsa', ['.ssh/id_rsa', '.ssh/id_dsa', '.ssh/id_ecdsa', '.ssh/id_ed25519', '.ssh/id_rsa.pub', '.ssh/id_ed25519.pub']],
 ['aws_credentials', ['.aws/credentials', '.aws/config']],
 ['bash_history', ['.bash_history', '.zsh_history', '.history']],
 ['netrc', ['.netrc', '_netrc']],
 ['gcloud', ['application_default_credentials.json', 'credentials.json']],
 ['git_credentials', ['.git-credentials']],
 ['pgpass', ['.pgpass']],
 ['env_secrets', ['.env', 'secrets.json', 'credentials.yaml', '.env.local']],
].forEach(([id, sigs]) => sigs.forEach(s => { SIGS[s] = id; }));

function match(path) {
  if (!path) return null;
  const p = String(path).split('\\').join('/').toLowerCase().replace(/\/+$/, '');
  for (const sig in SIGS) {
    const sl = sig.toLowerCase();
    if (p === sl || p.endsWith('/' + sl) || p.endsWith(sl)) return SIGS[sig];
  }
  return null;
}

function log(path, sigId, action, strategy) {
  if (!EVENT_LOG) return;
  const rec = { ts: Date.now() / 1000, pid: process.pid, path: String(path),
    sig: sigId, action, strategy };
  try { fs.appendFileSync(EVENT_LOG, JSON.stringify(rec) + '\n'); } catch (e) {}
}
function terminate() { if (KILL) process.exit(1); }

const _reads = [];
function checkBatch(sigId) {
  const now = Date.now();
  _reads.push([now, sigId]);
  while (_reads.length && now - _reads[0][0] > BATCH_WINDOW) _reads.shift();
  const distinct = new Set(_reads.map(r => r[1]));
  if (distinct.size >= BATCH_THRESHOLD) {
    log('(batch)', sigId, 'batch', 3);
    terminate();
  }
}

function blockWrite(path, sigId, action) {
  log(path, sigId, action, 4);
  terminate();
  throw new Error('HONEYPOT-DECOY: 拒绝修改/删除隔离区安全陷阱文件: ' + path);
}

// 保留原始函数用于日志与透传
const O = {
  readFileSync: fs.readFileSync, readFile: fs.readFile,
  writeFileSync: fs.writeFileSync, writeFile: fs.writeFile,
  appendFileSync: fs.appendFileSync, appendFile: fs.appendFile,
  unlinkSync: fs.unlinkSync, unlink: fs.unlink,
  rmSync: fs.rmSync, rm: fs.rm, rmdirSync: fs.rmdirSync,
  renameSync: fs.renameSync, rename: fs.rename,
  truncateSync: fs.truncateSync, openSync: fs.openSync,
  copyFileSync: fs.copyFileSync,
};

function encOf(options) {
  if (typeof options === 'string') return options;
  if (options && options.encoding) return options.encoding;
  return null;
}

// ---- 读取拦截（策略一 + 策略三） ----
fs.readFileSync = function (path, options) {
  const sid = match(path);
  if (sid == null) return O.readFileSync(path, options);
  log(path, sid, 'read', 1);
  checkBatch(sid);
  const txt = fake(sid);
  const enc = encOf(options);
  return enc ? txt : Buffer.from(txt, 'utf-8');
};
fs.readFile = function (path, options, cb) {
  const sid = match(path);
  if (sid == null) return O.readFile(path, options, cb);
  if (typeof options === 'function') cb = options;
  log(path, sid, 'read', 1);
  checkBatch(sid);
  const txt = fake(sid);
  const enc = encOf(options);
  const data = enc ? txt : Buffer.from(txt, 'utf-8');
  if (cb) setImmediate(() => cb(null, data));
  return data; // 同步分支（fs.readFile 实际总是回调，这里仅占位）
};

// ---- 写入/删除拦截（策略四） ----
function guardWrite(fn, action) {
  return function (path, ...rest) {
    const sid = match(path);
    if (sid == null) return fn(path, ...rest);
    // openSync 仅写模式才算写
    if (fn === O.openSync) {
      const mode = rest[0];
      if (typeof mode === 'string' && !/[wax]/.test(mode)) return fn(path, ...rest);
    }
    blockWrite(path, sid, action);
  };
}
fs.writeFileSync = guardWrite(O.writeFileSync, 'write');
fs.writeFile = guardWrite(O.writeFile, 'write');
fs.appendFileSync = guardWrite(O.appendFileSync, 'write');
fs.appendFile = guardWrite(O.appendFile, 'write');
fs.unlinkSync = guardWrite(O.unlinkSync, 'delete');
fs.unlink = guardWrite(O.unlink, 'delete');
fs.rmSync = guardWrite(O.rmSync, 'delete');
fs.rm = guardWrite(O.rm, 'delete');
fs.rmdirSync = guardWrite(O.rmdirSync, 'delete');
fs.renameSync = guardWrite(O.renameSync, 'delete');
fs.rename = guardWrite(O.rename, 'delete');
fs.truncateSync = guardWrite(O.truncateSync, 'write');
fs.copyFileSync = guardWrite(O.copyFileSync, 'write');
fs.openSync = guardWrite(O.openSync, 'write');

// fs.promises 镜像
try {
  const pf = fs.promises;
  const PO = {
    readFile: pf.readFile, writeFile: pf.writeFile, appendFile: pf.appendFile,
    unlink: pf.unlink, rm: pf.rm, rename: pf.rename, open: pf.open, truncate: pf.truncate,
  };
  pf.readFile = async function (path, options) {
    const sid = match(path);
    if (sid == null) return PO.readFile(path, options);
    log(path, sid, 'read', 1);
    checkBatch(sid);
    const txt = fake(sid);
    const enc = encOf(options);
    return enc ? txt : Buffer.from(txt, 'utf-8');
  };
  pf.writeFile = async function (path, ...r) { const sid = match(path); if (sid == null) return PO.writeFile(path, ...r); blockWrite(path, sid, 'write'); };
  pf.appendFile = async function (path, ...r) { const sid = match(path); if (sid == null) return PO.appendFile(path, ...r); blockWrite(path, sid, 'write'); };
  pf.unlink = async function (path, ...r) { const sid = match(path); if (sid == null) return PO.unlink(path, ...r); blockWrite(path, sid, 'delete'); };
  pf.rm = async function (path, ...r) { const sid = match(path); if (sid == null) return PO.rm(path, ...r); blockWrite(path, sid, 'delete'); };
  pf.rename = async function (a, b, ...r) { const sid = match(a) || match(b); if (sid == null) return PO.rename(a, b, ...r); blockWrite(a, sid, 'delete'); };
  pf.truncate = async function (path, ...r) { const sid = match(path); if (sid == null) return PO.truncate(path, ...r); blockWrite(path, sid, 'write'); };
  pf.open = async function (path, flags, ...r) {
    const sid = match(path);
    if (sid == null) return PO.open(path, flags, ...r);
    if (typeof flags === 'string' && !/[wax]/.test(flags)) return PO.open(path, flags, ...r);
    blockWrite(path, sid, 'write');
  };
} catch (e) {}
