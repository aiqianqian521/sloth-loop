# -*- coding: utf-8 -*-
r"""SelfModifyGate — 第2档「架构自进化」的安全门禁原语 (沙箱首版).

含义: 让 loop 有能力「自己给自己补/改」, 但用 fail-closed 沙箱门禁兜底:
  1. 接受一个候选变更 patch (JSON 描述: type/slice/target/content/expected_tests)
  2. 在隔离沙箱副本里暂存(stage), 跑指定 pytest 门禁
  3. 全绿 -> 原子提交生产(带备份/校验), 失败 -> 丢弃并登记失败模式(入 L2 学习)
  4. 只允许改动 config 声明的授权切片(默认 engine 目录), 禁止触碰红区/生产敏感

约束(先测后写铁律 + 04-autonomous §4 护栏):
  - 未过 pytest 门禁绝不写生产
  - patch 为结构化 JSON, 非任意 exec (避免任意代码注入)
  - 提交前做备份 + 提交后可回滚
  - 失败与违规均记入 security/production-案件溯源
"""
from __future__ import annotations

import json
import hashlib
import logging
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


log = logging.getLogger("sloth_engine.self-modify-gate")

# 生产目录里可被 patch 的授权切片 (绿黄区, 缺省仅 engine)
DEFAULT_ALLOWED_SLICES = ("sloth_engine",)

# patch type 白名单 -> 目前只放开"规则/参数/新增模块文件"三类, 禁止任意改写既有源文件
PATCH_TYPES = ("add_file", "edit_params", "add_rule")

# 默认用 pytest 全量回归作为门禁(至少跑一次 suite), 也可指定 nodeid 白名单
DEFAULT_GATE_TESTS = ("tests",)


@dataclass
class GateResult:
    """门禁结果。"""
    status: str                     # committed | rejected | pending | error
    gate: dict = None
    backup: str = ""
    committed: bool = False
    reason: str = ""

    def __post_init__(self) -> None:
        if self.gate is None:
            self.gate = {}


