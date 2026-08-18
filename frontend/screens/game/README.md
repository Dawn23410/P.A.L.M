# 界面：游戏生态

- 契约端点：
- `GET /api/game/state`
- `GET /api/game/shop`
- 说明：等级/经验/星砂/每日任务/商城
- 约定：原生 ES Modules，导出 `title`/`mount(root, ctx)`；后端 HTTP 适配层未就绪时按 UiPort 契约降级展示「后端未连接」。
