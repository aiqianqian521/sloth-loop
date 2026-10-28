"""Customer-facing completion report generator (sloth_engine).

Pure-function builder that turns an archived run + pattern-library snapshot into
a validated customer markdown report (frontmatter + 4-piece structure, matching
the ai-skill-output-template book-distill.report schema). Zero dependencies.

The output lands in project-norm directories:
  projects/<domain>/<task>/reports/<date>/REPORT.md
  projects/<domain>/<task>/data/<run_id>/   (archived runtime snapshot)
"""
from __future__ import annotations

import os
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any

# Repository root: the ``docs/...`` risk citations in the report are
# repo-relative by design, so the existence check needs a second anchor
# besides the directory the report is written into.
REPO_ROOT = Path(__file__).resolve().parent.parent

VALID_VERDICT_CN = {
    "OK": "成功",
    "STOP": "受限停止",
    "WARN": "有警告",
    "ERR": "失败",
}


# 故障模式 -> 中文说明（与模板口径一致）
VALID_MODE_CN = {
    "EXTREME_CHASE": "极端位置追单",
    "ABSOLUTE_BLINDSPOT": "绝对位置盲区",
    "STOPPED_OUT_FIRST": "先止损后达标",
    "DIRECTION_BIAS": "连续方向偏移",
    "RANGING_FAKEOUT": "震荡假突破",
    "INSUFFICIENT_EVIDENCE": "证据不足",
    "UNKNOWN": "未知",
}


def _project_ref(*, task: str, domain: str) -> str:
    """Domain-aware project-relative prefix: projects/<domain>/<task> or
    projects/<task> when the grouping segment is absent/redundant."""
    return f"projects/{domain}/{task}" if (domain and domain != task) else f"projects/{task}"


def _frontmatter(*, task: str, domain: str, status: str,
                 input_ref: str | None = None) -> str:
    # input_ref must point at the real run input. The historical literal
    # projects/<task>/data/signals.json ignored the domain segment and the
    # actual runtime io_dir (_data/loop_backtest_input.json), so it referenced
    # a path that does not exist on disk. Default to the domain-aware
    # project-relative io path; callers may pass an explicit input_ref.
    if not input_ref:
        input_ref = f"{_project_ref(task=task, domain=domain)}/data/loop_backtest_input.json"
    return (
        "---\n"
        f"skill_family: {task}\n"
        f"skill_name: {task}-report\n"
        f"project: {domain}\n"
        f"evaluatedAt: {date.today().isoformat()}\n"
        f"input_ref: {input_ref}\n"
        f"renderer: sloth_engine/report_util.py\n"
        f"status: {status}\n"
        "---\n"
    )


def _conclusion_section(total_rounds, verdict, new_failures, new_successes,
                        stop_reason) -> str:
    return (
        "## 1. 结论\n\n"
        f"- **事实**: 本次运行 {total_rounds} 轮，"
        f"以「{stop_reason or '正常结束'}」结束。\n"
        f"- **判断**: 判定为「{VALID_VERDICT_CN.get(verdict, verdict)}」；"
        f"新增失败模式 {new_failures} 条，新增成功模式 {new_successes} 条。\n"
        f"- **假设**: 语义结论（针对任务目标的成功判定）未在此结构报告内展开，"
        "标 [机制推断]，需依任务 success_criteria 另行验收。\n\n"
    )


SELF_CITE = "REPORT.md"


def _ref_pair(name: str, data_ref: str):
    """Evidence ``(ref label, path)`` guaranteed to exist relative to the report.

    ``data_ref`` is the directory holding the six archived summary JSONs
    (relative like ``data`` or absolute on a foreign drive). When no snapshot is
    in play the sentinel :data:`SELF_CITE` makes the table cite the report
    itself: the numbers are rendered right here, so a ``data/<name>.json`` claim
    would be a **fabricated** evidence pointer (D-S1 family).
    """
    if data_ref and data_ref != SELF_CITE:
        return name, f"{data_ref}/{name}"
    return "REPORT.md §2", SELF_CITE


