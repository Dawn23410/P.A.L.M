# 底层框架（微内核 + 三位一体底座）

> 定位：**底层框架** —— 骨架 + 底座 + 契约，不含任何业务能力。
> 三层：`L2 插件层` / `L1 内核层` / `L0 底座（安全·权限·日志）`

## 文件
| 文件 | 层 | 职责 |
|---|---|---|
| `log.js` | L0 日志 | append-only 事件流（单一真相源） |
| `permission.js` | L0 权限 | 授权状态 + 默认拒绝 |
| `security.js` | L0 安全 | 唯一出网门面(fail-closed) + 握手鉴权(主密钥+随机盐+AEAD) |
| `sandbox.js` | 沙箱 | 能力注入 ctx + 可逆副作用 + 故障边界 |
| `kernel.js` | L1 内核 | 加载/卸载/依赖/生命周期 + 服务容器(缺失归一 null) + 事件总线 + 单一装配点 |
| `index.js` | — | 统一导出 |
| `demo.html` / `demo.js` | — | 演示：装配 → 能力注入 → 握手鉴权 → 热插拔回滚 |

## 用法
```js
import { createKernel } from './index.js';

const k = await createKernel();

// 单一装配点：定义插件
k.define('storage', {
  provides: ['storage'],
  setup(ctx) { const m = new Map(); return { storage: { set:(k,v)=>m.set(k,v), get:(k)=>m.get(k)??null } }; },
});

k.define('greeter', {
  inject: ['storage'],                 // 依赖 → 自动加载
  provides: ['greeter'],
  setup(ctx) {
    const storage = ctx.use('storage');          // 能力注入（白名单 + 权限）
    const t = setInterval(() => {}, 1000);
    ctx.effect(() => clearInterval(t));          // 可逆副作用
    ctx.on('ping', (p) => ctx.log('pong', { p })); // 订阅（也是可逆副作用）
    return { greeter: { greet: (n) => `hi ${n}` } };
  },
});

k.permission.grant('use:storage');
k.permission.grant('use:greeter');

await k.assemble(['greeter']);          // 装配（自动带依赖）
k.container.get('greeter').greet('PALM');

// 握手鉴权
const header = await k.security.seal('greeter', 'hello');   // 加密信息头
await k.security.open(header);                              // 一致才接收

// 热插拔：卸载即回滚副作用（定时器清、订阅退、能力摘）
await k.unuse('greeter');
```

## 跑 demo
启动 dev server（`node core/devserver.js`）后访问：
`http://localhost:5173/framework/demo.html`
