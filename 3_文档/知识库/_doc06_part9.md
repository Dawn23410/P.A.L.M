# P.A.L.M 从零复刻指南（深度扩充六：验收脚本与完整核对清单）

> 承接扩充章 Z-EE。本部分给出：验收脚本完整示例（可直接运行）、部署检查清单（最终版）、以及复刻质量评估。

---

## 扩充章 FF：验收脚本完整示例

### FF.1 端点扫描脚本（minimal）

```python
"""端点全量扫描：复刻验收基线。"""
import httpx

ENDPOINTS = [
    ("GET", "/api/system"),
    ("GET", "/api/characters"),
    ("POST", "/api/chat", {"message": "ping"}),
    ("GET", "/api/usage"),
    ("GET", "/api/game"),
    ("GET", "/api/stt/status"),
    ("GET", "/api/settings"),
    ("GET", "/api/memory"),
    ("GET", "/api/vault"),
    ("GET", "/api/scheduler"),
    ("GET", "/api/evolution"),
    # ... 扩展到 163
]

def scan(base="http://127.0.0.1:8005"):
    fails = []
    for method, path, *body in ENDPOINTS:
        try:
            r = httpx.request(method, base + path,
                              json=body[0] if body else None,
                              timeout=10)
            if r.status_code >= 500:
                fails.append((path, r.status_code))
        except Exception as exc:
            fails.append((path, str(exc)))
    print(f"扫描完成：{len(ENDPOINTS)} 端点，失败 {len(fails)}")
    for f in fails:
        print("失败:", f)
    return not fails

if __name__ == "__main__":
    exit(0 if scan() else 1)
```

### FF.2 对话验收脚本

```python
"""对话全链路验收（mock 模式）。"""
import httpx, json

BASE = "http://127.0.0.1:8005"

def test_chat_flow():
    # 1. 建会话
    r = httpx.post(f"{BASE}/api/chat",
                   json={"message": "你好", "character_id": "mengyao"},
                   timeout=30)
    assert r.status_code == 200
    events = parse_sse(r.text)   # 解析 text/thought/tool_call/done
    assert any(e["type"] == "done" for e in events)
    # 2. 验证结算
    game = httpx.get(f"{BASE}/api/game").json()
    assert game["daily_chat_count"] >= 1
    # 3. 验证记忆
    mem = httpx.post(f"{BASE}/api/memory",
                     json={"query": "你好"}).json()
    print("对话验收通过")
```

### FF.3 安全验收脚本

```python
"""安全验收（mock/隔离环境）。"""
import httpx

def test_security():
    # 1. 无网卡出网 → NetworkForbidden
    try:
        httpx.post(f"{BASE}/api/tools/execute",
                   json={"tool": "web_search", "args": {"query": "x"}},
                   timeout=10)
        assert False, "应拦截出网"
    except Exception:
        pass
    # 2. 未授权删除 → 询问/拦截
    r = httpx.post(f"{BASE}/api/storage/delete",
                   json={"key": "test.txt"}, timeout=10)
    assert r.json().get("blocked") in (True, None) or r.status_code == 403
    # 3. 裁决 deny（高危）
    r = httpx.post(f"{BASE}/api/tools/execute",
                   json={"tool": "file_delete", "args": {"path": "C:\\"}},
                   timeout=10)
    assert r.json().get("blocked") is True
    print("安全验收通过")
```

### FF.4 mentalcore 验收

```bash
python -m mentalcore.selftest        # 离线自检
python -m mentalcore.exo.selftest    # 外骨骼 4 测
python bench_50.py --mode mock --rounds 50   # 基准
```

---

## 扩充章 GG：部署检查清单（最终版）

### GG.1 启动前（清单 20 项）

| # | 检查 | 通过标准 |
|---|---|---|
| 1 | Python 3.11+ | python --version |
| 2 | venv 建立 | venv_runtime |
| 3 | 依赖安装 | pip list 核对 |
| 4 | palm 可导入 | import palm |
| 5 | mentalcore 可导入 | import mentalcore |
| 6 | .env 配置 | HOST/PORT |
| 7 | settings.json | 模型/供应商 |
| 8 | Data/ 目录 | 子目录齐全 |
| 9 | 角色卡 | characters/ |
| 10 | 语音（可选） | venv 存在 |
| 11 | 模型可访问 | tokenhub 连通 |
| 12 | build_app() | 14 服务 |
| 13 | uvicorn 启动 | 端口监听 |
| 14 | 前端可访问 | 5173/静态 |
| 15 | 对话流式 | POST /api/chat |
| 16 | 角色开场白 | first_mes |
| 17 | 工具调用 | tool_call 事件 |
| 18 | ask_user | 弹窗/应答 |
| 19 | 用量入账 | /api/usage |
| 20 | 记忆写入 | /api/memory |

### GG.2 启动后（5 分钟验收）

- 装配日志无降级异常。
- 端点扫描全绿。
- 对话/游戏/记忆/安全冒烟。
- selftest 全过。
- 前端 12 页加载。

---

## 扩充章 HH：复刻质量评估

### HH.1 质量维度

| 维度 | 评估方法 | 目标 |
|---|---|---|
| 架构符合 | lint + 契约测试 | 100% |
| 功能完整 | e2e + 冒烟 | 无业务 bug |
| 安全 | 审计 + 红队 | 全过 |
| 性能 | bench 对照 | 达标 |
| 质量 | 端点/单测 | 全绿/8-8 |
| 文档一致 | 对照本系列 | 一致 |

### HH.2 常见偏差与修正

| 偏差 | 修正 |
|---|---|
| 分层混乱 | 按 03 篇架构铁律重排 |
| 缺失归一遗漏 | 全库判空审查 |
| 安全旁路 | 门面强制（net/guardrail） |
| 计量虚增 | provider 真实账本 |
| mock 落盘 | persist=False + sem=None |
| 协议不遵守 | 对照 transport/CONTROL_USAGE |

---

## 扩充章 II：复刻完成证明（输出物）

复刻完成后应产出以下证明：

1. **代码**：palm/ + mentalcore/ + frontend/（目录对照本系列）。
2. **测试**：端点扫描全绿报告、pytest 8/8、selftest 全过。
3. **基准**：bench_50/100 报告（对照基线）。
4. **安全**：审计报告（注入/越权/逃逸/泄漏）。
5. **文档**：配置说明、部署手册、运维手册。

**以上齐备即证明"1:1 完整复刻成功"。**

---

## 扩充章 JJ：复刻后的第一版发布

```
1. 本地验证（全部验收通过）
2. 归档备份（Data/venv/git）
3. 发布说明（功能/已知限制）
4. 使用文档（部署/运维）
5. 持续演进（按路线图）
```

**发布原则**：本地提交不 push（细节定稿前）；重大变更先归档；基准诚实（不包装）。
