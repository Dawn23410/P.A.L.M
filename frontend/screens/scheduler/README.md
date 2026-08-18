# 界面：定时任务

- 契约端点：
- `GET /api/scheduler/jobs`
- `POST /api/scheduler/jobs`
- 说明：任务列表/创建/启停
- 约定：原生 ES Modules，导出 `title`/`mount(root, ctx)`；后端 HTTP 适配层未就绪时按 UiPort 契约降级展示「后端未连接」。
