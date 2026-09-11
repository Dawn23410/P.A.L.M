# md-renderer · 可复用 Markdown 渲染控件

`<md-renderer>` 是一个**自包含、零样板**的 Web Component（Shadow DOM 隔离样式），
把 Markdown 文本渲染为带**代码高亮、emoji、国旗**的富文本。可直接拖入任意前端
（原生 / React / Vue / Svelte）使用，不污染宿主页面。

---

## 1. 快速开始

### 1.1 拷贝文件
把以下文件放进你的项目（保持相对目录结构）：

```
md-renderer.js              ← 控件本体
vendor/
  marked.min.js             ← Markdown 解析
  purify.min.js             ← HTML 净化（不可信来源必装）
  highlight.min.js          ← 代码高亮核心
  lang/aliases.js
  lang-loader.js            ← 192 语言按需加载
  emoji-common.js
  emoji-loader.js           ← emoji 二级加载
  flag-polyfill.js          ← 国旗 polyfill
  lang-bundle.js            ← 192 语言数据（离线/file:// 必备；省略则需保留 vendor/lang/*.js 共 195 个文件）
  emoji-full.js             ← emoji 全量数据（1911 个；省略则仅渲染 500 个常用 emoji）
  flags/                    ← 国旗 SVG（261 个；省略则国旗回退为文字或空白）
```

### 1.2 引入依赖与控件

```html
<script src="vendor/marked.min.js"></script>
<script src="vendor/purify.min.js"></script>
<script src="vendor/highlight.min.js"></script>
<script src="vendor/lang/aliases.js"></script>
<script src="vendor/lang-loader.js"></script>
<script src="vendor/emoji-common.js"></script>
<script src="vendor/emoji-loader.js"></script>
<script src="vendor/flag-polyfill.js"></script>
<script src="md-renderer.js"></script>
```

### 1.3 使用

**方式 A · 后端驱动（轮询）：**

```html
<md-renderer endpoint="/api/last" poll="2000" theme="dark"></md-renderer>
```

**方式 B · 纯前端赋值：**

```html
<md-renderer id="r" theme="light"></md-renderer>
<script>
  document.querySelector('#r').markdown = "# 你好\n这是 **Markdown** 渲染结果";
</script>
```

---

## 2. 属性（Attributes）

| 属性 | 说明 | 默认 |
|---|---|---|
| `endpoint` | 后端 Markdown 接口地址；设置后控件自动轮询渲染 | 无 |
| `poll` | 轮询间隔（毫秒）；`0` 或负数表示关闭轮询 | `2000` |
| `theme` | 主题：`dark`（默认） / `light` | `dark` |
| `placeholder` | 无内容时显示的提示文本 | `等待 markdown 输入…` |

**后端契约** —— `GET endpoint` 返回以下任一：
- 纯文本 Markdown；
- JSON：`{ "markdown": "..." }` 或 `{ "content": "..." }`；
- 可选 `updated_at`（Unix 秒），用于在状态栏显示更新时间。

---

## 3. JS 属性 / 方法（Property API）

| 成员 | 说明 |
|---|---|
| `el.markdown`（get/set） | 直接读写要渲染的 Markdown 文本 |
| `el.setMarkdown(text)` | 等价于 `el.markdown = text` |
| `el.theme`（get/set） | 读取 / 切换主题，如 `el.theme = "light"` |
| `el.refresh()` | 立即从 `endpoint` 拉取一次并渲染（手动刷新按钮用） |

示例：

```js
const el = document.querySelector('md-renderer');
el.markdown = "# 标题\n- 列表项";   // 立即渲染
el.theme = "light";                  // 切换亮色主题
await el.refresh();                 // 从 endpoint 重新拉取
```

---

## 4. 事件

- **`mdr-status`**（`CustomEvent`，`bubbles: true`）：控件把底部状态栏文本透传出来，
  便于宿主 UI 在外部展示语言包 / emoji 命中情况。

```js
el.addEventListener('mdr-status', (e) => console.log(e.detail));
// e.detail 形如："语言包注册 192 · emoji 命中 98% · 全量 是"
```

---

## 5. 主题与外观定制

控件通过 CSS 自定义属性暴露配色，宿主可在外部按需覆盖：

