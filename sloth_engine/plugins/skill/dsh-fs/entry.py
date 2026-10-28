"""dsh-fs (Python port) - model-facing read/write/edit/stat over a fenced workspace.

Translated (not copied) from @deepseek-ai/dsh-tool-fs (read/write/edit/read_image)
+ @deepseek-ai/dsh-tool-str-replace-editor (view/create/str_replace/insert).

Domain essence (preserved):
  - `read` returns LINE-NUMBERED UTF-8 content with a pagination footer; `offset`
    is 1-based, `limit` defaults to and caps at readLimit.
  - `write` creates or fully replaces a file ATOMICALLY (temp file + os.replace),
    so a crash never leaves a half-written file.
  - `edit` applies a LITERAL replacement: the `old_string` must match uniquely
    unless `replace_all` is true; whitespace/tabs outside the edit are preserved.
  - Results are CAPPED (readMaxBytes / readMaxLineLength) and failures carry
    stable codes (`FS_NOT_FOUND`, `FS_NOT_A_FILE`, `FS_AMBIGUOUS`,
    `FS_NO_MATCH`, `FS_OUT_OF_SCOPE`, `FS_TOO_LARGE`) with recovery hints.
  - Every path is FENCED: it must resolve under an authorized root
    (workspace_root + optional extra roots); escape -> fail-closed.

Deliberate scope notes (sloth-loop is a deterministic OODA backtest
orchestrator with no LLM-driven agent loop, so this is the ONE DSH fs domain
judged necessary — see the roadmap necessity assessment):
  - `read_image` is intentionally NOT ported (no image-capable routed model).
  - `str_replace_editor` overlaps `fs_edit`; not ported separately.

Tools: fs_read, fs_write, fs_edit, fs_stat.
"""
from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path

_log = logging.getLogger("sloth_engine.plugin.dsh-fs")

DEFAULTS = {
    "readLimit": 2000,          # default + max lines per read
    "readMaxLineLength": 2000,  # chars kept per line before truncation
    "readMaxBytes": 51200,      # byte cap on one read's selected lines
}


class FsError(Exception):
    """Classified fs failure with a stable code + recovery hint."""

    def __init__(self, code, message, remedy=""):
        super().__init__(message)
        self.code = code
        self.remedy = remedy


def _workspace_roots(config) -> list[Path]:
    """Authorized roots: workspace_root + optional extra_roots (all resolved)."""
    c = (config or {}).get("plugins") or {}
    fs_cfg = c.get("fs") or {}
    roots: list[Path] = []
    ws = fs_cfg.get("workspace_root")
    if ws:
        roots.append(Path(ws))
    for extra in (fs_cfg.get("extra_roots") or []):
        roots.append(Path(extra))
    if not roots:
        roots.append(Path("."))
    return [r.resolve() for r in roots]


def _fence(path_str: str, roots: list[Path]) -> Path:
    """Resolve + fence a path under one authorized root (fail-closed)."""
    if not isinstance(path_str, str) or not path_str.strip():
        raise FsError("FS_BAD_PATH", "file_path must be a non-empty string")
    raw = Path(path_str)
    if not raw.is_absolute():
        # relative paths resolve against the first (primary) root
        raw = (roots[0] / raw)
    resolved = raw.resolve()
    for root in roots:
        if resolved == root or resolved.is_relative_to(root):
            return resolved
    raise FsError(
        "FS_OUT_OF_SCOPE",
        'cannot access "{}": path is outside the authorized workspace'.format(path_str),
        "use a path under the configured workspace_root")


