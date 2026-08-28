"""外骨骼微核心（Work 大魔方）：WorkCore + WorkCube（对外插槽）。

WorkCore 采用归档双 Agent 设计（移植自 palm dual_core/dual_runner/dual_plan）：
- 原生 function-calling 循环（ExoLLM.complete(prompt, tools) → {text, tool_calls}），
  文本标记 ||TOOL||/||FIN|| 仅作兼容兜底；
- 提示构建沿用归档 NATIVE 模板（exo.prompt），专业记忆注入（ProfessionalMemory）；
- 反思自检（exo.runner.reflect_once）+ 自主规划（exo.plan_engine.PlanEngine，use_planning）；
- 干预队列（cancel/pause/resume/redirect）+ 轨迹存储（TraceStore，经 CommCube 审计）。

WorkCube 实现 ExoSlotPort（心智魔方那「一个 tool」）：后台线程拉起 Worker，完成回传 Boss。
"""
import json
import queue
import threading
from abc import ABC, abstractmethod

from .protocol import parse_worker_output, extract_exo
from .cubes import (ToolCube, SandboxCube, PlanCube, CommCube,
                    ProfessionalMemory, SecurityCube)
from .intent_router import IntentRouter, IntentResult
from security.prompt import build_worker_prompt
from .runner import reflect_once
from security.dual_parse import _should_reflect
from .trace_store import T_INTERVENTION, T_PLAN


class ExoSlotPort(ABC):
    """外骨骼对外边界（唯一可见接口，即心智魔方那「一个 tool」）。"""

    @abstractmethod
    def submit_async(self, task_goal: str, context: str, boss_core):
        """后台拉起 Worker（不阻塞 Boss）。"""

    @abstractmethod
    def get_status(self) -> dict:
        """返回 Worker 状态。"""

    @abstractmethod
    def query_trace(self, keyword: str = "") -> list:
        """检索 Worker 执行轨迹。"""

    @abstractmethod
    def get_capabilities(self) -> dict:
        """对外能力清单（镜像归档 WorkSlotPort）。"""

    @abstractmethod
    def make_broker(self, boss_core):
        """产出供 MentalCore.exo_broker 调用的 (payload)->None 闭包。"""


