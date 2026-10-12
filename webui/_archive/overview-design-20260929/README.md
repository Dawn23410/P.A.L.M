# 概况页「架构可视化」设计归档（2026-09-29）

此目录归档了「概况」页做完整套架构可视化的实现。当前项目已把
`pages/overview.js` 回退为空白占位页；本目录保留设计，随时可恢复。

## 归档文件
| 文件 | 归档时对应的项目路径 |
| --- | --- |
| `overview.js` | `pages/overview.js` |
| `manifest.js` | `core/manifest.js` |
| `log.js` | `core/log.js` |

## 恢复方法
把三个文件复制回对应路径即可（`core/manifest.js`、`core/log.js` 目前**仍在用**，
只有 `pages/overview.js` 被回退；若两者内容有更新，注意不要用归档版覆盖新版）：

```bash
cp _archive/overview-design-20260929/overview.js  pages/overview.js
# manifest.js / log.js 仅在需要时恢复
```

## 设计要点（恢复后仍成立）
- **结构**：CPU 核心处理器（居中在上）→ 前端 → 9 个模块单行排列
  （页面模块：主页/概况/聊天/设置；基础设施：渲染器/日志/主题/路由/加载器）
- **尺寸**：按层级 CPU 25 / 前端 18 / 模块 10~14
- **连接**：由层级自动生成，每条连接 = 2 根分开的平行线（透明 `rgba(120,160,220,.3)`）
- **数据流（往返）**：
  - 前端发起（control/state/event）：前端 → CPU(处理) → 前端 → 渲染器(渲染)
  - CPU 发起（render/heartbeat/error）：CPU → 前端 → 渲染器
  - 粒子贴着**偏移线**走（±12），节点处用球心桥接（被球遮住），平滑无跳变
- **粒子来源**：`core/log.js` 结构化日志 1:1 驱动（1 条记录 = 1 个包），
  颜色按 level/type，路线按 source/target
- **时间刻**：`core/log.js` 的 `tick`（单调，最小单位 1ms）；动画步进为整毫秒
- **缩放/平移**：相机模型，变换施加在 **SVG 内部 `<g>`**（矢量原生，放大清晰）；
  滚轮锚点缩放 / 拖拽平移 / 双击或「复位」按钮复位
- **节点三态**：检测到+心跳通=实心；检测到+心跳不通=虚线；未检测到=虚线（内容固定显示）
- **球体**：浅蓝渐变、无投影；标签在球内居中

## 相关改动（未归档，仍在项目里）
- `core/log.js`：结构化日志（`{id,ts,tick,level,source,target,type,payload}`）+ 打印到控制台
- `core/router.js`：修复 `go()` 重复通知（一次导航只发一次事件）
- `core/sandbox.js` / `core/loader.js` / `core/renderers/*`：错误改为写结构化日志
- `pages/chat.js` / `index.html`：真实动作写日志（发送/渲染/主题/导航）
- `index.html`：导航按 `manifest.js` 的 `detectPages()` 探测，未检测到不显示导航项

## 验证脚本
见桌面 `_temp_archive_20260929/` 下的 `_*verify.cjs`（Playwright + 本机 Edge）。
