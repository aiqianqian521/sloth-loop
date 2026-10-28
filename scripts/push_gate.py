#!/usr/bin/env python
"""Fail-closed *server-side* push gate (cycle-37 A, ROADMAP P0 fail-closed CI).

scripts/run_gate.py is a *client-side* pre-commit hook: `git commit --no-verify`,
`git -c core.hooksPath=<elsewhere>` and a fresh clone with no hook installed all
skip it.  This program is the other half.  It runs from a ``pre-receive`` hook on
the *receiving* repository, where the pusher cannot switch it off, and it gates
what the push would actually introduce:

  1. content scan (content_scan.scan_text, pinned beside this file) over every
     blob of each new tip: secret material, private keys, AWS access key ids,
     hard-coded credentials, developer home-directory paths in code/config;
  2. the full local gate (``scripts/run_gate.py --all`` of the *pushed tree* by
     default), so "green locally" and "green on arrival" are one measurement
     rather than two beliefs.

Trust boundary (stated, not implied): the hook, the pinned copy of this file and
its configuration live on the receiving host.  A pusher controls none of them,
so ``--no-verify`` / ``core.hooksPath`` / a fresh clone cannot bypass the check.
The one knob that can weaken it is ``LOOP_PUSH_GATE_CMD``, which is *host*
configuration written by scripts/install_push_gate.py: it exists so a deployment
can point at its own runner (it receives the materialized tree path as its last
argument and runs with that tree as its working directory).  The gate code is
never read from the pushed tree --
a push that neutralises ``scripts/push_gate.py`` is still gated by the pinned
copy (see tests/test_push_gate.py).

Host/CI tool: spawning git/``run_gate`` here is not a business spawn, and it is
registered as such in tests/test_contract_invariants.py (SPAWN_OUTSIDE_GATE).
"""
from __future__ import annotations

import argparse
import io
import json
import os
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import content_scan   # noqa: E402  (pinned copy lives beside this file)

DEFAULT_TIMEOUT = 1800
MAX_SCAN_BYTES = 2_000_000
GATE_SCRIPT = ("scripts", "run_gate.py")


class GateError(RuntimeError):
    """A condition that makes the gate unable to judge (always a reject)."""


def _safe_extract(tf, dest):
    for m in tf.getmembers():
        parts = Path(m.name).parts
        if m.name.startswith("/") or ".." in parts:
            raise GateError("archive member escapes the tree: " + m.name)
        if m.issym() or m.islnk():
            raise GateError("archive member is a link, refusing: " + m.name)
    try:
        tf.extractall(dest, filter="data")     # Python >= 3.12
    except TypeError:                          # pragma: no cover - older pythons
        tf.extractall(dest)


def materialize(repo, sha, dest):
    """Write the tree of *sha* into *dest* using git+tarfile (no external tar)."""
    r = subprocess.run(["git", "-C", str(repo), "archive", "--format=tar", sha],
                       capture_output=True)
    if r.returncode != 0:
        raise GateError("git archive %s failed: %s"
                        % (sha, r.stderr.decode("utf-8", "replace")[:400]))
    with tarfile.open(fileobj=io.BytesIO(r.stdout), mode="r:") as tf:
        _safe_extract(tf, str(dest))
    return Path(dest)


def scan_tree(tree):
    """Content findings for every text blob under *tree* (empty == clean)."""
    root = Path(tree)
    findings = []
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(root).as_posix()
        if rel == ".git" or rel.startswith(".git/"):
            continue
        try:
            if p.stat().st_size > MAX_SCAN_BYTES:
                continue
            blob = p.read_bytes()
        except OSError:
            continue
        if b"\x00" in blob[:4096]:
            continue
        findings.extend(content_scan.scan_text(rel, blob.decode("utf-8", "replace")))
    return findings