class _Fs:
    def __init__(self, config):
        self.roots = _workspace_roots(config)
        c = (config or {}).get("plugins") or {}
        fs_cfg = c.get("fs") or {}
        self.cfg = dict(DEFAULTS)
        for k in DEFAULTS:
            if fs_cfg.get(k) is not None:
                self.cfg[k] = int(fs_cfg[k])

    # ── read ──────────────────────────────────────────────
    def read(self, file_path, offset=1, limit=None):
        p = _fence(file_path, self.roots)
        if not p.exists():
            raise FsError("FS_NOT_FOUND", 'cannot read "{}": not found'.format(file_path),
                          "check the path, or create the file with fs_write")
        if not p.is_file():
            raise FsError("FS_NOT_A_FILE", 'cannot read "{}": not a regular file'.format(file_path))
        max_lines = self.cfg["readLimit"]
        try:
            limit = int(limit) if limit is not None else max_lines
        except (TypeError, ValueError):
            raise FsError("FS_BAD_ARG", "limit must be an integer")
        if limit < 1 or limit > max_lines:
            raise FsError("FS_BAD_ARG", "limit must be between 1 and {}".format(max_lines))
        try:
            offset = int(offset)
        except (TypeError, ValueError):
            raise FsError("FS_BAD_ARG", "offset must be an integer")
        if offset < 1:
            raise FsError("FS_BAD_ARG", "offset is 1-based and must be >= 1")

        max_line = self.cfg["readMaxLineLength"]
        max_bytes = self.cfg["readMaxBytes"]
        lines_out = []
        used = 0
        total = 0
        truncated_lines = 0
        with open(p, "r", encoding="utf-8", errors="replace") as fh:
            for i, line in enumerate(fh, start=1):
                total = i
                if i < offset:
                    continue
                if len(lines_out) >= limit:
                    # count remaining lines for the footer
                    for _ in fh:
                        total += 1
                    break
                text = line.rstrip("\n")
                if len(text) > max_line:
                    text = text[:max_line] + " …[line truncated]"
                    truncated_lines += 1
                rendered = "{:>6}\t{}".format(i, text)
                used += len(rendered.encode("utf-8")) + 1
                if used > max_bytes:
                    break
                lines_out.append(rendered)
        body = "\n".join(lines_out)
        shown = len(lines_out)
        footer = "[lines {}-{} of {} | limit={}{}]".format(
            offset, offset + max(0, shown - 1), total, limit,
            "; line(s) truncated" if truncated_lines else "")
        return {
            "ok": True, "file_path": str(p),
            "content": body + "\n" + footer,
            "shown": shown, "total_lines": total, "truncated_lines": truncated_lines,
        }

    # ── stat ──────────────────────────────────────────────
    def stat(self, file_path):
        p = _fence(file_path, self.roots)
        if not p.exists():
            return {"ok": True, "file_path": str(p), "exists": False}
        st = p.stat()
        return {
            "ok": True, "file_path": str(p), "exists": True,
            "is_file": p.is_file(), "is_dir": p.is_dir(),
            "size": st.st_size, "mtime": int(st.st_mtime),
        }

    # ── write (atomic) ────────────────────────────────────
    def write(self, file_path, content, overwrite=True):
        p = _fence(file_path, self.roots)
        if content is None:
            raise FsError("FS_BAD_ARG", "content is required")
        content = str(content)
        existed = p.exists()
        if existed and p.is_dir():
            raise FsError("FS_NOT_A_FILE", 'cannot write "{}": is a directory'.format(file_path))
        if existed and not overwrite:
            raise FsError("FS_EXISTS", 'cannot create "{}": already exists'.format(file_path),
                          "pass overwrite=true to replace")
        p.parent.mkdir(parents=True, exist_ok=True)
        # atomic replace: temp in same dir -> os.replace
        fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=".fs_", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
                fh.write(content)
            os.replace(tmp, p)
        finally:
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass
        verb = "Updated" if existed else "Created"
        _log.info("[fs] %s file %s (%d chars)", verb.lower(), p, len(content))
        return {"ok": True, "file_path": str(p), "action": verb.lower(),
                "bytes": len(content.encode("utf-8"))}

    # ── edit (literal) ────────────────────────────────────
    def edit(self, file_path, old_string, new_string, replace_all=False):
        p = _fence(file_path, self.roots)
        if not p.exists():
            raise FsError("FS_NOT_FOUND", 'cannot modify "{}": not found'.format(file_path),
                          "read the file first, or create it with fs_write")
        if not p.is_file():
            raise FsError("FS_NOT_A_FILE", 'cannot modify "{}": not a regular file'.format(file_path))
        if not isinstance(old_string, str) or old_string == "":
            raise FsError("FS_BAD_ARG", "old_string must be a non-empty string")
        if new_string is None:
            raise FsError("FS_BAD_ARG", "new_string is required (use \"\" to delete)")
        new_string = str(new_string)
        original = p.read_text(encoding="utf-8")
        count = original.count(old_string)
        if count == 0:
            raise FsError("FS_NO_MATCH", 'no match for old_string in "{}"'.format(file_path),
                          "check the exact text; whitespace matters")
        if count > 1 and not replace_all:
            raise FsError(
                "FS_AMBIGUOUS",
                'old_string matches {} times in "{}"'.format(count, file_path),
                "provide more surrounding context, or set replace_all=true")
        updated = (original.replace(old_string, new_string) if replace_all
                   else original.replace(old_string, new_string, 1))
        # atomic rewrite
        fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=".fs_", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
                fh.write(updated)
            os.replace(tmp, p)
        finally:
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass
        _log.info("[fs] edited %s (%d replacement(s))", p, count if replace_all else 1)
        return {"ok": True, "file_path": str(p), "action": "edited",
                "replacements": (count if replace_all else 1)}


