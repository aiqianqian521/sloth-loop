"""
Loop 自进化编排引擎 - 记忆持久层 (Memory Persistence Dimension)

这是 Loop 三维度中「记忆持久化」的实现。
- 后端: SQLite（结构化查询、去重、频次统计，比 YAML 更适合模式累积）
- 兼容: 提供 YAML 导入/导出，与现有`<KB_ROOT>/失败信号模式库.md` / `成功信号模式库.md` 互通
- 说明: 与外部任务工具加载能力有重叠，MVP 阶段各自独立；
        待流程跑通后合并为单一 PatternStore 被两边复用（见 README 技术债章节）

MVP 范围:
  ✅ SQLite 建表、增删查、频次统计、YAML 双向同步
  ✅ check_exclusion 匹配逻辑（复用外部任务工具的思路，本地化）
  ⏳ 向量检索（模式量 > 500 再做）
"""

import json
import re
import sqlite3
import time
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Any

from memory_store_abc import BasePatternStore, FAILURE_MODES, SUCCESS_MODES
from migrations import MIGRATIONS, MigrationRunner
from pattern_store_io import PatternStoreIO  # H1-P1: JSON 互通 mixin
from pattern_store_queue import PatternStoreQueue  # H1-P1c: 问题队列 mixin
from pattern_store_exclusion import PatternStoreExclusion  # H1-P1d: 排除检查 mixin
from pattern_store_checkpoint import PatternStoreCheckpoint  # H1-P1e: checkpoint/resume mixin
from pattern_store_l2 import PatternStoreL2  # H1-P1f: L2 analysis mixin
from pattern_store_corrections import PatternStoreCorrections  # H1-P1g: corrections mixin
from pattern_store_classify import PatternStoreClassify  # H1-P1h: classify statics mixin



class _ManagedConnection(sqlite3.Connection):
    """Connection whose context-manager exit also releases the file handle.

    ``sqlite3.Connection.__exit__`` commits or rolls back but deliberately
    leaves the connection open.  PatternStore uses short-lived connections;
    closing at the boundary prevents leaked locks, especially on Windows.
    """

    def __exit__(self, exc_type, exc, tb):
        if getattr(self, "_tx_bound", False):
            # Bound to an outer store.transaction(): the outer context owns
            # the commit/rollback/close boundary. Suppress sqlite3's implicit
            # commit/close so public helpers (append_failure, bump_failure,
            # log_round, ...) called inside ``with store.transaction():`` share
            # one atomic unit instead of committing each statement on its own.
            # Inner exceptions propagate to the outer rollback.
            return False
        try:
            return super().__exit__(exc_type, exc, tb)
        finally:
            self.close()




def _acquire_immediate(conn, *, attempts: int = 6, base_delay: float = 0.1) -> None:
    """Acquire the writer lock with app-level retry beyond sqlite busy_timeout.

    SQLITE_BUSY database-is-locked can still surface after busy_timeout when the
    OS scheduler starves the waiting writer under heavy subprocess-suite load
    (W1-STORE-01). Retry BEGIN IMMEDIATE with backoff so concurrent writers
    serialize instead of raising; non-lock errors propagate at once. A failed
    BEGIN leaves no transaction open, so retry is safe.
    """
    delay = base_delay
    for attempt in range(attempts):
        try:
            conn.execute("BEGIN IMMEDIATE")
            return
        except sqlite3.OperationalError as exc:
            if "locked" not in str(exc).lower() or attempt == attempts - 1:
                raise
        time.sleep(delay)
        delay = min(delay * 2, 3.2)


class CorruptDatabaseError(RuntimeError):
    """Raised when the SQLite pattern store file is not a valid database.

    Fails closed with an actionable, file-scoped message instead of leaking
    a bare ``sqlite3.DatabaseError: file is not a database`` from deep inside
    the migration/PRAGMA path. Carries ``path`` and ``hint`` so callers and
    operators can act (backup/restore, delete-and-rebuild) without guesswork.
    """

    def __init__(self, path, *, detail: str = "") -> None:
        self.path = str(path)
        self.hint = (
            "The store file exists but is not a readable SQLite database. "
            "Restore from a verified backup, or move the file aside and let "
            "the store rebuild an empty database."
        )
        super().__init__(
            f"corrupt pattern store at {self.path}: not a valid SQLite "
            f"database{' (' + detail + ')' if detail else ''}. {self.hint}")


