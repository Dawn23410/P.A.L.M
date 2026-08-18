# 界面：Token 用量

- 契约端点：
- `GET /api/token-usage`
- 说明：今日/本月/累计台账与最近明细
- 约定：原生 ES Modules，导出 `title`/`mount(root, ctx)`；后端 HTTP 适配层未就绪时按 UiPort 契约降级展示「后端未连接」。
