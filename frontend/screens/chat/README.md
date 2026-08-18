# 界面：对话

- 契约端点：
- `POST /api/chat（SSE 事件流）`
- `GET /api/chat/file-support`
- 说明：delta 正文增量 / reasoning 思维链 / usage 用量；流末 [DONE]
- 约定：原生 ES Modules，导出 `title`/`mount(root, ctx)`；后端 HTTP 适配层未就绪时按 UiPort 契约降级展示「后端未连接」。
