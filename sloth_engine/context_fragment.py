"""Phase 1 Task A: ContextFragment trait — 对标 Codex context-fragments.

Design: Provides a unified interface for all content injected into the LLM context,
including compaction summaries, tool outputs, RAG results, mental models, etc.
All fragments share a common trait (ABC) for consistent rendering, token estimation,
and budget management.

对标 Codex `context-fragments/src/lib.rs`:
- ContextualUserFragment → ContextFragment (ABC)
- ContentItemKind → ContentItemKind (String enum)
- render_fragment() → render() (with markers)
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import ClassVar, Optional, Tuple

# Reuse the same token estimation as context_compactor for consistency
from context_compactor import estimate_tokens

_log = logging.getLogger("sloth_engine.context-fragment")


# =============================================================================
# ContentItemKind — 对标 Codex ContentItemKind 枚举
# =============================================================================

class ContentItemKind:
    """Content kind constants — 对标 Codex ContentItemKind.

    Each kind represents a distinct type of content injected into the LLM context.
    These are also used as priority keys in FragmentBudget allocation.
    """

    COMPACTION_SUMMARY: ClassVar[str] = "compaction.summary"
    RAG_RESULT: ClassVar[str] = "rag.result"
    MENTAL_MODEL: ClassVar[str] = "mental_model"
    TOOL_OUTPUT: ClassVar[str] = "tool_output"
    ERROR_RECOVERY: ClassVar[str] = "error_recovery"
    GUARDIAN_DECISION: ClassVar[str] = "guardian_decision"
    SYSTEM_PROMPT: ClassVar[str] = "system_prompt"

    # Priority order for budget allocation (highest first)
    PRIORITY_ORDER: ClassVar[list[str]] = [
        "system_prompt",
        "mental_model",
        "rag.result",
        "compaction.summary",
        "tool_output",
        "error_recovery",
        "guardian_decision",
    ]

    @classmethod
    def priority(cls, kind: str) -> int:
        """Lower number = higher priority (0 = system_prompt, highest)."""
        try:
            return cls.PRIORITY_ORDER.index(kind)
        except ValueError:
            return len(cls.PRIORITY_ORDER)  # unknown kinds go last

    @classmethod
    def is_valid(cls, kind: str) -> bool:
        return kind in cls.PRIORITY_ORDER


# =============================================================================
# ContextFragment — 对标 Codex ContextualUserFragment trait
# =============================================================================

class ContextFragment(ABC):
    """Abstract base for all context fragments — 对标 Codex ContextualUserFragment.

    Each fragment represents a piece of content to be injected into the LLM context,
    wrapped in markers for later identification/stripping, and annotated with a role
    and content kind.

    Subclasses must implement:
        _build_body() → str          — construct the actual text content
        _default_markers() → Tuple[str, str] — opening/closing marker strings
        _default_role() → str        — "user", "assistant", or "system"
    """

    def __init__(
        self,
        *,
        markers: Optional[Tuple[str, str]] = None,
        role: Optional[str] = None,
    ):
        self._cached_body: Optional[str] = None
        self._markers: Tuple[str, str] = markers or self._default_markers()
        self._role: str = role or self._default_role()

    # ── abstract interface ──────────────────────────────────────────

    @abstractmethod
    def _build_body(self) -> str:
        """Build the fragment body text. Called once, cached thereafter."""
        ...

    @abstractmethod
    def _default_markers(self) -> Tuple[str, str]:
        """Default marker pair, e.g. ("<compact>", "</compact>")."""
        ...

    @abstractmethod
    def _default_role(self) -> str:
        """Default role: "user", "assistant", or "system"."""
        ...

    # ── public properties ────────────────────────────────────────────

    @property
    def content_kind(self) -> str:
        """Subclasses should define this as a class-level or property."""
        raise NotImplementedError("subclass must define content_kind")

    @property
    def role(self) -> str:
        return self._role

    @property
    def markers(self) -> Tuple[str, str]:
        """Opening and closing markers, e.g. ("<compact>", "</compact>")."""
        return self._markers

    @property
    def body(self) -> str:
        """The fragment body text, lazily built and cached."""
        if self._cached_body is None:
            self._cached_body = self._build_body()
        return self._cached_body

    @property
    def estimated_tokens(self) -> int:
        """Token estimate for the full rendered fragment."""
        return estimate_tokens(self.render())

    # ── render ───────────────────────────────────────────────────────

    def render(self) -> str:
        """Full rendering: markers + body. 对标 Codex render_fragment()."""
        open_m, close_m = self._markers
        return f"{open_m}\n{self.body}\n{close_m}"

    def render_body_only(self) -> str:
        """Render just the body, without markers (for stripping)."""
        return self.body

    # ── dunder ──────────────────────────────────────────────────────

    def __repr__(self) -> str:
        preview = self.body[:80].replace("\n", "\\n") if self.body else "(empty)"
        return f"<{type(self).__name__} kind={self.content_kind!r} role={self._role!r} tokens≈{self.estimated_tokens} body={preview!r}>"

    def __len__(self) -> int:
        return self.estimated_tokens


# =============================================================================
# Concrete fragment subclasses
# =============================================================================

class CompactionFragment(ContextFragment):
    """Compaction summary fragment — 压缩摘要片段.

    对标 Codex: compaction output injected as a user message,
    wrapped in <compact> / </compact> markers.
    """

    content_kind: str = ContentItemKind.COMPACTION_SUMMARY

    def __init__(
        self,
        summary_text: str,
        *,
        freed_tokens: int = 0,
        from_round: int = 0,
        to_round: int = 0,
        markers: Optional[Tuple[str, str]] = None,
    ):
        super().__init__(markers=markers)
        self.summary_text = summary_text
        self.freed_tokens = freed_tokens
        self.from_round = from_round
        self.to_round = to_round

    def _default_markers(self) -> Tuple[str, str]:
        return ("<compact>", "</compact>")

    def _default_role(self) -> str:
        return "user"

    def _build_body(self) -> str:
        header = (
            f"[Compaction Summary — rounds {self.from_round}→{self.to_round}, "
            f"freed ~{self.freed_tokens} tokens]"
        )
        return f"{header}\n{self.summary_text}"


class RagFragment(ContextFragment):
    """RAG retrieval result fragment — RAG 检索结果片段.

    对标 Codex: RAG results injected as context, wrapped in <rag> markers.
    """

    content_kind: str = ContentItemKind.RAG_RESULT

    def __init__(
        self,
        query: str,
        results: list[str],
        *,
        source: str = "",
        markers: Optional[Tuple[str, str]] = None,
    ):
        super().__init__(markers=markers)
        self.query = query
        self.results = results
        self.source = source

    def _default_markers(self) -> Tuple[str, str]:
        return ("<rag>", "</rag>")

    def _default_role(self) -> str:
        return "system"

    def _build_body(self) -> str:
        parts = [f"[RAG Results] query: {self.query}"]
        if self.source:
            parts.append(f"source: {self.source}")
        for i, r in enumerate(self.results, 1):
            parts.append(f"\n--- result {i} ---\n{r}")
        return "\n".join(parts)


class MentalModelFragment(ContextFragment):
    """Mental model fragment — 心智模型片段.

    Injects pre-computed mental model knowledge (from PatternStore statistics)
    into the context as a system-level hint. Wrapped in <mental_model> markers.

    Compatible with the existing MentalModel dataclass in mental_model.py.
    """

    content_kind: str = ContentItemKind.MENTAL_MODEL

    def __init__(
        self,
        model_id: str,
        category: str,
        question: str,
        best_value: str = "",
        confidence: float = 0.0,
        *,
        evidence_count: int = 0,
        markers: Optional[Tuple[str, str]] = None,
    ):
        super().__init__(markers=markers)
        self.model_id = model_id
        self.category = category
        self.question = question
        self.best_value = best_value
        self.confidence = confidence
        self.evidence_count = evidence_count

    def _default_markers(self) -> Tuple[str, str]:
        return ("<mental_model>", "</mental_model>")

    def _default_role(self) -> str:
        return "system"

    def _build_body(self) -> str:
        return (
            f"[Mental Model: {self.model_id}] category={self.category}\n"
            f"Q: {self.question}\n"
            f"Best: {self.best_value}  "
            f"(confidence={self.confidence:.2f}, n={self.evidence_count})"
        )

    @classmethod
    def from_mental_model(cls, mm: "MentalModel") -> "MentalModelFragment":
        """Construct from an existing mental_model.MentalModel instance."""
        return cls(
            model_id=mm.id,
            category=mm.category,
            question=mm.question_template,
            best_value=str(mm.best_value) if mm.best_value is not None else "",
            confidence=mm.confidence,
            evidence_count=mm.evidence_count,
        )


class ToolOutputFragment(ContextFragment):
    """Tool output fragment — 工具输出片段 (with budget truncation).

    对标 Codex Layer1 Tool Result Budget: each tool result is truncated
    to stay within a per-fragment character limit, keeping head and tail.

    Wrapped in <tool_output> markers.
    """

    content_kind: str = ContentItemKind.TOOL_OUTPUT

    # Default budget: 8000 chars, matching ContextCompactor.tool_result_budget
    DEFAULT_MAX_CHARS: ClassVar[int] = 8000
    DEFAULT_HEAD_RATIO: ClassVar[float] = 0.6

    def __init__(
        self,
        tool_name: str,
        output_text: str,
        *,
        call_id: str = "",
        max_chars: int = DEFAULT_MAX_CHARS,
        exit_code: int = 0,
        markers: Optional[Tuple[str, str]] = None,
        role: Optional[str] = None,
    ):
        super().__init__(markers=markers, role=role)
        self.tool_name = tool_name
        self.output_text = output_text
        self.call_id = call_id
        self.max_chars = max_chars
        self.exit_code = exit_code
        self._was_truncated: bool = False

    def _default_markers(self) -> Tuple[str, str]:
        return ("<tool_output>", "</tool_output>")

    def _default_role(self) -> str:
        return "user"

    @property
    def was_truncated(self) -> bool:
        """Whether the output was truncated by the budget."""
        # Force body build to determine truncation
        _ = self.body
        return self._was_truncated

    def _build_body(self) -> str:
        header = (
            f"[Tool: {self.tool_name}]"
            + (f" call_id={self.call_id}" if self.call_id else "")
            + (f" exit_code={self.exit_code}" if self.exit_code != 0 else "")
        )

        text = self.output_text
        if len(text) <= self.max_chars:
            self._was_truncated = False
            return f"{header}\n{text}"

        # Truncate: keep head (60%) and tail
        self._was_truncated = True
        head_size = int(self.max_chars * self.DEFAULT_HEAD_RATIO)
        tail_size = self.max_chars - head_size - 80  # reserve for truncation notice
        head = text[:head_size]
        tail = text[-tail_size:] if tail_size > 0 else ""

        truncated_chars = len(text) - head_size - (tail_size if tail_size > 0 else 0)
        notice = (
            f"\n... [{truncated_chars} chars truncated — "
            f"total original: {len(text)} chars] ...\n"
        )
        return f"{header}\n{head}{notice}{tail}"


class SystemFragment(ContextFragment):
    """System prompt fragment — 系统提示片段.

    The top-level system prompt, typically the first fragment in any context.
    Wrapped in <system> markers (or unmarked if is_bare=True).
    """

    content_kind: str = ContentItemKind.SYSTEM_PROMPT

    def __init__(
        self,
        prompt_text: str,
        *,
        is_bare: bool = False,
        markers: Optional[Tuple[str, str]] = None,
    ):
        super().__init__(markers=markers)
        self.prompt_text = prompt_text
        self.is_bare = is_bare

    def _default_markers(self) -> Tuple[str, str]:
        return ("<system>", "</system>")

    def _default_role(self) -> str:
        return "system"

    def _build_body(self) -> str:
        return self.prompt_text

    def render(self) -> str:
        """System fragment: if bare, render without markers."""
        if self.is_bare:
            return self.body
        return super().render()


class ErrorRecoveryFragment(ContextFragment):
    """Error recovery fragment — 错误恢复片段.

    Injected when the system enters a recovery path (collapse drain,
    reactive compact, max_output escalation). 对标 Codex recovery messages.
    """

    content_kind: str = ContentItemKind.ERROR_RECOVERY

    def __init__(
        self,
        recovery_action: str,
        detail: str = "",
        *,
        markers: Optional[Tuple[str, str]] = None,
    ):
        super().__init__(markers=markers)
        self.recovery_action = recovery_action
        self.detail = detail

    def _default_markers(self) -> Tuple[str, str]:
        return ("<error_recovery>", "</error_recovery>")

    def _default_role(self) -> str:
        return "system"

    def _build_body(self) -> str:
        body = f"[Error Recovery] action={self.recovery_action}"
        if self.detail:
            body += f"\ndetail: {self.detail}"
        return body


class GuardianDecisionFragment(ContextFragment):
    """Guardian decision fragment — 守护者决策片段.

    Injected when the safety guardian (orchestrator_safety) makes a blocking
    or modifying decision that must be communicated to the model.
    """

    content_kind: str = ContentItemKind.GUARDIAN_DECISION

    def __init__(
        self,
        decision: str,
        reason: str = "",
        *,
        markers: Optional[Tuple[str, str]] = None,
    ):
        super().__init__(markers=markers)
        self.decision = decision
        self.reason = reason

    def _default_markers(self) -> Tuple[str, str]:
        return ("<guardian>", "</guardian>")

    def _default_role(self) -> str:
        return "system"

    def _build_body(self) -> str:
        body = f"[Guardian Decision] {self.decision}"
        if self.reason:
            body += f"\nreason: {self.reason}"
        return body


# =============================================================================
# FragmentBudget — 对标 Codex fragment token budget management
# =============================================================================

@dataclass
class FragmentBudget:
    """Manages total token budget across all fragments.

    对标 Codex: token budget allocation with priority-based distribution.
    Allocation priorities (highest first):
        system_prompt > mental_model > rag.result > compaction.summary > tool_output

    Usage:
        budget = FragmentBudget(total=100_000)
        allocated = budget.allocate(ContentItemKind.TOOL_OUTPUT, requested=5000)
        # → returns min(requested, available_for_kind), respecting priorities
    """

    total: int
    _allocated: dict[str, int] = field(default_factory=dict)
    _min_reserve: dict[str, int] = field(default_factory=dict)

    # Soft caps per kind (as fraction of total)
    DEFAULT_CAPS: ClassVar[dict[str, float]] = {
        ContentItemKind.SYSTEM_PROMPT: 0.40,       # up to 40%
        ContentItemKind.MENTAL_MODEL: 0.10,         # up to 10%
        ContentItemKind.RAG_RESULT: 0.15,           # up to 15%
        ContentItemKind.COMPACTION_SUMMARY: 0.20,   # up to 20%
        ContentItemKind.TOOL_OUTPUT: 0.25,          # up to 25%
        ContentItemKind.ERROR_RECOVERY: 0.05,       # up to 5%
        ContentItemKind.GUARDIAN_DECISION: 0.05,    # up to 5%
    }

    def __post_init__(self):
        if self.total < 0:
            raise ValueError(f"total budget must be >= 0, got {self.total}")

    # ── allocation ────────────────────────────────────────────────────

    def available(self, kind: str) -> int:
        """Remaining tokens available for a given kind."""
        used = sum(self._allocated.values())
        remaining = max(0, self.total - used)
        cap = int(self.total * self.DEFAULT_CAPS.get(kind, 0.05))
        already = self._allocated.get(kind, 0)
        return max(0, min(remaining, cap - already))

    def allocate(self, kind: str, requested_tokens: int) -> int:
        """Allocate up to `requested_tokens` for the given kind.

        Returns the actual number of tokens allocated (may be less than requested).
        Allocation respects:
          1. Total budget remaining
          2. Per-kind soft cap
          3. Higher-priority kinds are reserved first
        """
        if requested_tokens <= 0:
            return 0

        avail = self.available(kind)
        granted = min(requested_tokens, avail)
        self._allocated[kind] = self._allocated.get(kind, 0) + granted
        return granted

    def allocate_fragment(self, fragment: ContextFragment) -> int:
        """Allocate budget for a fragment and return how many tokens were granted.

        If the fragment's estimated_tokens exceeds what's available, this
        still records the full allocation (the caller should handle truncation).
        """
        needed = fragment.estimated_tokens
        granted = self.allocate(fragment.content_kind, needed)
        if granted < needed:
            _log.debug(
                "[fragment-budget] under-allocated %s: needed %d, got %d (remaining=%d)",
                fragment.content_kind, needed, granted,
                self.total - self.used,
            )
        return granted

    # ── reserve ───────────────────────────────────────────────────────

    def reserve(self, kind: str, tokens: int):
        """Reserve a minimum number of tokens for a given kind."""
        self._min_reserve[kind] = tokens

    # ── queries ──────────────────────────────────────────────────────

    @property
    def used(self) -> int:
        return sum(self._allocated.values())

    @property
    def remaining(self) -> int:
        return max(0, self.total - self.used)

    @property
    def utilization(self) -> float:
        """Fraction of budget used, [0, 1]."""
        return self.used / self.total if self.total > 0 else 0.0

    def breakdown(self) -> dict[str, int]:
        """Per-kind allocation breakdown."""
        return dict(self._allocated)

    def summary(self) -> dict:
        return {
            "total": self.total,
            "used": self.used,
            "remaining": self.remaining,
            "utilization": round(self.utilization, 3),
            "breakdown": self.breakdown(),
        }


# =============================================================================
# FragmentCollector — convenience helper for managing a list of fragments
# =============================================================================

class FragmentCollector:
    """Collects fragments in insertion order and renders the full context.

    Convenience wrapper around a list of ContextFragment instances plus
    an optional FragmentBudget.
    """

    def __init__(self, budget: Optional[FragmentBudget] = None):
        self._fragments: list[ContextFragment] = []
        self.budget = budget

    def add(self, fragment: ContextFragment) -> bool:
        """Add a fragment. Returns True if added, False if rejected by budget."""
        if self.budget is not None:
            needed = fragment.estimated_tokens
            if self.budget.available(fragment.content_kind) < needed:
                _log.debug(
                    "[collector] fragment rejected by budget: kind=%s needed=%d",
                    fragment.content_kind, needed,
                )
                return False
            self.budget.allocate_fragment(fragment)
        self._fragments.append(fragment)
        return True

    @property
    def fragments(self) -> list[ContextFragment]:
        return list(self._fragments)

    @property
    def total_tokens(self) -> int:
        return sum(f.estimated_tokens for f in self._fragments)

    def render_all(self, separator: str = "\n\n") -> str:
        """Render all fragments in order, separated by `separator`."""
        return separator.join(f.render() for f in self._fragments)

    def to_messages(self) -> list[dict[str, str]]:
        """Convert to OpenAI-style message list."""
        return [{"role": f.role, "content": f.render()} for f in self._fragments]

    def by_kind(self, kind: str) -> list[ContextFragment]:
        return [f for f in self._fragments if f.content_kind == kind]

    def __len__(self) -> int:
        return len(self._fragments)

    def __iter__(self):
        return iter(self._fragments)

    def __repr__(self) -> str:
        return f"<FragmentCollector fragments={len(self._fragments)} tokens≈{self.total_tokens}>"
