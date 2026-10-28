"""cycle-37 A: the fail-closed *server-side* push gate (ROADMAP P0).

``scripts/run_gate.py`` is a pre-commit hook, and a pre-commit hook is bypassable
from the client: ``--no-verify``, ``core.hooksPath``, or a fresh clone with no
hook installed.  The ROADMAP item "P0 fail-closed CI" asks for the other half --
enforcement the pusher cannot switch off -- and names ``pre-receive`` as an
accepted mechanism.  That is what these tests pin:

  1. the scanner's rule set: real secret shapes are caught;
  2. its false-positive rate over the *shipped* corpus, **measured** rather than
     eyeballed (cycle-32/33 method: a detector that only looks reasonable is not
     evidence);
  3. end to end, through a real ``git push`` into a repository carrying the
     installed hook: a clean push is accepted, a secret or a red tests-half is
     rejected, and a push that tries to neutralise the gate code is *still*
     rejected -- the pinned bundle is never taken from the pushed tree.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import content_scan        # noqa: E402
import install_push_gate   # noqa: E402
import push_gate           # noqa: E402

def _s(*parts):
    """Assemble a fixture at run time.

    The scanner is pointed at *this* repository by the corpus test and by the
    push gate, so a literal secret in this file would be a true positive
    against our own tree.  Building the shapes from parts keeps the fixtures
    and the corpus clean at the same time -- the same reason the hash guards
    write _ghost() instead of a bare token.
    """
    return "".join(parts)


BS = chr(92)
AWS_KEY = _s("AKIA", "IOSFODNN7EXAMPLE")
PRIV_HEADER = _s("-----BEGIN RSA ", "PRIVATE KEY-----")
HEX_KEY = _s("8f3a9b1c2d4e5f60", "718293a4b5c6d7e8")
CLIENT_SECRET = _s("Zq7!vR2#pL9$", "wK4&tB1@nD8%q")
HOME_WIN = _s("home: C:", BS, "Users", BS, "someone", BS, "secret", BS, "x")
HOME_POSIX = _s("P = '/home/", "ci/worker/out'")
HOME_DOC = _s("run from C:", BS, "Users", BS, "someone", BS, "proj (documented)")

FAKE_GATE_SRC = (
    "import sys\n"
    "from pathlib import Path\n"
    "tree = Path(sys.argv[-1])\n"
    "sys.exit(1 if (tree / 'MAKE_IT_RED').exists() else 0)\n"
)

POSITIVES = [
    ("cfg/.env", "A=1"),
    ("certs/server.pem", "x"),
    ("a/credentials", "u:p"),
    ("keys/id_rsa", "x"),
    ("m.py", PRIV_HEADER),
    ("m.py", "k = '" + AWS_KEY + "'"),
    ("m.py", 'api_key = "' + HEX_KEY + '"'),
    ("m.py", 'client_secret = "' + CLIENT_SECRET + '"'),
    ("m.yaml", HOME_WIN),
    ("m.py", HOME_POSIX),
]

NEGATIVES = [
    ("m.py", 'api_key = "changeme"'),
    ("m.py", 'token = "your_token_here"'),
    ("m.py", 'secret = "${MY_SECRET}"'),
    ("m.py", "password = os.environ['PW']"),
    ("m.py", 'token = "abc"'),
    ("m.py", 'note = "a short label"'),
    ("docs/a.md", HOME_DOC),
]

CORPUS_MIN = 200


def _run(cmd, cwd):
    return subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def _commit(work: Path, msg: str) -> None:
    _run(["git", "add", "-A"], work)
    r = _run(["git", "-c", "user.email=t@example.invalid",
              "-c", "user.name=t", "-c", "commit.gpgsign=false",
              "commit", "-m", msg], work)
    assert r.returncode == 0, r.stderr


def _push(work: Path):
    return _run(["git", "push", "origin", "main"], work)


# --- 1. rule set -----------------------------------------------------------

@pytest.mark.parametrize("rel,text", POSITIVES)
def test_scanner_flags_each_real_secret_shape(rel, text):
    assert content_scan.scan_text(rel, text), (rel, text)


@pytest.mark.parametrize("rel,text", NEGATIVES)
def test_scanner_ignores_placeholders_env_lookups_and_prose(rel, text):
    assert content_scan.scan_text(rel, text) == [], (rel, text)


# --- 2. measured false-positive rate over the shipped corpus ---------------

def test_scanner_has_no_false_positives_over_the_shipped_corpus():
    listed = _run(["git", "ls-files", "--cached", "--others",
                   "--exclude-standard"], ROOT).stdout.split()
    assert len(listed) > CORPUS_MIN, "the measured corpus collapsed to %d files" % len(listed)
    findings = []
    for rel in listed:
        p = ROOT / rel
        try:
            if p.stat().st_size > push_gate.MAX_SCAN_BYTES:
                continue
            blob = p.read_bytes()
        except OSError:
            continue
        if b"\x00" in blob[:4096]:
            continue
        findings.extend(content_scan.scan_text(rel, blob.decode("utf-8", "replace")))
    assert findings == [], findings


# --- 3. the gate halves ----------------------------------------------------

def test_gate_tree_rejects_a_secret_even_when_the_tests_half_is_skipped(tmp_path, monkeypatch):
    tree = tmp_path / "tree"
    tree.mkdir()
    (tree / "app.py").write_text("k = '" + AWS_KEY + "'\n", encoding="utf-8")
    monkeypatch.setenv("LOOP_PUSH_GATE_SKIP_TESTS", "1")
    problems = push_gate.gate_tree(str(tree))
    assert any("AWS access key id" in p for p in problems), problems


def test_gate_tree_rejects_a_red_runner_and_accepts_a_green_one(tmp_path, monkeypatch):
    fake = tmp_path / "fake_gate.py"
    fake.write_text(FAKE_GATE_SRC, encoding="utf-8")
    monkeypatch.delenv("LOOP_PUSH_GATE_SKIP_TESTS", raising=False)
    monkeypatch.setenv("LOOP_PUSH_GATE_CMD", json.dumps([sys.executable, str(fake)]))
    tree = tmp_path / "tree"
    tree.mkdir()
    assert push_gate.gate_tree(str(tree)) == []
    (tree / "MAKE_IT_RED").write_text("x", encoding="utf-8")
    problems = push_gate.gate_tree(str(tree))
    assert any("exited 1" in p for p in problems), problems


def test_gate_tree_fails_closed_when_the_runner_cannot_start(tmp_path, monkeypatch):
    monkeypatch.delenv("LOOP_PUSH_GATE_SKIP_TESTS", raising=False)
    monkeypatch.setenv("LOOP_PUSH_GATE_CMD",
                       json.dumps([str(tmp_path / "nope-missing-binary")]))
    tree = tmp_path / "tree"
    tree.mkdir()
    problems = push_gate.gate_tree(str(tree))
    assert any("could not run" in p for p in problems), problems


def test_gate_cmd_config_must_be_a_json_argv_array(tmp_path, monkeypatch):
    monkeypatch.delenv("LOOP_PUSH_GATE_SKIP_TESTS", raising=False)
    monkeypatch.setenv("LOOP_PUSH_GATE_CMD", "python -c \"print(1)\"")
    tree = tmp_path / "tree"
    tree.mkdir()
    with pytest.raises(push_gate.GateError):
        push_gate.gate_tree(str(tree))


# --- 4. end to end: a real push through the installed hook -----------------

@pytest.fixture()
def repo_with_hook(tmp_path):
    origin = tmp_path / "origin.git"
    work = tmp_path / "work"
    assert _run(["git", "init", "--bare", "-b", "main", str(origin)], tmp_path).returncode == 0
    assert _run(["git", "clone", str(origin), str(work)], tmp_path).returncode == 0
    # Point the *client* at an empty hooks dir: this is exactly the bypass the
    # ROADMAP item asks us to survive (--no-verify / core.hooksPath / fresh
    # clone all leave the pre-commit gate unrun).  Every push below is therefore
    # gated only by the receiving side.
    nohooks = tmp_path / "nohooks"
    nohooks.mkdir()
    assert _run(["git", "config", "core.hooksPath", str(nohooks)], work).returncode == 0
    fake = tmp_path / "fake_gate.py"
    fake.write_text(FAKE_GATE_SRC, encoding="utf-8")
    assert install_push_gate.install(origin, python=sys.executable,
                                     cmd=[sys.executable, str(fake)]) == 0
    assert install_push_gate.is_installed(origin)
    return work, origin


def test_a_clean_push_is_accepted(repo_with_hook):
    work, _origin = repo_with_hook
    (work / "README.md").write_text("hello\n", encoding="utf-8")
    _commit(work, "init")
    r = _push(work)
    assert r.returncode == 0, (r.stdout, r.stderr)


def test_a_push_with_a_secret_is_rejected(repo_with_hook):
    work, _origin = repo_with_hook
    (work / "README.md").write_text("hello\n", encoding="utf-8")
    _commit(work, "init")
    assert _push(work).returncode == 0
    (work / "app.py").write_text("k = '" + AWS_KEY + "'\n", encoding="utf-8")
    _commit(work, "add a secret")
    r = _push(work)
    assert r.returncode != 0, (r.stdout, r.stderr)
    assert "REJECTED" in (r.stdout + r.stderr)
    assert "AWS access key id" in (r.stdout + r.stderr)


def test_a_push_with_a_red_tests_half_is_rejected(repo_with_hook):
    work, _origin = repo_with_hook
    (work / "README.md").write_text("hello\n", encoding="utf-8")
    _commit(work, "init")
    assert _push(work).returncode == 0
    (work / "MAKE_IT_RED").write_text("x", encoding="utf-8")
    _commit(work, "make the gate red")
    r = _push(work)
    assert r.returncode != 0, (r.stdout, r.stderr)
    assert "REJECTED" in (r.stdout + r.stderr)


def test_a_push_cannot_neutralise_the_gate_it_is_judged_by(repo_with_hook):
    """The bundle is pinned on the host; rewriting it inside the push does nothing."""
    work, _origin = repo_with_hook
    (work / "README.md").write_text("hello\n", encoding="utf-8")
    _commit(work, "init")
    assert _push(work).returncode == 0
    (work / "scripts").mkdir(exist_ok=True)
    (work / "scripts" / "push_gate.py").write_text("import sys\nsys.exit(0)\n",
                                                   encoding="utf-8")
    (work / "loot.py").write_text("k = '" + AWS_KEY + "'\n", encoding="utf-8")
    _commit(work, "neuter the gate, then add a secret")
    r = _push(work)
    assert r.returncode != 0, (r.stdout, r.stderr)
    assert "AWS access key id" in (r.stdout + r.stderr)


def test_without_the_gate_bundle_the_hook_fails_closed(repo_with_hook):
    work, origin = repo_with_hook
    bundle = origin / "hooks" / install_push_gate.BUNDLE_DIRNAME
    assert bundle.is_dir()
    for p in sorted(bundle.rglob("*"), reverse=True):
        p.unlink() if p.is_file() else p.rmdir()
    bundle.rmdir()
    (work / "README.md").write_text("hello\n", encoding="utf-8")
    _commit(work, "init")
    r = _push(work)
    assert r.returncode != 0, (r.stdout, r.stderr)
    assert "bundle missing" in (r.stdout + r.stderr)


# --- 5. installer hygiene --------------------------------------------------

def test_install_backs_up_an_existing_hook_and_uninstall_restores_it(tmp_path):
    repo = tmp_path / "r"
    hooks = repo / ".git" / "hooks"
    hooks.mkdir(parents=True)
    original = "#!/bin/sh\nexit 0\n"
    (hooks / "pre-receive").write_text(original, encoding="utf-8")
    assert install_push_gate.install(repo, python=sys.executable) == 0
    assert list(hooks.glob("pre-receive.bak-*")), "the old hook must be backed up"
    assert (hooks / "pre-receive").read_text(encoding="utf-8") != original
    assert install_push_gate.uninstall(repo) == 0
    assert (hooks / "pre-receive").read_text(encoding="utf-8") == original
    assert not install_push_gate.is_installed(repo)
