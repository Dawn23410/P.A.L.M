/**
 * 应用内核（单例）
 * =================
 * 把底层框架 kernel 作为 webui 的唯一运行时。
 * 页面、能力、底座（安全 / 权限 / 日志）全部挂在这一个 kernel 上 ——
 * 不再有第二套模块系统。
 *
 * 约定：createKernel 是异步的（安全底座要起随机主密钥），
 * 因此 bootKernel() 返回 Promise，首次 await 后内核就绪。
 */
import { createKernel } from '../framework/index.js';

let kernelPromise = null;
let kernel = null;

export function bootKernel() {
  if (!kernelPromise) {
    kernelPromise = createKernel().then((k) => {
      kernel = k;
      if (typeof window !== 'undefined') window.__kernel = k;
      return k;
    });
  }
  return kernelPromise;
}

/** 已解析的内核实例（boot 之前为 null） */
export function getKernel() {
  return kernel;
}
