# 界面：运行监控

- 契约端点：
- `GET /api/monitor/status`
- 说明：进程检测/运行模式解析
- 约定：原生 ES Modules，导出 `title`/`mount(root, ctx)`；后端 HTTP 适配层未就绪时按 UiPort 契约降级展示「后端未连接」。
