# 界面：总览

- 契约端点：
- `GET /health`
- `GET /api/services`
- 说明：替代旧 masterboard/bios/bricks；展示库装配健康与服务清单
- 约定：原生 ES Modules，导出 `title`/`mount(root, ctx)`；后端 HTTP 适配层未就绪时按 UiPort 契约降级展示「后端未连接」。
