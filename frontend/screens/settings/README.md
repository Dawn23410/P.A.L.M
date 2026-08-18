# 界面：应用设置

- 契约端点：
- `GET /api/settings`
- `POST /api/settings`
- 说明：外观/Token 限额等设置读写
- 约定：原生 ES Modules，导出 `title`/`mount(root, ctx)`；后端 HTTP 适配层未就绪时按 UiPort 契约降级展示「后端未连接」。
