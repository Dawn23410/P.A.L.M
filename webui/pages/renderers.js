/**
 * 渲染器演示页
 * ============
 * 生命周期：mount(host) -> { onShow, onHide, destroy }
 *
 * 本页不直接依赖任何具体渲染器，只通过 registry 查询「哪些渲染器可用」，
 * 因此将来新增 typst 渲染器后，本页会自动在下拉里出现，无需改动。
 */

const STYLE_ID = 'mod-renderer-style';
const CSS = `
.mod-renderers{
  height:100%;display:flex;flex-direction:column;background:var(--ui-bg,#fff);
  color:var(--ui-text,#1a1a1a);
  transition:background .2s ease,color .2s ease;
}
.mod-renderers .rv-bar{
  flex:none;display:flex;align-items:center;gap:10px;flex-wrap:wrap;
  padding:10px 16px;border-bottom:1px solid var(--ui-border-soft,#ececec);
  font-size:0.8571rem;color:var(--ui-muted,#8a8a8a);
}
.mod-renderers .rv-bar .sp{flex:1}
.mod-renderers .rv-bar select,
.mod-renderers .rv-bar button{
  font:inherit;font-size:0.8571rem;cursor:pointer;
  border:1px solid var(--ui-border,#dcdcdc);background:var(--ui-elev,#fff);
  color:var(--ui-text,#333);padding:4px 10px;border-radius:6px;
  transition:background .16s;
}
.mod-renderers .rv-bar select:hover,
.mod-renderers .rv-bar button:hover{background:var(--ui-hover,#f5f5f5)}
.mod-renderers .rv-bar button.on{
  background:var(--ui-accent,#333);color:#fff;border-color:var(--ui-accent,#333)
}
.mod-renderers .rv-wrap{flex:1;min-height:0;overflow:hidden}
.mod-renderers [data-slot]{width:100%;height:100%;display:block}
`;

function injectStyle() {
  const old = document.getElementById(STYLE_ID);
  if (old) old.remove();
  const el = document.createElement('style');
  el.id = STYLE_ID;
  el.textContent = CSS;
  document.head.appendChild(el);
}

