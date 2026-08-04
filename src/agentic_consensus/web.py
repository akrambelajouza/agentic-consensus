"""A local web interface for the consensus loop.

    uv sync --extra web
    uv run consensus-web
    uv run consensus-web --host 0.0.0.0 --port 8080

Serves run, history, replay, and architecture-comparison pages. Graph calls are
blocking, so each run executes in a worker thread and pushes updates onto a queue
that a generator drains into a Server-Sent Events response — this lets one server
process serve pages while model work is in flight.

Model calls happen server-side using whatever `.env` already configures; this is a
thin transport around the existing graph, not a second implementation of it.
"""

from __future__ import annotations

import argparse
import json
import queue
import sys
import threading
import time
from contextlib import asynccontextmanager, nullcontext
from typing import Any, Callable, Iterator

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse
from pydantic import BaseModel

from . import config, db
from .schemas import Usage
from .transcript import render_html, render_json, render_markdown
from .variants.registry import DEFAULT_VARIANT, VARIANTS, get_variant
from .web_templates import (
    EXPERIMENT_DETAIL_HTML,
    EXPERIMENTS_HTML,
    HISTORY_HTML,
    INDEX_HTML,
    NEW_EXPERIMENT_HTML,
    REPLAY_HTML,
)


@asynccontextmanager
async def _lifespan(app: FastAPI):
    db.init_db()
    yield


app = FastAPI(title="Agentic Consensus", lifespan=_lifespan)


class RunRequest(BaseModel):
    problem: str
    rounds: int | None = None
    variant: str = DEFAULT_VARIANT


class ExperimentRequest(BaseModel):
    problem: str
    rounds: int | None = None


class ExportRequest(BaseModel):
    state: dict[str, Any]


def _jsonable(update: dict[str, Any]) -> dict[str, Any]:
    """Reviews/usage are model instances in-process; the wire format is plain dicts."""

    def convert(key: str, value: Any) -> Any:
        if key == "reviews":
            return [v.model_dump() if isinstance(v, BaseModel) else v for v in value]
        if key == "usage":
            return [v.model_dump() if isinstance(v, Usage) else v for v in value]
        return value

    return {k: convert(k, v) for k, v in update.items()}


def _sse(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload)}\n\n"


def _execute_variant(
    problem: str,
    rounds: int,
    variant_id: str,
    emit: Callable[[dict[str, Any]], None],
    *,
    experiment_id: int | None = None,
    settings_snapshot: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], int | None]:
    """Execute one graph and persist it, independent of its HTTP entry point."""
    context = (
        config.use_settings(settings_snapshot)
        if settings_snapshot is not None
        else nullcontext()
    )
    with context:
        variant = get_variant(variant_id)
        graph = variant.build_graph()
        state: dict[str, Any] = {
            "problem": problem,
            "variant": variant.id,
            "variant_version": variant.version,
        }
        last_ts = time.perf_counter()
        for chunk in graph.stream(
            {
                "problem": problem,
                "variant": variant.id,
                "variant_version": variant.version,
                "max_rounds": rounds,
            },
            stream_mode="updates",
        ):
            for node, update in chunk.items():
                now = time.perf_counter()
                duration_ms = round((now - last_ts) * 1000)
                last_ts = now
                update = _jsonable(update)
                state.update(
                    {
                        key: (
                            state.get(key, []) + value
                            if key
                            in ("proposals", "reviews", "criteria_history", "usage")
                            else value
                        )
                        for key, value in update.items()
                    }
                )
                state["timings"] = state.get("timings", []) + [
                    {"node": node, "duration_ms": duration_ms}
                ]
                emit(
                    {
                        "type": "node",
                        "node": node,
                        "update": update,
                        "duration_ms": duration_ms,
                    }
                )
        try:
            run_id = db.save_run(
                problem, state, experiment_id=experiment_id
            )
        except Exception as exc:
            if experiment_id is not None:
                raise
            print(f"warning: failed to persist run to history: {exc}", file=sys.stderr)
            run_id = None
        return state, run_id


def _run_events(problem: str, rounds: int | None, variant_id: str) -> Iterator[str]:
    """Run the graph in a worker thread, yielding one SSE message per queued event.

    The generator itself stays synchronous and blocking-on-queue, which is fine here:
    Starlette runs sync generators returned to ``StreamingResponse`` in a thread pool,
    so it doesn't stall the event loop despite blocking on ``q.get()``.
    """
    q: "queue.Queue[dict[str, Any] | None]" = queue.Queue()

    def worker() -> None:
        try:
            cfg = config.settings()
            effective_rounds = rounds if rounds is not None else cfg["max_rounds"]
            state, run_id = _execute_variant(
                problem, effective_rounds, variant_id, q.put
            )
            q.put({"type": "result", "state": state, "run_id": run_id})
        except Exception as exc:  # noqa: BLE001 - surfaced to the client, not swallowed
            q.put({"type": "error", "message": str(exc)})
        finally:
            q.put(None)

    threading.Thread(target=worker, daemon=True).start()

    while True:
        item = q.get()
        if item is None:
            return
        yield _sse(item)


