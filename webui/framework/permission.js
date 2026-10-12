/**
 * L0 底座 · 权限（授权状态 + 默认拒绝）
 * ==================================
 * 权限 = 准不准做（授权状态，长期）；安全 = 能不能做（门面/防护，即时）。
 * 未授权 → 拒绝（fail-closed）。
 */

export function createPermission({ log } = {}) {
  const granted = new Set();

  return {
    grant(name) {
      granted.add(name);
      log?.record('permission.grant', { name });
    },
    revoke(name) {
      granted.delete(name);
      log?.record('permission.revoke', { name });
    },
    /** 判定（默认拒绝）。只记"拒绝"——放行不刷屏（热路径噪声） */
    check(name) {
      const ok = granted.has(name);
      if (!ok) log?.record('permission.deny', { name });
      return ok;
    },
    list() { return [...granted]; },
  };
}
