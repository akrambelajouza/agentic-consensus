"""SQLite persistence for completed runs and architecture experiments.

Only the web UI writes here (``web.py`` calls ``save_run`` once a graph completes);
the CLI and Studio are unaffected. Every function opens its own
short-lived connection rather than sharing one across threads — the web worker
thread writes while request handlers read concurrently, and stdlib ``sqlite3``
connections aren't safe to share across threads by default. SQLite's own
file-level locking handles the rest; this is a local, single-user tool, so no
connection pool is warranted.

The ``runs`` table splits cheap summary columns (for the history datatable) from
``state_json`` (the full run — proposals, reviews, usage, timings — parsed back out
only when a single run is opened for replay). Total provider-reported cost is also a
summary column so History can compare runs without loading every state blob. Nothing
about a run is dropped: it is simply not normalized into per-round columns.
"""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from typing import Any

from . import config
from .variants.registry import DEFAULT_VARIANT

_SCHEMA = """
CREATE TABLE IF NOT EXISTS experiments (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at         TEXT NOT NULL,
    completed_at       TEXT,
    problem            TEXT NOT NULL,
    experiment_type    TEXT NOT NULL DEFAULT 'architecture_comparison',
    status             TEXT NOT NULL DEFAULT 'running',
    evaluation_status  TEXT NOT NULL DEFAULT 'not_evaluated',
    max_rounds         INTEGER NOT NULL,
    config_json        TEXT NOT NULL,
    evaluation_criteria_json TEXT,
    evaluation_config_json TEXT
);
CREATE TABLE IF NOT EXISTS runs (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at       TEXT NOT NULL,
    variant          TEXT NOT NULL DEFAULT 'v1-posthoc-reviewer',
    variant_version  INTEGER NOT NULL DEFAULT 1,
    problem          TEXT NOT NULL,
    restated_problem TEXT,
    verdict          TEXT NOT NULL,
    rounds           INTEGER,
    max_rounds       INTEGER,
    last_score       INTEGER,
    total_cost       REAL,
    total_tokens     INTEGER,
    duration_ms      INTEGER,
    experiment_id    INTEGER REFERENCES experiments(id),
    config_json      TEXT,
    state_json       TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS experiment_variants (
    experiment_id  INTEGER NOT NULL REFERENCES experiments(id) ON DELETE CASCADE,
    variant        TEXT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'pending',
    error_message  TEXT,
    started_at     TEXT,
    completed_at   TEXT,
    PRIMARY KEY (experiment_id, variant)
);
CREATE TABLE IF NOT EXISTS evaluations (
    experiment_id   INTEGER NOT NULL REFERENCES experiments(id) ON DELETE CASCADE,
    variant         TEXT NOT NULL,
    run_id          INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    status          TEXT NOT NULL DEFAULT 'pending',
    result_json     TEXT,
    summary         TEXT,
    evaluator_model TEXT,
    evaluator_effort TEXT,
    usage_json      TEXT,
    total_cost      REAL,
    total_tokens    INTEGER,
    duration_ms     INTEGER,
    error_message   TEXT,
    started_at      TEXT,
    completed_at    TEXT,
    PRIMARY KEY (experiment_id, variant),
    UNIQUE (run_id)
);
CREATE TABLE IF NOT EXISTS model_catalog (
    model_id             TEXT PRIMARY KEY,
    name                 TEXT NOT NULL,
    provider             TEXT NOT NULL,
    prompt_price         TEXT,
    completion_price     TEXT,
    context_length       INTEGER,
    supported_parameters_json TEXT NOT NULL,
    popularity_rank      INTEGER NOT NULL,
    refreshed_at         TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS app_settings (
    setting_key TEXT PRIMARY KEY,
    setting_value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_runs_created_at ON runs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_experiments_created_at ON experiments(created_at DESC);
"""

_SUMMARY_COLUMNS = (
    "id",
    "created_at",
    "variant",
    "variant_version",
    "problem",
    "restated_problem",
    "verdict",
    "rounds",
    "max_rounds",
    "last_score",
    "total_cost",
    "total_tokens",
    "duration_ms",
    "experiment_id",
)


