// index.ts — P.A.L.M 网卡模块统一出口（npm 包入口）
// 三层职责：net(门面, fail-closed) → netguard(安全管道) → network(网卡砖)
// 消费方只 import 本出口，不直接深入内部。

export { net, NetFacade, NetworkForbidden } from './net.ts';
export type { NetExecutor, NetRequestOptions } from './net.ts';

export {
  NetGuardPipeline,
  NetGuardError,
  isPrivateIp,
  scanEgressBody,
  scanIngressBody,
  Quota,
  PolicyStore,
  DEFAULT_GUARD_OPTIONS,
} from './netguard.ts';
export type {
  GuardAction,
  GuardVerdict,
  NetGuardOptions,
  HostPolicy,
  DlpLevel,
} from './netguard.ts';

export { NetworkBrick, createFetchExecutor } from './network.ts';
export type { NetBrick } from './network.ts';