def _gate_argv(tree):
    """argv + cwd for the "tests half" of the gate (host configuration)."""
    raw = os.environ.get("LOOP_PUSH_GATE_CMD")
    if raw:
        try:
            argv = json.loads(raw)
        except Exception as exc:
            raise GateError("LOOP_PUSH_GATE_CMD is not valid JSON: %r" % (exc,))
        if not (isinstance(argv, list) and argv
                and all(isinstance(a, str) for a in argv)):
            raise GateError("LOOP_PUSH_GATE_CMD must be a non-empty JSON array "
                            "of argv strings")
        return argv + [str(tree)], str(tree)
    py = os.environ.get("LOOP_PUSH_GATE_PYTHON") or sys.executable
    return [py, str(Path(tree).joinpath(*GATE_SCRIPT)), "--all"], str(tree)


def gate_tree(tree, timeout=None):
    """Problems for one materialized tree (content scan + the tests half)."""
    problems = list(scan_tree(tree))
    if os.environ.get("LOOP_PUSH_GATE_SKIP_TESTS") == "1":
        return problems
    argv, cwd = _gate_argv(tree)
    limit = timeout if timeout is not None else int(
        os.environ.get("LOOP_PUSH_GATE_TIMEOUT", DEFAULT_TIMEOUT))
    try:
        r = subprocess.run(argv, cwd=cwd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=limit)
    except subprocess.TimeoutExpired:
        problems.append("gate command timed out after %ss" % limit)
        return problems
    except OSError as exc:
        problems.append("gate command could not run %r: %s" % (argv, exc))
        return problems
    sys.stdout.write(r.stdout or "")
    sys.stderr.write(r.stderr or "")
    if r.returncode != 0:
        problems.append("gate command exited %d (See the output above.)"
                        % r.returncode)
    return problems


def pre_receive(lines, repo, scratch=None):
    """Gate every new tip named on the pre-receive stdin (list of lines)."""
    problems = []
    for line in lines:
        if not line.strip():
            continue
        parts = line.split()
        if len(parts) < 3:
            problems.append("malformed pre-receive line: %r" % (line,))
            continue
        old, new, ref = parts[0], parts[1], parts[2]
        if new.strip("0") == "":
            continue                     # ref deletion: nothing to gate
        with tempfile.TemporaryDirectory(prefix="loop-push-gate-",
                                         dir=scratch) as tmp:
            tree = Path(tmp) / "tree"
            tree.mkdir()
            try:
                materialize(repo, new, tree)
            except GateError as exc:
                problems.append("%s %s: %s" % (ref, new[:10], exc))
                continue
            for f in gate_tree(tree):
                problems.append("%s %s: %s" % (ref, new[:10], f))
    return problems


def main(argv=None):
    ap = argparse.ArgumentParser(description="fail-closed push gate")
    ap.add_argument("--stdin", action="store_true",
                    help="read pre-receive '<old> <new> <ref>' lines from stdin")
    ap.add_argument("--repo", default=".",
                    help="repository whose objects are archived (default: .)")
    ap.add_argument("--tree", help="gate an already materialized tree instead")
    ap.add_argument("--content-only", action="store_true",
                    help="with --tree: content scan only (fast unit aid)")
    ap.add_argument("--scratch", default=None,
                    help="parent dir for the temporary checkout")
    args = ap.parse_args(sys.argv[1:] if argv is None else argv)
    try:
        if args.tree:
            problems = list(scan_tree(args.tree))
            if not args.content_only:
                problems += gate_tree(args.tree)
        elif args.stdin:
            problems = pre_receive(sys.stdin.read().splitlines(), args.repo,
                                   args.scratch)
        else:
            ap.error("one of --tree / --stdin is required")
            return 1
    except GateError as exc:
        print("[push-gate] REJECTED: " + str(exc), file=sys.stderr)
        return 1
    if problems:
        print("[push-gate] REJECTED (%d problem(s)):" % len(problems),
              file=sys.stderr)
        for p in problems:
            print("  - " + p, file=sys.stderr)
        return 1
    print("[push-gate] ACCEPTED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
