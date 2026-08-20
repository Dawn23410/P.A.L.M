"""储存面：对话记录（加密落盘）+ 对外控制码（设计 §6.12）。

- 存完整对话记录（落盘均经 CryptoProvider 加密；未启用则明文降级）。
- 不产 prompt 模块：它是存储与对外控制面，非 prompt 影响面。
- 处理 inbound 控制码（储存域：查/清/导出等），按 D2 子类路由；
  向量归档的查/清委托给 SemanticMemory（防污染删除链路）。
"""
import json
import os

from .base import BaseFace
from ..transport import ControlCode


class StorageFace(BaseFace):
    name = "storage"

    def __init__(self, path: str = "mentalcore_data/conversations",
                 crypto=None, semantic_memory=None):
        self.path = path
        os.makedirs(path, exist_ok=True)
        self.record_file = os.path.join(path, "conversations.dat")
        self.crypto = crypto
        self.semantic_memory = semantic_memory

    # —— 对话记录（加密落盘）——
    def save_turn(self, user: str, assistant: str):
        line = json.dumps({"user": user, "assistant": assistant},
                          ensure_ascii=False)
        enc = self.crypto.encrypt_text(line) if self.crypto else line
        with open(self.record_file, "a", encoding="utf-8") as f:
            f.write(enc + "\n")

    # —— 好感度状态（加密落盘，重启恢复；防污染清档不清好感度）——
    def save_affinity(self, base, bond, dynamics):
        line = json.dumps({"base": base, "bond": bond, "dynamics": dynamics})
        enc = self.crypto.encrypt_text(line) if self.crypto else line
        with open(os.path.join(self.path, "affinity.dat"), "w",
                  encoding="utf-8") as f:
            f.write(enc)

    def load_affinity(self) -> dict:
        path = os.path.join(self.path, "affinity.dat")
        if not os.path.exists(path):
            return {"base": 0.0, "bond": 0.0, "dynamics": 0.0}
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = f.read().strip()
            plain = self.crypto.decrypt_text(raw) if self.crypto else raw
            data = json.loads(plain)
            return {
                "base": float(data.get("base", 0.0)),
                "bond": float(data.get("bond", 0.0)),
                "dynamics": float(data.get("dynamics", 0.0)),
            }
        except Exception:
            # 文件损坏/解密失败：回退初始态，不阻断启动
            return {"base": 0.0, "bond": 0.0, "dynamics": 0.0}

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
                    plain = self.crypto.decrypt_text(line) if self.crypto else line
                    out.append(json.loads(plain))
                except Exception:
                    continue
        return out

    def clear_records(self):
        """防污染删除：清空全部对话记录（截断文件，逻辑等价且无需删除文件）。"""
        if os.path.exists(self.record_file):
            open(self.record_file, "w", encoding="utf-8").close()

    def encryption_status(self) -> str:
        return self.crypto.status() if self.crypto else "未配置加密"

    # —— 控制码处理（inbound，储存域）——
    def handle_control(self, code: ControlCode, payload: dict | None = None):
        """解析五位控制码，按 D2 子类路由；响应码沿用 D1/D2/D4，回显成功。

        颗粒度：D4=0 全部 / D4=1 最近N条（payload.limit）/ D4=2 指定编号（payload.index）；
        D3=2 导出走 JSON 明文返回（2000 字截断防爆）。
        """
        payload = payload or {}
        if code.d1 != 1:
            return None, "非储存域控制码"
        # D2=1 向量归档
        if code.d2 == 1:
            if code.d3 == 1:
                if self.semantic_memory:
                    self.semantic_memory.clear()
                return ControlCode.make(1, 1, 1, code.d4, 1), "已清空向量归档"
            if code.d3 == 0:
                n = self.semantic_memory.count() if self.semantic_memory else 0
                return ControlCode.make(1, 1, 0, code.d4, 1), f"向量归档数：{n}"
            return None, "未处理的向量归档控制码"
        # D2=3 加密状态
        if code.d2 == 3:
            if code.d3 == 0:
                return ControlCode.make(1, 3, 0, code.d4, 1), self.encryption_status()
            return None, "未处理的加密控制码"
        # D2=0 对话记录（默认）
        if code.d3 == 1:
            return self._clear_records_by(code.d4, payload)
        if code.d3 == 0:
            return self._query_records(code.d4, payload)
        if code.d3 == 2:
            text = json.dumps(self.load_history(), ensure_ascii=False)
            if len(text) > 2000:
                text = text[:2000] + "…（已截断）"
            return ControlCode.make(1, 0, 2, code.d4, 1), text
        return None, "未处理的储存控制码"

    def _query_records(self, obj: int, payload: dict):
        """查对话记录：0=条数 / 1=最近N条明细 / 2=指定编号条。"""
        hist = self.load_history()
        if obj == 1:
            n = max(1, int(payload.get("limit", 3)))
            rows = hist[-n:]
            if not rows:
                return ControlCode.make(1, 0, 0, obj, 1), "（无对话记录）"
            lines = []
            for i, turn in enumerate(rows, start=max(0, len(hist) - n)):
                lines.append(f"[{i}] 用户：{turn.get('user', '')}")
                lines.append(f"    回复：{turn.get('assistant', '')}")
            return ControlCode.make(1, 0, 0, obj, 1), "\n".join(lines)
        if obj == 2:
            idx = int(payload.get("index", -1))
            if not (0 <= idx < len(hist)):
                return ControlCode.make(1, 0, 0, obj, 2), f"编号越界（0~{max(0, len(hist) - 1)}）"
            turn = hist[idx]
            return ControlCode.make(1, 0, 0, obj, 1), (
                f"[{idx}] 用户：{turn.get('user', '')}\n    回复：{turn.get('assistant', '')}")
        return ControlCode.make(1, 0, 0, obj, 1), f"记录数：{len(hist)}"

    def _clear_records_by(self, obj: int, payload: dict):
        """清对话记录：0=全部 / 1=最近N条（保留更早）/ 2=指定编号条。"""
        if obj == 0:
            self.clear_records()
            return ControlCode.make(1, 0, 1, obj, 1), "已清空对话记录"
        hist = self.load_history()
        if obj == 1:
            n = max(1, int(payload.get("limit", 3)))
            keep = hist[:-n]
            self._rewrite(keep)
            return ControlCode.make(1, 0, 1, obj, 1), f"已清最近 {min(n, len(hist))} 条，保留 {len(keep)} 条"
        if obj == 2:
            idx = int(payload.get("index", -1))
            if not (0 <= idx < len(hist)):
                return ControlCode.make(1, 0, 1, obj, 2), f"编号越界（0~{max(0, len(hist) - 1)}）"
            removed = hist.pop(idx)
            self._rewrite(hist)
            return ControlCode.make(1, 0, 1, obj, 2), (
                f"已删除 [{idx}]（用户：{str(removed.get('user', ''))[:20]}…）")
        return None, "未处理的清除对象"

    def _rewrite(self, hist: list) -> None:
        """整档重写对话记录（清最近N条/删指定条用，逐条加密）。"""
        with open(self.record_file, "w", encoding="utf-8") as f:
            for turn in hist:
                line = json.dumps(turn, ensure_ascii=False)
                enc = self.crypto.encrypt_text(line) if self.crypto else line
                f.write(enc + "\n")