class PatternStore(PatternStoreQueue, PatternStoreIO, PatternStoreExclusion, PatternStoreCheckpoint, PatternStoreL2, PatternStoreCorrections, PatternStoreClassify, BasePatternStore):
    """模式库存储 — SQLite 后端（默认）。"""

    def __init__(self, db_path: str | Path, *, auto_migrate: bool = False):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        # W1-STORE-01 R1: write connection bound during transaction() so a full
        # OODA Learn unit (multi-table writes across append_failure / bump_failure
        # / log_round / problem_queue / L2) commits as one atomic statement.
        self._tx_conn: "sqlite3.Connection | None" = None
        self.migrations = MigrationRunner(self.db_path, MIGRATIONS)
        existed = self.db_path.exists() and self.db_path.stat().st_size > 0
        # P1-3: a truncated/garbage file makes SQLite raise a bare
        # ``sqlite3.DatabaseError: file is not a database`` from inside the
        # PRAGMA/migration path. Fail closed with a file-scoped, actionable
        # error instead of leaking the raw stack to the operator.
        try:
            current = self.migrations.inspect_current_version() if existed else 0
            target = max(item.version for item in MIGRATIONS)
            if not existed:
                self.migrations.apply()
            elif current < target:
                if not auto_migrate:
                    # A *racing* process creates the file before it commits the
                    # ledger, so a brand-new DB can briefly read v0/v2/v3.  Wait
                    # it out before failing closed (D-C1, 2026-10-25: 3 of 4
                    # concurrent runs died with a bogus "migration required").
                    current = self._converge_after_concurrent_init(current, target)
                if current >= target:
                    self.migrations.apply(target_version=current)
                elif auto_migrate:
                    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
                    backup = self.db_path.with_name(
                        f"{self.db_path.name}.pre-v{target}-{stamp}.bak")
                    self.migrations.apply_with_backup(backup)
                else:
                    raise RuntimeError(
                        f"database migration required: v{current} -> v{target}; "
                        "run the explicit migration command with a verified backup")
            else:
                # No schema write occurs; apply only validates immutable checksums.
                self.migrations.apply(target_version=current)
        except sqlite3.DatabaseError as exc:
            raise CorruptDatabaseError(self.db_path, detail=str(exc)) from exc

    #: Grace window for a concurrent first-init to finish committing the ledger.
    _FIRST_INIT_GRACE_SECONDS = 5.0

    def _converge_after_concurrent_init(self, current: int, target: int) -> int:
        """Wait out a concurrent first-init instead of mis-reporting it.

        ``db_path.exists() and size > 0`` becomes true the instant a racing
        process creates the SQLite file -- *before* the schema ledger is
        committed.  An observer then reads v0/v2/v3 and, with
        ``auto_migrate=False``, used to fail closed with "database migration
        required ... run the explicit migration command", i.e. a brand-new DB
        was reported as a legacy one (D-C1).

        A genuinely legacy DB never converges, and an old file is not waited on
        at all, so the fail-closed contract is preserved.
        """
        if current >= target:
            return current
        try:
            age = time.time() - self.db_path.stat().st_mtime
        except OSError:
            return current
        if age > self._FIRST_INIT_GRACE_SECONDS:
            return current  # old file: genuinely legacy, fail fast
        deadline = time.time() + self._FIRST_INIT_GRACE_SECONDS
        while time.time() < deadline:
            time.sleep(0.05)
            try:
                seen = self.migrations.inspect_current_version()
            except sqlite3.DatabaseError:
                continue
            if seen > current:
                current = seen
            if current >= target:
                break
        return current

    def _connect(self) -> sqlite3.Connection:
        """Open a configured connection for this process/thread.

        W1 keeps connection policy in one seam so later callers cannot
        accidentally omit WAL, foreign-key enforcement, or lock backoff.

        When a ``transaction()`` is active, the bound connection is reused so
        public helpers (append_failure, bump_failure, log_round, ...) called
        inside ``with store.transaction():`` participate in the same atomic
        write unit instead of opening independent connections.
        """
        bound = self._tx_conn
        if bound is not None:
            return bound
        conn = sqlite3.connect(str(self.db_path), timeout=30, factory=_ManagedConnection)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    @contextmanager
    def transaction(self):
        """Yield one write connection; multi-method writes join one atom.

        Public helpers used by Learn (``append_failure``/``bump_failure``/
        ``log_round``/problem_queue/L2) reuse the bound connection returned by
        ``_connect()`` while a transaction is active, so the entire round is
        committed or rolled back as a single unit.

        ``BEGIN IMMEDIATE`` reserves the writer slot early, making lock
        failures deterministic and enabling the whole unit to roll back.
        Nested ``transaction()`` calls reuse the active connection and let the
        outermost scope own commit/rollback/close.
        """
        existing = self._tx_conn
        if existing is not None:
            yield existing
            return
        conn = self._connect()
        try:
            _acquire_immediate(conn)
            conn._tx_bound = True
            self._tx_conn = conn
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn._tx_bound = False
            self._tx_conn = None
            conn.close()

    def _init_db(self):
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS failure_patterns (
                    id TEXT PRIMARY KEY,
                    date TEXT,
                    signal_pattern TEXT,
                    market_condition TEXT,
                    failure_mode TEXT,
                    impact_trades INTEGER DEFAULT 0,
                    impact_win_rate TEXT,
                    impact_total_pnl TEXT,
                    root_cause TEXT,
                    solution TEXT,
                    verification TEXT,
                    status TEXT,
                    exclusion_rule TEXT,
                    rule_type TEXT DEFAULT 'signal',  -- v2.1: 'signal' | 'methodology' | 'scene'
                    -- Phase 0: 通用字段
                    task_type TEXT DEFAULT 'backtest',
                    error_signature TEXT,
                    error_params TEXT,
                    fix_recipe TEXT,
                    fix_confidence REAL DEFAULT 0.0
                );
                CREATE TABLE IF NOT EXISTS success_patterns (
                    id TEXT PRIMARY KEY,
                    date TEXT,
                    signal_pattern TEXT,
                    market_condition TEXT,
                    entry TEXT,
                    stop_loss TEXT,
                    take_profit TEXT,
                    position_size TEXT,
                    quarters_tested INTEGER DEFAULT 0,
                    quarters_positive INTEGER DEFAULT 0,
                    avg_sharpe REAL DEFAULT 0,
                    avg_annual_excess TEXT,
                    status TEXT,
                    reuse_rule TEXT
                );
                CREATE TABLE IF NOT EXISTS rounds (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts TEXT,
                    input_count INTEGER,
                    excluded_count INTEGER,
                    passed_count INTEGER,
                    new_failures INTEGER,
                    new_successes INTEGER,
                    notes TEXT,
                    status TEXT DEFAULT 'success'
                );
                CREATE TABLE IF NOT EXISTS problem_queue (
                    id TEXT PRIMARY KEY,
                    type TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    source TEXT,
                    round INTEGER,
                    context TEXT,
                    evidence TEXT,
                    suggested_action TEXT,
                    status TEXT DEFAULT 'queued',
                    created_at TEXT,
                    resolved_at TEXT,
                    -- L2: 跨轮追踪字段
                    error_signature TEXT,
                    recurrence_count INTEGER DEFAULT 1,
                    l1_attempts TEXT,
                    task_step TEXT,
                    expected_behavior TEXT,
                    env_snapshot TEXT
                );
                CREATE TABLE IF NOT EXISTS run_history (
                    id TEXT PRIMARY KEY,
                    task TEXT,
                    total_rounds INTEGER,
                    elapsed_seconds REAL,
                    stop_reason TEXT,
                    new_failures INTEGER,
                    new_successes INTEGER,
                    active_rules INTEGER DEFAULT 0,
                    problems_queued INTEGER DEFAULT 0,
                    verdict TEXT,
                    created_at TEXT,
                    l2_health_score REAL DEFAULT 0,
                    l2_trigger_type TEXT,
                    problem_summary TEXT,
                    decision_context TEXT
                );
                -- Phase 0: 矫正规则持久化 (替代 playbook.json 运行时存储)
                CREATE TABLE IF NOT EXISTS corrections (
                    id TEXT PRIMARY KEY,
                    task_type TEXT NOT NULL DEFAULT '*',
                    severity TEXT NOT NULL DEFAULT 'warn',
                    trigger_signature TEXT NOT NULL,
                    condition_params TEXT,
                    action_type TEXT NOT NULL DEFAULT 'suggest',
                    fix_template TEXT,
                    source_problem_id TEXT,
                    created_at TEXT,
                    last_hit_at TEXT,
                    hit_count INTEGER DEFAULT 0,
                    confidence REAL DEFAULT 0.0,
                    status TEXT DEFAULT 'active'
                );
                -- L2: 健康评分快照
                CREATE TABLE IF NOT EXISTS l2_analysis (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts TEXT,
                    trigger_type TEXT,
                    health_score REAL,
                    progress_speed REAL,
                    error_recurrence REAL,
                    fix_effectiveness REAL,
                    pattern_diversity REAL,
                    stop_signal TEXT,
                    summary TEXT
                );
                -- L2: 改进建议队列
                CREATE TABLE IF NOT EXISTS l2_suggestions (
                    id TEXT PRIMARY KEY,
                    analysis_id INTEGER,
                    category TEXT,
                    priority TEXT,
                    suggestion TEXT,
                    auto_applicable INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'pending',
                    created_at TEXT,
                    applied_at TEXT
                );
                """
            )
            # 任务会话表：存储用户输入→理解→执行→校验的完整链路
            conn.execute("""
                CREATE TABLE IF NOT EXISTS task_sessions (
                    id TEXT PRIMARY KEY,
                    task_name TEXT NOT NULL,
                    status TEXT DEFAULT 'pending',  -- pending|confirmed|running|done|blocked
                    user_input TEXT,                 -- 原始任务描述
                    understanding TEXT,              -- 5W1H 理解结果
                    signals_count INTEGER DEFAULT 0,
                    verification_cfg TEXT,           -- verification 配置 JSON
                    created_at TEXT,
                    confirmed_at TEXT,
                    started_at TEXT,
                    finished_at TEXT,
                    total_rounds INTEGER DEFAULT 0,
                    success_count INTEGER DEFAULT 0,
                    failure_count INTEGER DEFAULT 0,
                    stop_reason TEXT,
                    defect_report_path TEXT
                )
            """)
            # W1 checkpoint state: one durable row per resumable run.
            conn.execute("""
                CREATE TABLE IF NOT EXISTS run_checkpoints (
                    run_id TEXT PRIMARY KEY,
                    task_name TEXT NOT NULL,
                    round INTEGER DEFAULT 0,
                    step TEXT DEFAULT '',
                    attempt INTEGER DEFAULT 0,
                    signal_cursor INTEGER DEFAULT 0,
                    pool_hash TEXT DEFAULT '',
                    config_hash TEXT DEFAULT '',
                    last_event_seq INTEGER DEFAULT 0,
                    consecutive_failures INTEGER DEFAULT 0,
                    payload TEXT DEFAULT '{}',
                    updated_at TEXT NOT NULL
                )
            """)
        self._migrate()

    def _migrate(self):
        """轻量迁移：给老库补列。OODA R4 新增 occurrences/last_seen；Phase 0 新增通用字段 + corrections 表。"""
        wanted = {
            "failure_patterns": [("occurrences", "INTEGER DEFAULT 1"),
                                 ("last_seen", "TEXT"),
                                 ("task_type", "TEXT DEFAULT 'backtest'"),
                                 ("error_signature", "TEXT"),
                                 ("error_params", "TEXT"),
                                 ("fix_recipe", "TEXT"),
                                 ("fix_confidence", "REAL DEFAULT 0.0"),
                                 ("rule_type", "TEXT DEFAULT 'signal'")],
            "success_patterns": [("occurrences", "INTEGER DEFAULT 1"),
                                 ("last_seen", "TEXT")],
            "problem_queue": [("error_signature", "TEXT"),
                              ("recurrence_count", "INTEGER DEFAULT 1"),
                              ("l1_attempts", "TEXT"),
                              ("task_step", "TEXT"),
                              ("expected_behavior", "TEXT"),
                              ("env_snapshot", "TEXT")],
            "rounds": [("status", "TEXT DEFAULT 'success'")],
            "run_history": [("l2_health_score", "REAL DEFAULT 0"),
                            ("l2_trigger_type", "TEXT"),
                            ("problem_summary", "TEXT"),
                            ("decision_context", "TEXT")],
            "schema_versions": [("checksum", "TEXT"),
                                 ("status", "TEXT DEFAULT 'applied'")],
        }
        with self._connect() as conn:
            # Create the migration ledger before inspecting its optional
            # columns so a brand-new database can pass through the same path
            # as an upgraded legacy database.
            conn.execute("""
                CREATE TABLE IF NOT EXISTS schema_versions (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL,
                    description TEXT DEFAULT '',
                    checksum TEXT DEFAULT '',
                    status TEXT DEFAULT 'applied'
                )
            """)
            for table, cols in wanted.items():
                existing = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
                for name, decl in cols:
                    if name not in existing:
                        conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")
            # Phase 0: corrections 表 (IF NOT EXISTS 保证幂等)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS corrections (
                    id TEXT PRIMARY KEY,
                    task_type TEXT NOT NULL DEFAULT '*',
                    severity TEXT NOT NULL DEFAULT 'warn',
                    trigger_signature TEXT NOT NULL,
                    condition_params TEXT,
                    action_type TEXT NOT NULL DEFAULT 'suggest',
                    fix_template TEXT,
                    source_problem_id TEXT,
                    created_at TEXT,
                    last_hit_at TEXT,
                    hit_count INTEGER DEFAULT 0,
                    confidence REAL DEFAULT 0.0,
                    status TEXT DEFAULT 'active'
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS schema_versions (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL,
                    description TEXT DEFAULT '',
                    checksum TEXT DEFAULT '',
                    status TEXT DEFAULT 'applied'
                )
            """)
            checksum = self._schema_checksum(conn)
            conn.execute(
                """INSERT OR IGNORE INTO schema_versions
                   (version, applied_at, description, checksum, status)
                   VALUES (?, ?, ?, ?, ?)""",
                (1, datetime.now().isoformat(),
                 "baseline schema", checksum, "applied"))
            conn.execute(
                """INSERT OR IGNORE INTO schema_versions
                   (version, applied_at, description, checksum, status)
                   VALUES (?, ?, ?, ?, ?)""",
                (2, datetime.now().isoformat(),
                 "W1 checkpoints + connection policy", checksum, "applied"))

    @staticmethod
    def _schema_checksum(conn: sqlite3.Connection) -> str:
        rows = conn.execute(
            """SELECT type, name, COALESCE(sql, '') FROM sqlite_master
               WHERE type IN ('table', 'index') AND name NOT LIKE 'sqlite_%'
               ORDER BY type, name"""
        ).fetchall()
        payload = json.dumps([list(r) for r in rows], ensure_ascii=False)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def schema_version(self) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COALESCE(MAX(version), 0) FROM schema_versions "
                "WHERE status='applied'"
            ).fetchone()
        return int(row[0] if row else 0)

    # ---------- 方法级经验复用 (v2.1 增强-P2) ----------

    def get_methodology_rules(self) -> list[dict]:
        """获取活跃的方法级规则（rule_type='methodology'）。"""
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """SELECT * FROM failure_patterns
                   WHERE rule_type='methodology'
                   AND status IN ('resolved','monitoring')
                   AND exclusion_rule IS NOT NULL"""
            ).fetchall()
        return [dict(r) for r in rows]

    def check_methodology(self, task_context: dict | None = None) -> dict:
        """检查当前测试方法是否违反已知的方法级规则。

        task_context: {"windows": int, "param_values": int, "scenario": str, ...}
        返回: {"passed": bool, "violations": [{"rule": str, "reason": str}]}
        """
        rules = self.get_methodology_rules()
        ctx = task_context or {}
        violations = []
        for r in rules:
            er = r.get("exclusion_rule", "")
            if not er:
                continue
            reason = r.get("root_cause", "")
            # 方法级规则匹配：检查 exclusion_rule 中的关键词
            # v2.1 增强-P2: PM 知识库规则关键词映射
            if "single_window" in er or "windows_tested" in er:
                if ctx.get("windows", 0) < 5:
                    violations.append({"rule": er, "reason": reason or "需要五窗口全量验证"})
            if "no_param_scan" in er or "param_scan" in er:
                if ctx.get("param_values", 0) < 3:
                    violations.append({"rule": er, "reason": reason or "需要参数扫描（≥3个值）"})
            if "cross_window_std" in er:
                actual_std = ctx.get("cross_window_std")
                if actual_std is not None and actual_std >= 10:
                    violations.append({"rule": er, "reason": reason or f"跨窗口std={actual_std}pp>=10pp，结论不可信"})
            if "mixed_scenarios" in er:
                if ctx.get("scenario") == "all":
                    violations.append({"rule": er, "reason": reason or "需要按场景分离测试"})
            if "no_posthoc" in er or "post_hoc" in er:
                if ctx.get("posthoc"):
                    violations.append({"rule": er, "reason": reason or "禁止事后补记录"})
        return {"passed": len(violations) == 0, "violations": violations}

    # ---------- 场景级规则 (v2.1 增强-P2) ----------

    def get_scene_rules(self) -> list[dict]:
        """获取场景绑定规则（rule_type='scene'）。"""
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """SELECT * FROM failure_patterns
                   WHERE rule_type='scene'
                   AND status IN ('resolved','monitoring')
                   AND exclusion_rule IS NOT NULL"""
            ).fetchall()
        return [dict(r) for r in rows]

    def check_scene_rules(self, scenario: str, filter_name: str = "") -> dict:
        """检查给定场景下某个 Filter 是否已知无效。

        例如: scenario="ranging", filter_name="Fib" → 检查是否有
        scene:fib_in_ranging 规则。

        返回: {"applicable": bool, "warnings": [str]}
        """
        # 中英文场景映射
        SCENE_MAP = {
            "震荡": "ranging", "趋势": "trend", "逆势": "counter",
            "极端": "extreme", "ranging": "ranging", "trend": "trend",
            "counter": "counter", "extreme": "extreme",
        }
        rules = self.get_scene_rules()
        warnings = []
        scene_key = SCENE_MAP.get(scenario, scenario.lower())
        filter_lower = filter_name.lower()
        for r in rules:
            er = r.get("exclusion_rule", "")
            if scene_key in er and (not filter_lower or filter_lower in er):
                warnings.append(r.get("root_cause", f"{filter_name} 在 {scenario} 场景下已知无效"))
        return {"applicable": len(warnings) > 0, "warnings": warnings}

    # ---------- ID 分配 (OODA R3) ----------

    def next_id(self, kind: str, day: str | None = None) -> str:
        """分配不冲突的模式 ID。

        原实现用 `len(new_failures)+1` 计数，同一天第二轮又会从 001 开始，
        配合 INSERT OR REPLACE 会静默覆盖前一轮的记录 —— 数据直接丢失。
        改为扫描库内当天最大序号 +1。
        """
        kind = kind.upper()
        table = "failure_patterns" if kind == "F" else "success_patterns"
        day = day or date.today().strftime("%Y%m%d")
        prefix = f"{kind}-{day}-"
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT id FROM {table} WHERE id LIKE ?", (prefix + "%",)
            ).fetchall()
        mx = 0
        for (rid,) in rows:
            tail = str(rid).rsplit("-", 1)[-1]
            if tail.isdigit():
                mx = max(mx, int(tail))
        return f"{prefix}{mx + 1:03d}"

    # ---------- 去重 (OODA R4) ----------

    def find_failure(self, signal_pattern: str, market_condition: str,
                     failure_mode: str | None = None) -> dict | None:
        """按「信号模式+市场条件+失败模式」三元组找已有记录。failure_mode=None 忽略。"""
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            if failure_mode:
                row = conn.execute(
                    """SELECT * FROM failure_patterns
                       WHERE signal_pattern=? AND market_condition=? AND failure_mode=?
                       LIMIT 1""",
                    (signal_pattern, market_condition, failure_mode),
                ).fetchone()
            else:
                row = conn.execute(
                    """SELECT * FROM failure_patterns
                       WHERE signal_pattern=? AND market_condition=?
                       LIMIT 1""",
                    (signal_pattern, market_condition),
                ).fetchone()
        return dict(row) if row else None

    def find_success(self, signal_pattern: str, market_condition: str) -> dict | None:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """SELECT * FROM success_patterns
                   WHERE signal_pattern=? AND market_condition=? LIMIT 1""",
                (signal_pattern, market_condition),
            ).fetchone()
        return dict(row) if row else None

    def bump_failure(self, pid: str, extra_trades: int = 1):
        """已知失败再次出现：累加计数，不新建记录。"""
        with self.transaction() as conn:
            conn.execute(
                """UPDATE failure_patterns
                   SET impact_trades = COALESCE(impact_trades,0) + ?,
                       occurrences = COALESCE(occurrences,1) + 1,
                       last_seen = ?
                   WHERE id = ?""",
                (extra_trades, datetime.now().isoformat(), pid),
            )

    def bump_success(self, pid: str, quarters: int = 1):
        """已知成功再次验证：累加季度数，达到阈值可升级 confirmed。"""
        with self._connect() as conn:
            conn.execute(
                """UPDATE success_patterns
                   SET occurrences = COALESCE(occurrences,1) + 1,
                       quarters_tested = COALESCE(quarters_tested,0) + ?,
                       quarters_positive = COALESCE(quarters_positive,0) + ?,
                       last_seen = ?
                   WHERE id = ?""",
                (quarters, quarters, datetime.now().isoformat(), pid),
            )

    def update_success_status(self, pid: str, status: str, reuse_rule: str | None = None):
        with self._connect() as conn:
            if reuse_rule is not None:
                conn.execute(
                    "UPDATE success_patterns SET status=?, reuse_rule=? WHERE id=?",
                    (status, reuse_rule, pid))
            else:
                conn.execute("UPDATE success_patterns SET status=? WHERE id=?",
                             (status, pid))

    # ---------- 写入 ----------

    def append_failure(self, patterns: list[dict]):
        with self._connect() as conn:
            for p in patterns:
                conn.execute(
                    """INSERT OR REPLACE INTO failure_patterns
                       (id,date,signal_pattern,market_condition,failure_mode,
                        impact_trades,impact_win_rate,impact_total_pnl,root_cause,
                        solution,verification,status,exclusion_rule,
                        task_type,error_signature,error_params,fix_recipe,fix_confidence,rule_type)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        p["id"], p.get("date"), p.get("signal_pattern"),
                        p.get("market_condition"), p.get("failure_mode"),
                        p.get("impact", {}).get("trades", 0),
                        p.get("impact", {}).get("win_rate"),
                        p.get("impact", {}).get("total_pnl"),
                        p.get("root_cause"), p.get("solution"),
                        p.get("verification"), p.get("status"),
                        p.get("exclusion_rule"),
                        p.get("task_type", "backtest"),
                        p.get("error_signature"),
                        p.get("error_params"),
                        p.get("fix_recipe"),
                        p.get("fix_confidence", 0.0),
                        p.get("rule_type", "signal"),
                    ),
                )

    def append_success(self, patterns: list[dict]):
        with self._connect() as conn:
            for p in patterns:
                params = p.get("parameters", {})
                perf = p.get("performance", {})
                conn.execute(
                    """INSERT OR REPLACE INTO success_patterns
                       (id,date,signal_pattern,market_condition,entry,stop_loss,
                        take_profit,position_size,quarters_tested,quarters_positive,
                        avg_sharpe,avg_annual_excess,status,reuse_rule)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        p["id"], p.get("date"), p.get("signal_pattern"),
                        p.get("market_condition"), params.get("entry"),
                        params.get("stop_loss"), params.get("take_profit"),
                        params.get("position_size"),
                        perf.get("quarters_tested", 0),
                        perf.get("quarters_positive", 0),
                        perf.get("avg_sharpe", 0),
                        perf.get("avg_annual_excess"),
                        p.get("status"), p.get("reuse_rule"),
                    ),
                )

    def update_failure_impact(self, pid: str, trades: int, pnl_pct: float):
        with self._connect() as conn:
            conn.execute(
                "UPDATE failure_patterns SET impact_trades = impact_trades + ? WHERE id = ?",
                (trades, pid),
            )

    def update_failure_status(self, pid: str, status: str, exclusion_rule: str | None = None):
        """人工审核升级（缺口2）：open → resolved 并生成排除规则。"""
        with self._connect() as conn:
            if exclusion_rule is not None:
                conn.execute(
                    "UPDATE failure_patterns SET status = ?, exclusion_rule = ? WHERE id = ?",
                    (status, exclusion_rule, pid),
                )
            else:
                conn.execute(
                    "UPDATE failure_patterns SET status = ? WHERE id = ?",
                    (status, pid),
                )

    def log_round(self, input_count, excluded_count, passed_count,
                  new_failures, new_successes, notes="", status="success"):
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO rounds (ts,input_count,excluded_count,passed_count,
                       new_failures,new_successes,notes,status)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (datetime.now().isoformat(), input_count, excluded_count,
                 passed_count, new_failures, new_successes, notes, status),
            )

    # ---------- 读取 ----------

    def load_failure_patterns(self) -> list[dict]:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM failure_patterns").fetchall()
        return [dict(r) for r in rows]

    def load_success_patterns(self) -> list[dict]:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM success_patterns").fetchall()
        return [dict(r) for r in rows]

    def get_active_exclusion_rules(self) -> list[dict]:
        """status=resolved/monitoring 的规则才参与排除。"""
        fs = self.load_failure_patterns()
        return [f for f in fs if f.get("status") in ("resolved", "monitoring")
                and f.get("exclusion_rule")]

    def get_rounds(self) -> list[dict]:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM rounds ORDER BY id").fetchall()
        return [dict(r) for r in rows]

    # ---------- 核心: 排除检查 ----------


    # ---------- 元循环频次统计 ----------

    def failure_mode_frequency(self) -> dict:
        fs = self.load_failure_patterns()
        freq = {}
        for f in fs:
            m = f.get("failure_mode", "UNKNOWN")
            freq[m] = freq.get(m, 0) + 1
        return freq


    # ---------- YAML 互通 ----------



    # ── P0 问题队列 ──────────────────────────────────────────────


    def save_run_history(self, summary: dict):
        """Save a completed run to run_history table."""
        with self._connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO run_history
                   (id, task, total_rounds, elapsed_seconds, stop_reason,
                    new_failures, new_successes, active_rules, problems_queued,
                    verdict, created_at, l2_health_score, l2_trigger_type,
                    problem_summary, decision_context)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (summary["run_id"], summary.get("task", ""),
                 summary.get("total_rounds", 0),
                 summary.get("elapsed_seconds", 0),
                 summary.get("stop_reason", ""),
                 summary.get("new_failures", 0),
                 summary.get("new_successes", 0),
                 summary.get("active_exclusion_rules", 0),
                 summary.get("problem_queue_total", 0),
                 summary.get("verdict", "OK"),
                 summary.get("created_at", datetime.now().isoformat()),
                 summary.get("l2_health_score", 0),
                 summary.get("l2_trigger_type", ""),
                 summary.get("problem_summary", ""),
                 summary.get("decision_context", "")))

    def get_run_history(self, limit: int = 20) -> list[dict]:
        """Get recent run history entries."""
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM run_history ORDER BY created_at DESC LIMIT ?",
                (limit,)).fetchall()
        return [dict(r) for r in rows]
