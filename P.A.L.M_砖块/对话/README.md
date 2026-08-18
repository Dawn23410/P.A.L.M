# 对话

> 独立砖块副本（由 P.A.L.M 主板架构拆分）
> 原英文砖名：`chat` ｜ 总线类型：`board`

本文件夹是「对话」砖的物理独立副本，用于**完全独立的单元测试 / 模块测试**。
原代码位于项目 `backend/app/bricks/chat`，本副本与之内容一致（截至拆分日），可单独安装依赖、单独运行。

## 目录

- `src/`：砖块代码（与原始包结构一致，可直接 `import src` 或按子模块导入）

## 独立运行 / 测试

本砖已用 [uv](https://github.com/astral-sh/uv) 建立独立虚拟环境：

```bash
cd 对话
uv venv                 # 已执行：生成 .venv
uv pip install -r requirements.txt
uv run python -c "import src; print('对话 import OK')"
```

## 依赖说明

`requirements.txt` 取自项目根 `requirements.txt`（全量后端依赖）。
在完全独立的测试里，绝大多数砖真正需要的依赖是子集——可按需裁减以加速安装。
本砖的关键依赖见 `src/` 各模块 import；若仅需静态/单元验证，可只保留 fastapi/pydantic 等核心项。

## 注意

- 本副本**不**反向依赖 `backend/app/bricks`（零互导契约）；其跨砖能力经主板
  `backend/app/bricks/_shared` 暴露，独立测试时该共享层也需一并纳入（见「主板」文件夹）。
- 修改请同步回 `backend/app/bricks/chat/`，本文件夹仅作独立测试沙盒。
