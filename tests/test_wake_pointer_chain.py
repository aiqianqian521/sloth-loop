"""cycle-18 A: behavioural guard for the GRAND-LOOP wake-pointer commit chain.

``docs/flow/GRAND-LOOP.md`` is the first file a fresh agent reads: it carries a
"commit chain" paragraph that lists, cycle by cycle, the commit hash that
shipped each increment, e.g.

    ... `a09421a`(cycle-16 A: ...) -> `006eea4`(architect-skills cycle-16 B: ...)

Nothing verified that this ledger matched git reality.  cycle-16's A commit was
recorded as ``710a3af`` -- which is actually cycle-17's A commit -- so every
reader that trusted the ledger was handed the wrong hash, and the duplicate
``710a3af`` masked the omission of the real one.  Same family as cycle-17
(recorded vs measured); this time the drifting record is the history chain.

These tests parse the live document (never a stub fixture) and fail closed:

  1. the chain paragraph (title ``**cycle-A -> cycle-B ...**``) and the
     ``head`` pointer must be locatable;
  2. an entry naming a cycle (``cycle-N``) must resolve in git, and its commit
     subject must not name a *different* cycle;
  3. one hash must not be annotated with two different cycle numbers;
  4. the chain title span must match the newest entry;
  5. the pointer ``head`` hash must name the same commit as
     ``docs/baseline.json["head"]`` (either length of that commit is accepted).

Every hash alphabet in this file is ``[0-9a-f]{7,40}`` and a claim resolves in
*any* known repo (cycle-27 A); a narrower recogniser used to drop a real record
silently instead of failing loudly.

Architect-skills B commits live in a sibling repo: they are verified whenever
that checkout is present on this machine, and never silently downgraded.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
GRAND_LOOP = REPO / "docs" / "flow" / "GRAND-LOOP.md"

# Sibling repo holding the architect-skills *B* commits (may be absent).
# The default is DERIVED from this checkout's own location (a sibling layout:
# <workspace>/skill/wend/...), so no source machine's absolute path is baked
# into the repo; set SLOTH_ARCH_REPO to point at it from anywhere else.
ARCH_REPO = Path(os.environ.get("SLOTH_ARCH_REPO")
                 or REPO.parent.parent / "skill" / "wend"
                 / "architect-skills-offline-bundle" / "architect-skills")

BT = "`"
# cycle-27 A: one hash alphabet for every ledger recogniser.  The chain, pointer
# and claim parsers each hard-coded a 7-char hash while the phantom-hash rule
# already accepted 7..40; a document that wrote a longer (still resolvable) hash
# was dropped by the ledger parser with no failure at all -- the recogniser was
# narrower than the reality it audits, so the record went invisible, not red.
HASH_SRC = r"[0-9a-f]{7,40}"
# cycle-31 A: every syntactic slot of a ledger record is ONE constant.  The
# brackets were the last slot still written inline and ASCII-only: ENTRY_RE --
# the chain-record parser -- dropped a record written with full-width brackets
# with no failure at all, so a chain entry whose cycle annotation was WRONG was
# invisible (cycle-27 fixed the hash alphabet and the *claim* brackets but left
# the *entry* brackets).  Family: a recogniser must not be narrower than the
# reality it audits.
BOPEN = "[" + "\uff08" + "(]"          # ASCII "(" or its full-width twin
BCLOSE = "[^)" + "\uff09" + "]*"       # up to ")" or its full-width twin
# The chain paragraph starts on its title line and stops at the next blank line
# or the next "**" heading -- both are language-independent anchors.
CHAIN_START_RE = re.compile(r"^\*\*cycle-(\d+)\s*(?:\u2192|->)\s*cycle-(\d+)")
# The prefix and the recogniser are one constant (D-S1 family): the literal
# cannot drift from the pattern it is quoted in.
HEAD_PREFIX = "\u4ee3\u7801 head "
HEAD_RE = re.compile(re.escape(HEAD_PREFIX) + BT + "(" + HASH_SRC + ")" + BT)
ENTRY_RE = re.compile(BT + "(" + HASH_SRC + ")" + BT + BOPEN + "(" + BCLOSE + ")")
CYCLE_RE = re.compile(r"cycle-(\d+)")
ARCH_TAG = "architect-skills"
MIN_ENTRIES = 20
MIN_CLAIMED = 10
MIN_LOCAL = 8


def _git(repo: Path, *args: str):
    return subprocess.run(
        ["git", "-C", str(repo)] + list(args),
        capture_output=True, text=True, encoding="utf-8", errors="replace")


_SUBJECT_CACHE: dict = {}


def _subject_map(repo: Path) -> dict:
    """{abbrev-hash: subject} for every commit reachable from any ref.

    One spawn per repo: spawning git once per entry made this file the slowest
    in the suite (~45s), which is itself a guard-quality problem.
    """
    key = str(repo)
    if key not in _SUBJECT_CACHE:
        out = _git(repo, "log", "--all", "--format=%h%x09%s").stdout
        table = {}
        for line in out.splitlines():
            if "\t" in line:
                ab, subj = line.split("\t", 1)
                table[ab] = subj
        _SUBJECT_CACHE[key] = table
    return _SUBJECT_CACHE[key]


_SUBJECT_FULL_CACHE: dict = {}


def _subject_direct(repo: Path, h: str):
    """Subject via a direct revision lookup (hashes longer than the abbrev).

    The abbrev table only holds ``%h`` (7 chars here), so before cycle-22 a doc
    that wrote an 8..40-char commit hash -- or a full 40-char SHA -- resolved in
    NO repo and was reported as a phantom.  Latent until now only because no
    shipped sloth-loop doc happened to write one; the sibling-repo sweep in
    cycle-22 is what surfaced it.
    """
    key = (str(repo), h)
    if key not in _SUBJECT_FULL_CACHE:
        out = _git(repo, "log", "-1", "--format=%s", h + "^{commit}", "--")
        lines = out.stdout.strip().splitlines()
        _SUBJECT_FULL_CACHE[key] = lines[0] if (out.returncode == 0 and lines) else None
    return _SUBJECT_FULL_CACHE[key]


def _subject_of(repo: Path, h: str):
    """Subject of commit *h* in *repo*, or None when the hash is unknown."""
    table = _subject_map(repo)
    if h in table:
        return table[h]
    for ab, subj in table.items():
        if ab.startswith(h):
            return subj
    if len(h) > 7:          # longer than any abbrev here: needs a direct lookup
        return _subject_direct(repo, h)
    return None


def chain_block(text: str):
    """Return (block, span_lo, span_hi); raise if the anchors are gone."""
    lines = text.splitlines()
    start = next((i for i, l in enumerate(lines) if CHAIN_START_RE.match(l)), None)
    if start is None:
        raise AssertionError("commit-chain title missing (fail-closed)")
    end = next((i for i in range(start + 1, len(lines))
                if lines[i].strip() == "" or lines[i].startswith("**")), None)
    if end is None:
        raise AssertionError("commit-chain terminator missing (fail-closed)")
    m = CHAIN_START_RE.match(lines[start])
    return "\n".join(lines[start:end]), int(m.group(1)), int(m.group(2))


def chain_entries(block: str):
    out = []
    for h, ann in ENTRY_RE.findall(block):
        m = CYCLE_RE.search(ann)
        out.append((h, ann, int(m.group(1)) if m else None))
    return out


def chain_violations(text: str, repo: Path = REPO,
                     arch_repo: Path | None = None) -> list:
    """Human-readable violations of the recorded chain (empty == it is true)."""
    problems = []
    try:
        block, span_lo, span_hi = chain_block(text)
    except AssertionError as exc:
        return ["GRAND-LOOP.md: " + str(exc)]

    entries = chain_entries(block)
    claimed = [e for e in entries if e[2] is not None]
    if len(entries) < MIN_ENTRIES:
        problems.append("chain has %d entries, expected >= %d"
                        % (len(entries), MIN_ENTRIES))
    if len(claimed) < MIN_CLAIMED:
        problems.append("only %d entries name a cycle, expected >= %d"
                        % (len(claimed), MIN_CLAIMED))

    seen: dict = {}
    for h, _ann, n in claimed:
        seen.setdefault(h, set()).add(n)
    for h in sorted(seen):
        if len(seen[h]) > 1:
            problems.append("hash %s is annotated with conflicting cycles %s"
                            % (h, sorted(seen[h])))

    for h, ann, n in claimed:
        target = arch_repo if ARCH_TAG in ann else repo
        if target is None:
            continue
        subj = _subject_of(target, h)
        if subj is None:
            problems.append("hash %s does not exist in %s" % (h, target))
            continue
        m = CYCLE_RE.search(subj)
        if m and int(m.group(1)) != n:
            problems.append(
                "hash %s annotated cycle-%d but its commit says cycle-%s (%s)"
                % (h, n, m.group(1), subj[:70]))

    if claimed and max(e[2] for e in claimed) != span_hi:
        problems.append("chain title says up to cycle-%d but the newest entry is cycle-%d"
                        % (span_hi, max(e[2] for e in claimed)))
    if claimed and min(e[2] for e in claimed) < span_lo:
        problems.append("chain title starts at cycle-%d but an entry claims cycle-%d"
                        % (span_lo, min(e[2] for e in claimed)))

    heads = HEAD_RE.findall(text)
    if not heads:
        problems.append("cannot locate the 'head <hash>' wake pointer")
    elif len(heads) > 1:
        # cycle-31 A: only the first pointer was ever compared; a second one
        # (the ledger shape, duplicated) used to be invisible.
        problems.append("found %d 'head <hash>' wake pointers; exactly one is expected"
                        % len(heads))
    else:
        recorded = json.loads(
            (repo / "docs" / "baseline.json").read_text(encoding="utf-8"))
        doc_head, base_head = heads[0], recorded.get("head")
        # cycle-27: once a longer hash is recognised, the two sides may write
        # different lengths of the *same* commit; git abbreviations are unique
        # prefixes, so a shared prefix means one commit and a non-prefix is a
        # genuine drift.
        if not (isinstance(base_head, str)
                and (doc_head.startswith(base_head)
                     or base_head.startswith(doc_head))):
            problems.append("wake pointer head %s != docs/baseline.json head %s"
                            % (doc_head, base_head))
    return problems


def _arch_repo():
    return ARCH_REPO if (ARCH_REPO / ".git").exists() else None


def _live_text() -> str:
    return GRAND_LOOP.read_text(encoding="utf-8")


def _doctor(old: str, new: str) -> str:
    text = _live_text()
    assert old in text, "fixture anchor missing: " + old
    return text.replace(old, new, 1)


def _first_local_entry():
    """A sloth-loop entry whose commit subject itself names its cycle."""
    for h, ann, n in chain_entries(chain_block(_live_text())[0]):
        if n is None or ARCH_TAG in ann:
            continue
        subj = _subject_of(REPO, h) or ""
        if ("cycle-%d" % n) in subj.lower():
            return h, ann, n
    raise AssertionError("no verifiable local entry in the chain")


def test_wake_pointer_chain_matches_git_reality() -> None:
    problems = chain_violations(_live_text(), arch_repo=_arch_repo())
    assert problems == [], "\n".join(problems)


def test_the_guard_covers_the_expected_number_of_entries() -> None:
    block, _lo, _hi = chain_block(_live_text())
    entries = chain_entries(block)
    claimed = [e for e in entries if e[2] is not None]
    local = [e for e in claimed if ARCH_TAG not in e[1]]
    assert len(entries) >= MIN_ENTRIES
    assert len(claimed) >= MIN_CLAIMED
    assert len(local) >= MIN_LOCAL


def test_the_architect_skills_commits_are_checked_when_present() -> None:
    arch = _arch_repo()
    if arch is None:
        return  # documented, machine-local gap: sibling checkout not present
    block, _lo, _hi = chain_block(_live_text())
    foreign = [e for e in chain_entries(block) if ARCH_TAG in e[1] and e[2] is not None]
    assert foreign, "the chain should reference architect-skills B commits"
    for h, _ann, n in foreign:
        subj = _subject_of(arch, h) or ""
        assert ("cycle-%d" % n) in subj.lower(), (h, subj)


def test_guard_catches_a_wrong_cycle_annotation() -> None:
    h, ann, n = _first_local_entry()
    bad_ann = CYCLE_RE.sub("cycle-%d" % (n + 1), ann, count=1)
    problems = chain_violations(_doctor("(" + ann + ")", "(" + bad_ann + ")"),
                                arch_repo=_arch_repo())
    assert any("annotated cycle-" in p for p in problems), problems


def test_guard_catches_a_hash_claimed_by_two_cycles() -> None:
    h, _ann, n = _first_local_entry()
    block, _lo, _hi = chain_block(_live_text())
    other = next(e for e in chain_entries(block)
                 if e[2] is not None and e[2] != n and e[0] != h and ARCH_TAG not in e[1])
    doctored_block = block.replace("`" + other[0] + "`(", "`" + h + "`(", 1)
    problems = chain_violations(_live_text().replace(block, doctored_block),
                                arch_repo=_arch_repo())
    assert any("conflicting cycles" in p for p in problems), problems


def test_guard_catches_a_title_span_mismatch() -> None:
    problems = chain_violations(_doctor("\u2192 cycle-", "\u2192 cycle-99"),
                                arch_repo=_arch_repo())
    assert any("title says up to" in p for p in problems), problems


def test_guard_fails_closed_when_the_anchor_is_gone() -> None:
    problems = chain_violations(_doctor("**cycle-5 ", "**cycleX-5 "))
    assert problems and "title missing" in problems[0], problems


def test_guard_fails_closed_when_the_head_pointer_drifts() -> None:
    text = _live_text()
    hm = HEAD_RE.search(text)
    assert hm is not None
    doctored = text[:hm.start(1)] + "0000abc" + text[hm.end(1):]
    problems = chain_violations(doctored, arch_repo=_arch_repo())
    assert any("wake pointer head" in p for p in problems), problems


# ---------------------------------------------------------------------------
# cycle-19 A: the same contradiction can also be *copied* elsewhere.  A
# repo-wide audit found 3 places where a defect write-up re-created the exact
# claim shape (`<hash>`(cycle-N ...)) around a hash whose commit says a
# different cycle -- the description of the bug re-created the bug.  Rule:
# a machine-claimed record uses the backticked claim form; prose that merely
# *mentions* a wrong hash must not be shaped like a claim (cycle-19 design note).
# ---------------------------------------------------------------------------

CLAIM_RE = re.compile(BT + "(" + HASH_SRC + ")" + BT + "[ \t]*" + BOPEN
                      + r"[ \t]*(architect-skills )?cycle-(\d+)")
# The pre-cycle-27 alphabets, kept only as the bug witness: the tests below
# assert the live recognisers see strictly more than these do.
NARROW_CLAIM_RE = re.compile(BT + "([0-9a-f]{7})" + BT + r"\((architect-skills )?cycle-(\d+)")
NARROW_ENTRY_RE = re.compile(BT + "([0-9a-f]{7})" + BT + r"\(([^)]*)\)")
# cycle-31 A: the bracket-blind witness -- identical to ENTRY_RE except for the
# ASCII-only bracket, so a full-width entry it loses is the red evidence.
ASCII_ENTRY_RE = re.compile(BT + "(" + HASH_SRC + ")" + BT + r"\(([^)]*)\)")
NARROW_HEAD_RE = re.compile("\u4ee3\u7801 head " + BT + "([0-9a-f]{7})" + BT)
MIN_REPO_CLAIMS = 15
SCAN_EXT = (".md", ".json", ".py")


def scan_targets():
    """Tracked + pending docs, plus the local (gitignored) work records.

    `--others --exclude-standard` is load-bearing: the first version listed only
    tracked files, so a brand-new doc escaped the scan exactly while it was being
    written -- and tripped the guard the moment it was committed (cycle-19 A2).
    Records that are never shipped still feed an agent's evidence chain, so local
    work records are scanned too (best-effort: a fresh clone simply has none).
    """
    out = [f for f in _git(REPO, "ls-files", "--cached", "--others",
                           "--exclude-standard").stdout.splitlines()
           if f.endswith(SCAN_EXT)]
    local = REPO / "work_ooda"
    if local.is_dir():
        out += [str(p.relative_to(REPO)).replace(os.sep, "/")
                for p in sorted(local.rglob("*.md"))]
    return out


def claim_problems(rel: str, text: str, arch_repo=None) -> list:
    """`<hash>`(cycle-N ...) claims in *text* that contradict the real commit.

    cycle-27: a claim may cite a commit of *any* known repo (the shipped docs
    record the legacy sloth-loop baseline too), so a claim that only resolves
    elsewhere is no phantom -- resolution falls back to the repo sweep.
    """
    problems = []
    repos = None
    for m in CLAIM_RE.finditer(text):
        h, arch, n = m.group(1), bool(m.group(2)), int(m.group(3))
        if arch:
            target = arch_repo
            if target is None:
                continue
        else:
            target = REPO
        subj = _subject_of(target, h)
        if subj is None and not arch:
            if repos is None:
                repos = _known_repos()
            _where, resolved = _resolve_any(h, repos)
            if resolved is not None:
                target, subj = resolved, _subject_of(resolved, h)
        if subj is None:
            where = str(target) if target is not None else "any known repo"
            problems.append("%s: `%s` does not exist in %s" % (rel, h, where))
            continue
        sm = CYCLE_RE.search(subj)
        if sm and int(sm.group(1)) != n:
            problems.append("%s: `%s`(cycle-%d ...) but its commit says cycle-%s"
                            % (rel, h, n, sm.group(1)))
    return problems


def test_no_document_claims_a_hash_for_the_wrong_cycle() -> None:
    arch = _arch_repo()
    hits = 0
    problems = []
    for rel in scan_targets():
        try:
            text = (REPO / rel).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        hits += len(CLAIM_RE.findall(text))
        problems.extend(claim_problems(rel, text, arch))
    assert hits >= MIN_REPO_CLAIMS, "scan found only %d hash claims" % hits
    assert problems == [], "\n".join(problems)


def test_the_repo_scan_catches_a_doctored_claim() -> None:
    text = _live_text()
    h, ann, n = _first_local_entry()
    bad_ann = CYCLE_RE.sub("cycle-%d" % (n + 1), ann, count=1)
    doctored = text.replace("(" + ann + ")", "(" + bad_ann + ")", 1)
    problems = claim_problems("test-fixture", doctored, _arch_repo())
    assert any("but its commit says" in p for p in problems), problems


# ---------------------------------------------------------------------------
# cycle-20 A: phantom hashes outside the claim shape.
#
# A repo-wide forensic sweep found three commit hashes recorded in prose that
# resolve in *no* repository at all:
#   * GRAND-LOOP.md legacy supplement chain "bb951ef -> 1fb4846 -> 11588a1 ->
#     edf2a55": 11588a1 is a transcription slip of the real 11542a1, which is
#     the actual parent of edf2a55;
#   * cycle-14 C design doc: a67594c, a slip of the real a67594e;
#   * status section 13.9: 8cf9d4c where the real backpressure commit is eb9f4b6.
# cycle-18/19 guarded only the backticked "hash(cycle-N)" claim form; a bare
# prose mention and the arrow-run form (A -> B -> C) were unguarded, which is
# exactly where the phantom hid.  An agent doing chain forensics on this ledger
# is handed a hash that exists nowhere and passes it on as fact.
#
# Rule: a shipped markdown document may name a commit hash only if it resolves
# in a known repo; naming a non-existent hash is allowed only when the same line
# marks it as a defect/phantom (the cycle-19 convention).  Arrow runs are also
# checked for topology: consecutive hashes in the same repo must be
# ancestor-related, so a wrong-but-existing hash cannot hide either.
#
# cycle-21 extended the existence rule (the wake-pointer path line and the
# registry commit columns were naming commits without backticks):
#   R1  a *bare* hash on a line that also carries a resolvable commit reference
#       is itself a commit reference and must resolve; the co-occurrence gate
#       keeps all-hex prose words out.
#   R2  external source-repo pins (SOURCE.md: "TencentDB-Agent-Memory@2ee2239")
#       resolve against the registered checkouts, so a true pin is never
#       mistaken for a phantom.
# ---------------------------------------------------------------------------

# Derived sibling (<workspace>/loop-dev); SLOTH_LEGACY_REPO overrides.
LEGACY_REPO = Path(os.environ.get("SLOTH_LEGACY_REPO")
                   or REPO.parent / "loop-dev")
LEDGER_EXT = ".md"
# cycle-32 A: the defect exemption must be no wider than the defect.  A
# marker used to mean "any of these words appears on the line", and it
# exempted *every* hash on that line; one of the "words" was the ordinary
# English "phantom", i.e. this module's own function name.  A comment that
# mentioned `phantom_hash_problems` therefore exempted the whole line, and
# 53 shipped lines were exempt only by that word (none hid a bad hash, so
# the hole was latent -- but a marker that is a code identifier has no
# signal).  The marker set is now the exhaustive writing convention only.
DEFECT_MARKERS = ("\u274c", "\u9519\u8bb0", "NOT-A-COMMIT")
# A marker labels the token that *follows* it, not the whole line: the
# nearest strong marker must sit before the token within this many chars.
# Ship evidence -- every genuinely labelled token sits 2..15 chars after
# its marker, while the widest prose / table-cell gap is 25..63 -- so 24
# separates a label from a mere co-occurrence with margin.
MARK_WINDOW = 24
# The one row-level form: the cycle-22 ledger table puts a single ❌ in
# a leading cell and the tokens in the next cell, 25..63 chars away.  A
# row-scoped exemption is a *claimed* exemption, so it is registered here
# (path, line stem, why) and a guard fails if an entry stops matching or
# stops being load-bearing -- it can never rot silently.
ROW_MARKED_RULES = (
    ("docs/design/2026-10-24-cycle22-A-cross-repo-ledger.md",
     "\u274c\u975e\u63d0\u4ea4\u58f0\u660e",
     "ledger table row: the marker is in a leading cell, the tokens in the"
     " next one"),
)
# cycle-22: a digest label may carry a separator (md5=..., matrix_md5=...,
# sha256:...).  The old form required the label at the *end* of the prefix, so
# "matrix_md5=<32hex>" was read as a commit claim and reported as a phantom.
# cycle-34 A: this anchored-at-the-end form is now the single per-token
# predicate (_digest_labelled) shared by the backtick and bare recognisers:
# the label exempts exactly the value it labels, no wider.
DIGEST_LABEL_RE = re.compile(
    r"(md5|sha1|sha256|sha512|checksum|digest)\s*[:=]?\s*$", re.I)
BACKTICK_HASH_RE = re.compile("`([0-9a-f]{7,40})`")
ARROW_RUN_RE = re.compile("[0-9a-f]{7,40}(?:\\s*\u2192\\s*[0-9a-f]{7,40})+")
BARE_HASH_RE = re.compile(r"[0-9a-f]{7,40}")
# cycle-32 A: a defect marker may label a *list* of hashes, not only the one
# that follows it -- "`a` / `b` / `c`" is one labelled enumeration, and every
# sibling must be exempt when the FIRST token is labelled.
ENUM_RUN_RE = re.compile("`" + HASH_SRC + "`(?:\\s*/\\s*`" + HASH_SRC + "`)+")
# A pure-digit token is almost always a date/version ("20261023"), not a
# commit prefix; keep it out of the existence rule (documented boundary).
DIGIT_ONLY_RE = re.compile(r"^[0-9]+$")
# cycle-21: bare (un-backticked) commit references.  The wake-pointer path line
# and the registry commit columns never used backticks, so the backtick-only
# rule never saw the 79 unique bare tokens shipped across the docs.
# A digest label (md5=..., sha256:...) marks a checksum, never a commit.
# cycle-34 A: the label's *scope* must not exceed the object it exempts.  The
# label used to switch the bare-hash scan off for the whole line, so a real
# commit claim sharing the line with "md5=<value>" was silenced.  The label
# now exempts only the token it labels (see _digest_labelled).
DIGEST_ANY_RE = re.compile(r"(md5|sha1|sha256|sha512|checksum|digest)\s*[:=]", re.I)
# A bare token must be whole: a 64-char hex digest must not be sliced into a
# 40-char pseudo-prefix by a greedy, unanchored match.
BARE_REF_RE = re.compile(r"(?<![0-9A-Za-z])[0-9a-f]{7,40}(?![0-9A-Za-z])")
# Backtick-delimited spans, dropped before the bare scan so a backticked hash is
# never reported a second time by the bare rule.
BACKTICK_SPAN_RE = re.compile(BT + "[^" + BT + "]*" + BT)
# cycle-33 A: the bare-hash gate's *trigger* was narrower than the
# declaration.  A bare token was policed only when the same line already
# carried a token that resolves ("co-occurrence"), so a lone
# "fixed in commit <bad>" -- no other ref on the line -- was silently
# skipped: the gate decides whether to look, and it looked away.
# A bare token that a git keyword *immediately* precedes is a declaration
# on its own.  The relaxation is defined by *adjacency* (local, measurable),
# never by *co-occurrence* (global, leaky): measured over the three corpora
# it adds 4 hits, every one a genuine commit ref, and 0 false positives
# (all-hex English words, dataset fingerprints and run ids never sit
# immediately after a keyword).
GIT_ADJACENT_RE = re.compile(
    r"(?i)(?:^|[\s(\uff08\[\u3010:\uff1a,\uff0c])"
    r"(commit|commits|head|baseline|tag|tagged|revision|rev|sha|merge)"
    r"[\s]*[:(\uff1a\uff08#]?[\s]*$")
# External source repos pinned by this project (docs/knowledge-distillation/
# SOURCE.md records "TencentDB-Agent-Memory@2ee2239").  Such a pin resolves in
# no sloth-loop repo, so the checkouts are registered as extra known repos --
# otherwise widening the scan would turn a true pin into a false alarm.
EXT_SOURCE_REPOS = (
    Path(os.environ.get("SLOTH_SOURCE_REPO_TENCENTDB")
         or REPO.parent / "other_project" / "TencentDB-Agent-Memory"),
)


def _known_repos():
    repos = [("sloth-loop", REPO)]
    if (LEGACY_REPO / ".git").exists():
        repos.append(("sloth-loop", LEGACY_REPO))
    arch = _arch_repo()
    if arch is not None:
        repos.append(("architect-skills", arch))
    for src_repo in EXT_SOURCE_REPOS:
        if (src_repo / ".git").exists():
            repos.append(("source:" + src_repo.name, src_repo))
    return repos


def _resolve_any(h, repos):
    for name, r in repos:
        if _subject_of(r, h) is not None:
            return name, r
    return None, None


_ANC_CACHE: dict = {}


def _ancestors(repo: Path):
    """(abbrev->full, {full_sha: set(full parent shas)}) from two rev-list walks.

    Keyed by full SHAs; abbrev lookups go through :func:`_to_full`.  Doing the
    per-pair ancestry by spawning ``git merge-base`` for every adjacent pair made
    the file slow and was the bug the first version shipped (a table keyed by
    full SHA queried with 7-char abbreviations -- every pair looked unrelated).
    """
    key = str(repo)
    if key not in _ANC_CACHE:
        amap: dict = {}
        for line in _git(repo, "log", "--all", "--format=%h%x09%H").stdout.splitlines():
            if "\t" in line:
                ab, full = line.split("\t", 1)
                amap[ab] = full
        order, parents = [], {}
        for line in _git(repo, "rev-list", "--all", "--topo-order",
                         "--parents").stdout.splitlines():
            parts = line.split()
            if parts:
                order.append(parts[0])
                parents[parts[0]] = parts[1:]
        table: dict = {}
        for h in reversed(order):  # parents appear before children here
            acc: set = set()
            for p in parents[h]:
                acc.add(p)
                acc |= table.get(p, set())
            table[h] = acc
        _ANC_CACHE[key] = (amap, table)
    return _ANC_CACHE[key]


_TO_FULL_CACHE: dict = {}


def _to_full(repo: Path, h: str):
    amap, _ = _ancestors(repo)
    if h in amap:
        return amap[h]
    for ab, full in amap.items():
        if ab.startswith(h):
            return full
    if len(h) > 7:          # cycle-22: a full/medium SHA is not in the abbrev map
        key = (str(repo), h)
        if key not in _TO_FULL_CACHE:
            out = _git(repo, "rev-parse", "--verify", h + "^{commit}")
            _TO_FULL_CACHE[key] = out.stdout.strip() if out.returncode == 0 else None
        return _TO_FULL_CACHE[key]
    return None


def _related(repo: Path, a: str, b: str) -> bool:
    if a == b:
        return True
    _, table = _ancestors(repo)
    fa, fb = _to_full(repo, a), _to_full(repo, b)
    if fa is None or fb is None:
        return True  # unresolvable here: not a topology claim (rule 1 covers it)
    return fb in table.get(fa, set()) or fa in table.get(fb, set())


def ledger_targets():
    """Tracked + pending shipped markdown (never the gitignored work records)."""
    return [f for f in _git(REPO, "ls-files", "--cached", "--others",
                            "--exclude-standard").stdout.splitlines()
            if f.lower().endswith(LEDGER_EXT)]


def _tokens_in_line(line: str) -> list:
    toks = []
    for m in BACKTICK_HASH_RE.finditer(line):
        if _digest_labelled(line, m.group(1), m.start()):
            continue  # e.g. a checksum, not a commit
        toks.append(m.group(1))
    # Flatten backticks first: `A` -> `B` is still an arrow chain.  Without this
    # the topology rule silently ignored every backticked run (cycle-20 A2,
    # found by the guard's own self-proof: a doctored run passed unnoticed).
    flat = line.replace("`", " ")
    for m in ARROW_RUN_RE.finditer(flat):
        toks.extend(BARE_HASH_RE.findall(m.group(0)))
    return sorted({x for x in toks if not DIGIT_ONLY_RE.match(x)})


def _window_marked(line: str, token: str) -> bool:
    """True iff a strong marker labels *token* within MARK_WINDOW chars.

    cycle-32 A: the marker must precede the token it labels, and sit close
    to it -- a marker elsewhere on the line no longer exempts this token.
    """
    at = line.find(token)
    if at < 0:
        return False
    before = line[:at]
    return any(mk in before
               and len(before) - (before.rfind(mk) + len(mk)) <= MARK_WINDOW
               for mk in DEFECT_MARKERS)


def _enum_marked(line: str, token: str) -> bool:
    """True iff *token* is a sibling in a labelled "/"-joined hash list.

    The marker labels the list as one slot, so "`a` / `b` / `c`" is fully
    exempt when the *first* token is within MARK_WINDOW of a marker.
    """
    for m in ENUM_RUN_RE.finditer(line):
        toks = BACKTICK_HASH_RE.findall(m.group(0))
        if token in toks and _window_marked(line, toks[0]):
            return True
    return False


def _marked_token(line: str, token: str, rel: str = "") -> bool:
    """True iff *token* is exempt because it is visibly labelled a defect.

    cycle-19 convention: a document may name a bad hash only if the same
    line labels it (cycle-32: only the token(s) it *labels*, within
    MARK_WINDOW or in a "/"-list it labels).  The exemption comes from the
    writing convention alone -- never from a code identifier -- plus the
    explicitly registered row-level forms above.
    """
    if _window_marked(line, token) or _enum_marked(line, token):
        return True
    at = line.find(token)
    if at < 0:
        return False
    before = line[:at]
    return any(rel == path and stem in line
               and any(mk in before for mk in DEFECT_MARKERS)
               for path, stem, _why in ROW_MARKED_RULES)


def _digest_labelled(line: str, token: str, at: int = -1) -> bool:
    """True iff a digest label immediately labels *token* (the digest value).

    cycle-34 A: a label's scope is the labelled object only.  The label must
    sit at the end of the prefix (DIGEST_LABEL_RE is anchored), so
    "md5=<value>" exempts *value* and nothing else that shares the line.
    """
    if at < 0:
        at = line.find(token)
    if at < 0:
        return False
    return DIGEST_LABEL_RE.search(line[:at]) is not None


def _bare_git_context_tokens(line: str, repos) -> list:
    """Bare (un-backticked) commit refs on a line that IS demonstrably git context.

    cycle-21: GRAND-LOOP's wake-pointer path line and the registry's commit
    columns ("766209c/24be2bb/56b1b6e") name commits without backticks, so the
    backtick-only rule never saw them -- 79 unique bare tokens across the
    shipped docs were unguarded.  A bare token is policed only when the same
    line already carries a token that resolves in a known repo; that gate keeps
    all-hex prose words ("defaced", "effaced") out, which a bare-only rule
    cannot.  A bare token is ALSO policed when a git keyword *immediately*
    precedes it (cycle-33 A: "fixed in commit <bad>" with no other ref is a
    declaration, and the co-occurrence gate alone looked away).  A digest
    label exempts only the value it labels (cycle-34 A), never the whole
    line.
    """
    flat = BACKTICK_SPAN_RE.sub(" ", line)
    bare = [(m.group(0), m.start()) for m in BARE_REF_RE.finditer(flat)
            if not DIGIT_ONLY_RE.match(m.group(0))
            and not _digest_labelled(line, m.group(0))]
    if not bare:
        return []
    context = ([h for h, _ in bare]
               + [h for h in BACKTICK_HASH_RE.findall(line)
                  if not DIGIT_ONLY_RE.match(h)])
    in_context = any(_resolve_any(h, repos)[0] is not None for h in context)
    return sorted({h for h, at in bare
                   if in_context or GIT_ADJACENT_RE.search(flat[:at])})


def phantom_hash_problems(rel: str, text: str, repos) -> list:
    """Hashes that resolve in no known repo and are not marked as phantom."""
    problems = []
    for i, line in enumerate(text.splitlines(), 1):
        for h in _tokens_in_line(line):
            if _marked_token(line, h, rel):
                continue
            if _resolve_any(h, repos)[0] is None:
                problems.append("%s:%d: `%s` resolves in no known repo"
                                % (rel, i, h))
        for h in _bare_git_context_tokens(line, repos):
            if _marked_token(line, h, rel):
                continue
            if _resolve_any(h, repos)[0] is None:
                problems.append("%s:%d: bare `%s` resolves in no known repo"
                                % (rel, i, h))
    return problems


def arrow_topology_problems(rel: str, text: str, repos) -> list:
    """Consecutive same-repo hashes in an arrow run must be ancestor-related."""
    problems = []
    for i, line in enumerate(text.splitlines(), 1):
        for run in ARROW_RUN_RE.finditer(line.replace("`", " ")):
            run_tokens = BARE_HASH_RE.findall(run.group(0))
            if run_tokens and _marked_token(line, run_tokens[0], rel):
                continue
            prev = None
            for h in run_tokens:
                name, r = _resolve_any(h, repos)
                if name is None:
                    prev = None
                    continue
                if prev and prev[0] == name and not _related(r, prev[1], h):
                    problems.append(
                        "%s:%d: %s -> %s not ancestor-related in %s"
                        % (rel, i, prev[1], h, name))
                prev = (name, h)
    return problems


def test_no_shipped_document_names_a_nonexistent_hash() -> None:
    repos = _known_repos()
    scanned, problems = 0, []
    for rel in ledger_targets():
        try:
            text = (REPO / rel).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        scanned += 1
        problems.extend(phantom_hash_problems(rel, text, repos))
    assert scanned > 30, "the ledger scan covered only %d docs" % scanned
    assert problems == [], "\n".join(problems)


def test_shipped_arrow_chains_are_ancestor_ordered() -> None:
    repos = _known_repos()
    runs, problems = 0, []
    for rel in ledger_targets():
        try:
            text = (REPO / rel).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for line in text.splitlines():
            runs += len(ARROW_RUN_RE.findall(line))
        problems.extend(arrow_topology_problems(rel, text, repos))
    assert runs >= 1, "no arrow chain found to verify"
    assert problems == [], "\n".join(problems)


def _ghost():
    """A 7-hex token built at runtime.

    It must NOT appear as a literal backticked claim in this source file: the
    repo-wide claim scan (cycle-19) reads .py files too, and a literal here
    would make this very test fail its own guard.
    """
    return "dead" + "bee"


def test_guard_catches_a_phantom_hash() -> None:
    text = _live_text() + "\nanchor `" + _ghost() + "`(cycle-99)\n"
    problems = phantom_hash_problems("test-fixture", text, _known_repos())
    assert any("resolves in no known repo" in p for p in problems), problems


def test_guard_lets_a_marked_phantom_through() -> None:
    marked = "\n> \u274c\u9519\u8bb0: `" + _ghost() + "`(cycle-99) not counted\n"
    assert phantom_hash_problems("test-fixture", marked, _known_repos()) == []

def test_the_marker_set_is_a_writing_convention_not_an_identifier() -> None:
    # cycle-32 A: "phantom" used to be a marker, so a comment that merely
    # named this module's own function exempted the whole line.  A marker is
    # a glyph or an upper-case writing token; never a lowercase word that
    # doubles as a code identifier.
    assert "phantom" not in DEFECT_MARKERS
    assert all(not mk.isascii() or mk.isupper() for mk in DEFECT_MARKERS)


def test_an_incidental_word_no_longer_exempts_a_bad_hash() -> None:
    # cycle-32 A red evidence: this exact line used to report nothing.
    text = "\ncycle-20 fixed the phantom issue in `" + _ghost() + "`\n"
    problems = phantom_hash_problems("test-fixture", text, _known_repos())
    assert any(_ghost() in p for p in problems), problems


def test_a_marker_exempts_only_the_token_it_labels() -> None:
    # The marker labels the first token; the second sits far away on the
    # same line and must still fail.
    near, far = _ghost(), "feedface"
    assert _resolve_any(far, _known_repos())[0] is None, far
    line = ("\n\u274c\u9519\u8bb0: `" + near + "` ... "
            + "x" * 40 + " `" + far + "`\n")
    problems = phantom_hash_problems("test-fixture", line, _known_repos())
    assert any(far in p for p in problems), problems
    assert not any(near in p for p in problems), problems


def test_a_marker_must_precede_the_token_it_labels() -> None:
    # Fail-closed boundary: a marker *after* the token is not a label.
    text = "\n`" + _ghost() + "`(cycle-99) -- see the \u274c\u9519\u8bb0 note\n"
    problems = phantom_hash_problems("test-fixture", text, _known_repos())

def test_a_marker_labels_a_slash_joined_hash_list_as_one_slot() -> None:
    # cycle-32 A: "`a` / `b` / `c`" is one labelled slot, so every sibling
    # is exempt -- but only when the first token is itself labelled.
    first, mid, tail = _ghost(), "feedface", "cafebabe"
    repos = _known_repos()
    for h in (mid, tail):
        assert _resolve_any(h, repos)[0] is None, h
    labelled = ("\n\u274c\u9519\u8bb0: `" + first + "` / `" + mid
                + "` / `" + tail + "`\n")
    assert phantom_hash_problems("test-fixture", labelled, repos) == []
    unlabelled = "\nsee `" + first + "` / `" + mid + "` / `" + tail + "`\n"
    problems = phantom_hash_problems("test-fixture", unlabelled, repos)
    assert len(problems) == 3, problems
    assert any(_ghost() in p for p in problems), problems


def test_the_marker_window_is_inclusive_at_24_and_exclusive_at_25() -> None:
    def probe(gap):
        # gap = chars between the end of the marker and the start of the token
        body = "\n\u274c\u9519\u8bb0" + " " * (gap - 1) + "`" + _ghost() + "`\n"
        return phantom_hash_problems("test-fixture", body, _known_repos())
    assert probe(24) == [], "a marker 24 chars before the token still labels it"
    assert probe(25), "a marker 25 chars before the token no longer labels it"


def test_row_level_marker_exemptions_are_registered_and_load_bearing() -> None:
    # A row-scoped exemption is a claim, not an inference: it must name a
    # real shipped file, its stem must survive, and it must still be doing
    # work -- otherwise the entry is stale and must be removed.
    repos = _known_repos()
    for rel, stem, _why in ROW_MARKED_RULES:
        assert rel in ledger_targets(), rel
        text = (REPO / rel).read_text(encoding="utf-8")
        assert stem in text, "stem vanished from %s: %r" % (rel, stem)
        relies = False
        for line in text.splitlines():
            if stem not in line:
                continue
            for h in (_tokens_in_line(line)
                      + _bare_git_context_tokens(line, repos)):
                if _resolve_any(h, repos)[0] is None:
                    assert _marked_token(line, h, rel), (rel, h)
                    if not _window_marked(line, h):
                        relies = True
        assert relies, "registry entry is no longer load-bearing: %s" % rel


def test_a_row_level_exemption_is_scoped_to_its_registered_file() -> None:
    (rel, stem, _why), = ROW_MARKED_RULES
    line = "| filler | " + stem + " | " + "x" * 40 + " `" + _ghost() + "`"
    text = "\n" + line + "\n"
    assert phantom_hash_problems(rel, text, _known_repos()) == [], "registered"
    assert phantom_hash_problems("some/other.md", text, _known_repos()), \
        "the row exemption must not leak into an unregistered file"




def test_guard_ignores_a_date_shaped_token() -> None:
    # 20261023 is a date, and it matches [0-9a-f]{7,40}; it must not be a finding.
    text = "\nsession dated `20261023`\n"
    assert phantom_hash_problems("test-fixture", text, _known_repos()) == []


def test_guard_catches_a_disordered_arrow_chain(tmp_path) -> None:
    repo = tmp_path / "synth"
    repo.mkdir()

    def g(*a):
        # -c core.hooksPath= : this machine has a global hook that runs a slow
        # AK scanner on every commit; a guard test must not pay for that.
        return subprocess.run(
            ["git", "-C", str(repo), "-c", "core.hooksPath="] + list(a),
            capture_output=True, text=True, encoding="utf-8")

    who = ["-c", "user.email=t@example.invalid", "-c", "user.name=t"]
    g("init", "-q")
    (repo / "f.txt").write_text("base", encoding="utf-8")
    g("add", "f.txt")
    g(*who, "commit", "-q", "-m", "base")
    g("branch", "left")
    g("checkout", "-q", "-b", "right")
    (repo / "f.txt").write_text("right", encoding="utf-8")
    g(*who, "commit", "-q", "-am", "right")
    right = g("rev-parse", "--short", "HEAD").stdout.strip()
    g("checkout", "-q", "left")
    (repo / "f.txt").write_text("left", encoding="utf-8")
    g(*who, "commit", "-q", "-am", "left")
    left = g("rev-parse", "--short", "HEAD").stdout.strip()
    text = "chain: %s\u2192%s\n" % (left, right)
    problems = arrow_topology_problems("synth.md", text, [("synth", repo)])
    assert any("not ancestor-related" in p for p in problems), problems



def test_guard_catches_a_doctored_bare_hash() -> None:
    # cycle-21: bare commit refs (wake-pointer path line, registry columns) were
    # invisible; a wrong one there must now be caught.  af5cd11 is real, so the
    # line is git context and the ghost beside it is a finding.
    text = "\nsource pin: %s/af5cd11\n" % _ghost()
    problems = phantom_hash_problems("test-fixture", text, _known_repos())
    assert any("bare" in p and _ghost() in p for p in problems), problems


def test_guard_ignores_a_bare_hex_word_without_git_context() -> None:
    # "defaced"/"effaced" are all-hex English words; with no resolvable commit on
    # the line the bare rule stays silent (why the rule is context-gated).
    text = "\nthe defaced record was effaced\n"
    assert phantom_hash_problems("test-fixture", text, _known_repos()) == []


def test_guard_catches_a_lone_bare_hash_after_a_git_keyword() -> None:
    # cycle-33 A red evidence: a lone bare ref with no resolvable co-token
    # used to be invisible ("the gate looked away").  An adjacent keyword
    # declares it on its own.
    text = "\nfixed in commit " + _ghost() + " (no other ref)\n"
    problems = phantom_hash_problems("test-fixture", text, _known_repos())
    assert any("bare" in p and _ghost() in p for p in problems), problems


def test_a_git_keyword_only_widens_the_gate_when_it_is_adjacent() -> None:
    # The relaxation is *adjacency*, never co-occurrence: an all-hex English
    # word far from the keyword stays silent (0 false positives is the
    # contract this clause was measured against).
    text = "\nthe commit history was rewritten; the defaced record was effaced\n"
    assert phantom_hash_problems("test-fixture", text, _known_repos()) == []


def test_the_adjacency_clause_covers_the_writing_conventions() -> None:
    repos = _known_repos()
    for kw in ("commit", "HEAD", "baseline", "tag", "revision", "sha"):
        line = "\n%s %s\n" % (kw, _ghost())
        problems = phantom_hash_problems("test-fixture", line, repos)
        assert any("bare" in p and _ghost() in p for p in problems), (kw, problems)



# ---------------------------------------------------------------------------
# cycle-34 A: the *scope* of a switch must not exceed the object it exempts.
# cycle-32 fixed a value-scoped hole (a marker exempted the whole line);
# cycle-33 fixed a trigger-scoped hole (the gate looked away).  cycle-34 is
# the third axis -- an exemption's scope: DIGEST_ANY_RE switched the bare scan
# off for the entire line, so "fixed in commit <bad>, md5=<value>" silenced a
# real commit claim (a latent hole: 0 shipped lines hide a bad hash behind a
# digest label).  The label now exempts only the value it labels.
# ---------------------------------------------------------------------------

def test_guard_catches_a_bad_hash_beside_a_digest_label() -> None:
    # Red evidence: a commit claim sharing a line with "md5=<value>" used to
    # be invisible because the label skipped the whole line.
    text = ("\nfixed in commit " + _ghost()
            + ", md5=cfd2d6efd2c3c92374535b7d3c04f8f3\n")
    problems = phantom_hash_problems("test-fixture", text, _known_repos())
    assert any("bare" in p and _ghost() in p for p in problems), problems
    # ... and the digest's own value is still exempt.
    assert not any("cfd2d6ef" in p for p in problems), problems


def test_a_digest_label_exempts_only_the_value_it_labels() -> None:
    # The label never exempts a token that merely shares the line.
    text = ("\nmd5=cfd2d6efd2c3c92374535b7d3c04f8f3 then fixed in commit "
            + _ghost() + "\n")
    problems = phantom_hash_problems("test-fixture", text, _known_repos())
    assert any("bare" in p and _ghost() in p for p in problems), problems
    assert not any("cfd2d6ef" in p for p in problems), problems


def test_the_digest_exemption_is_anchored_to_its_own_value() -> None:
    # The predicate is per token, anchored at the end of the prefix: a hex
    # token merely near a label, but not the labelled value, is not exempt.
    line = ("md5=cfd2d6efd2c3c92374535b7d3c04f8f3 and " + _ghost() + " later")
    assert _digest_labelled(line, "cfd2d6efd2c3c92374535b7d3c04f8f3")
    assert not _digest_labelled(line, _ghost())


def test_the_classifier_is_deliberately_looser_than_the_gate() -> None:
    # The forensic classifier may explain a token the gate reports (line-level
    # evidence); the asymmetry is a decision, pinned here.
    line = ("fixed in commit " + _ghost()
            + ", md5=cfd2d6efd2c3c92374535b7d3c04f8f3")
    assert classify_finding(line, _ghost(), line + "\n") == "fingerprint"



def test_guard_ignores_a_labelled_digest_bare() -> None:
    # A retest log records an md5, not a commit; the label must exempt it.
    text = "\nretest md5=cfd2d6efd2c3c92374535b7d3c04f8f3... 1184 passed\n"
    assert phantom_hash_problems("test-fixture", text, _known_repos()) == []


def test_external_source_pin_resolves_when_repo_present() -> None:
    # 2ee2239 pins TencentDB-Agent-Memory (docs/.../SOURCE.md).  It is a real
    # commit there, so it must never be reported as a phantom.
    if not any((src / ".git").exists() for src in EXT_SOURCE_REPOS):
        return  # sibling source repo absent on this machine: nothing to assert
    repos = _known_repos()
    assert _resolve_any("2ee2239", repos)[0] is not None
    line = "\n| A | 766209c/24be2bb/56b1b6e | TencentDB@2ee2239 |\n"
    assert phantom_hash_problems("test-fixture", line, repos) == []



def _full_head() -> str:
    return _git(REPO, "rev-parse", "HEAD").stdout.strip()


def test_guard_resolves_a_full_length_hash() -> None:
    # cycle-22: the abbrev table only holds %h, so a 40-char commit hash used to
    # resolve in no repo -- a latent false positive the ledger never hit.
    full = _full_head()
    assert len(full) == 40, full
    text = "\nanchor `" + full + "`\n"
    assert phantom_hash_problems("test-fixture", text, _known_repos()) == []


def test_guard_resolves_a_medium_length_hash() -> None:
    full = _full_head()
    text = "\nanchor `" + full[:10] + "`\n"
    assert phantom_hash_problems("test-fixture", text, _known_repos()) == []


def test_guard_ignores_a_separator_labelled_digest() -> None:
    # "matrix_md5=<32hex>" is a checksum, not a commit claim; the separator form
    # (md5=..., sha256:...) must be recognised.
    text = "\nverify input_hash matrix_md5=3c8e35f6d10a22d863c3097e388fb56a ok\n"
    assert phantom_hash_problems("test-fixture", text, _known_repos()) == []


# ---------------------------------------------------------------------------
# cycle-22 A2: the cross-repo ledger sweep.
#
# cycle-18..21 guarded *this* repo's ledger.  cycle-22 pointed the identical
# rule set at the two sibling corpora the ledger cites -- legacy sloth-loop
# (2300 shipped .md) and architect-skills (86) -- and got 34 findings, of which
# ZERO are phantom commit claims.  Every one is a value that is legitimately
# unresolvable in a git object store:
#
#   * a dataset fingerprint ("verify input_hash ...", "matrix_md5=...");
#   * a runtime object id (a container / pod / sandbox id on a crictl line);
#   * a commit the ledger itself records as amended away on an unpushed branch,
#     so it exists in no clone;
#   * the baseline HEAD of a foreign repo with no local checkout;
#   * the guard's own example tokens, quoted verbatim (TES-15 family, 7th).
#
# The rule set is right; the corpus is different.  A foreign-corpus sweep
# therefore needs a classifier, and the classifier must stay *fail-closed*:
# anything it cannot positively explain remains a phantom.
#
# Deliberate boundary: the classifier is used ONLY by the forensic sweep
# (scripts/audit_cross_repo_ledger.py).  The shipped gate above still runs
# phantom_hash_problems() over this repo's docs with NO classification, so a
# forged 16/32-hex claim is still a hard FAIL in sloth-loop's own ledger.
# ---------------------------------------------------------------------------

# Tokens the ledger itself documents as no longer existing in any checkout,
# each with the receipt that makes it legitimate: an entry here is a claim.
REGISTERED_UNRESOLVABLE = {
    # architect-skills' sloth-loop history: an unpushed branch was amended twice
    # before it was pushed (ADR-008), so the intermediates exist in no clone.
    "441cef4": "sloth-loop amend-twice intermediate (architect-skills ADR-008)",
    "f6ea7aa": "sloth-loop amend-twice intermediate (architect-skills ADR-008)",
    # architect-skills' cspm-agent audit: the baseline HEAD of a foreign repo
    # that has no checkout on this machine.
    "9d51fcd": "foreign repo baseline (cspm-agent, not checked out here)",
    "e9714fe": "foreign repo commit (cspm-agent, not checked out here)",
    # cycle-33 A: legacy's OODA evidence doc cites the HEAD of an exploration
    # session ("HEAD 4b22b8d"); it exists in no clone (a frozen runtime
    # artifact, not a commit the ledger can point at).  Surfaced only once the
    # bare-hash gate gained the adjacency clause; receipt = the doc itself.
    "4b22b8d": "legacy work_ooda exploration HEAD (frozen pre-amend evidence)",
}
# A hex token of exactly these lengths is a digest, not a git object id: the
# repos here abbreviate to 7..12 (core.abbrev=auto) and a full SHA-1 is 40.
DIGEST_LENGTHS = (16, 32, 64)
# Classifier-only evidence: a line that *names* the value a digest (even with no
# "=" / ":" separator, as in "matrix_md5 across sweeps") is writing a
# fingerprint.  Deliberately looser than the gate's DIGEST_ANY_RE -- and it can
# only ever relax the forensic report, never the shipped gate.
FINGERPRINT_EVIDENCE_RE = re.compile(
    r"(md5|sha1|sha256|sha512|checksum|digest|input_hash|指纹)", re.I)
# A line naming a runtime object carries container/pod/sandbox ids, which
# resolve in a container runtime, not in a git object store.
RUNTIME_CONTEXT_RE = re.compile(
    r"(crictl|\bpod\b|sandbox|\u5bb9\u5668|\u6c99\u7bb1)", re.I)


def _runtime_object_ids(text: str) -> set:
    """Tokens that sit on a runtime-object line anywhere in the document.

    A container id is often quoted a second time on a line that no longer says
    "crictl" ("local probe hit `791d2cec1f22b` Running"), so the class is
    resolved per document, not per line.
    """
    ids: set = set()
    for line in text.splitlines():
        if RUNTIME_CONTEXT_RE.search(line):
            ids |= set(BARE_HASH_RE.findall(line))
    return ids


def classify_finding(line: str, token: str, text: str, rel: str = "") -> str:
    """Why *token* is not a commit claim, or "phantom" when nothing explains it.

    Fail-closed: the default is "phantom".  A defect exemption is per token
    (cycle-32 A): it is granted only to the token a marker actually labels.
    """
    if _marked_token(line, token, rel):
        return "defect-marked"
    if token in REGISTERED_UNRESOLVABLE:
        return "registered-external"
    if FINGERPRINT_EVIDENCE_RE.search(line) or len(token) in DIGEST_LENGTHS:
        return "fingerprint"
    if token in _runtime_object_ids(text):
        return "runtime-id"
    return "phantom"


def classify_document(rel: str, text: str, repos) -> list:
    """(line, token, class) for every hash *text* names that resolves nowhere."""
    out = []
    for i, line in enumerate(text.splitlines(), 1):
        seen: set = set()
        for h in _tokens_in_line(line) + _bare_git_context_tokens(line, repos):
            if h in seen:
                continue
            seen.add(h)
            if _resolve_any(h, repos)[0] is None:
                out.append((i, h, classify_finding(line, h, text, rel)))
    return out


# Each line below is a real shape the cycle-22 sweep of legacy sloth-loop and
# architect-skills produced; none of them is a commit claim.
_CROSS_REPO_SAMPLE = (
    "host `crictl ps` shows container `940e36878ccc1` created\n"
    "local probe hit `940e36878ccc1` Running\n"
    "digest agrees across 3 rounds `02390456e3fe7e0d1874db3bcce9736d`\n"
    "verify input_hash agrees `6decf46b459cece9`\n"
    "atomic commits `441cef4` and `f6ea7aa` live on an amended-away branch\n"
    "Git baseline: HEAD `9d51fcd` (2026-08-17)\n"
    "> \u274c\u9519\u8bb0: `" + _ghost() + "`(cycle-99) not counted\n"
)


def test_classifier_explains_every_cross_repo_finding_shape() -> None:
    found = classify_document("sample.md", _CROSS_REPO_SAMPLE, _known_repos())
    classes = {k for _, _, k in found}
    assert found, "the sample must produce findings"
    assert "phantom" not in classes, found
    assert {"runtime-id", "fingerprint", "registered-external"} <= classes, classes


def test_classifier_resolves_a_runtime_id_from_document_context() -> None:
    # The id is quoted again on a line that no longer says "crictl"; the class
    # comes from the document, and a document with no runtime context at all
    # still leaves the same token unexplained.
    doc = "`crictl ps` shows container `f00dbabe1234`\n"
    assert classify_finding(doc.splitlines()[0], "f00dbabe1234", doc) == "runtime-id"
    bare_doc = "local probe hit `f00dbabe1234`\n"
    assert classify_finding(bare_doc.splitlines()[0], "f00dbabe1234",
                            bare_doc) == "phantom"


def test_classifier_keeps_an_unexplained_hash_as_phantom() -> None:
    text = "\nanchor `" + _ghost() + "`(cycle-99)\n"
    found = classify_document("sample.md", text, _known_repos())
    assert [k for _, _, k in found] == ["phantom"], found


def test_classifier_treats_a_digest_named_on_the_line_as_a_fingerprint() -> None:
    # "matrix_md5 agrees <hex>" names a checksum with no separator; the very
    # same token on a line that names nothing stays unexplained.
    named = "matrix_md5 agrees `" + _ghost() + "`\n"
    assert classify_finding(named.splitlines()[0], _ghost(), named) == "fingerprint"
    unnamed = "plain note `" + _ghost() + "`\n"
    assert classify_finding(unnamed.splitlines()[0], _ghost(), unnamed) == "phantom"


# ---------------------------------------------------------------------------
# cycle-23 A: "verify the verifier".  cycle-22 shipped
# scripts/audit_cross_repo_ledger.py -- the *only* code path that calls the
# cross-repo classifier (classify_document) -- with zero coverage, and its exit
# code (1 iff an unexplained phantom remains) was never exercised by anything.
# A tool whose verdicts are evidence must have its verdicts tested: an untested
# gate is a claim, not a fact.  Same family as the TES-12/13 line and the
# cycle-16..22 run of "the check was never itself checked".
#
# The registry REGISTERED_UNRESOLVABLE is a hand-written receipt table; it can
# rot silently, so one test asserts every entry still resolves NOWHERE (the
# moment one starts resolving, the receipt is stale and the sweep lies).
# ---------------------------------------------------------------------------
import importlib.util

_AUDIT_SCRIPT = REPO / "scripts" / "audit_cross_repo_ledger.py"


def _load_audit_module():
    spec = importlib.util.spec_from_file_location("_audit_ledger", _AUDIT_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _synth_corpus_repo(tmp_path, body: str):
    """A throwaway git checkout holding one shipped .md corpus file."""
    repo = tmp_path / "synth-corpus"
    repo.mkdir()
    subprocess.run(["git", "-C", str(repo), "-c", "core.hooksPath=",
                    "init", "-q"], capture_output=True, text=True)
    (repo / "corpus.md").write_text(body, encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "corpus.md"],
                   capture_output=True, text=True)
    return repo


def _run_audit(audit, repo, capsys):
    """Run main() against only the synthetic corpus, never this machine.

    The default targets are cleared so a unit test can never sweep a sibling
    checkout (slow, and machine-dependent).
    """
    audit.DEFAULT_TARGETS = ()
    rc = audit.main(["--repo", "synth=" + str(repo), "--json"])
    return rc, json.loads(capsys.readouterr().out)


def test_cross_repo_sweep_flags_an_unexplained_phantom(tmp_path, capsys) -> None:
    repo = _synth_corpus_repo(
        tmp_path, _CROSS_REPO_SAMPLE + "anchor `" + _ghost() + "`(cycle-99)\n")
    audit = _load_audit_module()
    rc, payload = _run_audit(audit, repo, capsys)
    assert rc == 1, payload
    assert [f["token"] for f in payload["unexplained"]] == [_ghost()], payload
    classes = [f["class"] for r in payload["report"] for f in r["findings"]]
    assert classes.count("phantom") == 1, classes
    assert {"runtime-id", "fingerprint", "registered-external"} <= set(classes)


def test_cross_repo_sweep_exits_zero_when_every_finding_is_explained(
        tmp_path, capsys) -> None:
    repo = _synth_corpus_repo(tmp_path, _CROSS_REPO_SAMPLE)
    audit = _load_audit_module()
    rc, payload = _run_audit(audit, repo, capsys)
    assert rc == 0, payload
    assert payload["unexplained"] == [], payload["unexplained"]
    (entry,) = payload["report"]
    assert entry["present"] is True and entry["files"] == 1, entry


def test_registered_unresolvable_entries_are_still_unresolvable() -> None:
    # Silently-rotting registry: an entry that starts resolving means the
    # receipt it cites is stale, and every sweep verdict built on it is wrong.
    repos = _known_repos()
    for token in REGISTERED_UNRESOLVABLE:
        assert _resolve_any(token, repos)[0] is None, token


# ---------------------------------------------------------------------------
# cycle-25 A: the wake pointer's "next target" section pointer is hand-typed.
#
# GRAND-LOOP.md ends its status line with a next-target pointer ("... by 13.N")
# into the append-only status registry
# (docs/flow/2026-09-05-grand-loop-status.md).  Every cycle's C/D step bumps
# that number by hand and nothing verified it.  A stale pointer sends the next
# agent to an older "next target" list -- the same failure as cycle-18/19/21 (a
# written pointer nobody compares to reality), now on the *section* axis.
#
# Evidence (cycle-25 A): rewriting the pointer from 13.50 to the stale 13.49
# left tests/test_wake_pointer_chain.py at 30 passed and docs_baseline at OK.
#
# Rule: the pointer number must equal the LATEST "### 13.N" section, and the
# registry itself must be strictly increasing and gap-free (append-only).
# ---------------------------------------------------------------------------

STATUS_DOC = REPO / "docs" / "flow" / "2026-09-05-grand-loop-status.md"
# the pointer phrase is "? ?13.N ??"; ? is \xa7 so the pattern stays ASCII-source
NEXT_TARGET_RE = re.compile("\u6309 \xa7(13\\.[0-9]+) \u6392\u5e8f")
SECTION_RE = re.compile(r"^### (13\.([0-9]+)) ", re.M)


def registry_sections(text: str) -> list:
    return [int(m.group(2)) for m in SECTION_RE.finditer(text)]


def next_target_pointer(text: str):
    m = NEXT_TARGET_RE.search(text)
    return int(m.group(1).split(".")[1]) if m else None


def next_target_problems(pointer_text: str, registry_text: str) -> list:
    """Violations of the pointer-vs-registry contract (empty == consistent)."""
    problems = []
    nums = registry_sections(registry_text)
    if not nums:
        return ["status registry: no '### 13.N' section found (fail-closed)"]
    for a, b in zip(nums, nums[1:]):
        if b <= a:
            problems.append("status registry: section 13.%d is not after 13.%d" % (b, a))
        elif b != a + 1:
            problems.append("status registry: gap between 13.%d and 13.%d" % (a, b))
    ptr = next_target_pointer(pointer_text)
    if ptr is None:
        problems.append("GRAND-LOOP.md: next-target pointer missing (fail-closed)")
    elif ptr != nums[-1]:
        problems.append(
            "GRAND-LOOP.md: next-target points at 13.%d but the registry's newest section is 13.%d"
            % (ptr, nums[-1]))
    return problems


def _registry_text() -> str:
    return STATUS_DOC.read_text(encoding="utf-8")


def test_next_target_pointer_matches_the_registry_head() -> None:
    problems = next_target_problems(_live_text(), _registry_text())
    assert problems == [], "\n".join(problems)


def test_next_target_guard_fails_closed_when_the_pointer_is_stale() -> None:
    stale = NEXT_TARGET_RE.sub("\u6309 \xa713.1 \u6392\u5e8f", _live_text(), count=1)
    problems = next_target_problems(stale, _registry_text())
    assert any("newest section" in p for p in problems), problems


def test_next_target_guard_catches_a_duplicate_or_gap_section() -> None:
    reg = _registry_text()
    dup = reg.replace("### 13.50 ", "### 13.49 ", 1)
    assert any("not after" in p for p in next_target_problems(_live_text(), dup))
    gapped = reg.replace("### 13.50 ", "### 13.99 ", 1)
    assert any("gap between" in p for p in next_target_problems(_live_text(), gapped))


def test_next_target_guard_fails_closed_when_the_pointer_is_gone() -> None:
    problems = next_target_problems("\u6ca1\u6709\u6307\u9488\u4e86\n", _registry_text())
    assert problems and "missing" in problems[0], problems


# ---------------------------------------------------------------------------
# cycle-27 A: a recogniser must not be narrower than the reality it audits.
#
# cycle-26 registered the candidate "the cycle annotation next to a hash is never
# machine-checked".  Chasing it exposed the *engine* underneath: the chain-entry
# parser, the head-pointer parser and the hash-claim parser each hard-coded a
# 7-char hash while the phantom-hash rule already accepted 7..40.  A document
# that wrote an 8..40-char (still resolvable) hash therefore lost its record
# **silently** -- the entry was skipped and every floor (MIN_ENTRIES) still
# passed.  The claim parser was narrower again: it demanded an ASCII "(" glued
# to the backtick, so the shipped legacy-baseline claim in
# docs/flow/2026-09-05-grand-loop-task.md -- written with a fullwidth bracket --
# was invisible to every sweep.  That claim also only resolves in the *legacy*
# repo, which claim_problems never looked at, so recognising it would have been
# reported as a phantom.
#
# Red evidence (cycle-27 A, on the pre-cycle-27 parsers): rewriting one chain
# entry to its 8-char form kept this file green while chain_entries dropped
# 49 -> 48; the pinned legacy claim was seen by 0 recognisers; a fullwidth claim
# written next to "head <hash>" was seen by 0 thresholds.
#
# Rule: one alphabet for every recogniser, and a claim resolves in any known
# repo before it may be called a phantom.
# ---------------------------------------------------------------------------

LEGACY_SPEC_REL = "docs/flow/2026-09-05-grand-loop-task.md"
LEGACY_SPEC = REPO / LEGACY_SPEC_REL
# HEAD_PREFIX is defined once, beside HEAD_RE (cycle-31 A).
FULLWIDTH_OPEN, FULLWIDTH_CLOSE = "\uff08", "\uff09"


def _claim_keys(pattern, text: str) -> list:
    """(hash, cycle) pairs a recogniser sees, in document order."""
    return [(m.group(1), int(m.group(3))) for m in pattern.finditer(text)]


def _longer_form(repo: Path, h: str) -> str:
    """An 8-char abbreviation of the same commit (7 alone is not enough here)."""
    full = _to_full(repo, h)
    assert full is not None, h
    return full[:8]


def test_the_ledger_recognisers_share_one_hash_alphabet() -> None:
    h = _longer_form(REPO, HEAD_RE.search(_live_text()).group(1))
    entry = BT + h + BT + "(cycle-1 A: x)"
    head = HEAD_PREFIX + BT + h + BT
    claim = "... " + BT + h + BT + "(cycle-1 A: x)"
    assert ENTRY_RE.findall(entry) == [(h, "cycle-1 A: x")]
    assert HEAD_RE.findall(head) == [h]
    assert _claim_keys(CLAIM_RE, claim) == [(h, 1)]
    assert NARROW_ENTRY_RE.findall(entry) == []
    assert NARROW_HEAD_RE.findall(head) == []
    assert _claim_keys(NARROW_CLAIM_RE, claim) == []


def test_the_widened_recognisers_keep_the_shipped_verdicts_clean() -> None:
    text = _live_text()
    # The claim alphabet is *deliberately* wider (cycle-27) and cycle-31 widened
    # the entry *brackets*; across the whole document a wider recogniser may see
    # more records (defect prose, the legacy chain), so what must hold is the
    # verdict -- no new problem -- plus "nothing the narrow one saw is lost", and
    # inside the chain block the two must agree exactly.
    block = chain_block(text)[0]
    assert NARROW_ENTRY_RE.findall(block) == ENTRY_RE.findall(block)
    wide_entries = ENTRY_RE.findall(text)
    for pair in NARROW_ENTRY_RE.findall(text):
        assert pair in wide_entries, pair
    assert NARROW_HEAD_RE.findall(text) == HEAD_RE.findall(text)
    for key in _claim_keys(NARROW_CLAIM_RE, text):
        assert key in _claim_keys(CLAIM_RE, text), key
    assert claim_problems("docs/flow/GRAND-LOOP.md", text, _arch_repo()) == []


def test_chain_recogniser_keeps_coverage_for_a_longer_hash() -> None:
    text = _live_text()
    entries = chain_entries(chain_block(text)[0])
    h, ann, _n = _first_local_entry()
    long_h = _longer_form(REPO, h)
    doctored = text.replace(BT + h + BT + "(" + ann + ")",
                            BT + long_h + BT + "(" + ann + ")", 1)
    assert doctored != text
    dblock = chain_block(doctored)[0]
    assert len(NARROW_ENTRY_RE.findall(dblock)) == len(entries) - 1, \
        "the pre-cycle-27 parser must lose the entry (silent loss is the bug)"
    assert len(chain_entries(dblock)) == len(entries), \
        "the widened parser must keep it"
    assert chain_violations(doctored, arch_repo=_arch_repo()) == []


def test_guard_catches_a_fullwidth_bracket_claim() -> None:
    h, ann, n = _first_local_entry()
    bad_ann = CYCLE_RE.sub("cycle-%d" % (n + 1), ann, count=1)
    doctored = _live_text().replace(
        BT + h + BT + "(" + ann + ")",
        BT + h + BT + FULLWIDTH_OPEN + bad_ann + FULLWIDTH_CLOSE, 1)
    assert FULLWIDTH_OPEN in doctored
    assert (h, n + 1) not in _claim_keys(NARROW_CLAIM_RE, doctored)
    problems = claim_problems("test-fixture", doctored, _arch_repo())
    assert any("but its commit says" in p for p in problems), problems


def test_guard_catches_a_space_before_the_bracket() -> None:
    h, ann, n = _first_local_entry()
    bad_ann = CYCLE_RE.sub("cycle-%d" % (n + 1), ann, count=1)
    doctored = _live_text().replace(
        BT + h + BT + "(" + ann + ")", BT + h + BT + " (" + bad_ann + ")", 1)
    problems = claim_problems("test-fixture", doctored, _arch_repo())
    assert any("but its commit says" in p for p in problems), problems


def test_the_widened_claim_recogniser_sees_every_narrow_claim() -> None:
    narrow = wide = 0
    rescued = []
    for rel in scan_targets():
        try:
            text = (REPO / rel).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        a, b = _claim_keys(NARROW_CLAIM_RE, text), _claim_keys(CLAIM_RE, text)
        for key in a:
            assert key in b, (rel, key)
        narrow += len(a)
        wide += len(b)
        rescued += [rel for key in b if key not in a]
    assert narrow >= MIN_REPO_CLAIMS
    assert wide >= narrow
    assert LEGACY_SPEC_REL in rescued, rescued


def test_the_pinned_legacy_spec_claim_resolves_across_repos() -> None:
    text = LEGACY_SPEC.read_text(encoding="utf-8")
    assert _claim_keys(CLAIM_RE, text) == [("64de89b", 1)]
    assert _claim_keys(NARROW_CLAIM_RE, text) == []
    assert claim_problems(LEGACY_SPEC_REL, text, _arch_repo()) == []


def test_claim_scan_still_reports_an_unknown_hash() -> None:
    ghost = "dec0de1"
    assert _resolve_any(ghost, _known_repos())[0] is None
    h, ann, _n = _first_local_entry()
    doctored = _live_text().replace(BT + h + BT + "(" + ann + ")",
                                    BT + ghost + BT + "(" + ann + ")", 1)
    problems = claim_problems("test-fixture", doctored, _arch_repo())
    assert any("does not exist" in p for p in problems), problems


def test_head_pointer_accepts_a_longer_form_of_the_recorded_head() -> None:
    text = _live_text()
    h = HEAD_RE.search(text).group(1)
    long_h = _longer_form(REPO, h)
    assert long_h != h
    doctored = text.replace(HEAD_PREFIX + BT + h + BT,
                            HEAD_PREFIX + BT + long_h + BT, 1)
    assert NARROW_HEAD_RE.search(doctored) is None
    assert chain_violations(doctored, arch_repo=_arch_repo()) == []


def test_head_pointer_guard_still_catches_a_different_head() -> None:
    text = _live_text()
    h = HEAD_RE.search(text).group(1)
    other = next(e[0] for e in chain_entries(chain_block(text)[0])
                 if ARCH_TAG not in e[1] and e[0] != h
                 and not _to_full(REPO, e[0]).startswith(h))
    doctored = text.replace(HEAD_PREFIX + BT + h + BT,
                            HEAD_PREFIX + BT + other + BT, 1)
    problems = chain_violations(doctored, arch_repo=_arch_repo())
    assert any("wake pointer head" in p for p in problems), problems


# ---------------------------------------------------------------------------
# cycle-31 A: the ledger recogniser's *syntax* must be one constant per slot.
#
# cycle-27 unified the hash alphabet and taught the claim parser the full-width
# bracket, but ENTRY_RE -- the chain-record parser -- stayed ASCII-only.  Red
# evidence (live corpus): a chain record whose cycle annotation was WRONG and
# written with full-width brackets left `chain_entries` at 56 and
# `chain_violations` at [] -- it was dropped silently (a wrong hash written
# the same way is invisible too).  (The shape is described, not written: the
# repo-wide scan reads .py files and a literal here would fail its own guard.)
# ---------------------------------------------------------------------------


def test_guard_catches_a_full_width_bracket_chain_entry() -> None:
    h, ann, n = _first_local_entry()
    bad_ann = CYCLE_RE.sub("cycle-%d" % (n + 1), ann, count=1)
    doctored = _live_text().replace(
        BT + h + BT + "(" + ann + ")",
        BT + h + BT + FULLWIDTH_OPEN + bad_ann + FULLWIDTH_CLOSE, 1)
    assert FULLWIDTH_OPEN in doctored
    problems = chain_violations(doctored, arch_repo=_arch_repo())
    assert any("annotated cycle-" in p for p in problems), problems


def test_the_entry_recogniser_keeps_a_full_width_record() -> None:
    text = _live_text()
    entries = chain_entries(chain_block(text)[0])
    h, ann, _n = _first_local_entry()
    doctored = text.replace(
        BT + h + BT + "(" + ann + ")",
        BT + h + BT + FULLWIDTH_OPEN + ann + FULLWIDTH_CLOSE, 1)
    dblock = chain_block(doctored)[0]
    assert len(ASCII_ENTRY_RE.findall(dblock)) == len(entries) - 1, \
        "the ASCII-only parser must lose the entry (silent loss is the bug)"
    assert len(chain_entries(dblock)) == len(entries), \
        "the widened parser must keep it"
    assert chain_violations(doctored, arch_repo=_arch_repo()) == []


def test_the_bracket_class_is_one_constant_for_every_recogniser() -> None:
    h = HEAD_RE.search(_live_text()).group(1)
    for op, cl in ((FULLWIDTH_OPEN, FULLWIDTH_CLOSE), ("(", ")")):
        assert ENTRY_RE.findall(BT + h + BT + op + "cycle-1 A" + cl) == \
            [(h, "cycle-1 A")]
        assert _claim_keys(CLAIM_RE, BT + h + BT + op + "cycle-1") == [(h, 1)]


def test_the_head_pointer_is_one_constant_and_appears_once() -> None:
    text = _live_text()
    assert HEAD_RE.pattern.startswith(re.escape(HEAD_PREFIX))
    assert HEAD_PREFIX in text
    heads = HEAD_RE.findall(text)
    assert len(heads) == 1
    doctored = text + "\n" + HEAD_PREFIX + BT + heads[0] + BT + "\n"
    problems = chain_violations(doctored, arch_repo=_arch_repo())
    assert any("wake pointers" in p for p in problems), problems


def test_an_unbracketed_cycle_annotation_is_a_decided_boundary() -> None:
    """A cycle number merely *near* a hash is not a machine claim (cycle-31 A).

    Widening CLAIM_RE to commas/dashes would read prose ("as of cycle-N") as a
    claim and manufacture false reds; cycle-19/20 fixed the rule that only the
    explicit bracket form is machine-claimed.  The decision is pinned here: the
    annotation is NOT checked, but the hash itself still is.
    """
    h = HEAD_RE.search(_live_text()).group(1)
    line = "\nsee `" + h + "`, cycle-99 for details\n"
    assert _claim_keys(CLAIM_RE, line) == []
    assert claim_problems("probe.md", line, _arch_repo()) == []
    assert _tokens_in_line(line) == [h]      # the hash is still existence-policed
