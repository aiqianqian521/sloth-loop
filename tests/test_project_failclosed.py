"""P0 regression: unresolvable --project / --task inputs must fail closed.

Guards the stress-test finding invalid_project_rejected=false: a missing or
invalid --project (or --task) used to silently fall back to root/config
defaults and keep running, producing a report that looked like a PASS.
"""
from __future__ import annotations

import sys
from pathlib import Path

ENGINE = Path(__file__).resolve().parents[1] / "sloth_engine"
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

from project_loader import ProjectLoader  # noqa: E402

MISSING = "definitely-not-a-real-project-xyz"


class _Stub(ProjectLoader):
    def __init__(self, allow=False, cfg=None, allow_task=False):
        self.cfg = cfg or {}
        self._project_path = ""
        self.allow_missing_project = allow
        self.allow_missing_task = allow_task
        self._project_error = None
        self._task_error = None
        self._sec_log = None


# ---- --project ----

def test_unknown_project_fails_closed():
    s = _Stub()
    assert s._load_project(MISSING) is False
    assert s._project_error["error_code"] == "project_not_loadable"


def test_allow_missing_project_escape_hatch():
    s = _Stub(allow=True)
    assert s._load_project(MISSING) is True
    assert s._project_error is None


def test_config_allow_missing_flag():
    s = _Stub(cfg={"project": {"allow_missing": True}})
    assert s._load_project(MISSING) is True


def test_traversal_project_fails_closed():
    s = _Stub()
    assert s._load_project("../etc") is False
    assert s._project_error["error_code"] == "project_not_loadable"


# ---- --task ----

def test_missing_task_file_fails_closed():
    s = _Stub()
    assert s._load_task_file("no-such-task-file-xyz.yaml") is False
    assert s._task_error["error_code"] == "task_not_loadable"


def test_allow_missing_task_escape_hatch():
    s = _Stub(allow_task=True)
    assert s._load_task_file("no-such-task-file-xyz.yaml") is True
    assert s._task_error is None


def test_task_config_allow_missing_flag():
    s = _Stub(cfg={"task_file": {"allow_missing": True}})
    assert s._load_task_file("no-such-task-file-xyz.yaml") is True
