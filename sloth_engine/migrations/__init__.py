"""Immutable migration registry."""
from .base import DestructiveMigrationError, Migration, MigrationDriftError, MigrationRunner
from .v001_baseline import MIGRATION as V001
from .v002_runtime_contract import MIGRATION as V002
from .v003_l2_suggestion_contract import MIGRATION as V003
from .v004_learn_idempotency_ledger import MIGRATION as V004
from .v005_idempotency_signature import MIGRATION as V005
from .v006_commit_sentinel import MIGRATION as V006

MIGRATIONS = (V001, V002, V003, V004, V005, V006)

__all__ = ["DestructiveMigrationError", "Migration", "MigrationDriftError",
           "MigrationRunner", "MIGRATIONS"]
