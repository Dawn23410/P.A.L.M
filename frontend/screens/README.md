# 界面模块（screens）

一个目录 = 一个界面，模块化装配（shell.html 懒加载）。

- **overview**：总览——替代旧 masterboard/bios/bricks；展示库装配健康与服务清单
- **chat**：对话——delta 正文增量 / reasoning 思维链 / usage 用量；流末 [DONE]
- **characters**：角色卡——人设卡片与好感度展示
- **game**：游戏生态——等级/经验/星砂/每日任务/商城
- **memory**：记忆——语义检索/Token 预算/情绪五因子
- **files**：文件——上传/列表/解析结果读取
- **scheduler**：定时任务——任务列表/创建/启停
- **usage**：Token 用量——今日/本月/累计台账与最近明细
- **monitor**：运行监控——进程检测/运行模式解析
- **mcp**：MCP 工具台——已连接 MCP 工具清单与调用
- **settings**：应用设置——外观/Token 限额等设置读写

## 界面约定
- 每个 screen 导出 `title`(string) 与 `mount(root, ctx)`；卸载返回清理函数。
- 所有 fetch 经 `ui/api.js`（唯一出网口），禁止界面内裸 fetch。
- 界面间零互调，跨界面状态经外壳事件总线（待建）。