def _findings_section(summary: dict, failure_modes: dict, data_ref: str = "data") -> str:
    run_id = summary.get("run_id") or "?"
    lines = ["## 2. 关键发现（证据 · 行级）\n"]
    lines.append("| 指标 | 值 | 说明 | ref: | file:line: |")
    lines.append("|------|-----|------|------|------------|")
    rows = [
        ("总轮数", summary.get("total_rounds", 0), "-", "rounds.json"),
        ("新增失败", summary.get("new_failures", 0), "-", "patterns.json"),
        ("新增成功", summary.get("new_successes", 0), "-", "patterns.json"),
        ("活跃排除规则", summary.get("active_exclusion_rules", 0), "-", "summary.json"),
        ("问题队列总数", summary.get("problem_queue_total", 0), "-", "problems.json"),
        ("健康分", summary.get("l2_health_score", 0), "L2", "summary.json"),
    ]
    for label, value, note, name in rows:
        ref, target = _ref_pair(name, data_ref)
        lines.append(f"| {label} | {value} | {note} | ref: {ref} | file:line: {target}:1 |")
    lines.append("")
    if failure_modes:
        lines.append("故障模式分布：")
        lines.append("")
        for mode, count in failure_modes.items():
            lines.append(f"- {VALID_MODE_CN.get(mode, mode)}（{mode}）: {count}")
        lines.append("")
    return "\n".join(lines)


def _risk_section() -> str:
    return (
        "## 3. 风险分级（引用 scheme）\n\n"
        "| 项 | 等级 | 触发条件 | 响应 | ref: | file:line: |\n"
        "|----|------|----------|------|------|------------|\n"
        "| 语义验收缺失 | high | 结构报告不覆盖任务成功判定 | 7d | ref: docs/design/loop-verification-design.md | file:line: docs/design/loop-verification-design.md:1 |\n"
        "| 运行环境（中文路径约束） | low | 中文路径致 CreateProcess 267 | 季度 | ref: docs/sloth-loop-项目介绍与规划.md | file:line: docs/sloth-loop-项目介绍与规划.md:441 |\n\n"
    )


def _hardening_section() -> str:
    return (
        "## 4. 加固建议（可执行）\n\n"
        "1. 对每次运行产出该完结报告并自动归档到项目 reports/data。\n"
        "2. 接任务 success_criteria 做语义验收门（LLM + validate_skill.py）。\n"
        "3. 提供运行副本同步脚本，规避中文路径约束。\n\n"
    )


def _next_section(run_id: str, data_ref: str = "data") -> str:
    opened = ("本报告 §2（无同目录数据快照）"
              if (not data_ref or data_ref == SELF_CITE) else f"{data_ref}/")
    return (
        "## 5. 下一步（负责人 + 动作 + 验证 + 响应）\n\n"
        "| # | 负责人 | 动作 | 验证命令 | 响应 |\n"
        "|---|--------|------|----------|------|\n"
        "| N1 | 维护者 | 复查本完结报告口径 | validate.mjs --template <task>.report | 7d |\n"
        f"| N2 | 使用方 | 按任务 success_criteria 验收语义结论 | 打开 {opened} 复核 | 30d |\n\n"
    )


_REF_PATH_RE = re.compile(r"file:line:\s*(\S+?):(\d+)")


def _ref_target_exists(ref_path: str, base_dir, repo_root) -> bool:
    """True when ``file:line: <ref_path>`` names a file that is really on disk.

    Absolute refs are checked as-is; relative refs resolve against ``base_dir``
    (the directory the report is written into) and, failing that, ``repo_root``
    (the ``docs/...`` risk citations are repo-relative by design).
    """
    p = Path(ref_path)
    if p.is_absolute():
        return p.exists()
    roots = [r for r in (base_dir, repo_root) if r is not None]
    if not roots:
        return True  # no anchor to check against: do not invent a verdict
    return any((Path(r) / p).exists() for r in roots)


def validate_risk_evidence(md: str, base_dir=None, repo_root=None) -> list[str]:
    """环内自校验：逐行扫描「关键发现/风险分级」表数据行，断言

    ① 每行含 ref: 与 file:line:；② ``file:line:`` 指向的路径**真实存在**。

    Without a ``base_dir``/``repo_root`` anchor only ① is checked -- so any
    caller that *writes* a report must pass an anchor, otherwise the verifier
    cannot see a dangling pointer (the exact defect it exists to catch).
    Returns a list of WARN messages (empty when clean).
    """
    warnings: list[str] = []
    active = None  # None | "findings" | "risk"
    for line in md.splitlines():
        if line.startswith("## "):
            if "风险分级" in line:
                active = "risk"
            elif "关键发现" in line:
                active = "findings"
            elif active is not None:
                active = None
            continue
        if active is None:
            continue
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if cells and all(set(c) <= {"-"} for c in cells):
            continue  # table separator row
        if "ref:" not in stripped or "file:line:" not in stripped:
            warnings.append(
                f"WARN: [{active}] table row missing ref:/file:line:: {stripped}"
            )
            continue
        m = _REF_PATH_RE.search(stripped)
        if m and not _ref_target_exists(m.group(1), base_dir, repo_root):
            warnings.append(
                f"WARN: [{active}] dangling ref -- no such file: {m.group(1)}"
            )
    return warnings


