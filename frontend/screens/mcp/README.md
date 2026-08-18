# 界面：MCP 工具台

- 契约端点：
- `GET /api/mcp/tools`
- `POST /api/mcp/call`
- 说明：已连接 MCP 工具清单与调用
- 约定：原生 ES Modules，导出 `title`/`mount(root, ctx)`；后端 HTTP 适配层未就绪时按 UiPort 契约降级展示「后端未连接」。