def _connect(path: str | None) -> sqlite3.Connection:
    conn = sqlite3.connect(path or config.db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(path: str | None = None) -> None:
    """Create and migrate the local schema. Safe to call on every startup."""
    with _connect(path) as conn:
        conn.executescript(_SCHEMA)
        experiment_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(experiments)")
        }
        if "evaluation_criteria_json" not in experiment_columns:
            conn.execute(
                "ALTER TABLE experiments ADD COLUMN evaluation_criteria_json TEXT"
            )
        if "evaluation_config_json" not in experiment_columns:
            conn.execute(
                "ALTER TABLE experiments ADD COLUMN evaluation_config_json TEXT"
            )
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(runs)")}
        if "total_cost" not in columns:
            conn.execute("ALTER TABLE runs ADD COLUMN total_cost REAL")
        if "duration_ms" not in columns:
            conn.execute("ALTER TABLE runs ADD COLUMN duration_ms INTEGER")
        if "variant" not in columns:
            conn.execute(
                "ALTER TABLE runs ADD COLUMN variant TEXT NOT NULL "
                "DEFAULT 'v1-posthoc-reviewer'"
            )
        if "variant_version" not in columns:
            conn.execute(
                "ALTER TABLE runs ADD COLUMN variant_version INTEGER NOT NULL DEFAULT 1"
            )
        if "total_tokens" not in columns:
            conn.execute("ALTER TABLE runs ADD COLUMN total_tokens INTEGER")
        if "experiment_id" not in columns:
            conn.execute(
                "ALTER TABLE runs ADD COLUMN experiment_id INTEGER "
                "REFERENCES experiments(id)"
            )
        if "config_json" not in columns:
            conn.execute("ALTER TABLE runs ADD COLUMN config_json TEXT")
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_runs_experiment_variant "
            "ON runs(experiment_id, variant) WHERE experiment_id IS NOT NULL"
        )
        # Older rows already contain per-node timings inside state_json. Backfill the
        # new summary column so History can show duration without requiring new runs.
        for row in conn.execute(
            "SELECT id, state_json FROM runs WHERE duration_ms IS NULL"
        ):
            try:
                timings = json.loads(row["state_json"]).get("timings") or []
                duration_ms = (
                    sum(timing["duration_ms"] for timing in timings)
                    if timings
                    and all(timing.get("duration_ms") is not None for timing in timings)
                    else None
                )
            except (json.JSONDecodeError, TypeError, KeyError):
                continue
            if duration_ms is not None:
                conn.execute(
                    "UPDATE runs SET duration_ms = ? WHERE id = ?",
                    (duration_ms, row["id"]),
                )
        for row in conn.execute(
            "SELECT id, state_json FROM runs WHERE total_tokens IS NULL"
        ):
            try:
                usage = json.loads(row["state_json"]).get("usage") or []
                tokens = [
                    item.get("total_tokens")
                    for item in usage
                    if item.get("total_tokens") is not None
                ]
                total_tokens = (
                    sum(tokens) if usage and len(tokens) == len(usage) else None
                )
            except (json.JSONDecodeError, TypeError):
                continue
            if total_tokens is not None:
                conn.execute(
                    "UPDATE runs SET total_tokens = ? WHERE id = ?",
                    (total_tokens, row["id"]),
                )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sanitize_error(error: object) -> str:
    """Make provider errors safe and compact enough to display in the browser."""
    message = " ".join(str(error).split())[:2000] or "Unknown execution error"
    message = re.sub(
        r"(?i)\b(api[_ -]?key|authorization|bearer)(\s*[:=]?\s*)\S+",
        r"\1\2[redacted]",
        message,
    )
    message = re.sub(r"\bsk-[A-Za-z0-9_-]{8,}\b", "[redacted]", message)
    return message[:1000]