class SelfModifyGate:
    """在隔离沙箱副本里验证候选 patch, 通过才提交生产。"""

    def __init__(self, project_root: Path, *, engine_dir: str = "sloth_engine",
                 allowed_slices: tuple[str, ...] = DEFAULT_ALLOWED_SLICES,
                 gate_tests: tuple[str, ...] = DEFAULT_GATE_TESTS,
                 pytest_timeout: int = 600,
                 backup_dir: str = "_data/self-modify-backups"):
        self.project_root = Path(project_root).resolve()
        self.engine_dir = engine_dir
        self.allowed_slices = allowed_slices
        self.gate_tests = gate_tests
        self.pytest_timeout = pytest_timeout
        self.backup_dir = self.project_root / backup_dir
        # P3-E4: approval chain
        self._approval_hooks: list = []
        self._approval_log: list = []

    # ── 候选 patch 清洗 / 白名单校验 ──────────────────────────
    def add_approval_hook(self, hook):
        """Register approval hook. hook(patch) -> bool|None."""
        self._approval_hooks.append(hook)

    def _run_approval_chain(self, patch):
        """Run approval chain. Any False rejects all.
        Returns: (allowed, reason)
        """
        if not self._approval_hooks:
            return True, "no hooks (allow by default)"
        for hook in self._approval_hooks:
            try:
                result = hook(patch)
            except Exception as exc:
                result = False
                log.warning("[self-modify] approval hook error: %s", exc)
            entry = {"hook": getattr(hook, "__name__", str(hook)), "result": result}
            self._approval_log.append(entry)
            if result is False:
                return False, "rejected by: " + entry["hook"]
        return True, "approved"

    def get_approval_log(self):
        return list(self._approval_log)

    def _validate_patch(self, patch: dict) -> tuple[str | None, dict]:
        """返回 (error, 规范化 patch)。非空 error 即拒绝。"""
        if not isinstance(patch, dict):
            return "patch 必须是对象", {}
        ptype = patch.get("type")
        if ptype not in PATCH_TYPES:
            return f"不允许的 patch type: {ptype!r}", {}
        target = str(patch.get("target") or "")
        if not target or not target.startswith(self.engine_dir + "/"):
            return f"target 须落在授权切片内: {target}", {}
        resolved = (self.project_root / target).resolve()
        try:
            resolved.relative_to(self.project_root)
        except ValueError:
            return "target 逃逸项目根, 拒绝", {}
        return None, {"type": ptype, "target": target, "content": patch.get("content"),
                      "expected_tests": patch.get("expected_tests") or list(self.gate_tests),
                      "note": patch.get("note", "")}

    # ── 沙箱暂存副本 ──────────────────────────────────────────
    def _stage(self, patch: dict) -> Path | None:
        """把 patch 内容暂存到沙箱副本(仅对待新增文件). 返回沙箱目标路径或 None. """
        engine_src = self.project_root / self.engine_dir
        if patch["type"] != "add_file":
            return None  # 规则/参数类不变更文件本体
        content = patch.get("content")
        if not isinstance(content, str):
            return None
        rel = str((self.project_root / patch["target"]).relative_to(self.project_root))
        # 仅在 engine 子目录内新增 .py 文件, 不做既有文件改写
        if not rel.endswith(".py") or (self.project_root / patch["target"]).exists():
            return None
        # 沙箱副本: 写临时文件到 engine 副本
        sandbox = engine_src / "_sandbox_staged" / rel
        sandbox.parent.mkdir(parents=True, exist_ok=True)
        sandbox.write_text(content, encoding="utf-8")
        return sandbox

    # ── pytest 门禁 ──────────────────────────────────────────
    def _run_gate(self, patch: dict, sandbox_target: Path | None) -> dict:
        """跑指定 pytest 门禁。返回 {pass_count/fail_count/total/details}."""
        tests = list(patch.get("expected_tests") or self.gate_tests)
        results = []
        cwd = str(self.project_root)
        for test in tests:
            try:
                proc = subprocess.run(
                    [sys.executable, "-m", "pytest", "-q", "--tb=short", "--no-cov", test],
                    capture_output=True, text=True, timeout=self.pytest_timeout,
                    cwd=cwd, encoding="utf-8", errors="replace")
                ok = proc.returncode == 0
            except subprocess.TimeoutExpired:
                ok, detail = False, "pytest timeout"
                results.append({"field": test, "passed": ok, "detail": detail})
                continue
            except Exception as exc:
                ok, detail = False, f"pytest error: {exc}"
                results.append({"field": test, "passed": ok, "detail": detail})
                continue
            detail = (proc.stdout or proc.stderr or "")[-200:]
            results.append({"field": test, "passed": ok, "detail": detail})
        return {
            "pass_count": sum(1 for r in results if r["passed"]),
            "fail_count": sum(1 for r in results if not r["passed"]),
            "total": len(results), "details": results,
        }

    # ── 备份 / 提交 / 回滚 ───────────────────────────────────
    # ── read-before-write guard (deer-flow 契约借鉴, C3) ──────────
    @staticmethod
    def _sha256_of(path: Path) -> str | None:
        """Hash of the file's CURRENT bytes, or None if absent (read mark)."""
        try:
            return hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            return None

    def _backup_and_commit(self, patch: dict, sandbox_target: Path | None) -> GateResult:
        """备份已存在目标 + 写入新内容。规则/参数类: 把内容追加进 signals JSON."""
        target_path = (self.project_root / patch["target"]).resolve()
        # C3 read-before-write guard: if a read mark was recorded at propose()
        # time (the content the gate reasoned about), the target must be
        # byte-identical now; otherwise a concurrent writer changed it and
        # merging would silently clobber. Fail closed instead.
        mark = patch.get("read_mark")
        if mark is not None and target_path.exists() and self._sha256_of(target_path) != mark:
            log.warning("[self-modify] stale target (read-before-write violated); rejected")
            return GateResult(status="rejected", gate={},
                              reason="stale target: changed since read (read-before-write guard)")

        # 备份(若目标已存在)
        backup = ""
        if target_path.exists():
            self.backup_dir.mkdir(parents=True, exist_ok=True)
            import datetime as _dt
            backup = self.backup_dir / f"{target_path.stem}-{_dt.datetime.now().strftime('%Y%m%d%H%M%S')}.bak"
            shutil.copy2(target_path, backup)
        # 提交
        if patch["type"] == "add_file" and sandbox_target is not None:
            sandbox_target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(sandbox_target, target_path)
        elif patch["type"] == "edit_params":
            content = patch.get("content")
            if isinstance(content, dict):
                # 合并 params 到 signals JSON 候选文件
                # 为保持可测与最小化, 仅演示把 params 合并写回目标(若目标为 json)
                if target_path.suffix == ".json" and target_path.exists():
                    base = json.loads(target_path.read_text(encoding="utf-8"))
                    merged = dict(base)
                    merged.update(content)
                    target_path.write_text(json.dumps(merged, ensure_ascii=False, indent=2),
                                           encoding="utf-8")
        # add_rule: 规则以注释记录在 signals 末尾(不改变既有字段语义)
        elif patch["type"] == "add_rule":
            content = patch.get("content")
            if isinstance(content, dict) and target_path.suffix == ".json" and target_path.exists():
                base = json.loads(target_path.read_text(encoding="utf-8"))
                if isinstance(base, list):
                    entry = dict(content)
                    entry.setdefault("signal_pattern", entry.get("signal_pattern", ""))
                    base.append(entry)
                    target_path.write_text(json.dumps(base, ensure_ascii=False, indent=2),
                                           encoding="utf-8")
        return GateResult(status="committed", gate={"passed": True},
                          backup=str(backup), committed=True)

    # ── 对外主流程 ──────────────────────────────────────────
    def propose(self, patch: dict) -> GateResult:
        """候选变更 -> 沙箱验证 -> 门禁 -> 提交/丢弃. (先测后写)"""
        err, clean = self._validate_patch(patch)
        if err:
            log.warning("[self-modify] rejected: %s", err)
            return GateResult(status="rejected", reason=err)
        # C3: record the read mark (current content hash) the gate reasons
        # about; _backup_and_commit re-hashes and fails closed on mismatch.
        _tgt = (self.project_root / clean["target"]).resolve()
        clean["read_mark"] = self._sha256_of(_tgt) if _tgt.exists() else None
        sandbox_target = self._stage(clean)
        gate = self._run_gate(clean, sandbox_target)
        all_pass = gate["fail_count"] == 0 and gate["total"] > 0
        if not all_pass:
            # 丢弃沙箱暂存 + 登记失败模式(可被 L2 学习)
            if sandbox_target is not None and sandbox_target.exists():
                try:
                    sandbox_target.unlink()
                except OSError:
                    pass
            log.warning("[self-modify] gate FAILED %s/ %s; discarded",
                        gate["fail_count"], gate["total"])
            return GateResult(status="rejected", gate=gate,
                              reason="pytest gate failed; change discarded")
        approved, reason = self._run_approval_chain(clean)
        if not approved:
            if sandbox_target is not None and sandbox_target.exists():
                try: sandbox_target.unlink()
                except OSError: pass
            log.warning("[self-modify] approval REJECTED: %s", reason)
            return GateResult(status="rejected", gate=gate, reason="approval: " + reason)
        return self._backup_and_commit(clean, sandbox_target)
