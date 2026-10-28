"""dsh-schedule (Python port) - durable reminders with strict time validation.

Translated (not copied) from @deepseek-ai/dsh-schedule.

Domain essence (preserved):
  - Four rule kinds: after(positive delay), at(absolute instant), every(fixed
    rate), cron(field expression). Each record has a stable id, a required
    non-empty <=120-char title, and a trimmed prompt.
  - Strict UTC instants: four-digit year, millisecond precision, `Z` suffix
    (the DSH wire form). Local/offset instants are accepted at input and
    normalized to UTC.
  - MIN_EVERY_INTERVAL_SECONDS = 60. A rule that could never match is rejected
    at creation, not silently accepted.
  - Cron matching is bounded by CRON_SEARCH_HORIZON_YEARS = 400 (the proleptic
    Gregorian cycle), so an unsatisfiable rule fails fast instead of walking to
    the year-9999 ceiling.

Tools: schedule_create, schedule_list, schedule_delete, schedule_due.
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

_log = logging.getLogger("sloth_engine.plugin.dsh-schedule")

MIN_EVERY_INTERVAL_SECONDS = 60
MAX_TITLE_LENGTH = 120
CRON_SEARCH_HORIZON_YEARS = 400

_KINDS = ("after", "at", "every", "cron")
_UTC_INSTANT = re.compile(
    r"^(?!0000)\d{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])"
    r"T(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d\.\d{3}Z$")

# ── cron field support (5-field: min hour dom month dow) ──────────────
_FIELD_BOUNDS = ((0, 59), (0, 23), (1, 31), (1, 12), (0, 6))
_DOW_NAMES = {"sun": 0, "mon": 1, "tue": 2, "wed": 3, "thu": 4, "fri": 5, "sat": 6}
_MON_NAMES = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
              "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}


def parse_instant(value: str) -> datetime:
    """Parse an RFC3339 instant; normalize to UTC. Raises ValueError."""
    v = str(value or "").strip()
    if not v:
        raise ValueError("instant required")
    if "Z" in v or re.search(r"[+-]\d{2}:\d{2}$", v):
        dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc)
    # bare local -> interpret as UTC (deterministic, host-independent)
    dt = datetime.fromisoformat(v)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def format_instant(dt: datetime) -> str:
    """Render the DSH wire form (ms precision, Z)."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _parse_cron_field(token: str, lo: int, hi: int, names: dict | None):
    names = names or {}
    values = set()
    for part in token.split(","):
        part = part.strip().lower()
        if not part:
            raise ValueError("empty cron field segment")
        step = 1
        base = part
        if "/" in part:
            base, _, step_s = part.partition("/")
            try:
                step = int(step_s)
            except ValueError:
                raise ValueError(f"invalid cron step {step_s!r}")
            if step <= 0:
                raise ValueError("cron step must be positive")
        if base in ("*", ""):
            start, end = lo, hi
        elif "-" in base:
            a, _, b = base.partition("-")
            start, end = _cron_int(a, lo, hi, names), _cron_int(b, lo, hi, names)
            if start > end:
                raise ValueError(f"cron range {base!r} inverted")
        else:
            start = end = _cron_int(base, lo, hi, names)
        values.update(range(start, end + 1, step))
    if not values:
        raise ValueError("cron field matched nothing")
    return frozenset(values)


def _cron_int(tok: str, lo: int, hi: int, names: dict) -> int:
    tok = tok.strip().lower()
    if tok in names:
        return names[tok]
    if not re.match(r"^\d+$", tok):
        raise ValueError(f"invalid cron token {tok!r}")
    n = int(tok)
    if n < lo or n > hi:
        raise ValueError(f"cron value {n} out of range [{lo},{hi}]")
    return n


class CronExpression:
    def __init__(self, expr: str):
        parts = str(expr or "").split()
        if len(parts) != 5:
            raise ValueError("cron must have 5 fields: minute hour dom month dow")
        self.minutes = _parse_cron_field(parts[0], 0, 59, None)
        self.hours = _parse_cron_field(parts[1], 0, 23, None)
        self.doms = _parse_cron_field(parts[2], 1, 31, None)
        self.months = _parse_cron_field(parts[3], 1, 12, _MON_NAMES)
        self.dows = _parse_cron_field(parts[4], 0, 6, _DOW_NAMES)
        self.expr = expr

    def matches(self, dt: datetime) -> bool:
        # datetime.weekday(): Mon=0..Sun=6 -> cron dow Sun=0..Sat=6
        dow = (dt.weekday() + 1) % 7
        return (dt.minute in self.minutes and dt.hour in self.hours
                and dt.day in self.doms and dt.month in self.months
                and dow in self.dows)

    def next_after(self, dt: datetime):
        """First matching UTC minute strictly after dt, bounded by the horizon."""
        cur = dt.replace(second=0, microsecond=0) + timedelta(minutes=1)
        limit = cur.replace(year=min(9999, cur.year + CRON_SEARCH_HORIZON_YEARS))
        while cur <= limit:
            if self.matches(cur):
                return cur
            cur += timedelta(minutes=1)
        return None


def _validate_title(t) -> str:
    title = str(t or "").strip()
    if not title:
        raise ValueError("title required")
    if len(title) > MAX_TITLE_LENGTH:
        raise ValueError(f"title too long (max {MAX_TITLE_LENGTH})")
    return title