def get_app_settings(*, path: str | None = None) -> dict[str, str]:
    """Return persisted application overrides as a key/value mapping."""
    with _connect(path) as conn:
        try:
            rows = conn.execute(
                "SELECT setting_key, setting_value FROM app_settings"
            ).fetchall()
        except sqlite3.OperationalError as exc:
            # CLI/library use does not initialize the web database. In that mode,
            # persisted web overrides are simply absent and environment config wins.
            if "no such table" not in str(exc).lower():
                raise
            return {}
    return {row["setting_key"]: row["setting_value"] for row in rows}


def replace_app_settings(
    values: dict[str, str | None], *, path: str | None = None
) -> None:
    """Upsert nonempty values and delete keys whose value is empty/None."""
    timestamp = _now()
    with _connect(path) as conn:
        for key, value in values.items():
            clean = value.strip() if isinstance(value, str) else None
            if clean:
                conn.execute(
                    "INSERT INTO app_settings (setting_key, setting_value, updated_at) "
                    "VALUES (?, ?, ?) ON CONFLICT(setting_key) DO UPDATE SET "
                    "setting_value=excluded.setting_value, updated_at=excluded.updated_at",
                    (key, clean, timestamp),
                )
            else:
                conn.execute("DELETE FROM app_settings WHERE setting_key=?", (key,))


