#!/usr/bin/env python
"""Server-side content scan for the fail-closed push gate (cycle-37 A).

The LOCAL gate (scripts/run_gate.py) is bypassable from the client side:
--no-verify skips the pre-commit hook, core.hooksPath can point elsewhere, and a
fresh clone simply has no hook installed.  A check that protects the repository
itself (rather than the committer's convenience) therefore has to run where the
client cannot switch it off.  This module is the content half of that check: a
push may not introduce secret material, a private key, an AWS access key id, a
hard-coded high-entropy credential, or a developer home-directory path in
code/config.

Pure functions only (relative path + text -> findings), so the rule set is
unit-testable and -- cycle-32/33 method -- its false-positive rate is
*measurable over the shipped corpus*.  A detector that merely looks reasonable
is not evidence; the measurement is.

Deliberately NOT rules (each omission is a decision, pinned by that measurement):
  * generic absolute paths: the repo's own docs legitimately quote the
    developer's E: drive, and a rule that flags them is noise, not protection;
  * "entropy over every long token": English prose is full of long tokens.
"""
from __future__ import annotations

import math
import re
from pathlib import PurePosixPath

SECRET_FILE_RE = re.compile(
    r"(^|/)(\.env(\..*)?|id_rsa|id_dsa|id_ecdsa|id_ed25519|credentials|"
    r"\.netrc|\.npmrc|\.pypirc)$",
    re.I,
)
SECRET_EXT_RE = re.compile(r"\.(pem|key|p12|pfx|keystore|jks|ppk|kdbx)$", re.I)
PRIVATE_KEY_RE = re.compile(r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----")
AWS_KEY_ID_RE = re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")
GENERIC_SECRET_RE = re.compile(
    r"(?i)\b(api[_-]?key|apikey|secret|passwd|password|token|access[_-]?key|"
    r"private[_-]?key|client[_-]?secret|auth[_-]?token)\b\s*[:=]\s*"
    r"[\"\']([^\"\'\n]{16,96})[\"\']"
)
HOME_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9_:/\\])(?:[A-Za-z]:[\\/]Users[\\/][^\\/\s\"\'<>|]+"
    r"|[\\/]home[\\/][^\\/\s\"\'<>|]+)"
)
PLACEHOLDER_RE = re.compile(
    r"(?i)(changeme|change[_-]me|placeholder|example|sample|dummy|redacted|"
    r"your[_-]|<[^>\n]{1,40}>|\$\{[^}\n]{1,60}\}|%s|os\.environ|getenv|"
    r"process\.env|scandir|todo|fixme|not[_-]?a[_-]?real|abcdefgh|x{6,}|"
    r"\*{4,}|\.\.\.)"
)
# A hard-coded credential must *look* like one, not merely be long.
_ENTROPY_MIN = 3.4
# Files whose content we treat as machine-consumed (home paths there are leaks
# in an artifact, not prose in a document).
_CODEISH = (".py", ".json", ".yaml", ".yml", ".toml", ".sh", ".env", ".ini", ".cfg")


def _shannon(text):
    if not text:
        return 0.0
    counts = {}
    for ch in text:
        counts[ch] = counts.get(ch, 0) + 1
    n = len(text)
    return -sum((c / n) * math.log2(c / n) for c in counts.values())


def _looks_like_secret(value):
    """True when a quoted value is credential-shaped, not prose or a placeholder."""
    if PLACEHOLDER_RE.search(value):
        return False
    if len(value) < 16:
        return False
    if _shannon(value) < _ENTROPY_MIN:
        return False
    return value.count(" ") < 3      # a credential is not a sentence


def scan_text(rel, text):
    """Findings for one blob as human-readable strings (empty == clean).

    rel is a repo-relative POSIX path; text is the decoded blob content.
    """
    findings = []
    name = PurePosixPath(rel).name
    if SECRET_FILE_RE.search("/" + rel) or SECRET_EXT_RE.search(name):
        findings.append("secret-bearing file path: " + rel)
    codeish = rel.endswith(_CODEISH)
    for i, line in enumerate(text.splitlines(), 1):
        if PRIVATE_KEY_RE.search(line):
            findings.append("%s:%d: private key material" % (rel, i))
        if AWS_KEY_ID_RE.search(line):
            findings.append("%s:%d: AWS access key id" % (rel, i))
        m = GENERIC_SECRET_RE.search(line)
        if m and _looks_like_secret(m.group(2)):
            findings.append("%s:%d: hard-coded credential (%s)" % (rel, i, m.group(1)))
        if codeish:
            for hm in HOME_PATH_RE.finditer(line):
                findings.append("%s:%d: home directory path %s" % (rel, i, hm.group(0)))
    return findings


def mine(text):
    """True when *text* contains any secret we would refuse to ship."""
    return bool(scan_text("probe.txt", text))
