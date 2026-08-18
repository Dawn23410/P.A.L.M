# 界面：记忆

- 契约端点：
- `POST /api/memory/retrieve`
- `GET /api/memory/status`
- 说明：语义检索/Token 预算/情绪五因子
- 约定：原生 ES Modules，导出 `title`/`mount(root, ctx)`；后端 HTTP 适配层未就绪时按 UiPort 契约降级展示「后端未连接」。
