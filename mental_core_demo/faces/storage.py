"""储存面：对话记录 + 向量归档落盘 + 控制码处理（设计 §6.12）。

- 存完整对话记录、记忆向量归档（落盘均加密）。
- 加密层为演示级、零依赖（标准库派生密钥 + 流密码）；真实接入换 crypto 芯片（SM4 国密）。
- 不产 prompt 模块：它是存储与对外控制面，非 prompt 影响面。
- 处理 inbound 控制码（储存域：查/清/导出等），按 D2 子类路由。
"""
import hashlib
import json
import os

from .base import BaseFace
from ..transport import ControlCode

# demo 加密密钥（真实环境由 crypto 芯片持有，禁止其他组件持有）
_DEMO_KEY = b"mental_core_demo_key_v1"


def _keystream(seed: bytes, length: int) -> bytes:
    """由种子派生确定性伪随机流（演示加密，非高强度）。"""
    out = b""
    block = seed
    while len(out) < length:
        block = hashlib.sha256(block).digest()
        out += block
    return out[:length]


def _encrypt(plain: str) -> str:
    """加密：返回 hex（含种子前缀，便于解密）。"""
    data = plain.encode("utf-8")
    # 每行为独立加密单元，种子含内容哈希 + 固定密钥，避免跨行相同明文同密文
    seed = hashlib.sha256(_DEMO_KEY + data).digest()
    ks = _keystream(seed, len(data))
    cipher = bytes(a ^ b for a, b in zip(data, ks))
    return (seed + cipher).hex()


def _decrypt(blob: str) -> str:
    """解密：从 hex 还原明文。"""
    raw = bytes.fromhex(blob)
    seed = raw[:32]
    cipher = raw[32:]
    ks = _keystream(seed, len(cipher))
    return bytes(a ^ b for a, b in zip(cipher, ks)).decode("utf-8", errors="ignore")


class StorageFace(BaseFace):
    name = "storage"

    def __init__(self, path: str = "mental_core_demo/.data"):
        self.path = path
        os.makedirs(path, exist_ok=True)
        self.record_file = os.path.join(path, "conversations.dat")
        self.vector_file = os.path.join(path, "vectors.dat")

    # —— 对话记录（加密落盘）——
    def save_turn(self, user: str, assistant: str):
        line = json.dumps({"user": user, "assistant": assistant},
                          ensure_ascii=False)
        with open(self.record_file, "a", encoding="utf-8") as f:
            f.write(_encrypt(line) + "\n")

    def load_history(self) -> list:
        if not os.path.exists(self.record_file):
            return []
        out = []
        with open(self.record_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(_decrypt(line)))
                except Exception:
                    continue
        return out

    def clear_records(self):
        """防污染删除：清空全部对话记录。"""
        if os.path.exists(self.record_file):
            os.remove(self.record_file)

    # —— 向量归档（加密落盘，记忆面写入，防污染链路清除）——
    def save_vector_record(self, text: str):
        line = json.dumps({"text": text}, ensure_ascii=False)
        with open(self.vector_file, "a", encoding="utf-8") as f:
            f.write(_encrypt(line) + "\n")

    def load_vectors(self) -> list:
        if not os.path.exists(self.vector_file):
            return []
        out = []
        with open(self.vector_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(_decrypt(line)).get("text", ""))
                except Exception:
                    continue
        return out

    def clear_vectors(self):
        """防污染删除：清空向量归档。"""
        if os.path.exists(self.vector_file):
            os.remove(self.vector_file)

    def encryption_status(self) -> str:
        return "演示级流密码（真接 crypto 芯片 SM4）"

    # —— 控制码处理（inbound，储存域）——
    def handle_control(self, code: ControlCode):
        """解析五位控制码，按 D2 子类路由；响应码沿用 D1/D2/D4，改 D3 回显与 D5=成功。"""
        if code.d1 != 1:
            return None, "非储存域控制码"
        # D2=1 向量归档
        if code.d2 == 1:
            if code.d3 == 1:
                self.clear_vectors()
                return ControlCode.make(1, 1, 1, code.d4, 1), "已清空向量归档"
            if code.d3 == 0:
                n = len(self.load_vectors())
                return ControlCode.make(1, 1, 0, code.d4, 1), f"向量归档数：{n}"
            return None, "未处理的向量归档控制码"
        # D2=3 加密状态
        if code.d2 == 3:
            if code.d3 == 0:
                return ControlCode.make(1, 3, 0, code.d4, 1), self.encryption_status()
            return None, "未处理的加密控制码"
        # D2=0 对话记录（默认）
        if code.d3 == 1:
            self.clear_records()
            return ControlCode.make(1, 0, 1, code.d4, 1), "已清空对话记录"
        if code.d3 == 0:
            n = len(self.load_history())
            return ControlCode.make(1, 0, 0, code.d4, 1), f"记录数：{n}"
        return None, "未处理的储存控制码"