```css
md-renderer {
  --mdr-panel:   #ffffff;   /* 主背景 */
  --mdr-panel-2: #f6f8fa;   /* 状态栏背景 */
  --mdr-text:    #1f2328;   /* 正文文字 */
  --mdr-muted:   #57606a;   /* 次要文字 */
  --mdr-border:  #d0d7de;   /* 边框 */
  --mdr-code-bg: #f6f8fa;   /* 代码块背景 */
  --mdr-accent:  #0969da;   /* 链接 / 强调 */
}
```

内置**暗 / 亮双主题**由 `theme` 属性切换，代码高亮同步适配
（亮色：浅底深字；暗色：深底浅字），无需额外处理。

---

## 6. 依赖与优雅降级

控件**本身不含**渲染引擎，需宿主页面提供以下全局对象。任一缺失时**优雅降级**，
不会报错崩溃：

| 全局 | 缺失时表现 |
|---|---|
| `marked` | 退回转义后的纯文本 |
| `DOMPurify` | 不做 HTML 净化（**不可信来源务必引入**） |
| `highlight.js` + `LangLoader` | 代码不高亮，仅保留原文 |
| `EMOJI_MAP` / `EmojiLoader` | emoji 显示为 `:shortcode:` 原文 |
| `FlagPolyfill` | 国旗不渲染 |

---

## 7. 在框架中集成

**React**
```jsx
function MdBox({ text }) {
  const ref = useRef(null);
  useEffect(() => { if (ref.current) ref.current.markdown = text; }, [text]);
  return <md-renderer ref={ref} theme="dark" />;
}
```

**Vue 3**
```vue
<template><md-renderer ref="r" theme="dark" /></template>
<script setup>
const r = ref(null);
watch(() => props.text, t => { if (r.value) r.value.markdown = t; });
</script>
```

**Svelte / 原生**：直接操作 DOM 属性或上面的 Property API 即可。

---

## 8. 最小可运行示例（静态文件）

把 `md-renderer.js` 与 `vendor/` 放在同目录，新建 `index.html`：

```html
<!doctype html>
<html><head><meta charset="utf-8">
  <style>html,body{margin:0;height:100%} md-renderer{height:100vh}</style>
  <!-- 引入第 1.2 节的 vendor 脚本 -->
  <script src="md-renderer.js"></script>
</head><body>
  <md-renderer theme="dark"></md-renderer>
  <script>
    document.querySelector('md-renderer').markdown =
      "# 标题\n\n```python\nprint('hello')\n```\n\n:smile: :flag_cn:";
  </script>
</body></html>
```

双击以 `file://` 打开即可（首次会按相对路径自动加载语言包与 emoji 全量数据）。

---

# ai-message · 可复用 AI 对话消息组件

`<ai-message>` 在 `<md-renderer>` 之上封装了**一条 AI 对话消息**所需的全部 UI：
Markdown 渲染、**Token 计数器**、**延迟计数器**、**一键复制**、**重新生成**。
同样是基于 Shadow DOM 的自包含 Web Component，可直接嵌入任意前端。

> 它复用 `<md-renderer>` 的渲染管线，因此 §1.1 列出的全部 `vendor/` 依赖
> **外加 `md-renderer.js`** 都是前置条件；只需再追加本文件：
> ```
> ai-message.js               ← 对话消息组件
> md-renderer.js             ← 复用其渲染管线（已在上方拷贝）
> vendor/ …                  ← 同 §1.1
> ```

## 引入

```html
<!-- 先引入 §1.2 的全部 vendor 脚本，再加两个控件 -->
<script src="md-renderer.js"></script>
<script src="ai-message.js"></script>
```

## 使用

**方式 A · 直接写内容（含标签文本）：**
```html
<ai-message theme="dark" label="AI 助手"># 你好
这是 **Markdown** 渲染结果，下方自动统计 token 与延迟。</ai-message>
```

**方式 B · 后端轮询（与 md-renderer 一致）：**
```html
<ai-message id="m" endpoint="/api/last" poll="2000" theme="dark"></ai-message>
```

