# 加解密内核

P.A.L.M 的**统一加解密模块**：国密 SM2 / SM3 / SM4 三重原语 + 密钥库/文件级加解密/硬件指纹（`vault`），
以国密为主、国际算法（AES / RSA / SHA-2 / ChaCha20）可选，摆脱对单一算法族的依赖。

**范围边界（有意不做，不是缺依赖）**：只做**机密性 + 完整性**——不做**数字签名**
（单机单用户无不可否认需求，完整性由 HMAC 承担）、不做**后量子 KEM**
（常规公钥加密已够用，且少一片攻击面）、不做**密钥协商**（单机无对端）。

- **SM3**：密码哈希（256 位，对标 SHA-256）—— 内容指纹、完整性标签
- **SM4**：对称分组密码（128 位分组/密钥，对标 AES-128）—— 记忆正文落盘加密
- **SM2**：椭圆曲线公钥密码（256 位，对标 RSA-2048）—— 密钥信封（公钥加密原语）
- **vault**：主密钥生命周期（硬件指纹密封密钥库 + 恢复密钥）+ 文件级加解密
  （自 P.A.L.M `palm/adapters/crypto` 收敛而来，P.A.L.M 侧仅剩 shim）
- **C 加速后端**：装 `pip install tongsuopy`（铜锁，PyPI 最新 **1.0.1**）后自动启用——
  本机实测（1MB 缓冲，无 base64）：**SM3 436 MB/s、SM4-CBC 126/146 MB/s（加/解）、
  HMAC-SM3 378 MB/s**，比纯 Python 快 **2 个数量级**；未装则回退纯 Python gmssl
  （~0.2–0.3 MB/s）。两后端经 GB/T 32907-2016 国标向量与互操作验证，**密文逐字节一致**，
  存量数据不受换后端影响（`palm_cryptokernel.backends.backend_name()` 可查当前后端）。

## 运行方式（内嵌，无需安装）

本目录是 P.A.L.M 主目录下的**内嵌独立项目**：源码自带、开箱即用，**不需要 pip install**。
在 P.A.L.M 主目录内先导入自举内核即可（见主目录 `palm_boot.py`）：

```python
import palm_boot            # 自动把 加解密内核/ 等内嵌项目挂进 sys.path
from palm_cryptokernel import MemoryCipher
```

唯一第三方依赖：`gmssl`（纯 Python，BSD 协议）—— 环境里装好即可，无网络也能跑。

## 快速开始

### 记忆落盘加密（对接 VectorMemory）

```python
from palm_cryptokernel import MemoryCipher

# 方式一：从环境变量读取密钥（32 位 hex）
import os
os.environ["PALM_CRYPTO_KEY"] = "3f5b0d1e26a7c3133f5b0d1e26a7c31"  # 32 位 hex = 16 字节密钥
cipher = MemoryCipher.from_env()

# 方式二：随机生成并落盘密钥文件
cipher = MemoryCipher.generate(key_file="memory.key")  # 私钥离线保管！

enc = cipher.encrypt_text("用户偏好：喜欢猫娘，讨厌被叫作 AI")
dec = cipher.decrypt_text(enc)
assert dec == "用户偏好：喜欢猫娘，讨厌被叫作 AI"

# 稳定内容指纹（替代跨进程随机化的 hash()）
h = cipher.content_hash("同一段文本")   # 任意进程结果一致
```

### 接入 VectorMemory

```python
from palm_memory.domain_memory.vector_memory import VectorMemory
from palm_cryptokernel import MemoryCipher

cipher = MemoryCipher.generate(key_file="memory.key")
vm = VectorMemory(persist_dir="Data/vector_memory", cipher=cipher)
vm.initialize()
vm.add("用户最喜欢蓝色")
print(vm.search("用户喜欢什么颜色", top_k=3))
```

### SM2 密钥信封（密钥与数据分离）

```python
from palm_cryptokernel import Sm2Key, Sm4Cipher

sm2k = Sm2Key.generate()
sm4_key = Sm4Cipher.random_key()
wrapped = sm2k.encrypt(sm4_key)          # 用 SM2 公钥加密 SM4 密钥，随数据存库
# 离线保管 sm2k.private_key；解密时用私钥还原 sm4_key
```

## 设计要点

- **默认对称加密（SM4-CBC）**：落盘开销低、实现简单，满足单机 Agent 记忆的静态加密需求。
- **可选完整性标签**：解密时校验 SM3 摘要，被篡改/损坏的密文返回空串而非错误内容。
- **可选 SM2 信封**：SM4 密钥用 SM2 公钥加密后入库，私钥离线保管，实现"密钥分离"。
- **公钥信封（`families.envelope`）**：任意长正文走 AEAD，其数据密钥用 SM2/RSA 信封封装；
  报文自描述（算法名与长度前缀内嵌），数据密钥与 nonce **逐条新生成**，
  从结构上杜绝"同一密钥配同一 nonce"这类致命误用。
- **content_hash 修复**：Python 原生 `hash()` 受 `PYTHONHASHSEED` 影响跨进程随机化，
  ChromaDB 持久化去重会失效；改用 SM3 指纹保证跨进程稳定。