def _experiment_events(problem: str, rounds: int | None) -> Iterator[str]:
    q: "queue.Queue[dict[str, Any] | None]" = queue.Queue()

    def worker() -> None:
        try:
            snapshot = config.settings()
            effective_rounds = rounds if rounds is not None else snapshot["max_rounds"]
            snapshot["max_rounds"] = effective_rounds
            variant_ids = list(VARIANTS)
            experiment_id = db.create_experiment(
                problem, effective_rounds, snapshot, variant_ids
            )
            q.put({"type": "experiment_created", "experiment_id": experiment_id})
            for variant_id in variant_ids:
                if not db.start_experiment_variant(experiment_id, variant_id):
                    q.put(
                        {
                            "type": "variant_failed",
                            "variant": variant_id,
                            "message": "Execution slot could not be started.",
                        }
                    )
                    continue
                q.put({"type": "variant_started", "variant": variant_id})
                try:
                    state, run_id = _execute_variant(
                        problem,
                        effective_rounds,
                        variant_id,
                        lambda event, current=variant_id: q.put(
                            {
                                "type": "variant_progress",
                                "variant": current,
                                "node": event["node"],
                                "duration_ms": event["duration_ms"],
                            }
                        ),
                        experiment_id=experiment_id,
                        settings_snapshot=snapshot,
                    )
                    q.put(
                        {
                            "type": "variant_completed",
                            "variant": variant_id,
                            "run_id": run_id,
                            "verdict": state.get("verdict"),
                        }
                    )
                except Exception as exc:  # noqa: BLE001 - one variant must not stop the experiment
                    message = db.sanitize_error(exc)
                    db.fail_experiment_variant(
                        experiment_id, variant_id, message
                    )
                    q.put(
                        {
                            "type": "variant_failed",
                            "variant": variant_id,
                            "message": message,
                        }
                    )
            result = db.get_experiment(experiment_id)
            q.put(
                {
                    "type": "experiment_completed",
                    "experiment_id": experiment_id,
                    "status": result["status"] if result else "failed",
                    "url": f"/experiments/{experiment_id}",
                }
            )
        except Exception as exc:  # noqa: BLE001 - surfaced through SSE
            q.put({"type": "error", "message": db.sanitize_error(exc)})
        finally:
            q.put(None)

    threading.Thread(target=worker, daemon=True).start()
    while True:
        item = q.get()
        if item is None:
            return
        yield _sse(item)


def _retry_experiment_events(
    experiment: dict[str, Any], variant_id: str
) -> Iterator[str]:
    q: "queue.Queue[dict[str, Any] | None]" = queue.Queue()

    def worker() -> None:
        try:
            q.put({"type": "variant_started", "variant": variant_id})
            try:
                state, run_id = _execute_variant(
                    experiment["problem"],
                    experiment["max_rounds"],
                    variant_id,
                    lambda event: q.put(
                        {
                            "type": "variant_progress",
                            "variant": variant_id,
                            "node": event["node"],
                            "duration_ms": event["duration_ms"],
                        }
                    ),
                    experiment_id=experiment["id"],
                    settings_snapshot=experiment["config"],
                )
                q.put(
                    {
                        "type": "variant_completed",
                        "variant": variant_id,
                        "run_id": run_id,
                        "verdict": state.get("verdict"),
                    }
                )
            except Exception as exc:  # noqa: BLE001 - persisted and surfaced
                message = db.sanitize_error(exc)
                db.fail_experiment_variant(
                    experiment["id"], variant_id, message
                )
                q.put(
                    {
                        "type": "variant_failed",
                        "variant": variant_id,
                        "message": message,
                    }
                )
            result = db.get_experiment(experiment["id"])
            q.put(
                {
                    "type": "experiment_completed",
                    "experiment_id": experiment["id"],
                    "status": result["status"] if result else "failed",
                    "url": f"/experiments/{experiment['id']}",
                }
            )
        except Exception as exc:  # noqa: BLE001 - surfaced through SSE
            q.put({"type": "error", "message": db.sanitize_error(exc)})
        finally:
            q.put(None)

    threading.Thread(target=worker, daemon=True).start()
    while True:
        item = q.get()
        if item is None:
            return
        yield _sse(item)


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return INDEX_HTML