**方式 C · 编程驱动（流式 / 事件回调）：**
```js
const m = document.querySelector('#m');
m.loading = true;                 // 进入"生成中"态（显示 spinner、禁用按钮）
m.markdown = "思考中…";           // 可以先放占位，再逐步替换
// …后端返回完成后：
m.markdown = fullText;            // 设置最终内容
m.tokens   = 128;                // 精确输出 token（覆盖估算）
m.latency  = 1234;               // 总生成耗时(ms)
m.ttft     = 320;                // 首字延迟(ms)，可选
m.loading  = false;              // 结束生成态
```

## 属性（Attributes）

| 属性 | 说明 | 默认 |
|---|---|---|
| `theme` | 主题：`dark` / `light`（同时透传给内嵌 md-renderer） | `dark` |
| `label` | 头部显示的标题（如「AI 助手」「我」） | 按 `role` 推断 |
| `role` | 角色：`assistant` / `user` / `system` | `assistant` |
| `loading` | 存在即进入生成中态：显示 spinner、禁用复制/重新生成 | 无 |
| `markdown` | 直接写入初始 Markdown 文本（等价于设属性） | 无 |

## JS 属性 / 方法（Property API）

| 成员 | 说明 |
|---|---|
| `el.markdown`（get/set） | 读写要渲染的 Markdown 文本（设值后自动重算估算 token） |
| `el.setMarkdown(text)` | 等价于 `el.markdown = text` |
| `el.tokens`（get/set） | 注入**精确**输出 token 数；设为 `null` 恢复估算 |
| `el.latency`（get/set） | 总生成耗时（ms）；设为 `null` 恢复占位 |
| `el.ttft`（get/set） | 首字延迟（ms，可选） |
| `el.loading`（get/set） | 布尔，切换生成中态 |
| `el.tokenizer`（get/set） | 自定义 token 估算函数 `(text) => number` |
| `el.theme`（get/set） | 切换 `dark` / `light` |
| `el.copy()` | 复制当前 Markdown 到剪贴板（带「已复制」反馈） |
| `el.regenerate()` | 派发 `ai-regenerate` 事件 |

## 事件

- **`ai-regenerate`**（`bubbles: true, composed: true`）：点击「重新生成」时触发。
  组件**不内置任何后端调用**，由宿主监听此事件并接入自己的接口，保持与具体后端解耦。
  `detail: { markdown, tokens, latency, ttft }`。
- **`ai-copy`**（`bubbles: true, composed: true`）：复制成功时触发，`detail: { text }`。

```js
document.querySelector('#m').addEventListener('ai-regenerate', async (e) => {
  const m = e.currentTarget;
  m.loading = true;
  // 在这里调用你自己的后端，例如已有的 SSE 流式接口：
  const res = await fetch('/api/chat/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ messages: [{ role: 'user', content: e.detail.markdown }] })
  });
  // …读取流、边读边 m.markdown = chunk、记录首字/结束时间…
  m.tokens  = outputTokens;   // 后端返回的精确 token
  m.latency = Date.now() - startTs;
  m.loading = false;
});
```

## Token 计数器

- 未显式设置 `tokens` 时，按**多语言启发式**实时估算（CJK ≈1 token/字，英文按词 ≈1.3，
  标点 ≈0.3），界面显示 `≈ N tokens`。
- 后端如能返回精确 token，直接 `el.tokens = N`，界面显示 `N tokens`（无 `≈`）。
- 需要更准的估算可注入自定义函数：`el.tokenizer = (text) => myTiktoken.encode(text).length;`

## 延迟计数器

- `latency` 显示总耗时，自动在 `ms` / `s` 间格式化；配合 `ttft` 显示
  `⏱ 1.23 s · TTFT 320 ms`。
- `loading` 态且尚无耗时数据时显示 `⏱ 生成中…`。

## 主题

与 `<md-renderer>` 一致：`theme="dark|light"` 通过 `:host([theme=...])` 同时驱动
组件外壳与内嵌渲染区的配色（含代码高亮双主题），不污染宿主页。

## 在框架中集成

**React**
```jsx
function AiMsg({ text, tokens, latency, onRegen }) {
  const ref = useRef(null);
  useEffect(() => {
    if (!ref.current) return;
    ref.current.markdown = text;
    if (tokens != null) ref.current.tokens = tokens;
    if (latency != null) ref.current.latency = latency;
  }, [text, tokens, latency]);
  return <ai-message ref={ref} theme="dark"
                    onAi-regenerate={(e) => onRegen(e.detail)} />;
}
```