- **向后兼容**：`decrypt_text` 对旧明文 / 解码失败数据原样返回；无 tag 的密文也能解密。
- **最小权限落盘（`_private_fs`）**：密钥/明文一律 0600（POSIX）/ 仅当前用户（Windows）。
  Windows 的 `icacls` 是**子进程**（≈15–22ms/次），故按「**同一对象只收紧一次**」实现——
  自管目录带 `(OI)(CI)` 继承位（子文件自动继承）、文件按**身份**（`st_dev,st_ino`）缓存
  （删后重建即失效重收紧）。**覆盖写同一文件**时 icacls 残量 ~1%（1KB 写 0.21ms，
  1MB 加密 14.2ms）；⚠️ 已知边界：**每个文件只写一次**的批量场景仍逐文件付一次
  （任意目录不能做目录级收紧）——详见 `docs/`。

## vault：密钥库 / 文件级加解密

```python
from palm_cryptokernel import vault

# 数据位置（密钥库/校验码落盘处）：默认 PALM_CRYPTO_HOME 或 ~/.palm_cryptokernel
vault.set_data_dir(r"D:\somewhere\.keys")   # 须在 boot() 之前调用

vault.boot()                                 # 绑定硬件指纹 → 加载/生成主密钥 → 就绪
print(vault.is_bound(), vault.fingerprint_prefix())

ct = vault.encrypt_data(b"机密数据")         # SM4-CBC + HMAC-SM3（iv+密文+认证标签）
pt = vault.decrypt_data(ct)

enc = vault.encrypt_file("report.txt")       # 文件级 → report.txt.enc
vault.decrypt_file(enc, "report_restored.txt")

# 换机恢复：凭 32 位 hex 恢复密钥（主密钥明文）导入
from palm_cryptokernel.vault.operations import set_master_key
set_master_key(bytes.fromhex("<32位hex恢复密钥>"))
```

## 内核级工程件

本模块按 P.A.L.M「内核」标准（对照 `LLM内核`）配备工程件：源码 + 测试 + 示例 +
依赖声明 + 基准 + 设计文档 + 质量/安全证据。

```
加解密内核/
  README.md                    # 本文件（定位 / 用法 / 工程件）
  requirements.txt             # 依赖声明（gmssl 必需；tongsuopy 可选 C 加速）
  palm_cryptokernel/                 # 源码
    __init__.py                # 对外门面（sm3_hash / Sm4Cipher / Sm2Key / MemoryCipher / vault）
    backends.py                # SM4/SM3 后端：C（tongsuo）优先、纯 Python（gmssl）保底
    sm3.py  sm4.py  sm2.py     # 国密三重原语
    cipher.py                  # MemoryCipher（对接 VectorMemory 落盘加密）
    _private_fs.py             # 私有落盘助手（最小权限；同一对象只收紧一次，见 docs）
    families/                  # 族薄接口（hash/mac/kdf/cipher/aead/pubkey/envelope）
    providers/                 # 各密码学库的适配实现（Cryptodome/hashlib/gmssl/argon2cffi）
    vault/                     # 密钥库 / 文件级加解密 / 硬件指纹
  tests/                       # 单元测试（无 pytest，统一 python -m unittest）
    test_sm3.py                # GB/T 32905-2016 标准向量 + 接口契约
    test_sm4.py                # GB/T 32907-2016 标准向量（零 IV CBC 对拍 ECB）+ CBC/base64 契约
    test_sm2.py                # 加解密 / 密钥信封 / 缺钥守卫
    test_backends.py           # 后端探测 + HMAC-SM3 + PKCS7 填充
    test_private_fs.py         # 最小权限落盘：缓存**不削弱**安全（文件身份/目录继承/失败重试）
    test_cipher.py             # 四种密钥来源 / 完整性标签 / 篡改检测 / content_hash
    test_vault.py              # 密钥库密封 / 数据与文件加解密 / 篡改拒绝 / 指纹密封
  examples/
    basic_usage.py             # 可直接运行的四段示例
  benchmarks/
    bench_palm_cryptokernel.py       # 国密原语吞吐基准
    bench_concurrency_tp999.py # 并发基准
    bench_crypto_audit.json    # 基准结果（审计口径）
    bench_concurrency_tp999.json  # 并发基准结果
  docs/                        # 设计/审计文档（纯中文 + 版本号）
    统一加解密模块_安全与性能审计_v1.0.md
    C后端换装与并发基准_v1.0.md
  security_kernel.json         # 安全证据（dynprobe --kind security）
  codequal_kernel.json         # 代码质量证据（codequal --dims all）
```

**运行方式**（在项目根目录内执行；无须安装）：

```bash
python -m unittest discover -s tests -v   # 跑全部单元测试
python examples/basic_usage.py            # 跑用法示例
```

单元测试硬编码**国标测试向量**对拍（SM3 GB/T 32905-2016、SM4 GB/T 32907-2016），
非本库自产，杜绝循环验证；SM4 单块向量经「全零 IV 的 CBC 首块 == ECB」复用 CBC
接口校验，无需额外暴露 ECB 入口。
