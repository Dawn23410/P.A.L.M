# palm-ollama

Ollama 嵌入适配器 + 本地模型管理工作区（**内嵌独立项目**）。

> **对话不在本包。** 模型调用（`/api/chat`）已统一收归
> `LLM内核/palm_llm`，见 `palm_llm.providers.OllamaProvider`（配置写 `type: "ollama"`）。
> 这样本包保持**零第三方依赖**（仅标准库），可被记忆层等底层模块安全引用。
> 详见 `LLM内核/docs/Ollama原生适配_v1.0.md`。

本包职责：

| 模块 | 说明 |
|---|---|
| `OllamaEmbedder` | 原生 `/api/embed` 嵌入。从 P.A.L.M 记忆层 `palm-memory/palm_memory/domain_memory/vector_memory.py` 的 Ollama 回退代码中抽取。记忆层现已改为**纯本地 ONNX（bge-m3）**，Ollama 不再作为回退路径；仅作可选外部嵌入后端。 |
| `palm_ollama.workspace` | 本地模型工作区：目录浏览、模型文件下载与传输。 |

> 运行方式：本目录是 P.A.L.M 主目录下的**内嵌项目**，源码自带、开箱即用，
> **无需 pip install**；在 P.A.L.M 主目录内 `import palm_boot` 即自动挂载（见主目录 `palm_boot.py`）。

## 设计要点

- **fail-closed**：嵌入的主模型失败自动降级后备模型（`mxbai-embed-large:latest`），
  全不可用返回 `None`，绝不抛异常。
- **零第三方依赖**：仅经包级 `_net` 出网（主工程在场走网卡门面，否则标准库 `urllib` 降级）。
- **维度一致性**：Ollama 主/后备嵌入模型需与目标向量库维度一致（bge-m3 / mxbai-embed-large 均为 1024 维）。

## 用法

```python
import palm_boot  # noqa: F401  自举：挂载 palm-ollama/ 等内嵌项目

from palm_ollama import OllamaEmbedder

emb = OllamaEmbedder(
    base_url="http://127.0.0.1:11434",
    model="bge-m3:latest",
    fallback_model="mxbai-embed-large:latest",
).embed(["今天天气真好", "另一句话"])
# -> list[list[float]]（1024 维）或 None（Ollama 未运行 / 模型缺失）
```

对话请改用内核 provider：

```python
from palm_llm import get_provider_instance, ProviderConfig, Message, ModelParameters

prov = get_provider_instance(ProviderConfig(
    name="ollama", type="ollama",                   # 原生协议，base_url 不带 /v1
    base_url="http://127.0.0.1:11434", default_model="spark-x2.5:1.7b"))

params = ModelParameters(max_tokens=256, extra_body={"think": False})  # 关思考
async for ev in prov.complete([Message(role="user", content="你好")], params, "spark-x2.5:1.7b"):
    ev.get("reasoning")   # 思维链增量
    ev.get("content")     # 正文增量
```

## 与记忆层的关系

| 项 | 变更前 | 变更后 |
|---|---|---|
| 向量记忆嵌入后端 | 本地 ONNX 优先 → Ollama 回退 | 仅本地 ONNX（失败返回 None，由调用方降级 lexical） |
| Ollama 代码位置 | 内联在 `vector_memory.py` | 内嵌独立项目 `palm-ollama`（`OllamaEmbedder`） |
| 是否仍作回退 | 是 | **否** |

记忆层已确保其"只有 ONNX"；本包保留 Ollama 嵌入能力以便独立复用，但不回灌进记忆向量路径。