**Vue 3**
```vue
<template><ai-message ref="r" theme="dark"
  @ai-regenerate="onRegen" /></template>
<script setup>
const r = ref(null);
watch(() => props.text, t => { if (r.value) r.value.markdown = t; });
function onRegen(detail) { /* 调用后端 */ }
</script>
```

---

## 运行沙箱（代码执行）

两个控件渲染出的**代码块**会自动出现「▶ 运行」按钮，支持在对话 / 文档中直接执行示例代码。

### 支持的语言与执行位置

| 语言（围栏标识） | 执行位置 | 说明 |
|---|---|---|
| `js` / `javascript` | **浏览器内** | 独立 `sandbox` iframe（无同源），捕获 `console.*` 与未捕获错误，5s 超时 |
| `html` | **浏览器内** | 以 `sandbox="allow-scripts"` 的 iframe `srcdoc` 实时预览 |
| `css` | **浏览器内** | 注入示例 DOM 后预览（无独立 HTML 上下文时给出常见元素供查看效果） |
| `python` / `py` | **后端沙箱** | 经 `sandbox` 属性指向的端点执行（见下） |
| `node` | **后端沙箱** | 同上 |
| `bash` / `sh` / `shell` | **后端沙箱** | 同上 |

> 浏览器内执行**零后端依赖**，双击 `file://` 也能跑 JS/HTML/CSS。
> Python/Node/Bash 需要后端执行端点。

### 启用后端沙箱端点

仅当 `<md-renderer>` / `<ai-message>` 设置了 **`sandbox` 属性**（指向后端 `/api/run`）时，
Python/Node/Bash 代码块才会真正执行；否则点击运行会显示提示，不会报错。

后端 `web.py` 的 `/api/run` **默认关闭**，需显式开启（避免误开造成命令执行风险）：

```bash
# 方式一：启动参数
.venv/Scripts/python.exe web.py --sandbox

# 方式二：环境变量（适合已用其它方式启动的场景）
set ENABLE_SANDBOX=1
.venv/Scripts/python.exe web.py
```

启用后启动日志会打印安全警告。可用的解释器通过 PATH 自动查找，也可用环境变量覆盖：
`SANDBOX_PYTHON` / `SANDBOX_NODE` / `SANDBOX_BASH`（例如 `set SANDBOX_NODE=C:\node\node.exe`）。
Python 默认复用 `web.py` 自身的解释器，开箱即用。

### 用法

```html
<!-- 在控件上设置 sandbox 属性，指向后端 /api/run -->
<md-renderer theme="dark" sandbox="/api/run"></md-renderer>

<!-- ai-message 透传同一属性 -->
<ai-message theme="dark" sandbox="/api/run"></ai-message>

<script>
  document.querySelector('md-renderer').markdown = [
    '# 可执行示例',
    '```python',
    "print('hello from python')\nprint(2**10)",
    '```',
    '```js',
    "console.log('hello from js')",
    '```'
  ].join('\n');
</script>
```

代码块右上角「▶ 运行」→ 展开输出面板：浏览器内语言显示 console 输出 / 预览，
后端语言显示 `stdout` / `stderr` 与退出码。

### 后端接口契约

```
POST /api/run
Content-Type: application/json
{ "lang": "python|node|bash", "code": "<源码字符串>" }

→ 200 { "output": "...", "error": "...", "exitCode": 0 }
→ 403 沙箱未启用（未加 --sandbox / ENABLE_SANDBOX）
→ 400 不支持的语言或请求体错误
```

单次执行有超时（默认 10s，超时被中止并返回提示）。该执行**不是安全沙箱**
（仅做了超时隔离），仅用于本机可信环境，请勿在公网暴露启用态。

### 安全提示

- 浏览器内 JS 运行在 `sandbox="allow-scripts"` 的**匿名跨源 iframe** 中，无法访问父页面 DOM / Cookie。
- 后端 `/api/run` 会**真实执行任意代码**，务必仅在本地、可信网络中启用，且不要将其暴露到公网。
- 生产环境如需更强的隔离，请在容器 / 专用沙箱（seccomp、gVisor、Firecracker 等）中承载该端点。
```

