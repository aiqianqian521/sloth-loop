"""Import helper for scripts executed from arbitrary working directories."""

from pathlib import Path
import sys


def ensure_engine_imports() -> None:
    engine = Path(__file__).resolve().parents[1] / "sloth_engine"
    if str(engine) not in sys.path:
        sys.path.insert(0, str(engine))
