"""dsh-jobs (Python port) - bounded-output-ring job registry.

Translated (not copied) from the DSH jobs domain:
  @deepseek-ai/dsh-jobs (types/view/brand) + @deepseek-ai/dsh-jobs-local
  (ring/pump) + @deepseek-ai/dsh-tool-jobs (model surface).

Domain essence (preserved):
  - A job has a lifecycle: running -> (stopping) -> exactly one terminal
    status (completed | killed | failed). Producer narration never changes it.
  - Output is a BOUNDED RING of chunks at ABSOLUTE byte offsets. Appends land
    whole; head eviction advances `earliest` but NEVER moves an assigned
    offset. A reader below `earliest` is told `lossy=True` so it can render the
    discontinuity instead of a silent splice.
  - Reads are NON-CONSUMING: `read_at(from)` returns every retained chunk
    overlapping [from, total) plus the resume offset (`next = total`, always a
    chunk boundary). A consuming model cursor is tracked separately.
  - Retention is bounded by a byte cap; a single oversized chunk keeps only its
    UTF-8-safe TAIL (the cut advances past continuation bytes so the surviving
    text never starts inside a code point) and gains `gapBefore`.
  - A `JobOutcome.result` (value result, not a stream) is handed out by the
    first consuming read after settlement, exactly once.

Tools: job_submit, job_list, job_read, job_kill.
"""
from __future__ import annotations

import logging
import threading
import time

_log = logging.getLogger("sloth_engine.plugin.dsh-jobs")

STATUSES = ("running", "stopping", "completed", "killed", "failed")
TERMINAL = ("completed", "killed", "failed")
CHANNELS = ("stdout", "stderr", "log")

DEFAULT_CAP_BYTES = 64 * 1024


def _utf8_len(text):
    return len(text.encode("utf-8"))


def utf8_tail(text, max_bytes):
    """The UTF-8-safe tail of `text` no longer than `max_bytes`.

    The byte cut advances past continuation bytes (0b10xxxxxx) so the surviving
    text never starts inside a code point. Mirrors ring.utf8Tail().
    """
    raw = text.encode("utf-8")
    if max_bytes <= 0:
        return "", 0
    start = len(raw) - max_bytes
    if start < 0:
        start = 0
    while start < len(raw) and (raw[start] & 0xC0) == 0x80:
        start += 1
    tail = raw[start:]
    return tail.decode("utf-8", errors="replace"), len(tail)


class OutputRing:
    """Bounded ring of chunks at absolute byte offsets (ring.ts parity)."""

    def __init__(self):
        self.chunks = []
        self.retained_bytes = 0
        self.total = 0
        self.earliest = 0

    def append(self, text, options=None, cap=DEFAULT_CAP_BYTES):
        if not text:
            return False
        b = _utf8_len(text)
        entry = {"at": self.total, "text": text, "bytes": b}
        options = options or {}
        if options.get("channel") is not None:
            entry["channel"] = options["channel"]
        if options.get("gapBefore"):
            entry["gapBefore"] = True
        self.chunks.append(entry)
        self.total += b
        self.retained_bytes += b
        self.trim(cap)
        return True

    def trim(self, cap):
        while self.retained_bytes > cap and len(self.chunks) > 1:
            dropped = self.chunks.pop(0)
            self.retained_bytes -= dropped["bytes"]
        if len(self.chunks) == 1 and self.chunks[0]["bytes"] > cap:
            single = self.chunks[0]
            text, nbytes = utf8_tail(single["text"], cap)
            single["at"] += single["bytes"] - nbytes
            single["text"] = text
            single["bytes"] = nbytes
            single["gapBefore"] = True
            self.retained_bytes = nbytes
        self.earliest = self.chunks[0]["at"] if self.chunks else self.total

    def read_from(self, frm):
        """Retained chunks overlapping [frm, total); non-consuming (readFrom)."""
        out = []
        for c in self.chunks:
            if c["at"] + c["bytes"] <= frm:
                continue
            chunk = {"at": c["at"], "text": c["text"]}
            if c.get("channel") is not None:
                chunk["channel"] = c["channel"]
            if c.get("gapBefore"):
                chunk["gapBefore"] = True
            out.append(chunk)
        return {"chunks": out, "next": self.total, "lossy": frm < self.earliest}


class Job:
    """One registered job record (registry-owned identity + lifecycle)."""

    def __init__(self, job_id, kind, label, cap):
        self.id = job_id
        self.kind = kind
        self.label = label
        self.cap = cap
        self.status = "running"
        self.progress = None
        self.detail = None
        self.result = None
        self.result_delivered = False
        self.started_at = int(time.time() * 1000)
        self.finished_at = None
        self.ring = OutputRing()

    def append(self, text, options=None):
        if self.status in TERMINAL:
            _log.debug("[jobs] drop append on settled job %s", self.id)
            return False
        return self.ring.append(text, options, self.cap)

    def view(self):
        v = {
            "id": self.id,
            "kind": self.kind,
            "label": self.label,
            "status": self.status,
            "startedAt": self.started_at,
            "output": {"total": self.ring.total, "earliest": self.ring.earliest},
        }
        if self.progress is not None:
            v["progress"] = self.progress
        if self.detail is not None:
            v["detail"] = self.detail
        if self.finished_at is not None:
            v["finishedAt"] = self.finished_at
        return v


