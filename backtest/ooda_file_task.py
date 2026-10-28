#!/usr/bin/env python
"""Small deterministic task used to validate Loop's OODA file workflow.

It follows the normal backtest adapter contract, but its business action is
creating five artifacts.  The output metrics make the Verify step able to
assert the file count and manifest size without reaching into the filesystem.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()

    payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
    signals = payload.get("signals") or []
    out_path = Path(args.output)
    artifact_dir = out_path.parent / "ooda-file-artifacts"
    artifact_dir.mkdir(parents=True, exist_ok=True)

    artifacts = []
    for idx, signal in enumerate(signals[:4], 1):
        path = artifact_dir / f"ooda_{idx:02d}.md"
        path.write_text(
            f"# OODA artifact {idx}\n\n"
            f"signal: {signal.get('signal_pattern', 'unknown')}\n"
            f"market: {signal.get('market_condition', 'unknown')}\n",
            encoding="utf-8",
        )
        artifacts.append(str(path))

    manifest = artifact_dir / "manifest.json"
    manifest.write_text(json.dumps({"artifacts": artifacts}, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    artifacts.append(str(manifest))

    trades = [
        {
            "signal_pattern": s.get("signal_pattern", "unknown"),
            "market_condition": s.get("market_condition", "unknown"),
            "pnl": 1.0,
            "entry_condition": "file-task verified",
        }
        for s in signals[:4]
    ]
    result = {
        "trades": trades,
        "pnl": {"total": float(len(trades))},
        "win_rate": "100%",
        "sharpe": 1.0,
        "files_created": len(artifacts),
        "artifact_dir": str(artifact_dir),
        "manifest": str(manifest),
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"OODA file task: created {len(artifacts)} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
