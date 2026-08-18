# 界面：文件

- 契约端点：
- `POST /api/files/upload`
- `GET /api/files`
- 说明：上传/列表/解析结果读取
- 约定：原生 ES Modules，导出 `title`/`mount(root, ctx)`；后端 HTTP 适配层未就绪时按 UiPort 契约降级展示「后端未连接」。