def replace_model_catalog(
    models: list[dict[str, Any]], *, refreshed_at: str | None = None,
    path: str | None = None,
) -> str:
    """Atomically replace the locally saved OpenRouter catalog."""
    timestamp = refreshed_at or _now()
    with _connect(path) as conn:
        conn.execute("DELETE FROM model_catalog")
        conn.executemany(
            """INSERT INTO model_catalog
               (model_id, name, provider, prompt_price, completion_price,
                context_length, supported_parameters_json, popularity_rank,
                refreshed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [(
                item["id"], item["name"], item["provider"],
                item.get("prompt_price"), item.get("completion_price"),
                item.get("context_length"),
                json.dumps(item.get("supported_parameters") or []),
                item["popularity_rank"], timestamp,
            ) for item in models],
        )
    return timestamp


def get_model_catalog(*, path: str | None = None) -> dict[str, Any]:
    with _connect(path) as conn:
        rows = conn.execute(
            "SELECT * FROM model_catalog ORDER BY popularity_rank"
        ).fetchall()
    models = []
    for row in rows:
        item = dict(row)
        item["id"] = item.pop("model_id")
        item["supported_parameters"] = json.loads(
            item.pop("supported_parameters_json")
        )
        models.append(item)
    return {
        "models": models,
        "refreshed_at": models[0]["refreshed_at"] if models else None,
    }


def freeze_evaluation_config(
    experiment_id: int, evaluator: dict[str, Any], *, path: str | None = None
) -> dict[str, Any]:
    """Freeze the evaluator on first use and return the persisted choice."""
    with _connect(path) as conn:
        row = conn.execute(
            "SELECT status, evaluation_status, evaluation_criteria_json, "
            "evaluation_config_json FROM experiments WHERE id=?",
            (experiment_id,),
        ).fetchone()
        if row is None:
            raise ValueError("experiment not found")
        if row["status"] != "completed":
            raise ValueError("all workflow variants must complete before evaluation")
        if not row["evaluation_criteria_json"]:
            raise ValueError("experiment has no evaluation criteria")
        if row["evaluation_status"] == "evaluating":
            raise RuntimeError("evaluation is already running")
        if row["evaluation_status"] == "completed":
            raise RuntimeError("evaluation is already completed")
        if row["evaluation_config_json"]:
            return json.loads(row["evaluation_config_json"])
        conn.execute(
            "UPDATE experiments SET evaluation_config_json=? WHERE id=?",
            (json.dumps(evaluator), experiment_id),
        )
    return evaluator


def _refresh_experiment_status(
    conn: sqlite3.Connection, experiment_id: int
) -> str:
    statuses = [
        row["status"]
        for row in conn.execute(
            "SELECT status FROM experiment_variants WHERE experiment_id = ?",
            (experiment_id,),
        )
    ]
    if statuses and all(status == "completed" for status in statuses):
        status = "completed"
    elif statuses and all(status == "failed" for status in statuses):
        status = "failed"
    elif statuses and all(status in ("completed", "failed") for status in statuses):
        status = "partial"
    else:
        status = "running"
    completed_at = _now() if status in ("completed", "partial", "failed") else None
    conn.execute(
        "UPDATE experiments SET status = ?, completed_at = ? WHERE id = ?",
        (status, completed_at, experiment_id),
    )
    return status


def create_experiment(
    problem: str,
    max_rounds: int,
    config_snapshot: dict[str, Any],
    variant_ids: list[str],
    evaluation_criteria: list[dict[str, str]] | None = None,
    *,
    path: str | None = None,
) -> int:
    """Create an architecture comparison and its planned variant slots."""
    if not problem.strip():
        raise ValueError("create_experiment requires a non-empty problem")
    if not variant_ids:
        raise ValueError("create_experiment requires at least one variant")
    created_at = _now()
    with _connect(path) as conn:
        cur = conn.execute(
            """
            INSERT INTO experiments
                (created_at, problem, experiment_type, status, evaluation_status,
                 max_rounds, config_json, evaluation_criteria_json)
            VALUES (?, ?, 'architecture_comparison', 'running', 'not_evaluated', ?, ?, ?)
            """,
            (
                created_at,
                problem.strip(),
                max_rounds,
                json.dumps(config_snapshot),
                json.dumps(evaluation_criteria) if evaluation_criteria else None,
            ),
        )
        experiment_id = int(cur.lastrowid)
        conn.executemany(
            """
            INSERT INTO experiment_variants (experiment_id, variant, status)
            VALUES (?, ?, 'pending')
            """,
            [(experiment_id, variant_id) for variant_id in variant_ids],
        )
    return experiment_id


def start_experiment_variant(
    experiment_id: int,
    variant: str,
    *,
    retry: bool = False,
    path: str | None = None,
) -> bool:
    """Claim a pending slot, or a failed slot when ``retry`` is true."""
    expected = "failed" if retry else "pending"
    with _connect(path) as conn:
        cur = conn.execute(
            """
            UPDATE experiment_variants
            SET status = 'running', error_message = NULL, started_at = ?,
                completed_at = NULL
            WHERE experiment_id = ? AND variant = ? AND status = ?
            """,
            (_now(), experiment_id, variant, expected),
        )
        if cur.rowcount:
            conn.execute(
                "UPDATE experiments SET status = 'running', completed_at = NULL "
                "WHERE id = ?",
                (experiment_id,),
            )
    return bool(cur.rowcount)


def fail_experiment_variant(
    experiment_id: int,
    variant: str,
    error: str,
    *,
    path: str | None = None,
) -> str:
    """Persist a sanitized failure and return the aggregate experiment status."""
    message = sanitize_error(error)
    with _connect(path) as conn:
        cur = conn.execute(
            """
            UPDATE experiment_variants
            SET status = 'failed', error_message = ?, completed_at = ?
            WHERE experiment_id = ? AND variant = ? AND status = 'running'
            """,
            (message, _now(), experiment_id, variant),
        )
        if not cur.rowcount:
            raise ValueError("experiment variant is not running")
        return _refresh_experiment_status(conn, experiment_id)


def save_run(
    problem: str,
    state: dict[str, Any],
    *,
    experiment_id: int | None = None,
    config_snapshot: dict[str, Any] | None = None,
    path: str | None = None,
) -> int:
    """Persist a completed run. Returns the new row's id.

    ``state`` must already carry a ``verdict`` — every variant sets one only when the
    graph has finished. The web worker calls this after ``graph.stream(...)`` returns
    without raising. Raising here instead of silently writing a partial row keeps
    that guarantee from rotting silently.
    """
    if "verdict" not in state:
        raise ValueError("save_run requires a completed state (missing 'verdict')")

    reviews = state.get("reviews") or []
    last_score = reviews[-1].get("score") if reviews else None
    usage = state.get("usage") or []
    costs = [
        u.get("cost")
        for u in usage
        if u.get("cost") is not None
    ]
    total_cost = sum(costs) if usage and len(costs) == len(usage) else None
    tokens = [
        item.get("total_tokens")
        for item in usage
        if item.get("total_tokens") is not None
    ]
    total_tokens = sum(tokens) if usage and len(tokens) == len(usage) else None
    timings = state.get("timings") or []
    duration_ms = (
        sum(timing["duration_ms"] for timing in timings)
        if timings and all(timing.get("duration_ms") is not None for timing in timings)
        else None
    )
    # Python-side ISO 8601 (with offset) rather than SQLite's `datetime('now')`,
    # which emits a space-separated, offset-less string that browsers don't
    # reliably parse with `new Date(...)`.
    created_at = _now()

    with _connect(path) as conn:
        cur = conn.execute(
            """
            INSERT INTO runs
                (created_at, variant, variant_version, problem, restated_problem,
                 verdict, rounds, max_rounds, last_score, total_cost, total_tokens,
                 duration_ms, experiment_id, config_json, state_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                created_at,
                state.get("variant", DEFAULT_VARIANT),
                state.get("variant_version", 1),
                problem,
                state.get("restated_problem"),
                state["verdict"],
                state.get("round"),
                state.get("max_rounds"),
                last_score,
                total_cost,
                total_tokens,
                duration_ms,
                experiment_id,
                json.dumps(config_snapshot) if config_snapshot else None,
                json.dumps(state),
            ),
        )
        run_id = int(cur.lastrowid)
        if experiment_id is not None:
            slot = conn.execute(
                """
                UPDATE experiment_variants
                SET status = 'completed', error_message = NULL, completed_at = ?
                WHERE experiment_id = ? AND variant = ? AND status = 'running'
                """,
                (created_at, experiment_id, state.get("variant", DEFAULT_VARIANT)),
            )
            if not slot.rowcount:
                raise ValueError("experiment variant is not running")
            _refresh_experiment_status(conn, experiment_id)
        return run_id