const SAMPLE_MD = `# 渲染器架构演示

这段内容由 **Markdown 渲染器** 渲染 —— 它是 \`Renderer\` 抽象基类的一个实现。

## 架构

> 基类固定渲染流程，子类只实现 \`ensureDeps()\` 和 \`parse()\`

### 各司其职

- **基类**：Shadow DOM、主题变量、状态栏、轮询、代码块装饰
- **Markdown 渲染器**：marked 解析 + DOMPurify 消毒 + 语法高亮
- **增强模块**：KaTeX 公式、Mermaid 图表（\`math.js\` / \`mermaid.js\`）
- **将来的 Typst 渲染器**：只换 \`parse()\`，其余白拿

### 数学公式

行内公式：质能方程 $E = mc^2$，欧拉恒等式 $e^{i\\pi} + 1 = 0$，
以及 $\\alpha$、$\\beta$、$\\gamma$ 这些希腊字母。

行间公式（独立成段、居中）：

$$
\\int_{-\\infty}^{\\infty} e^{-x^2}\\,dx = \\sqrt{\\pi}
$$

$$
f(x) = \\sum_{n=0}^{\\infty} \\frac{f^{(n)}(a)}{n!}(x-a)^n
$$

$$
\\begin{pmatrix} a & b \\\\ c & d \\end{pmatrix}
\\begin{pmatrix} x \\\\ y \\end{pmatrix}
= \\begin{pmatrix} ax + by \\\\ cx + dy \\end{pmatrix}
$$

公式里也可以换行对齐：

$$
\\begin{aligned}
\\nabla \\cdot \\mathbf{E} &= \\frac{\\rho}{\\varepsilon_0} \\\\
\\nabla \\cdot \\mathbf{B} &= 0
\\end{aligned}
$$

### 脑图（markmap）

> 与上面的 Mermaid mindmap 是**两种范式**：
> Mermaid 是「语义型」（手写分支表达概念关系），
> markmap 是「结构型」（把 Markdown 标题层级直接变成可折叠脑图）。
> 节点可点击折叠，支持滚轮缩放与拖拽平移。

\`\`\`markmap
# 渲染器架构

## 抽象层
### base.js
### registry.js
## 具体实现
### MarkdownRenderer
### TypstRenderer
## 增强模块
### KaTeX 公式
### Mermaid 图表
### markmap 脑图
## 主题系统
### light
### dark
### system
\`\`\`


### 脑图（markmap）— 压测用例：216 节点 / 20 层 / 5 路

> 下面是 markmap 的**压测用例**：**216 个节点 / 20 层垂直嵌套 / 每层 5 路水平分支**。
> 验证目标：缩放钳制在基准自适应 ×0.5 ~ ×3（base 极小时兜底 max ≥ 1.5）、拖拽到边界后 Δ0、
> 节点可点击折叠、主题切换即换色。fit 时文字约 1px（缩略视图），放大到上限时 24px 可读。

\`\`\`markmap
- 主干 L1 \`#1\`
  - 主干 L2 \`#2\`
  - 侧枝 L2.1 \`#3\`
    - 叶 L3.1.1 \`#4\`
    - 叶 L3.1.2 \`#5\`
    - 叶 L3.1.3 \`#6\`
  - 侧枝 L2.2 \`#7\`
    - 叶 L3.2.1 \`#8\`
    - 叶 L3.2.2 \`#9\`
    - 叶 L3.2.3 \`#10\`
  - 侧枝 L2.3 \`#11\`
    - 叶 L3.3.1 \`#12\`
    - 叶 L3.3.2 \`#13\`
    - 叶 L3.3.3 \`#14\`
  - 侧枝 L2.4 \`#15\`
    - 叶 L3.4.1 \`#16\`
    - 叶 L3.4.2 \`#17\`
    - 叶 L3.4.3 \`#18\`
    - 主干 L3 \`#19\`
    - 侧枝 L3.1 \`#20\`
      - 叶 L4.1.1 \`#21\`
      - 叶 L4.1.2 \`#22\`
      - 叶 L4.1.3 \`#23\`
    - 侧枝 L3.2 \`#24\`
      - 叶 L4.2.1 \`#25\`
      - 叶 L4.2.2 \`#26\`
      - 叶 L4.2.3 \`#27\`
    - 侧枝 L3.3 \`#28\`
      - 叶 L4.3.1 \`#29\`
      - 叶 L4.3.2 \`#30\`
      - 叶 L4.3.3 \`#31\`
    - 侧枝 L3.4 \`#32\`
      - 叶 L4.4.1 \`#33\`
      - 叶 L4.4.2 \`#34\`
      - 叶 L4.4.3 \`#35\`
      - 主干 L4 \`#36\`
      - 侧枝 L4.1 \`#37\`
        - 叶 L5.1.1 \`#38\`
        - 叶 L5.1.2 \`#39\`
        - 叶 L5.1.3 \`#40\`
      - 侧枝 L4.2 \`#41\`
        - 叶 L5.2.1 \`#42\`
        - 叶 L5.2.2 \`#43\`
        - 叶 L5.2.3 \`#44\`
      - 侧枝 L4.3 \`#45\`
        - 叶 L5.3.1 \`#46\`
        - 叶 L5.3.2 \`#47\`
        - 叶 L5.3.3 \`#48\`
      - 侧枝 L4.4 \`#49\`
        - 叶 L5.4.1 \`#50\`
        - 叶 L5.4.2 \`#51\`
        - 叶 L5.4.3 \`#52\`
        - 主干 L5 \`#53\`
        - 侧枝 L5.1 \`#54\`
          - 叶 L6.1.1 \`#55\`
          - 叶 L6.1.2 \`#56\`
          - 叶 L6.1.3 \`#57\`
        - 侧枝 L5.2 \`#58\`
          - 叶 L6.2.1 \`#59\`
          - 叶 L6.2.2 \`#60\`
          - 叶 L6.2.3 \`#61\`
        - 侧枝 L5.3 \`#62\`
          - 叶 L6.3.1 \`#63\`
          - 叶 L6.3.2 \`#64\`
          - 叶 L6.3.3 \`#65\`
        - 侧枝 L5.4 \`#66\`
          - 叶 L6.4.1 \`#67\`
          - 叶 L6.4.2 \`#68\`
          - 叶 L6.4.3 \`#69\`
          - 主干 L6 \`#70\`
          - 侧枝 L6.1 \`#71\`
            - 叶 L7.1.1 \`#72\`
            - 叶 L7.1.2 \`#73\`
            - 叶 L7.1.3 \`#74\`
          - 侧枝 L6.2 \`#75\`
            - 叶 L7.2.1 \`#76\`
            - 叶 L7.2.2 \`#77\`
            - 叶 L7.2.3 \`#78\`
          - 侧枝 L6.3 \`#79\`
            - 叶 L7.3.1 \`#80\`
            - 叶 L7.3.2 \`#81\`
            - 叶 L7.3.3 \`#82\`
          - 侧枝 L6.4 \`#83\`
            - 叶 L7.4.1 \`#84\`
            - 叶 L7.4.2 \`#85\`
            - 叶 L7.4.3 \`#86\`
            - 主干 L7 \`#87\`
            - 侧枝 L7.1 \`#88\`
              - 叶 L8.1.1 \`#89\`
              - 叶 L8.1.2 \`#90\`
              - 叶 L8.1.3 \`#91\`
            - 侧枝 L7.2 \`#92\`
              - 叶 L8.2.1 \`#93\`
              - 叶 L8.2.2 \`#94\`
              - 叶 L8.2.3 \`#95\`
            - 侧枝 L7.3 \`#96\`
              - 叶 L8.3.1 \`#97\`
              - 叶 L8.3.2 \`#98\`
              - 叶 L8.3.3 \`#99\`
            - 侧枝 L7.4 \`#100\`
              - 叶 L8.4.1 \`#101\`
              - 叶 L8.4.2 \`#102\`
              - 叶 L8.4.3 \`#103\`
              - 主干 L8 \`#104\`
              - 侧枝 L8.1 \`#105\`
                - 叶 L9.1.1 \`#106\`
                - 叶 L9.1.2 \`#107\`
                - 叶 L9.1.3 \`#108\`
              - 侧枝 L8.2 \`#109\`
                - 叶 L9.2.1 \`#110\`
                - 叶 L9.2.2 \`#111\`
                - 叶 L9.2.3 \`#112\`
              - 侧枝 L8.3 \`#113\`
                - 叶 L9.3.1 \`#114\`
                - 叶 L9.3.2 \`#115\`
                - 叶 L9.3.3 \`#116\`
              - 侧枝 L8.4 \`#117\`
                - 叶 L9.4.1 \`#118\`
                - 叶 L9.4.2 \`#119\`
                - 叶 L9.4.3 \`#120\`
                - 主干 L9 \`#121\`
                - 侧枝 L9.1 \`#122\`
                  - 叶 L10.1.1 \`#123\`
                  - 叶 L10.1.2 \`#124\`
                  - 叶 L10.1.3 \`#125\`
                - 侧枝 L9.2 \`#126\`
                  - 叶 L10.2.1 \`#127\`
                  - 叶 L10.2.2 \`#128\`
                  - 叶 L10.2.3 \`#129\`
                - 侧枝 L9.3 \`#130\`
                  - 叶 L10.3.1 \`#131\`
                  - 叶 L10.3.2 \`#132\`
                  - 叶 L10.3.3 \`#133\`
                - 侧枝 L9.4 \`#134\`
                  - 叶 L10.4.1 \`#135\`
                  - 叶 L10.4.2 \`#136\`
                  - 叶 L10.4.3 \`#137\`
                  - 主干 L10 \`#138\`
                  - 侧枝 L10.1 \`#139\`
                    - 叶 L11.1.1 \`#140\`
                    - 叶 L11.1.2 \`#141\`
                    - 叶 L11.1.3 \`#142\`
                  - 侧枝 L10.2 \`#143\`
                    - 叶 L11.2.1 \`#144\`
                    - 叶 L11.2.2 \`#145\`
                    - 叶 L11.2.3 \`#146\`
                  - 侧枝 L10.3 \`#147\`
                    - 叶 L11.3.1 \`#148\`
                    - 叶 L11.3.2 \`#149\`
                    - 叶 L11.3.3 \`#150\`
                  - 侧枝 L10.4 \`#151\`
                    - 叶 L11.4.1 \`#152\`
                    - 叶 L11.4.2 \`#153\`
                    - 叶 L11.4.3 \`#154\`
                    - 主干 L11 \`#155\`
                    - 侧枝 L11.1 \`#156\`
                      - 叶 L12.1.1 \`#157\`
                      - 叶 L12.1.2 \`#158\`
                      - 叶 L12.1.3 \`#159\`
                    - 侧枝 L11.2 \`#160\`
                      - 叶 L12.2.1 \`#161\`
                      - 叶 L12.2.2 \`#162\`
                      - 叶 L12.2.3 \`#163\`
                    - 侧枝 L11.3 \`#164\`
                      - 叶 L12.3.1 \`#165\`
                      - 叶 L12.3.2 \`#166\`
                      - 叶 L12.3.3 \`#167\`
                    - 侧枝 L11.4 \`#168\`
                      - 叶 L12.4.1 \`#169\`
                      - 叶 L12.4.2 \`#170\`
                      - 叶 L12.4.3 \`#171\`
                      - 主干 L12 \`#172\`
                      - 侧枝 L12.1 \`#173\`
                      - 侧枝 L12.2 \`#174\`
                      - 侧枝 L12.3 \`#175\`
                      - 侧枝 L12.4 \`#176\`
                        - 主干 L13 \`#177\`
                        - 侧枝 L13.1 \`#178\`
                        - 侧枝 L13.2 \`#179\`
                        - 侧枝 L13.3 \`#180\`
                        - 侧枝 L13.4 \`#181\`
                          - 主干 L14 \`#182\`
                          - 侧枝 L14.1 \`#183\`
                          - 侧枝 L14.2 \`#184\`
                          - 侧枝 L14.3 \`#185\`
                          - 侧枝 L14.4 \`#186\`
                            - 主干 L15 \`#187\`
                            - 侧枝 L15.1 \`#188\`
                            - 侧枝 L15.2 \`#189\`
                            - 侧枝 L15.3 \`#190\`
                            - 侧枝 L15.4 \`#191\`
                              - 主干 L16 \`#192\`
                              - 侧枝 L16.1 \`#193\`
                              - 侧枝 L16.2 \`#194\`
                              - 侧枝 L16.3 \`#195\`
                              - 侧枝 L16.4 \`#196\`
                                - 主干 L17 \`#197\`
                                - 侧枝 L17.1 \`#198\`
                                - 侧枝 L17.2 \`#199\`
                                - 侧枝 L17.3 \`#200\`
                                - 侧枝 L17.4 \`#201\`
                                  - 主干 L18 \`#202\`
                                  - 侧枝 L18.1 \`#203\`
                                  - 侧枝 L18.2 \`#204\`
                                  - 侧枝 L18.3 \`#205\`
                                  - 侧枝 L18.4 \`#206\`
                                    - 主干 L19 \`#207\`
                                    - 侧枝 L19.1 \`#208\`
                                    - 侧枝 L19.2 \`#209\`
                                    - 侧枝 L19.3 \`#210\`
                                    - 侧枝 L19.4 \`#211\`
                                      - 主干 L20 \`#212\`
                                      - 侧枝 L20.1 \`#213\`
                                      - 侧枝 L20.2 \`#214\`
                                      - 侧枝 L20.3 \`#215\`
                                      - 侧枝 L20.4 \`#216\`
\`\`\`
### 图表

> Mermaid 支持：脑图 mindmap、饼图 pie、时间线 timeline、
> 架构图 flowchart（配 classDef 可任意分色）、时序图、类图、状态图、
> 甘特图、四象限 quadrantChart、折线柱状 xychart、gitGraph、
> 旅程图、ER 图、块图 block-beta。

\`\`\`mermaid
mindmap
  root((渲染器))
    抽象层
      base.js
      registry.js
    实现
      Markdown
      Typst
    增强
      KaTeX
      Mermaid
\`\`\`

彩色架构图（\`classDef\` 分色 —— 输入 / 抽象 / 实现 / 增强 / 输出 五层五色）：

\`\`\`mermaid
flowchart TD
    A[源码文本] --> C{Renderer ABC}
    C --> D[MarkdownRenderer]
    C --> E[TypstRenderer]
    D --> F[KaTeX 公式]
    D --> G[Mermaid 图表]
    F --> H[上屏]
    G --> H
    classDef src fill:#dbeafe,stroke:#3b82f6,color:#1e3a8a
    classDef abs fill:#fef3c7,stroke:#f59e0b,color:#78350f
    classDef impl fill:#dcfce7,stroke:#22c55e,color:#14532d
    classDef out fill:#fee2e2,stroke:#ef4444,color:#7f1d1d
    class A src
    class C abs
    class D,E impl
    class F,G out
    class H out
\`\`\`

饼图：

\`\`\`mermaid
pie showData
    title 各模块代码量占比
    "渲染器基类" : 420
    "Markdown 实现" : 380
    "增强模块" : 210
    "注册表" : 90
\`\`\`

时序图：

\`\`\`mermaid
sequenceDiagram
    participant U as 用户
    participant R as 渲染器
    participant E as 增强模块
    U->>R: setContent(src)
    R->>R: parse()
    R->>E: preprocess / schedule
    E-->>R: 回填公式与图表
    R-->>U: 渲染完成
\`\`\`

⚠️ 注意 \`quadrantChart\` / \`xychart\` 的词法器限制：**轴标签、象限名、分类名、
数据点若含中文，必须用双引号包起来**，否则报 \`Lexical error\`。

\`\`\`mermaid
quadrantChart
    title 渲染器选型评估
    x-axis "实现成本" --> "体积开销"
    y-axis "功能能力" --> "表现力"
    quadrant-1 "理想候选"
    quadrant-2 "过度设计"
    quadrant-3 "暂不考虑"
    quadrant-4 "性价比高"
    KaTeX: [0.3, 0.8]
    Mermaid: [0.6, 0.9]
\`\`\`

\`\`\`mermaid
xychart-beta
    title "各阶段渲染耗时"
    x-axis ["首屏", "公式", "图表", "主题切换"]
    y-axis "耗时 ms" 0 --> 1200
    bar [120, 80, 900, 60]
    line [120, 80, 900, 60]
\`\`\`

### 代码块

\`\`\`js
class TypstRenderer extends Renderer {
  static get tagName() { return 'typst-renderer'; }
  async ensureDeps() { /* 加载 typst wasm */ }
  parse(text) { /* typst 源码 → HTML/SVG */ }
}
\`\`\`

\`\`\`dart
void main() {
  final list = List.generate(5, (i) => i * i);
  print('squares: $list');
}
\`\`\`

### Emoji 与国旗

短代码 :smile: :rocket: :tada: :fire: :sparkles: :heart:
原生 emoji 😀 🚀 🎉 🔥 ✨ ❤️
国旗 🇨🇳 🇺🇸 🇯🇵 🇬🇧 🇩🇪 🇫🇷

### 表格

| 抽象成员 | 类型 | 说明 |
| --- | --- | --- |
| \`ensureDeps()\` | 抽象 | 加载依赖 |
| \`parse()\` | 抽象 | 源码 → HTML |
| \`postProcess()\` | 可选 | 解析后处理 |
| \`shouldDecorateBlock()\` | 可选 | 跳过非代码块 |
| \`onThemeChange()\` | 可选 | 主题切换回调 |
| \`statusItems()\` | 可选 | 状态栏片段 |

---

行内代码 \`const x = 1\`、链接 [WorkBuddy](https://www.workbuddy.cn)。

- [x] 抽象基类抽出
- [x] 注册表按语言分发
- [x] KaTeX 公式 + Mermaid 图表
- [ ] Typst 渲染器
`;