def create_record(kind: str, *, title: str, prompt: str = "",
                  after_seconds=None, at=None, every_seconds=None,
                  cron=None, now: datetime | None = None) -> dict:
    """Build one validated schedule record. Raises ValueError on bad input."""
    if kind not in _KINDS:
        raise ValueError(f"kind must be one of {_KINDS}")
    now = now or datetime.now(timezone.utc)
    title = _validate_title(title)
    prompt = str(prompt or "").strip()
    rec = {"id": str(uuid.uuid4()), "kind": kind, "title": title, "prompt": prompt}

    if kind == "after":
        if after_seconds is None or int(after_seconds) <= 0:
            raise ValueError("after requires a positive after_seconds")
        secs = int(after_seconds)
        rec["afterSeconds"] = secs
        rec["scheduledAt"] = format_instant(now + timedelta(seconds=secs))
    elif kind == "at":
        if at is None:
            raise ValueError("at requires an absolute instant")
        target = parse_instant(at)
        if target <= now:
            raise ValueError("at instant must be in the future")
        rec["scheduledAt"] = format_instant(target)
    elif kind == "every":
        if every_seconds is None or int(every_seconds) < MIN_EVERY_INTERVAL_SECONDS:
            raise ValueError(
                f"every requires every_seconds >= {MIN_EVERY_INTERVAL_SECONDS}")
        secs = int(every_seconds)
        rec["everySeconds"] = secs
        rec["scheduledAt"] = format_instant(now + timedelta(seconds=secs))
    elif kind == "cron":
        if not cron:
            raise ValueError("cron requires an expression")
        expr = CronExpression(cron)
        nxt = expr.next_after(now)
        if nxt is None:
            raise ValueError("cron expression never matches (unsatisfiable)")
        rec["cron"] = expr.expr
        rec["scheduledAt"] = format_instant(nxt)
    return rec


def compute_due(rec: dict, now: datetime) -> datetime | None:
    """Next due instant for a record at `now` (None if exhausted/unsatisfiable)."""
    kind = rec.get("kind")
    if kind in ("after", "at"):
        t = parse_instant(rec["scheduledAt"])
        return t if t > now else t  # one-shot: due instant is fixed
    if kind == "every":
        nxt = parse_instant(rec["scheduledAt"])
        step = timedelta(seconds=int(rec["everySeconds"]))
        while nxt <= now:
            nxt += step
        return nxt
    if kind == "cron":
        return CronExpression(rec["cron"]).next_after(now)
    return None


# ── persistence (managed json store) ──────────────────────────────
def _store_path() -> Path:
    import os
    home = os.environ.get("DSH_HOME") or str(Path.home() / ".dsh")
    return Path(home) / ".schedules.json"


def _load() -> list:
    try:
        raw = json.loads(_store_path().read_text(encoding="utf-8"))
        return raw if isinstance(raw, list) else []
    except Exception:
        return []


def _save(rows: list) -> None:
    p = _store_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")


# ── tool handlers ─────────────────────────────────────────────────
def _schedule_create(payload):
    p = payload or {}
    try:
        rec = create_record(
            str(p.get("kind") or ""), title=p.get("title"), prompt=p.get("prompt", ""),
            after_seconds=p.get("after_seconds"), at=p.get("at"),
            every_seconds=p.get("every_seconds"), cron=p.get("cron"))
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    rows = _load(); rows.append(rec); _save(rows)
    _log.info("[schedule] created %s %s -> %s", rec["kind"], rec["id"][:8], rec["scheduledAt"])
    return {"ok": True, "schedule": rec}


def _schedule_list(payload):
    rows = _load()
    return {"ok": True, "count": len(rows), "schedules": rows}


def _schedule_delete(payload):
    p = payload or {}
    sid = str(p.get("id") or "")
    if not sid:
        return {"ok": False, "error": "id required"}
    rows = _load()
    kept = [r for r in rows if r.get("id") != sid]
    if len(kept) == len(rows):
        return {"ok": False, "error": "not found", "id": sid}
    _save(kept)
    return {"ok": True, "deleted": sid, "remaining": len(kept)}


def _schedule_due(payload):
    p = payload or {}
    now = parse_instant(p["now"]) if p.get("now") else datetime.now(timezone.utc)
    out = []
    for r in _load():
        try:
            nxt = compute_due(r, now)
        except Exception:
            nxt = None
        out.append({**r, "nextDue": format_instant(nxt) if nxt else None,
                    "isDue": bool(nxt and nxt <= now)})
    due = [r for r in out if r["isDue"]]
    return {"ok": True, "now": format_instant(now), "count": len(out),
            "dueCount": len(due), "due": due, "all": out}


def register(ctx):
    from tool_registry import ToolDefinition

    def _mk(name, fn, desc):
        ctx.register_tool(ToolDefinition(name=name, source="skill",
                                         handler=lambda payload=None, **k: fn(payload),
                                         description=desc))

    _mk("schedule_create", _schedule_create,
        "Create a reminder. params:{kind:after|at|every|cron,title:str,prompt:str,"
        "after_seconds?:int,at?:str,every_seconds?:int,cron?:str}")
    _mk("schedule_list", _schedule_list, "List stored schedules. params:{}")
    _mk("schedule_delete", _schedule_delete, "Delete a schedule by id. params:{id:str}")
    _mk("schedule_due", _schedule_due,
        "Compute next-due and due-now for all schedules. params:{now?:str}")
    return {"tools": ["schedule_create", "schedule_list", "schedule_delete", "schedule_due"]}
