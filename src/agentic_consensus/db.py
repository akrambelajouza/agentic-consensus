"""Run history: SQLite persistence for completed runs.

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
import sqlite3
from datetime import datetime, timezone
from typing import Any

from . import config
from .variants.registry import DEFAULT_VARIANT

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at       TEXT NOT NULL,
    variant          TEXT NOT NULL DEFAULT 'v1-moderated-criteria',
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
    state_json       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_runs_created_at ON runs(created_at DESC);
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
)


def _connect(path: str | None) -> sqlite3.Connection:
    conn = sqlite3.connect(path or config.db_path())
    conn.row_factory = sqlite3.Row
    return conn


def init_db(path: str | None = None) -> None:
    """Create the ``runs`` table if it doesn't exist yet. Safe to call every startup."""
    with _connect(path) as conn:
        conn.executescript(_SCHEMA)
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(runs)")}
        if "total_cost" not in columns:
            conn.execute("ALTER TABLE runs ADD COLUMN total_cost REAL")
        if "duration_ms" not in columns:
            conn.execute("ALTER TABLE runs ADD COLUMN duration_ms INTEGER")
        if "variant" not in columns:
            conn.execute(
                "ALTER TABLE runs ADD COLUMN variant TEXT NOT NULL "
                "DEFAULT 'v1-moderated-criteria'"
            )
        if "variant_version" not in columns:
            conn.execute(
                "ALTER TABLE runs ADD COLUMN variant_version INTEGER NOT NULL DEFAULT 1"
            )
        if "total_tokens" not in columns:
            conn.execute("ALTER TABLE runs ADD COLUMN total_tokens INTEGER")
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


def save_run(problem: str, state: dict[str, Any], *, path: str | None = None) -> int:
    """Persist a completed run. Returns the new row's id.

    ``state`` must already carry a ``verdict`` — both variants set one only when the
    graph has finished. The web worker calls this after ``graph.stream(...)`` returns
    without raising. Raising here instead of silently writing a partial row keeps
    that guarantee from rotting silently.
    """
    if "verdict" not in state:
        raise ValueError("save_run requires a completed state (missing 'verdict')")

    reviews = state.get("reviews") or []
    last_score = reviews[-1]["score"] if reviews else None
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
    created_at = datetime.now(timezone.utc).isoformat()

    with _connect(path) as conn:
        cur = conn.execute(
            """
            INSERT INTO runs
                (created_at, variant, variant_version, problem, restated_problem,
                 verdict, rounds, max_rounds, last_score, total_cost, total_tokens,
                 duration_ms, state_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                json.dumps(state),
            ),
        )
        return int(cur.lastrowid)


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
    data["state"] = json.loads(data.pop("state_json"))
    return data
