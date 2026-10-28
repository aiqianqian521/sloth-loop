#!/usr/bin/env python
"""Install / uninstall the fail-closed push gate (cycle-37 A, ROADMAP P0).

Installs, into a *receiving* repository's hooks directory:

    hooks/pre-receive                     the shim that git runs
    hooks/loop-push-gate/push_gate.py     pinned copy of the gate
    hooks/loop-push-gate/content_scan.py  pinned copy of the scanner
    hooks/loop-push-gate.env              host config (interpreter, timeout)

The pinned copies matter: the gate must not be read from the pushed tree, or a
push could weaken its own check (tests/test_push_gate.py pins that).  An
existing ``pre-receive`` is backed up before being replaced, and --uninstall
restores it.

Usage:
    python scripts/install_push_gate.py --repo <receiving repo>     # install
    python scripts/install_push_gate.py --repo <repo> --uninstall   # remove
    python scripts/install_push_gate.py --repo <repo> --status
With no --repo it falls back to `git remote get-url origin`, then to '.'.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
BUNDLE_FILES = ("push_gate.py", "content_scan.py")
HOOK_SRC = HERE / "pre-receive"
BUNDLE_DIRNAME = "loop-push-gate"
ENV_NAME = "loop-push-gate.env"


def _sh(value: str) -> str:
    """Single-quote *value* for a POSIX shell (the hook is sourced by sh)."""
    return "'" + str(value).replace("'", "'\\''") + "'"


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo)] + list(args),
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace")


def _is_git_repo(repo) -> bool:
    return _git(repo, "rev-parse", "--git-dir").returncode == 0


def _local_hookspath(repo):
    r = _git(repo, "config", "--local", "--get", "core.hooksPath")
    return (r.stdout or "").strip() or None


def hooks_dir(repo) -> Path:
    """``<repo>/hooks`` for a bare repo, ``<repo>/.git/hooks`` otherwise."""
    repo = Path(repo)
    if (repo / "objects").is_dir() and (repo / "refs").is_dir():
        return repo / "hooks"
    return repo / ".git" / "hooks"


def default_repo(cwd=None) -> Path:
    cwd = Path(cwd or os.getcwd())
    r = subprocess.run(["git", "-C", str(cwd), "remote", "get-url", "origin"],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    url = (r.stdout or "").strip()
    if r.returncode == 0 and url:
        return Path(url)
    return cwd


def is_installed(repo) -> bool:
    hd = hooks_dir(repo)
    return (hd / "pre-receive").is_file() and (hd / BUNDLE_DIRNAME).is_dir()


def install(repo, python=None, cmd=None, timeout=None) -> int:
    repo = Path(repo).resolve()
    hd = hooks_dir(repo)
    if not hd.is_dir():
        print("[install-push-gate] FAIL: no hooks dir at %s (is that a repo?)"
              % hd, file=sys.stderr)
        return 1
    hook, bundle, env = hd / "pre-receive", hd / BUNDLE_DIRNAME, hd / ENV_NAME
    if hook.exists():
        backup = hook.with_name("pre-receive.bak-%s"
                                % time.strftime("%Y%m%d%H%M%S"))
        shutil.copy2(hook, backup)
        print("[install-push-gate] existing pre-receive backed up -> %s"
              % backup.name)
    bundle.mkdir(parents=True, exist_ok=True)
    for name in BUNDLE_FILES:
        (bundle / name).write_bytes((HERE / name).read_bytes())
    shutil.copyfile(HOOK_SRC, hook)
    try:
        os.chmod(hook, 0o755)
    except OSError:
        pass
    lines = [
        "# sloth-loop fail-closed push gate -- host side configuration.",
        "# Written by scripts/install_push_gate.py; sourced by hooks/pre-receive.",
        "export LOOP_PUSH_GATE_PYTHON=%s" % _sh(python or sys.executable),
        "export LOOP_PUSH_GATE_TIMEOUT=%s" % (timeout or 1800),
    ]
    if cmd:
        lines.append("# tests half: argv JSON array (tree path is appended):")
        lines.append("export LOOP_PUSH_GATE_CMD=%s" % _sh(json.dumps(list(cmd))))
    env.write_bytes(("\n".join(lines) + "\n").encode("utf-8"))
    # PIN core.hooksPath on the receiving repo.  Without this a *global*
    # core.hooksPath (this machine sets one) silently replaces the repo's own
    # hooks directory, so the installed gate would never run -- an invisible
    # bypass.  The previous local value is recorded for --uninstall.
    if _is_git_repo(repo):
        meta = {"repo": str(repo), "hooks_dir": str(hd),
                "prev_hooks_path": _local_hookspath(repo)}
        _git(repo, "config", "core.hooksPath", str(hd))
        (bundle / "install.json").write_text(
            json.dumps(meta, indent=2), encoding="utf-8")
        print("[install-push-gate] core.hooksPath pinned to %s (was %s)"
              % (hd, meta["prev_hooks_path"] or "unset"))
    else:
        print("[install-push-gate] WARNING: %s is not a git repo; the hook was "
              "written but core.hooksPath could not be pinned." % repo)
    print("[install-push-gate] installed into %s" % hd)
    print("  hook   : %s" % hook)
    print("  bundle : %s" % bundle)
    print("  config : %s" % env)
    return 0


def uninstall(repo) -> int:
    repo = Path(repo).resolve()
    hd = hooks_dir(repo)
    hook, bundle, env = hd / "pre-receive", hd / BUNDLE_DIRNAME, hd / ENV_NAME
    meta = {}
    meta_path = bundle / "install.json"
    if meta_path.is_file():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            meta = {}
    removed = []
    if bundle.is_dir():
        shutil.rmtree(bundle)
        removed.append(bundle.name + "/")
    if env.is_file():
        env.unlink()
        removed.append(env.name)
    if hook.is_file():
        hook.unlink()
        backups = sorted(hd.glob("pre-receive.bak-*"))
        if backups:
            shutil.copyfile(backups[-1], hook)
            print("[install-push-gate] restored %s from %s"
                  % (hook.name, backups[-1].name))
        else:
            removed.append(hook.name)
    target = Path(meta.get("repo") or repo)
    if meta.get("hooks_dir") and _is_git_repo(target):
        prev = meta.get("prev_hooks_path")
        if prev:
            _git(target, "config", "core.hooksPath", prev)
            print("[install-push-gate] core.hooksPath restored to %s" % prev)
        else:
            _git(target, "config", "--local", "--unset", "core.hooksPath")
            print("[install-push-gate] core.hooksPath unset (it was unset before)")
    print("[install-push-gate] uninstalled from %s (removed %s)"
          % (hd, ", ".join(removed) or "nothing"))
    return 0


def status(repo) -> int:
    repo = Path(repo).resolve()
    hd = hooks_dir(repo)
    print("[install-push-gate] repo       : %s" % repo)
    print("[install-push-gate] hooks dir  : %s" % hd)
    print("[install-push-gate] installed  : %s" % ("yes" if is_installed(repo) else "no"))
    env = hd / ENV_NAME
    if env.is_file():
        print("[install-push-gate] config     :")
        for ln in env.read_text(encoding="utf-8").splitlines():
            print("    " + ln)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="install the fail-closed push gate")
    ap.add_argument("--repo", default=None,
                    help="receiving repository (default: origin remote, else .)")
    ap.add_argument("--python", default=None,
                    help="interpreter for the tests half (default: this python)")
    ap.add_argument("--cmd-json", default=None,
                    help="JSON array argv for the tests half (advanced)")
    ap.add_argument("--timeout", type=int, default=None)
    ap.add_argument("--uninstall", action="store_true")
    ap.add_argument("--status", action="store_true")
    args = ap.parse_args(sys.argv[1:] if argv is None else argv)
    repo = Path(args.repo).resolve() if args.repo else default_repo()
    if args.status:
        return status(repo)
    if args.uninstall:
        return uninstall(repo)
    cmd = json.loads(args.cmd_json) if args.cmd_json else None
    return install(repo, python=args.python, cmd=cmd, timeout=args.timeout)


if __name__ == "__main__":
    raise SystemExit(main())