# process-wide singleton (config-bound at registration)
_FS = None


def _get():
    if _FS is None:
        raise FsError("FS_NOT_INIT", "dsh-fs not registered")
    return _FS


def _fs_read(payload):
    p = payload or {}
    try:
        return _get().read(p.get("file_path") or p.get("path"),
                           offset=p.get("offset", 1), limit=p.get("limit"))
    except FsError as exc:
        return {"ok": False, "code": exc.code, "error": str(exc), "remedy": exc.remedy}


def _fs_stat(payload):
    p = payload or {}
    try:
        return _get().stat(p.get("file_path") or p.get("path"))
    except FsError as exc:
        return {"ok": False, "code": exc.code, "error": str(exc), "remedy": exc.remedy}


def _fs_write(payload):
    p = payload or {}
    try:
        return _get().write(p.get("file_path") or p.get("path"),
                            p.get("content"), overwrite=bool(p.get("overwrite", True)))
    except FsError as exc:
        return {"ok": False, "code": exc.code, "error": str(exc), "remedy": exc.remedy}


def _fs_edit(payload):
    p = payload or {}
    try:
        return _get().edit(p.get("file_path") or p.get("path"),
                           p.get("old_string"), p.get("new_string"),
                           replace_all=bool(p.get("replace_all", False)))
    except FsError as exc:
        return {"ok": False, "code": exc.code, "error": str(exc), "remedy": exc.remedy}


def register(ctx):
    from tool_registry import ToolDefinition
    global _FS
    _FS = _Fs(getattr(ctx, "config", None) or {})

    def _mk(name, fn, desc):
        ctx.register_tool(ToolDefinition(name=name, source="skill",
                                         handler=lambda payload=None, **k: fn(payload),
                                         description=desc))

    _mk("fs_read", _fs_read,
        "Read a UTF-8 file with 1-based line numbers and a pagination footer. "
        "params:{file_path:str,offset?:int,limit?:int}")
    _mk("fs_write", _fs_write,
        "Create or atomically replace a file. params:{file_path:str,content:str,overwrite?:bool}")
    _mk("fs_edit", _fs_edit,
        "Literal replacement; old_string must match uniquely unless replace_all. "
        "params:{file_path:str,old_string:str,new_string:str,replace_all?:bool}")
    _mk("fs_stat", _fs_stat,
        "Stat a path under the fenced workspace (existence/type/size/mtime). "
        "params:{file_path:str}")
    return {"tools": ["fs_read", "fs_write", "fs_edit", "fs_stat"],
            "workspace_roots": [str(r) for r in _FS.roots]}
