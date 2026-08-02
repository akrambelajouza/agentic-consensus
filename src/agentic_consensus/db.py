"""Run history: SQLite persistence for completed runs.

Only the web UI writes here (``web.py`` calls ``save_run`` once a run reaches
``finalize``); the CLI and Studio are unaffected. Every function opens its own
short-lived connection rather than sharing one across threads — the web worker
thread writes while request handlers read concurrently, and stdlib ``sqlite3``
connections aren't safe to share across threads by default. SQLite's own
file-level locking handles the rest; this is a local, single-user tool, so no
connection pool is warranted.

The ``runs`` table splits cheap summary columns (for the history datatable) from
``state_json`` (the full run — proposals, reviews, usage, timings — parsed back out
only when a single run is opened for replay). Nothing about a run is dropped: it's
just not normalized into per-round columns, because nothing ever queries across
runs at that granularity.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

from . import config

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at       TEXT NOT NULL,
    problem          TEXT NOT NULL,
    restated_problem TEXT,
    verdict          TEXT NOT NULL,
    rounds           INTEGER,
    max_rounds       INTEGER,
    last_score       INTEGER,
    state_json       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_runs_created_at ON runs(created_at DESC);
"""

_SUMMARY_COLUMNS = (
    "id",
    "created_at",
    "problem",
    "restated_problem",
    "verdict",
    "rounds",
    "max_rounds",
    "last_score",
)


def _connect(path: str | None) -> sqlite3.Connection:
    conn = sqlite3.connect(path or config.db_path())
    conn.row_factory = sqlite3.Row
    return conn


def init_db(path: str | None = None) -> None:
    """Create the ``runs`` table if it doesn't exist yet. Safe to call every startup."""
    with _connect(path) as conn:
        conn.executescript(_SCHEMA)


def save_run(problem: str, state: dict[str, Any], *, path: str | None = None) -> int:
    """Persist a completed run. Returns the new row's id.

    ``state`` must already carry a ``verdict`` — that's only true once a run has
    reached ``finalize``, which is the "only persist completed runs" rule enforced
    by construction at the call site (``web.py``'s worker only calls this after
    ``graph.stream(...)`` finishes without raising). Raising here instead of
    silently writing a partial row keeps that guarantee from rotting silently.
    """
    if "verdict" not in state:
        raise ValueError("save_run requires a completed state (missing 'verdict')")

    reviews = state.get("reviews") or []
    last_score = reviews[-1]["score"] if reviews else None
    # Python-side ISO 8601 (with offset) rather than SQLite's `datetime('now')`,
    # which emits a space-separated, offset-less string that browsers don't
    # reliably parse with `new Date(...)`.
    created_at = datetime.now(timezone.utc).isoformat()

    with _connect(path) as conn:
        cur = conn.execute(
            """
            INSERT INTO runs
                (created_at, problem, restated_problem, verdict, rounds, max_rounds,
                 last_score, state_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                created_at,
                problem,
                state.get("restated_problem"),
                state["verdict"],
                state.get("round"),
                state.get("max_rounds"),
                last_score,
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
