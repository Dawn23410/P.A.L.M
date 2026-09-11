// Node.js 代理 shim — 强制 http/https/TCP 经沙箱 HTTP 代理
'use strict';
const PROXY = process.env.HTTP_PROXY || process.env.HTTPS_PROXY || 'http://127.0.0.1:18100';
const P = new URL(PROXY);
const LOCAL = h=>['127.0.0.1','localhost','::1','0.0.0.0'].includes(h)||h.startsWith('10.')||h.startsWith('192.168.')||h.startsWith('172.');

// ====== 补丁 http.request + http.get ======
const http = require('http');
const _req = http.request;
http.request = function(o, ...r) {
  let h = typeof o === 'string' ? '' : (o.hostname||o.host||'');
  if (typeof o === 'string') try { h = new URL(o).hostname; } catch(e) {}
  if (!h || LOCAL(h)) return _req.call(this, o, ...r);
  const opts = typeof o === 'object' ? Object.assign({}, o) : {hostname:P.hostname,port:+P.port,path:o};
  if (typeof o === 'object') {
    opts.path = (o.protocol||'http:')+'//'+(o.hostname||o.host||'localhost')+':'+(o.port||80)+(o.path||'/');
    opts.hostname = P.hostname; opts.port = +P.port;
  }
  return _req.call(this, opts, ...r);
};
const _get = http.get;
http.get = function(u, o, ...r) {
  const cb = typeof o === 'function' ? o : (typeof r[0] === 'function' ? r[0] : null);
  const opts = typeof u === 'string' ? Object.assign({}, {hostname:P.hostname,port:+P.port,path:u}) : (typeof o === 'object' ? Object.assign({}, o) : {});
  if (typeof u === 'object') Object.assign(opts, u);
  let h = opts.hostname||opts.host||'';
  if (typeof u === 'string') try { h = new URL(u).hostname; } catch(e) {}
  if (!h || LOCAL(h)) return _get.call(this, u, o, ...r);
  opts.hostname = P.hostname; opts.port = +P.port;
  opts.path = (typeof u === 'string' ? u : ((opts.protocol||'http:')+'//'+h+':'+(opts.port||80)+(opts.path||'/')));
  return _req.call(this, opts, cb);
};

// ====== 补丁 https.request + https.get ======
const https = require('https');
const _hreq = https.request;
https.request = function(o, ...r) {
  let h = typeof o === 'string' ? '' : (o.hostname||o.host||'');
  if (typeof o === 'string') try { h = new URL(o).hostname; } catch(e) {}
  if (!h || LOCAL(h)) return _hreq.call(this, o, ...r);
  // HTTPS → 通过 http CONNECT 隧道
  const opts = Object.assign({}, typeof o === 'object' ? o : {});
  opts.method = 'CONNECT'; opts.hostname = P.hostname; opts.port = +P.port;
  opts.path = (o.hostname||o.host||'localhost')+':'+(o.port||443);
  const creq = http.request(opts);
  creq.on('connect', (res, sock) => {
    const tls = require('tls');
    const tlsSock = tls.connect({socket:sock, servername:o.servername||o.hostname||o.host||'localhost'});
    const hreq = new https.ClientRequest(o, r[r.length-1]);
    hreq.onSocket(tlsSock);
  });
  creq.end();
  return creq;
};
const _hget = https.get;
https.get = function(u, o, ...r) {
  const opts = typeof u === 'string' ? {hostname:P.hostname,port:+P.port,path:u} : (typeof o === 'object' ? Object.assign({}, o) : {});
  if (typeof u === 'object') Object.assign(opts, u);
  let h = opts.hostname||opts.host||'';
  if (typeof u === 'string') try { h = new URL(u).hostname; } catch(e) {}
  if (!h || LOCAL(h)) return _hget.call(this, u, o, ...r);
  return https.request.call(this, opts, typeof o === 'function' ? o : (typeof r[0] === 'function' ? r[0] : undefined));
};