def _parse_arguments(raw: str) -> dict:
    """解析原生 tool_call 的 arguments JSON；失败回退空字典（fail-operational）。"""
    try:
        data = json.loads(raw or "{}")
    except (ValueError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def build_ask_bridge(boss_core, timeout: float = 60.0):
    """产出 ask_user 工具的中转闭包：提问经心智魔方传达，阻塞等用户回复。

    心智魔方须具备 receive(fields, body)（入队传达）与 _ask_replies 队列
    （宿主调用 answer_ask 推送用户回复）。超时返回提示文本（不永久阻塞）。
    """
    def _ask(question: str) -> str:
        boss_core.receive(fields={"ask_user": question},
                          body=f"[Worker 询问] {question}")
        try:
            return boss_core._ask_replies.get(timeout=timeout)
        except queue.Empty:
            return "（用户未在时限内回复，Worker 请自行决定下一步）"
    return _ask


class WorkCore:
    """Worker 微核心：归档式原生工具循环 + 反思 + 可选规划，编排 5 小魔方。"""

    def __init__(self, exo_llm, tool_cube: ToolCube, sandbox_cube: SandboxCube,
                 plan_cube: PlanCube, comm_cube: CommCube, memory_cube: ProfessionalMemory,
                 max_iter: int = 8, enable_reflect: bool = False,
                 security_cube: SecurityCube | None = None,
                 ask_bridge=None, ask_timeout: float = 60.0,
                 board=None, token_budget: float | None = None):
        self.llm = exo_llm
        self.tools = tool_cube
        self.sandbox = sandbox_cube
        self.plan = plan_cube
        self.comm = comm_cube
        self.memory = memory_cube
        self.security = security_cube or SecurityCube()
        self.ask_bridge = ask_bridge  # ask_user 工具经心智魔方中转（提问→等待用户回复）
        self.ask_timeout = ask_timeout
        # 完成判定门：确定性工具结果直接收尾，防空转（归档 completion_gate 移植）
        from .completion_gate import CompletionGate
        self.gate = CompletionGate()
        # PCB 扩展板：AI 自注册技能的插槽（技能注入 Worker 提示）
        if board is None:
            from .expansion import ExpansionBoard
            board = ExpansionBoard()
        self.board = board
        # Token 计量台账（接入 ExoLLM.complete 记账）
        from .token_ledger import TokenLedger
        self.ledger = TokenLedger(budget=token_budget)
        self.max_iter = max_iter
        self._enable_reflect = enable_reflect
        # 干预队列：Boss 经此向 Worker 发 cancel/pause/resume/redirect（对齐 palm dual_core）
        self._interrupt_q: "queue.Queue" = queue.Queue()
        self._redirect_instruction = ""

    def run(self, goal: str, context: str = "", use_planning: bool = False) -> dict:
        """执行委派任务；use_planning=True 走归档自主规划引擎，否则直接原生循环。"""
        if use_planning:
            from .plan_engine import PlanEngine
            return PlanEngine(self).run(goal)
        return self.run_react(goal, context)

    def run_react(self, goal: str, context: str = "", max_iter: int | None = None) -> dict:
        """原生工具调用循环（||TOOL||/||FIN|| 文本标记兜底），返回 {'result','trace'}。"""
        limit = max_iter or self.max_iter
        hint = self.memory.build_injection_context(goal)
        self.plan.build_plan(goal, hint)
        history: list[tuple] = []
        result = "未产生结论"
        used_tools = False
        error = False
        for _ in range(limit):
            iv = self._check_interrupt()
            if iv == "cancel":
                result = "已被 Boss 取消"
                self.comm.trace.add(T_INTERVENTION, "任务被 Boss 取消")
                break
            if iv == "redirect":
                goal = self._redirect_instruction or goal
                self.plan.build_plan(goal, self.memory.build_injection_context(goal))
                self._redirect_instruction = ""
            prompt = self._build_prompt(goal, context, history)
            out = self.llm.complete(
                prompt, tools=self.tools.to_openai_tool(query=goal))
            text = out.get("text", "") if isinstance(out, dict) else str(out)
            # Token 计量：字符估算（中文≈2 字符/token），供用量/预算统计
            self.ledger.record("worker",
                               prompt_tokens=max(1, len(prompt) // 2),
                               completion_tokens=max(1, len(text) // 2))
            tool_calls = out.get("tool_calls", []) if isinstance(out, dict) else []
            if tool_calls:  # 原生工具调用优先
                for tc in tool_calls:
                    fn = tc.get("function") or {}
                    name = fn.get("name", "")
                    obs = self._execute_tool(
                        name, _parse_arguments(fn.get("arguments", "")))
                    history.append((name, obs))
                    # 完成判定门：工具输出已直接回答请求 → 收尾防空转
                    final = self.gate.check(goal, name, obs)
                    if final is not None:
                        result = final
                        used_tools = True
                        break
                if result != "未产生结论":
                    break
                used_tools = True
                continue
            kind, payload = parse_worker_output(text)  # 文本标记兜底
            if kind == "tool":
                obs = self._execute_tool(payload["name"], payload.get("args", {}))
                history.append((payload["name"], obs))
                final = self.gate.check(goal, payload["name"], obs)
                if final is not None:
                    result = final
                    used_tools = True
                    break
                used_tools = True
                continue
            if kind == "fin":
                candidate = payload.get("result", "") or "已完成"
                instruction = self._maybe_reflect(goal, candidate, used_tools)
                if instruction:
                    history.append(("note", f"[自检反馈] {instruction}"))
                    continue
                result = candidate
                break
            history.append(("note", text[:200]))
        else:
            error = True
        self.comm.audit("finish", result)
        return {"result": result, "trace": self.comm.get_audit(), "error": error}

    def run_step(self, description: str, max_iter: int) -> dict:
        """执行计划中的单步（供 PlanEngine 调用），返回 {"text","error"}。"""
        out = self.run_react(description, "", max_iter=max_iter)
        return {"text": out["result"], "error": out.get("error", False)}

    def _llm_text(self, prompt: str) -> str:
        """纯文本收口（规划器用）：只取正文，忽略原生 tool_calls。"""
        out = self.llm.complete(prompt)
        return out.get("text", "") if isinstance(out, dict) else str(out)

    def _maybe_reflect(self, request: str, draft: str, used_tools: bool) -> str:
        """反思自检：仅当开关开启且本轮用过工具时触发（对齐 _should_reflect）。"""
        if not self._enable_reflect or not used_tools or not draft.strip():
            return ""
        return reflect_once(self, request, draft)

    def _execute_tool(self, name: str, args: dict) -> str:
        # 安全总闸：注入清洗 → 前置门（防幻觉/确认）→ 权限闸门 → 护栏规则 → 执行 → 输出清洗
        cleaned = {k: (self.security.sanitize_input(str(v)) if isinstance(v, str) else v)
                   for k, v in args.items()}
        decision = self.tools.decide(name, cleaned)
        if not decision.allowed:
            obs = f"拒绝：{decision.reason}"
            self.comm.audit(name, str(cleaned), obs)
            return obs
        spec = decision.spec
        gate = self.security.check_grounding(
            name, spec.requires_grounding, cleaned.get("verification_id"))
        if gate:
            obs = f"拒绝：{gate}"
            self.comm.audit(name, str(cleaned), obs)
            return obs
        gate = self.security.check_confirmation(
            name, spec.requires_confirmation, cleaned.get("confirmed"))
        if gate:
            obs = f"拒绝：{gate}"
            self.comm.audit(name, str(cleaned), obs)
            return obs
        ruling = self.security.evaluate(name, cleaned)
        if ruling == "deny":
            obs = "拒绝：命中安全护栏规则（已阻止该操作）"
            self.comm.audit(name, str(cleaned), obs)
            return obs
        if ruling == "warn":
            self.security.audit("rule_warn", name, "护栏规则告警（放行但记录）")
        try:
            if spec.run_in_sandbox:
                obs = self.sandbox.run(cleaned.get("cmd", ""))
            else:
                obs = spec.fn(cleaned) if spec.fn else "（无执行体）"
        except Exception as exc:  # noqa: BLE001
            # 单次工具失败不得终止整个任务：转观测文本回灌，让模型自行纠偏或收尾
            obs = f"执行失败：{exc}"
        obs = self.security.sanitize_output(obs)
        self.comm.audit(name, str(cleaned), obs)
        return obs

    def _build_prompt(self, goal: str, context: str, history: list) -> str:
        return build_worker_prompt(
            goal, context, history,
            memory_context=self.memory.build_injection_context(goal),
            tools_desc=self.tools.describe_for_prompt(query=goal),
            skill_context=self.board.inject_into_prompt(goal),
        )

    def _check_interrupt(self) -> str | None:
        """Boss 干预闸门（对齐 palm dual_core.check_intervention）。

        - None：无干预，继续执行
        - "cancel"：取消，Worker 应终止
        - "redirect"：重定向，读取 self._redirect_instruction
        - "pause"：阻塞直到收到 resume 或 cancel
        """
        try:
            cmd = self._interrupt_q.get_nowait()
        except queue.Empty:
            return None
        action = cmd.get("action", "")
        if action == "redirect":
            self._redirect_instruction = cmd.get("instruction", "")
            return "redirect"
        if action == "cancel":
            return "cancel"
        if action == "pause":
            while True:
                nxt = self._interrupt_q.get()
                n_action = nxt.get("action", "")
                if n_action == "resume":
                    return None
                if n_action == "cancel":
                    return "cancel"
        return None

    def intervene(self, action: str, instruction: str = "") -> bool:
        """Boss 调用：向 Worker 发送干预指令（对齐 dual_core.send_intervention）。"""
        if action not in ("cancel", "pause", "resume", "redirect"):
            return False
        self._interrupt_q.put({"action": action, "instruction": instruction})
        return True


class WorkCube(ExoSlotPort):
    """外骨骼对外边界（ExoSlotPort）：后台拉起 Worker，完成回传 Boss。"""

    def __init__(self, core: WorkCore):
        self.core = core
        self._active = False
        self._goal = ""
        self._router = IntentRouter()

    def submit_async(self, task_goal: str, context: str, boss_core) -> None:
        """后台线程拉起 Worker；完成经 core.receive 回传 Boss（异步、不阻塞）。"""
        self._goal = task_goal
        self._active = True
        threading.Thread(
            target=self._run_task, args=(task_goal, context, boss_core),
            daemon=True, name="exo-worker",
        ).start()

    def _run_task(self, goal: str, context: str, boss_core) -> None:
        try:
            outcome = self.core.run(goal, context)
            feedback = self.core.comm.build_feedback(outcome["result"], goal)
            if boss_core is not None:
                boss_core.receive(fields={"exo_result": outcome["result"]},
                                  body=feedback)
        except Exception as exc:  # noqa: BLE001
            # Worker 异常也要回传失败，不静默死线程（fail-operational）
            if boss_core is not None:
                boss_core.receive(
                    fields={"exo_result": ""},
                    body=f"[外骨骼回传] 任务「{goal}」执行异常：{str(exc)[:200]}")
        finally:
            self.core.comm.mark_finished()
            self._active = False

    def make_broker(self, boss_core):
        """产出 (exo_payload) -> None，供 MentalCore.exo_broker 调用。"""
        boss_core._exo_cube = self
        # ask_user 中转：Boss 支持 answer_ask 时自动接线（提问经心智魔方传达）
        if self.core.ask_bridge is None and hasattr(boss_core, "_ask_replies"):
            from .archived_tools import _ask_ref
            self.core.ask_bridge = build_ask_bridge(
                boss_core, timeout=self.core.ask_timeout)
            _ask_ref["bridge"] = self.core.ask_bridge
        # 提醒/后台任务完成：经心智魔方 receive 传达（scheduler/background 用）
        from .extended_tools import _notify_ref
        if _notify_ref["fn"] is None:
            _notify_ref["fn"] = lambda text: boss_core.receive(
                fields={"reminder": text}, body=text)

        def _broker(payload) -> None:
            goal = extract_exo(payload)
            self.submit_async(goal.goal, goal.context, boss_core)
        return _broker

    def get_capabilities(self) -> dict:
        """对外能力清单（镜像归档 WorkSlotPort.get_capabilities）。"""
        return {
            "name": "外骨骼 Worker",
            "chat": False,
            "modes": ["task", "plan"],
            "tools": [t.name for t in self.core.tools.list_tools()],
            "model": getattr(self.core.llm, "model", "?"),
            "worker_active": self._active,
        }

    def classify(self, message: str) -> "IntentResult":
        """对用户消息做意图分类（镜像 coordinator 的任务/干预/查询路由）。"""
        return self._router.route(message, worker_active=self.worker_active)

    def answer_query(self, message: str) -> str:
        """处理进度查询（对应 coordinator 的 _handle_query）。"""
        return self.core.comm.get_summary()

    def forward_intervention(self, action: str, instruction: str = "") -> bool:
        """处理干预指令（对应 coordinator 的 _handle_intervention）。"""
        return self.core.intervene(action, instruction)

    def worker_summary(self) -> str:
        """供 Boss 注入的 Worker 轨迹摘要；无轨迹时返回空串（避免污染闲聊）。"""
        if self.core.comm.trace.entry_count == 0:
            return ""
        return self.core.comm.get_summary()

    @property
    def worker_active(self) -> bool:
        return self._active

    def get_status(self) -> dict:
        return {
            "worker_active": self._active,
            "goal": self._goal,
            "trace_entries": self.core.comm.trace.entry_count,
            "finished": self.core.comm.trace.is_finished,
        }

    def query_trace(self, keyword: str = "") -> list:
        if not keyword:
            return self.core.comm.get_audit()
        return self.core.comm.query(keyword)