def list_runs(*, limit: int = 200, path: str | None = None) -> list[dict[str, Any]]:
    """Summary rows for the history datatable, most recent first. No ``state_json``."""
    with _connect(path) as conn:
        rows = conn.execute(
            f"SELECT {', '.join(_SUMMARY_COLUMNS)} FROM runs ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def get_run(run_id: int, *, path: str | None = None) -> dict[str, Any] | None:
    """A single run with its full state, for replay. ``None`` if ``run_id`` is unknown."""
    with _connect(path) as conn:
        row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    if row is None:
        return None
    data = dict(row)
    raw_config = data.pop("config_json", None)
    data["config"] = json.loads(raw_config) if raw_config else None
    data["state"] = json.loads(data.pop("state_json"))
    return data


def _experiment_cost(runs: list[dict[str, Any]]) -> float | None:
    completed = [run for run in runs if run.get("id") is not None]
    if not completed or any(run.get("total_cost") is None for run in completed):
        return None
    return sum(run["total_cost"] for run in completed)


def _refresh_evaluation_status(conn: sqlite3.Connection, experiment_id: int) -> str:
    statuses = [
        row["status"]
        for row in conn.execute(
            "SELECT status FROM evaluations WHERE experiment_id = ?", (experiment_id,)
        )
    ]
    if statuses and all(status == "completed" for status in statuses):
        status = "completed"
    elif statuses and all(status == "failed" for status in statuses):
        status = "failed"
    elif statuses and all(status in ("completed", "failed") for status in statuses):
        status = "partial"
    else:
        status = "evaluating"
    conn.execute(
        "UPDATE experiments SET evaluation_status = ? WHERE id = ?",
        (status, experiment_id),
    )
    return status


def start_evaluations(
    experiment_id: int, *, path: str | None = None
) -> list[dict[str, Any]]:
    """Atomically claim missing/failed evaluations and preserve completed ones."""
    with _connect(path) as conn:
        # Serialize the status check and claim so two browser clicks cannot both
        # start paid evaluator calls for the same outputs.
        conn.execute("BEGIN IMMEDIATE")
        experiment = conn.execute(
            "SELECT status, evaluation_status, evaluation_criteria_json "
            "FROM experiments WHERE id = ?", (experiment_id,)
        ).fetchone()
        if experiment is None:
            raise LookupError(f"experiment {experiment_id} not found")
        if experiment["status"] != "completed":
            raise ValueError("all workflow variants must complete before evaluation")
        if not experiment["evaluation_criteria_json"]:
            raise ValueError("experiment has no evaluation criteria")
        if experiment["evaluation_status"] == "evaluating":
            raise RuntimeError("evaluation is already running")
        if experiment["evaluation_status"] == "completed":
            raise RuntimeError("evaluation is already completed")
        runs = conn.execute(
            "SELECT id, variant FROM runs WHERE experiment_id = ? ORDER BY variant",
            (experiment_id,),
        ).fetchall()
        for run in runs:
            conn.execute(
                "INSERT OR IGNORE INTO evaluations "
                "(experiment_id, variant, run_id, status) VALUES (?, ?, ?, 'pending')",
                (experiment_id, run["variant"], run["id"]),
            )
        claimed = [
            dict(row)
            for row in conn.execute(
                "SELECT e.variant, e.run_id, r.state_json FROM evaluations e "
                "JOIN runs r ON r.id = e.run_id "
                "WHERE e.experiment_id = ? AND e.status IN ('pending', 'failed') "
                "ORDER BY e.variant", (experiment_id,)
            )
        ]
        now = _now()
        conn.execute(
            "UPDATE evaluations SET status='running', error_message=NULL, "
            "started_at=?, completed_at=NULL WHERE experiment_id=? "
            "AND status IN ('pending', 'failed')", (now, experiment_id),
        )
        conn.execute(
            "UPDATE experiments SET evaluation_status='evaluating' WHERE id=?",
            (experiment_id,),
        )
    for item in claimed:
        state = json.loads(item.pop("state_json"))
        item["final_answer"] = state.get("final_answer") or ""
    return claimed


def save_evaluation(
    experiment_id: int,
    variant: str,
    result: dict[str, Any],
    usage: dict[str, Any],
    duration_ms: int,
    evaluator_settings: dict[str, Any],
    *,
    path: str | None = None,
) -> str:
    with _connect(path) as conn:
        cur = conn.execute(
            """UPDATE evaluations SET status='completed', result_json=?, summary=?,
               evaluator_model=?, evaluator_effort=?, usage_json=?, total_cost=?,
               total_tokens=?, duration_ms=?, error_message=NULL, completed_at=?
               WHERE experiment_id=? AND variant=? AND status='running'""",
            (
                json.dumps(result), result.get("summary"), evaluator_settings.get("model"),
                evaluator_settings.get("effort"), json.dumps(usage), usage.get("cost"),
                usage.get("total_tokens"), duration_ms, _now(), experiment_id, variant,
            ),
        )
        if not cur.rowcount:
            raise ValueError("evaluation is not running")
        return _refresh_evaluation_status(conn, experiment_id)


def fail_evaluation(
    experiment_id: int,
    variant: str,
    error: object,
    duration_ms: int | None = None,
    evaluator_settings: dict[str, Any] | None = None,
    *,
    path: str | None = None,
) -> str:
    evaluator_settings = evaluator_settings or {}
    with _connect(path) as conn:
        cur = conn.execute(
            "UPDATE evaluations SET status='failed', error_message=?, duration_ms=?, "
            "evaluator_model=?, evaluator_effort=?, completed_at=? "
            "WHERE experiment_id=? AND variant=? AND status='running'",
            (
                sanitize_error(error), duration_ms, evaluator_settings.get("model"),
                evaluator_settings.get("effort"), _now(), experiment_id, variant,
            ),
        )
        if not cur.rowcount:
            raise ValueError("evaluation is not running")
        return _refresh_evaluation_status(conn, experiment_id)


def list_experiments(
    *, limit: int = 200, path: str | None = None
) -> list[dict[str, Any]]:
    """Compact experiment summaries without loading any ``state_json`` blobs."""
    with _connect(path) as conn:
        experiments = [
            dict(row)
            for row in conn.execute(
                "SELECT * FROM experiments ORDER BY id DESC LIMIT ?", (limit,)
            )
        ]
        if not experiments:
            return []
        ids = [experiment["id"] for experiment in experiments]
        placeholders = ",".join("?" for _ in ids)
        rows = conn.execute(
            f"""
            SELECT ev.experiment_id, ev.variant, ev.status, ev.error_message,
                   r.id, r.verdict, r.rounds, r.max_rounds, r.total_cost,
                   r.total_tokens, r.duration_ms
            FROM experiment_variants ev
            LEFT JOIN runs r
              ON r.experiment_id = ev.experiment_id AND r.variant = ev.variant
            WHERE ev.experiment_id IN ({placeholders})
            ORDER BY ev.experiment_id DESC, ev.variant
            """,
            ids,
        ).fetchall()
    grouped: dict[int, list[dict[str, Any]]] = {experiment_id: [] for experiment_id in ids}
    for row in rows:
        grouped[row["experiment_id"]].append(dict(row))
    for experiment in experiments:
        experiment["variants"] = grouped[experiment["id"]]
        experiment["total_cost"] = _experiment_cost(experiment["variants"])
        experiment.pop("config_json", None)
        experiment.pop("evaluation_criteria_json", None)
        experiment.pop("evaluation_config_json", None)
    return experiments


def get_experiment(
    experiment_id: int, *, path: str | None = None
) -> dict[str, Any] | None:
    """Experiment details with compact final outputs; replay keeps the full state."""
    with _connect(path) as conn:
        row = conn.execute(
            "SELECT * FROM experiments WHERE id = ?", (experiment_id,)
        ).fetchone()
        if row is None:
            return None
        experiment = dict(row)
        variant_rows = conn.execute(
            """
            SELECT ev.variant, ev.status, ev.error_message, ev.started_at,
                   ev.completed_at, r.id, r.verdict, r.rounds, r.max_rounds,
                   r.total_cost, r.total_tokens, r.duration_ms, r.state_json
            FROM experiment_variants ev
            LEFT JOIN runs r
              ON r.experiment_id = ev.experiment_id AND r.variant = ev.variant
            WHERE ev.experiment_id = ?
            ORDER BY ev.variant
            """,
            (experiment_id,),
        ).fetchall()
        evaluation_rows = conn.execute(
            "SELECT * FROM evaluations WHERE experiment_id = ? ORDER BY variant",
            (experiment_id,),
        ).fetchall()
    variants = []
    for row in variant_rows:
        item = dict(row)
        raw_state = item.pop("state_json")
        if raw_state:
            state = json.loads(raw_state)
            item["final_answer"] = state.get("final_answer")
            item["model_calls"] = len(state.get("usage") or [])
        else:
            item["final_answer"] = None
            item["model_calls"] = None
        variants.append(item)
    experiment["config"] = json.loads(experiment.pop("config_json"))
    raw_criteria = experiment.pop("evaluation_criteria_json")
    experiment["evaluation_criteria"] = json.loads(raw_criteria) if raw_criteria else []
    raw_evaluation_config = experiment.pop("evaluation_config_json")
    experiment["evaluation_config"] = (
        json.loads(raw_evaluation_config) if raw_evaluation_config else None
    )
    experiment["variants"] = variants
    experiment["total_cost"] = _experiment_cost(variants)
    evaluations = []
    for row in evaluation_rows:
        item = dict(row)
        item["result"] = json.loads(item.pop("result_json")) if item["result_json"] else None
        item["usage"] = json.loads(item.pop("usage_json")) if item["usage_json"] else None
        evaluations.append(item)
    experiment["evaluations"] = evaluations
    return experiment