export default async function mount(host) {
  injectStyle();

  host.innerHTML = `
    <div class="mod-renderers">
      <div class="rv-bar">
        <span>渲染器</span>
        <select data-act="pick"><option>加载中…</option></select>
        <span class="sp"></span>
        <button data-act="empty">空态</button>
        <button data-act="reload">重载</button>
      </div>
      <div class="rv-wrap" data-slot></div>
    </div>`;

  const slot = host.querySelector('[data-slot]');
  const pick = host.querySelector('select[data-act="pick"]');

  // ---- 引入渲染器运行时（统一入口）----
  let api = null;
  try {
    api = await import('../../core/renderers/index.js');
    await api.ensureRenderers();
  } catch (e) {
    console.error('[Renderers page] 加载失败', e);
  }

  const available = api ? api.list() : [];
  pick.innerHTML = available.length
    ? available.map((r) => `<option value="${r.tagName}">${r.title}</option>`).join('')
    : '<option value="">（无可用渲染器）</option>';

  let currentEl = null;
  let empty = false;

  // 主题统一由全局主题系统管理（core/theme），本页不再自己记住主题。
  // 渲染器是 Shadow DOM，取不到外部变量，因此靠 theme 属性同步。
  function mountRenderer(tagName) {
    slot.innerHTML = '';
    if (!tagName) {
      slot.innerHTML =
        '<div style="padding:24px;color:var(--ui-danger,#b3261e);font-size:0.9286rem">没有可用的渲染器。</div>';
      currentEl = null;
      return;
    }
    const tag = document.createElement(tagName);
    slot.appendChild(tag);
    currentEl = tag;
    // 新建的元素也要立刻跟上当前主题
    if (window.Theme) window.Theme.sync(slot);
    render();
  }

  function render() {
    if (!currentEl) return;
    // 自定义元素的 tagName 一律是大写，比较时需统一大小写
    const isMd = currentEl.tagName.toLowerCase() === 'md-renderer';
    currentEl.setContent(empty ? '' : (isMd ? SAMPLE_MD : '# 示例'));
  }

  // 初始挂载第一个渲染器
  mountRenderer(available.length ? available[0].tagName : '');

  // ---- 交互 ----
  const onClick = (e) => {
    const btn = e.target.closest('button[data-act]');
    if (!btn) return;
    const act = btn.dataset.act;
    if (act === 'empty') {
      empty = !empty;
      btn.classList.toggle('on', empty);
      render();
    } else if (act === 'reload') {
      render();
    }
  };
  const onChange = (e) => {
    if (e.target === pick) mountRenderer(pick.value);
  };
  host.addEventListener('click', onClick);
  host.addEventListener('change', onChange);

  // 全局主题变化 → 同步到本页的渲染器（含跟随系统自动切换的场景）
  const offTheme = window.Theme
    ? window.Theme.onChange(() => { if (currentEl) currentEl.theme = window.Theme.theme; })
    : null;

  return {
    onShow() {
      if (window.Theme) window.Theme.sync(slot);
    },
    onHide() {},
    destroy() {
      if (offTheme) offTheme();
      host.removeEventListener('click', onClick);
      host.removeEventListener('change', onChange);
      host.innerHTML = '';
    },
  };
}
