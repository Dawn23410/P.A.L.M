# 界面：角色卡

- 契约端点：
- `GET /api/characters`
- `GET /api/affinity`
- 说明：人设卡片与好感度展示
- 约定：原生 ES Modules，导出 `title`/`mount(root, ctx)`；后端 HTTP 适配层未就绪时按 UiPort 契约降级展示「后端未连接」。