class JobRegistry:
    """Process-wide registry: identity, lifecycle state, and the output ring."""

    def __init__(self):
        self._jobs = {}
        self._ordinal = {}
        self._lock = threading.Lock()

    def _next_id(self, kind):
        n = self._ordinal.get(kind, 0) + 1
        self._ordinal[kind] = n
        return "{}-{}".format(kind, n)

    def submit(self, kind, label, cap=DEFAULT_CAP_BYTES):
        with self._lock:
            jid = self._next_id(kind)
            job = Job(jid, kind, label, cap)
            self._jobs[jid] = job
            return job

    def get(self, job_id):
        return self._jobs.get(job_id)

    def list(self):
        return [j.view() for j in self._jobs.values()]

    def settle(self, job_id, status, detail=None, result=None):
        """Apply a terminal status once; later calls are no-ops (idempotent)."""
        job = self._jobs.get(job_id)
        if job is None:
            return None
        if job.status in TERMINAL:
            return job.view()
        if status not in TERMINAL:
            raise ValueError("terminal status required, got {}".format(status))
        job.status = status
        job.progress = None
        if detail is not None:
            job.detail = detail
        if result is not None:
            job.result = result
        job.finished_at = int(time.time() * 1000)
        return job.view()

    def request_stop(self, job_id, reason=None):
        job = self._jobs.get(job_id)
        if job is None:
            return None
        if job.status == "running":
            job.status = "stopping"
            if reason:
                job.detail = reason
        return job.view()

    def read_at(self, job_id, frm):
        job = self._jobs.get(job_id)
        if job is None:
            return None
        r = job.ring.read_from(int(frm))
        r["job"] = job.view()
        return r

    def read(self, job_id):
        """Consuming read: hands out the settled `result` exactly once."""
        job = self._jobs.get(job_id)
        if job is None:
            return None
        r = job.ring.read_from(0)
        out = {"chunks": r["chunks"], "lossy": r["lossy"], "job": job.view()}
        if job.status in TERMINAL and job.result is not None and not job.result_delivered:
            job.result_delivered = True
            out["result"] = job.result
        return out


_REGISTRY = JobRegistry()


def _job_submit(payload):
    p = payload or {}
    kind = str(p.get("kind") or "bash").strip()
    label = str(p.get("label") or "").strip()
    if not kind:
        return {"ok": False, "error": "kind required"}
    if not label:
        return {"ok": False, "error": "label required"}
    cap = p.get("capBytes")
    try:
        cap = int(cap) if cap is not None else DEFAULT_CAP_BYTES
    except (TypeError, ValueError):
        return {"ok": False, "error": "capBytes must be an integer"}
    if cap <= 0:
        return {"ok": False, "error": "capBytes must be positive"}
    job = _REGISTRY.submit(kind, label, cap=cap)
    initial = p.get("output")
    if isinstance(initial, str) and initial:
        job.append(initial, {"channel": p.get("channel") or "stdout"})
    _log.info("[jobs] submit %s kind=%s label=%r", job.id, kind, label)
    return {"ok": True, "job": job.view()}


def _job_list(payload):
    p = payload or {}
    status = p.get("status")
    jobs = _REGISTRY.list()
    if status:
        jobs = [j for j in jobs if j["status"] == status]
    return {"ok": True, "count": len(jobs), "jobs": jobs}


def _job_read(payload):
    p = payload or {}
    jid = str(p.get("id") or "").strip()
    if not jid:
        return {"ok": False, "error": "id required"}
    job = _REGISTRY.get(jid)
    if job is None:
        return {"ok": False, "error": "no such job: {}".format(jid)}
    if p.get("from") is not None:
        try:
            frm = int(p["from"])
        except (TypeError, ValueError):
            return {"ok": False, "error": "from must be an integer"}
        r = _REGISTRY.read_at(jid, frm)
        return {"ok": True, "id": jid, "mode": "at", **r}
    r = _REGISTRY.read(jid)
    return {"ok": True, "id": jid, "mode": "consume", **r}


def _job_kill(payload):
    p = payload or {}
    jid = str(p.get("id") or "").strip()
    if not jid:
        return {"ok": False, "error": "id required"}
    reason = p.get("reason")
    job = _REGISTRY.get(jid)
    if job is None:
        return {"ok": False, "error": "no such job: {}".format(jid)}
    if job.status in TERMINAL:
        return {"ok": True, "job": job.view(), "already": True}
    _REGISTRY.request_stop(jid, reason)
    view = _REGISTRY.settle(jid, "killed", detail=(str(reason) if reason else None))
    _log.info("[jobs] kill %s reason=%r", jid, reason)
    return {"ok": True, "job": view}


def register(ctx):
    from tool_registry import ToolDefinition
    cfg = {}
    try:
        cfg = (getattr(ctx, "config", None) or {}).get("dsh-jobs") or {}
    except Exception:
        cfg = {}
    cap = cfg.get("capBytes", DEFAULT_CAP_BYTES)

    def _mk(name, fn, desc):
        ctx.register_tool(ToolDefinition(name=name, source="ops",
                                         handler=lambda payload=None, **k: fn(payload),
                                         description=desc))

    _mk("job_submit", _job_submit,
        "Register a background job (running) and return its view. "
        "params:{kind:str,label:str,output?:str,channel?:stdout|stderr|log,capBytes?:int}")
    _mk("job_list", _job_list,
        "List registered jobs (optionally filtered by status). "
        "params:{status?:running|stopping|completed|killed|failed}")
    _mk("job_read", _job_read,
        "Read a job's output ring. `from` gives a NON-consuming read at an "
        "absolute byte offset; otherwise the consuming read (hands out a "
        "settled result once). params:{id:str,from?:int}")
    _mk("job_kill", _job_kill,
        "Request stop then settle a job as `killed` (idempotent). "
        "params:{id:str,reason?:str}")
    return {"tools": ["job_submit", "job_list", "job_read", "job_kill"],
            "default_cap_bytes": cap}