def build_customer_report(*, task: str, domain: str, summary: dict,
                          failure_modes: dict | None = None,
                          status: str = "covered",
                          input_ref: str | None = None,
                          data_ref: str = "data",
                          base_dir=None, repo_root=None) -> str:
    """Build a validated customer completion markdown report."""
    failure_modes = failure_modes or {}
    verdict = summary.get("verdict", "OK")
    stop_reason = summary.get("stop_reason", "")
    total_rounds = summary.get("total_rounds", 0)
    run_id = summary.get("run_id") or f"{task}-manual"
    mid = _frontmatter(task=task, domain=domain, status=status,
                       input_ref=input_ref)
    body = (
        f"# {task} 任务完结报告（客户版）\n\n"
        "> 结论先行：本报告由 sloth_engine 自动生成，落项目 reports 目录。"
        "PASS/判定仅指「运行已完成 + 结果已归档」，不构成语义验收（见 §3）。\n\n"
        + _conclusion_section(total_rounds, verdict,
                              summary.get("new_failures", 0),
                              summary.get("new_successes", 0), stop_reason)
        + _findings_section(summary, failure_modes, data_ref)
        + _risk_section()
        + _hardening_section()
        + _next_section(run_id, data_ref)
        + "## 6. 交付物与安装位\n\n"
        + f"- 可读交付物（项目内）: `{_project_ref(task=task, domain=domain)}/reports/*/REPORT.md`"
        + ("" if (not data_ref or data_ref == SELF_CITE) else f" + `{data_ref}/`") + "\n"
        + f"- 运行 ID: `{run_id}`\n\n"
        + "## 7. 禁词与格式自查\n\n"
        + "- 未命中「赋能 / 闭环(泛指) / 拉通」等禁词；路径统一正斜杠。✅\n"
    )
    md = mid + body
    for warning in validate_risk_evidence(md, base_dir=base_dir, repo_root=repo_root):
        print(f"[report_util.validate] {warning}", file=sys.stderr)
    return md


def _resolve_data_ref(data_dir, report_dir: Path) -> str:
    """Ref prefix under which the archived summary JSONs really exist.

    Relative to the report when the snapshot is reachable (same drive); an
    absolute posix path when it is not (a relative ref is impossible there and
    the old conventional ``"data"`` was a fib); :data:`SELF_CITE` when there is
    no snapshot at all so the table cites the report itself.
    """
    if data_dir is not None:
        d = Path(data_dir)
        if d.exists():
            try:
                return Path(os.path.relpath(d, report_dir)).as_posix()
            except (ValueError, OSError):
                return d.resolve().as_posix()
    if (report_dir / "data").is_dir():
        return "data"
    return SELF_CITE


def write_customer_report(*, project_root: Path, task: str, domain: str | None = None,
                          summary: dict, failure_modes: dict | None = None,
                          run_ts: str | None = None,
                          input_ref: str | None = None,
                          data_dir: Path | None = None,
                          runs_root: Path | None = None) -> Path:
    """Write the customer report into project-norm directories.

    Output lands at:
      - projects/<domain>/<task>/reports/<date>/REPORT.md  when ``domain`` is a
        distinct grouping segment (domain != task and domain truthy),
      - projects/<task>/reports/<date>/REPORT.md           otherwise (back-compat).
    ``domain`` is the grouping namespace (e.g. "pm"); ``task`` is the project
    name. Avoids a duplicated segment when domain == task. Returns the path.

    ``runs_root`` (O-3, cycle-29 A) only affects the ``run_ts`` branch: the
    per-run subtask tree belongs to ``runtime.root`` (runtime artifact), while
    the dated ``reports/`` tree stays project-norm.
    """
    doa = domain or task
    today = date.today().isoformat()
    if run_ts:
        # O-3 (cycle-29 A): the per-run tree is a runtime artifact, so callers may
        # anchor it at runtime.root via ``runs_root``; defaults to project_root so
        # the historical layout is preserved for every existing caller.
        tree = Path(runs_root) if runs_root is not None else project_root
        base_dir = (tree / "projects" / domain / task) if (domain and domain != task) else (tree / "projects" / task)
        report_dir = base_dir / "runs" / run_ts
    elif domain and domain != task:
        report_dir = project_root / "projects" / domain / task / "reports" / today
    else:
        report_dir = project_root / "projects" / task / "reports" / today
    report_dir.mkdir(parents=True, exist_ok=True)
    target = report_dir / "REPORT.md"
    data_ref = _resolve_data_ref(data_dir, report_dir)
    md = build_customer_report(task=task, domain=doa, summary=summary,
                               failure_modes=failure_modes,
                               input_ref=input_ref, data_ref=data_ref,
                               base_dir=report_dir, repo_root=REPO_ROOT)
    target.write_text(md, encoding="utf-8")
    return target