@app.get("/history", response_class=HTMLResponse)
def history_page() -> str:
    return HISTORY_HTML


@app.get("/history/{run_id}", response_class=HTMLResponse)
def replay_page(run_id: int) -> str:
    return REPLAY_HTML


@app.get("/experiments/new", response_class=HTMLResponse)
def new_experiment_page() -> str:
    return NEW_EXPERIMENT_HTML


@app.get("/experiments", response_class=HTMLResponse)
def experiments_page() -> str:
    return EXPERIMENTS_HTML


@app.get("/experiments/{experiment_id}", response_class=HTMLResponse)
def experiment_detail_page(experiment_id: int) -> str:
    return EXPERIMENT_DETAIL_HTML


@app.get("/api/history")
def api_list_history(limit: int = 200) -> JSONResponse:
    return JSONResponse(db.list_runs(limit=limit))


@app.get("/api/history/{run_id}")
def api_get_history(run_id: int) -> Response:
    row = db.get_run(run_id)
    if row is None:
        return JSONResponse({"error": f"run {run_id} not found"}, status_code=404)
    return JSONResponse(row)


@app.get("/api/experiments")
def api_list_experiments(limit: int = 200) -> JSONResponse:
    return JSONResponse(db.list_experiments(limit=limit))


@app.get("/api/experiments/{experiment_id}")
def api_get_experiment(experiment_id: int) -> Response:
    experiment = db.get_experiment(experiment_id)
    if experiment is None:
        return JSONResponse(
            {"error": f"experiment {experiment_id} not found"}, status_code=404
        )
    return JSONResponse(experiment)


@app.get("/api/config")
def get_config() -> JSONResponse:
    try:
        payload = config.settings()
        payload["default_variant"] = DEFAULT_VARIANT
        payload["variants"] = [
            {
                "id": variant.id,
                "version": variant.version,
                "label": variant.label,
                "description": variant.description,
            }
            for variant in VARIANTS.values()
        ]
        return JSONResponse(payload)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.post("/api/run")
def run(req: RunRequest) -> StreamingResponse:
    problem = req.problem.strip()
    if not problem:
        return StreamingResponse(
            iter([_sse({"type": "error", "message": "The problem statement is empty."})]),
            media_type="text/event-stream",
        )
    return StreamingResponse(
        _run_events(problem, req.rounds, req.variant), media_type="text/event-stream"
    )


@app.post("/api/experiments")
def run_experiment(req: ExperimentRequest) -> StreamingResponse:
    problem = req.problem.strip()
    if not problem:
        return StreamingResponse(
            iter([_sse({"type": "error", "message": "The problem statement is empty."})]),
            media_type="text/event-stream",
        )
    return StreamingResponse(
        _experiment_events(problem, req.rounds), media_type="text/event-stream"
    )


@app.post("/api/experiments/{experiment_id}/retry/{variant_id}")
def retry_experiment_variant(experiment_id: int, variant_id: str) -> Response:
    experiment = db.get_experiment(experiment_id)
    if experiment is None:
        return JSONResponse(
            {"error": f"experiment {experiment_id} not found"}, status_code=404
        )
    if variant_id not in VARIANTS:
        return JSONResponse(
            {"error": f"unknown variant {variant_id!r}"}, status_code=404
        )
    if not db.start_experiment_variant(experiment_id, variant_id, retry=True):
        return JSONResponse(
            {"error": "only a failed experiment variant can be retried"},
            status_code=409,
        )
    return StreamingResponse(
        _retry_experiment_events(experiment, variant_id),
        media_type="text/event-stream",
    )


_EXPORTERS = {
    "md": (render_markdown, "text/markdown"),
    "html": (render_html, "text/html"),
    "json": (render_json, "application/json"),
}


@app.post("/api/export/{fmt}")
def export(fmt: str, req: ExportRequest) -> Response:
    if fmt not in _EXPORTERS:
        return JSONResponse({"error": f"unknown format {fmt!r}"}, status_code=404)
    renderer, media_type = _EXPORTERS[fmt]
    body = renderer(req.state)
    return Response(
        body,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="consensus-run.{fmt}"'},
    )


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="consensus-web", description="Serve the Agentic Consensus web interface."
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true", help="Auto-reload on source changes.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    import uvicorn

    args = _parse_args(argv)
    uvicorn.run(
        "agentic_consensus.web:app" if args.reload else app,
        host=args.host,
        port=args.port,
        reload=args.reload,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
