/**
 * L0 底座 · 安全（唯一出口门面 + 握手鉴权）
 * ======================================
 * - 主密钥：随框架初始化随机生成，仅存内存、不落盘，重启即轮换
 * - 握手：模块加载时读主密钥 + 自己生成随机盐 → 对称会话密钥 SK = HKDF(MK, salt)
 * - 请求前缀「加密信息头」：moduleId.saltId.nonce.密文 → 接收方同法派生 SK 解密校验 → 一致才接收
 * - 唯一出网门面：默认拒绝（fail-closed）
 * 统一用对称 AEAD（AES-GCM），便于统一解密且自带完整性。
 */

const enc = new TextEncoder();
const dec = new TextDecoder();
const b64 = (buf) => btoa(String.fromCharCode(...new Uint8Array(buf)));
const unb64 = (s) => Uint8Array.from(atob(s), (c) => c.charCodeAt(0));

export async function createSecurity({ log } = {}) {
  // 主密钥：随机生成，仅存内存
  const master = crypto.getRandomValues(new Uint8Array(32));
  const baseKey = await crypto.subtle.importKey('raw', master, 'HKDF', false, ['deriveKey']);
  const sessions = new Map(); // moduleId -> { saltId, key }

  async function deriveKey(moduleId, salt) {
    return crypto.subtle.deriveKey(
      { name: 'HKDF', hash: 'SHA-256', salt, info: enc.encode(moduleId) },
      baseKey,
      { name: 'AES-GCM', length: 256 },
      false,
      ['encrypt', 'decrypt'],
    );
  }

  /** 握手（模块加载时调用）：生成随机盐并注册会话密钥 */
  async function handshake(moduleId) {
    const salt = crypto.getRandomValues(new Uint8Array(16));
    const key = await deriveKey(moduleId, salt);
    const saltId = b64(salt).slice(0, 8);
    sessions.set(moduleId, { saltId, key });
    log?.record('security.handshake', { moduleId, saltId });
    return { moduleId, saltId };
  }

  /** 生成「加密信息头」（请求前缀） */
  async function seal(moduleId, payload = '') {
    const s = sessions.get(moduleId);
    if (!s) return null;
    const nonce = crypto.getRandomValues(new Uint8Array(12));
    const ct = await crypto.subtle.encrypt({ name: 'AES-GCM', iv: nonce }, s.key, enc.encode(payload));
    return `${moduleId}.${s.saltId}.${b64(nonce)}.${b64(ct)}`;
  }

  /** 校验「加密信息头」：识别一致才接收，否则返回 null */
  async function open(header, _payload = '') {
    const parts = String(header || '').split('.');
    if (parts.length !== 4) { log?.record('security.reject', { reason: 'malformed' }); return null; }
    const [moduleId, saltId, n, ct] = parts;
    const s = sessions.get(moduleId);
    if (!s || s.saltId !== saltId) {
      log?.record('security.reject', { moduleId, reason: 'no-session' });
      return null;
    }
    try {
      const pt = await crypto.subtle.decrypt({ name: 'AES-GCM', iv: unb64(n) }, s.key, unb64(ct));
      log?.record('security.accept', { moduleId });
      return dec.decode(pt);
    } catch {
      log?.record('security.reject', { moduleId, reason: 'aead-fail' });
      return null;
    }
  }

  // 唯一出网门面：默认拒绝（fail-closed）
  let netAllowed = false;
  const net = {
    allow(v) { netAllowed = !!v; },
    async fetch(url, opts) {
      if (!netAllowed) {
        log?.record('security.net.deny', { url });
        throw new Error('出网被拒（fail-closed，未放行）');
      }
      log?.record('security.net', { url });
      return fetch(url, opts);
    },
  };

  return { handshake, seal, open, net, hasSession: (id) => sessions.has(id) };
}
