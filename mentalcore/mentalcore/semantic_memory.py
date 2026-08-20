"""语义记忆适配器：桥接 palm.domain.memory.vector_memory.VectorMemory。

- 底层 ChromaDB 持久化 + Ollama bge-m3 嵌入（经网卡门面出网，localhost 回环放行）。
- 惰性初始化：构造时不建立 ChromaDB 客户端（避免 Windows 下 SQLite 文件锁导致
  临时目录无法清理），首次 add/search 时才真正建库；初始化失败 → available=False，
  记忆面自动退化为仅近期对话（fail-operational），不阻断主流程。
- clear() 用于防污染删除链路：关闭客户端释放锁 → 清空目录 → 置惰性（下次操作重建）。
"""
import logging
import shutil

from .logging_setup import get_logger

_logger = get_logger()

try:
    from palm.domain.memory.vector_memory import VectorMemory
    _HAS_PALM_VM = True
except Exception:
    VectorMemory = None
    _HAS_PALM_VM = False


class SemanticMemory:
    """长期语义记忆封装；add/search 失败静默降级。"""

    def __init__(self, chroma_dir: str, cipher=None):
        self.chroma_dir = chroma_dir
        # 可选加密器（encrypt_text/decrypt_text）：向量文档加密落盘；None=明文
        self._cipher = cipher
        # 探测可用性（VectorMemory 可导入即乐观可用）；真实建库延迟到首次操作
        self.available = bool(_HAS_PALM_VM)
        self._vm = None
        if not _HAS_PALM_VM:
            _logger.warning("palm VectorMemory 不可导入，语义记忆关闭（仅近期对话）")

    def _ensure_vm(self):
        """惰性建库：首次操作时初始化 VectorMemory；失败则置不可用。"""
        if self._vm is not None:
            return self._vm
        if not _HAS_PALM_VM:
            self.available = False
            return None
        try:
            vm = VectorMemory(persist_dir=self.chroma_dir, cipher=self._cipher)
            vm.initialize()
            if vm.is_ready:
                self._vm = vm
                self.available = True
            else:
                self.available = False
                _logger.warning("ChromaDB 初始化失败，语义记忆关闭（仅近期对话）")
        except Exception as exc:
            self.available = False
            _logger.warning("语义记忆初始化异常，关闭：%s", exc)
        return self._vm

    def add(self, text: str, metadata: dict | None = None) -> str | None:
        vm = self._ensure_vm()
        if vm is None:
            return None
        try:
            return vm.add(text, metadata)
        except Exception as exc:
            _logger.warning("语义记忆写入失败：%s", exc)
            return None

    def search(self, query: str, top_k: int = 5) -> list:
        vm = self._ensure_vm()
        if vm is None:
            return []
        try:
            return vm.search(query, top_k)
        except Exception as exc:
            _logger.warning("语义记忆检索失败：%s", exc)
            return []

    def count(self) -> int:
        vm = self._ensure_vm()
        if vm is None:
            return 0
        try:
            return vm.count()
        except Exception:
            return 0

    def clear(self) -> None:
        """防污染删除：关闭客户端释放锁 → 清空目录 → 置惰性（下次操作重建）。

        仅当曾真正可用（有真实落盘数据）时才触碰目录；从未写入则仅复位状态。
        """
        had_vm = self._vm is not None
        if had_vm:
            try:
                self._vm.close()  # palm close 已改：真正关闭 client 释放 SQLite 锁
            except Exception:
                pass
            self._vm = None
        self.available = bool(_HAS_PALM_VM)
        if not had_vm:
            return
        try:
            import os
            if os.path.isdir(self.chroma_dir):
                shutil.rmtree(self.chroma_dir)
        except Exception as exc:
            _logger.warning("向量归档目录清理失败（已降级）：%s", exc)

    def close(self) -> None:
        """释放资源（关闭客户端、释放文件锁）；下次操作自动重建。"""
        if self._vm is not None:
            try:
                self._vm.close()
            except Exception:
                pass
            self._vm = None
        self.available = bool(_HAS_PALM_VM)
