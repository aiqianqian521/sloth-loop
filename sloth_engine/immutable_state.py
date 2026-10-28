"""
Immutable State Transitions — P2-N6
====================================
对标 Claude Code query() generator 模式核心思想：每次循环返回新 State，
不原地修改。

Claude Code 的 query() 是 async generator：
- 每轮产生 (NewState, ToolCalls, Terminal | None)
- State 是不可变的，下游通过 reducer 折叠
- 这避免了跨轮状态污染（一个异常轮不会污染后续轮的状态快照）

sloth-loop 对标实现：
- LoopState: frozen dataclass — 一轮循环的完整快照
- StateReducer: 将本轮结果 fold 进下一轮初始状态
- 每个 field 都带来源标注（值 vs 派生 vs 继承）
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, fields, replace
from datetime import datetime, timezone
from typing import Any, Optional

# ---------------------------------------------------------------------------
# 1. 核心不可变状态
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class LoopState:
    """一轮循环的不可变快照。

    对标 Claude Code: State 包含两大层
    - Mutable: 本轮计算结果（信号、决定、因子）
    - Reactive: 累积统计（轮数、break 条件、问题计数）

    每个属性有明确的来源标注：
    - "init":  运行开始前从配置初始化
    - "prev":  从上一轮 StateReducer 继承
    - "calc":  本轮计算产生
    - "check": 合同检查快照
    """

    # ---- 身份 ----
    run_id: str = ""
    round_num: int = 0
    started_at: float = 0.0

    # ---- 合同/配置快照 (init → prev) ----
    max_rounds: int = 0
    no_progress_stop: int = 0
    max_seconds: Optional[float] = None
    error_stop: int = 0
    budget_hard: dict = field(default_factory=dict)
    meta_every: int = 0
    enable_ooda: bool = False

    # ---- 进度 (prev) ----
    cursor: int = 0
    last_progress_round: int = 0
    total_rounds: int = 0
    consecutive_errors: int = 0

    # ---- 本轮计算 (calc) ----
    signals_generated: int = 0
    signals_input: int = 0
    signals_excluded: int = 0
    decision: str = ""            # "apply" | "reject" | "skip"
    progressed: bool = False
    new_failures: int = 0
    new_successes: int = 0
    bumped_failures: int = 0
    bumped_successes: int = 0
    backtest_status: str = ""     # "completed" | "error" | "deferred" | ""
    backtest_error: str = ""
    execution_failed: bool = False
    deferred: bool = False        # backpressure: not counted as a failure
    all_excluded: bool = False

    # ---- 停止条件 (check) ----
    stop_reason: str = ""
    circuit_open: bool = False
    contract_breach: str = ""
    scope_violation: str = ""
    l2_health_score: Optional[float] = None
    l2_stop_signal: str = ""
    token_exhausted: bool = False
    time_exhausted: bool = False

    # ---- 上下文 (prev) ----
    prev_round_ctx: Optional[dict] = None

    # ---- 元数据 ----
    elapsed: float = 0.0
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    # ---- 来源标注（内部追踪，不入序列化） ----
    _sources: dict = field(default_factory=dict, compare=False)

    def with_update(self, **overrides) -> "LoopState":
        """返回一个更新的不可变副本。

        对标 Claude Code: spread operator + overrides 模式。
        这是唯一合法的"修改"方式——返回新实例。
        """
        sources = dict(self._sources)
        for k in overrides:
            sources[k] = "calc"
        # 继承字段自动标 "prev"
        for fld in fields(LoopState):
            if fld.name not in overrides and fld.name not in sources and fld.name != "_sources":
                if fld.name in ("created_at",):
                    continue
                sources[fld.name] = "prev"
        return replace(self, **overrides, _sources=sources)

    @classmethod
    def from_config(cls, config: dict) -> "LoopState":
        """从运行配置创建初始状态（来源: init）。"""
        hard = config.get("budget_hard", {})
        return cls(
            max_rounds=int(config.get("max_rounds", 0)),
            no_progress_stop=int(config.get("no_progress_stop", 0)),
            max_seconds=config.get("max_seconds"),
            error_stop=int(config.get("error_stop", 0)),
            budget_hard=hard,
            meta_every=int(config.get("meta_every", 0)),
            enable_ooda=bool(config.get("enable_ooda", False)),
            _sources={
                f.name: "init" for f in fields(cls)
                if f.name not in ("_sources", "created_at", "prev_round_ctx")
            },
        )

    def to_dict(self) -> dict:
        """序列化为可 JSON 持久化的字典。"""
        d = {}
        for fld in fields(self):
            if fld.name.startswith("_"):
                continue
            val = getattr(self, fld.name)
            if hasattr(val, "to_dict"):
                val = val.to_dict()
            d[fld.name] = val
        return d

    def trace_changes(self, prev: "LoopState") -> dict:
        """对比两个状态，返回变更追踪（用于调试/审计）。

        Returns: {field: (prev_val, curr_val, source)}
        """
        diffs = {}
        for fld in fields(self):
            name = fld.name
            if name.startswith("_"):
                continue
            pv = getattr(prev, name)
            cv = getattr(self, name)
            if pv != cv:
                diffs[name] = (pv, cv, self._sources.get(name, "unknown"))
        return diffs


# ---------------------------------------------------------------------------
# 2. StateReducer — 折叠本轮结果到下一轮初始状态
# ---------------------------------------------------------------------------

class StateReducer:
    """将本轮 State + 计算结果 fold 为下一轮的初始 State。

    对标 Claude Code: reducer 模式 —— 每轮 query() 产生新状态后，
    通过 reduce() 叠加到累积状态，再传给下一轮。
    """

    @staticmethod
    def reduce(
        prev: LoopState,
        *,
        round_num: int = 0,
        cursor: int = 0,
        signals_generated: int = 0,
        signals_input: int = 0,
        signals_excluded: int = 0,
        decision: str = "",
        progressed: bool = False,
        new_failures: int = 0,
        new_successes: int = 0,
        bumped_failures: int = 0,
        bumped_successes: int = 0,
        backtest_status: str = "",
        backtest_error: str = "",
        execution_failed: bool = False,
        deferred: bool = False,
        all_excluded: bool = False,
        last_progress_round: Optional[int] = None,
        consecutive_errors: Optional[int] = None,
        prev_round_ctx: Optional[dict] = None,
        # 停止条件
        stop_reason: str = "",
        circuit_open: bool = False,
        contract_breach: str = "",
        scope_violation: str = "",
        l2_health_score: Optional[float] = None,
        l2_stop_signal: str = "",
        token_exhausted: bool = False,
        time_exhausted: bool = False,
        # 继承字段
        run_id: Optional[str] = None,
        started_at: Optional[float] = None,
        elapsed: Optional[float] = None,
    ) -> LoopState:
        """折叠本轮计算结果到下一轮初始状态。

        规则：
        1. 身份字段：继承（除非显式覆盖）
        2. 配置字段：继承（不可变）
        3. 进度字段：用计算值覆盖
        4. 上下文字段：用计算值覆盖

        Returns: 新的 LoopState（下一轮起点）
        """
        last_prog = last_progress_round if last_progress_round is not None else prev.last_progress_round
        if progressed:
            last_prog = round_num

        cons_errs = consecutive_errors if consecutive_errors is not None else prev.consecutive_errors

        return LoopState(
            # 身份（继承）
            run_id=run_id or prev.run_id,
            started_at=started_at if started_at is not None else prev.started_at,

            # 配置（继承，不可变）
            max_rounds=prev.max_rounds,
            no_progress_stop=prev.no_progress_stop,
            max_seconds=prev.max_seconds,
            error_stop=prev.error_stop,
            budget_hard=prev.budget_hard,
            meta_every=prev.meta_every,
            enable_ooda=prev.enable_ooda,

            # 本轮轮号
            round_num=round_num,
            total_rounds=round_num,

            # 进度（计算覆盖）
            cursor=cursor,
            last_progress_round=last_prog,
            consecutive_errors=cons_errs,

            # 本轮计算结果（calc）
            signals_generated=signals_generated,
            signals_input=signals_input,
            signals_excluded=signals_excluded,
            decision=decision,
            progressed=progressed,
            new_failures=new_failures,
            new_successes=new_successes,
            bumped_failures=bumped_failures,
            bumped_successes=bumped_successes,
            backtest_status=backtest_status,
            backtest_error=backtest_error,
            execution_failed=execution_failed,
            deferred=deferred,
            all_excluded=all_excluded,

            # 停止条件（check）
            stop_reason=stop_reason,
            circuit_open=circuit_open,
            contract_breach=contract_breach,
            scope_violation=scope_violation,
            l2_health_score=l2_health_score,
            l2_stop_signal=l2_stop_signal,
            token_exhausted=token_exhausted,
            time_exhausted=time_exhausted,

            # 上下文
            prev_round_ctx=prev_round_ctx,

            # 元数据
            elapsed=elapsed or prev.elapsed,
            _sources={
                "run_id": "prev",
                "started_at": "prev",
                "max_rounds": "prev",
                "no_progress_stop": "prev",
                "max_seconds": "prev",
                "error_stop": "prev",
                "budget_hard": "prev",
                "meta_every": "prev",
                "enable_ooda": "prev",
                "round_num": "calc",
                "total_rounds": "calc",
                "cursor": "calc",
                "last_progress_round": "calc",
                "consecutive_errors": "calc",
                "signals_generated": "calc",
                "signals_input": "calc",
                "signals_excluded": "calc",
                "decision": "calc",
                "progressed": "calc",
                "new_failures": "calc",
                "new_successes": "calc",
                "bumped_failures": "calc",
                "bumped_successes": "calc",
                "backtest_status": "calc",
                "backtest_error": "calc",
                "execution_failed": "calc",
                "deferred": "calc",
                "all_excluded": "calc",
                "stop_reason": "calc",
                "circuit_open": "calc",
                "contract_breach": "calc",
                "scope_violation": "calc",
                "l2_health_score": "calc",
                "l2_stop_signal": "calc",
                "token_exhausted": "calc",
                "time_exhausted": "calc",
                "prev_round_ctx": "calc",
                "elapsed": "calc",
            },
        )

    @staticmethod
    def init(config: dict, run_id: str = "", started_at: float = 0) -> LoopState:
        """从配置创建身份注入的初始状态。"""
        return LoopState.from_config(config).with_update(
            run_id=run_id,
            started_at=started_at,
        )


# ---------------------------------------------------------------------------
# 3. StateDiff — 状态差异分析（用于审计/调试）
# ---------------------------------------------------------------------------

@dataclass
class StateDiff:
    """两个 LoopState 之间的差异。"""
    field_name: str
    prev_value: Any
    curr_value: Any
    source: str  # "calc" | "prev" | "init" | "check"

    @property
    def is_significant(self) -> bool:
        """是否为有意义的变更（非空到空、非0到0）。"""
        # 跳过 trivial 变化
        if self.prev_value == self.curr_value:
            return False
        if self.prev_value == 0 and self.curr_value == 0:
            return False
        if self.prev_value == "" and self.curr_value == "":
            return False
        return True


def compute_diff(prev: LoopState, curr: LoopState) -> list[StateDiff]:
    """计算两个状态的差异列表。"""
    diffs = []
    # Non-semantic fields excluded from semantic diff (consistent with
    # to_dict()/signature(), which already ignore created_at and prev_round_ctx).
    _NON_SEMANTIC = {"created_at", "prev_round_ctx"}
    for fld in fields(LoopState):
        name = fld.name
        if name.startswith("_") or name in _NON_SEMANTIC:
            continue
        pv = getattr(prev, name)
        cv = getattr(curr, name)
        if pv != cv:
            diffs.append(StateDiff(
                field_name=name,
                prev_value=pv,
                curr_value=cv,
                source=curr._sources.get(name, "unknown"),
            ))
    return diffs


# ---------------------------------------------------------------------------
# 4. StateHistory — 状态历史记录（支持回放/审计）
# ---------------------------------------------------------------------------

class StateHistory:
    """状态历史管理器。

    对标 Claude Code: 每次 query() 产生的 State 都追加到 history。
    支持：
    - 回放：重放 N 轮的状态序列
    - 审计：检查某字段的变更序列
    - 溯源：定位某个值的首次出现轮次
    """

    def __init__(self, max_size: int = 1000):
        self._states: list[LoopState] = []
        self.max_size = max_size

    def append(self, state: LoopState):
        """追加一个状态快照（自动截断到 max_size）。"""
        self._states.append(state)
        if len(self._states) > self.max_size:
            self._states = self._states[-self.max_size:]

    @property
    def latest(self) -> Optional[LoopState]:
        """最新的状态快照。"""
        return self._states[-1] if self._states else None

    @property
    def count(self) -> int:
        return len(self._states)

    def replay(self, start: int = 0, end: Optional[int] = None) -> list[LoopState]:
        """回放指定范围的状态序列。"""
        e = end if end is not None else len(self._states)
        return self._states[start:e]

    def field_trace(self, field_name: str) -> list[tuple[int, Any]]:
        """返回某个字段在各轮的值序列 [(round_num, value), ...]"""
        return [(s.round_num, getattr(s, field_name, None)) for s in self._states]

    def find_first_where(self, field_name: str, value: Any) -> Optional[LoopState]:
        """找到首次出现某值的状态。"""
        for s in self._states:
            if getattr(s, field_name, None) == value:
                return s
        return None

    def to_jsonl(self, filepath) -> None:
        """导出为 JSONL 格式（每行一个 JSON 对象）。

        cycle-14 修复：原实现用 ``str(dict).replace("'", '"')`` 拼"伪 JSON"——
        值里含单引号（如 ``it's``）或需转义的字符时会产出非法行，``json.loads``
        直接失败（该导出此前还有一处不可达，见 sloth_engine/run_loop.py）。
        现改为 ``json.dumps``：``ensure_ascii=False`` 保留中文，
        ``default=str`` 兜底非原生类型，保证每行都是合法 JSON。
        """
        with open(filepath, "w", encoding="utf-8") as f:
            for s in self._states:
                f.write(json.dumps(s.to_dict(), ensure_ascii=False, default=str) + "\n")

    def __len__(self) -> int:
        return len(self._states)

    def __iter__(self):
        return iter(self._states)

    def __getitem__(self, idx):
        return self._states[idx]
