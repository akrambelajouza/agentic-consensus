"""A local web interface for the consensus loop.

    uv sync --extra web
    uv run consensus-web
    uv run consensus-web --host 0.0.0.0 --port 8080

Serves a single-page UI at ``/`` that submits a problem and watches the run stream
live, node by node, the same way ``__main__.py`` streams to the terminal. The graph
call is blocking, so each run executes in a worker thread and pushes updates onto a
queue that an async generator drains into a Server-Sent Events response — this lets
one server process serve the page while a run is in flight.

Model calls happen server-side using whatever `.env` already configures; this is a
thin transport around the existing graph, not a second implementation of it.
"""

from __future__ import annotations

import argparse
import json
import queue
import threading
import time
from typing import Any, Iterator

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse
from pydantic import BaseModel

from . import config
from .graph import build_graph
from .state import Review, Usage
from .transcript import render_html, render_json, render_markdown

app = FastAPI(title="Agentic Consensus")


class RunRequest(BaseModel):
    problem: str
    rounds: int | None = None


class ExportRequest(BaseModel):
    state: dict[str, Any]


def _jsonable(update: dict[str, Any]) -> dict[str, Any]:
    """Reviews/usage are model instances in-process; the wire format is plain dicts."""

    def convert(key: str, value: Any) -> Any:
        if key == "reviews":
            return [v.model_dump() if isinstance(v, Review) else v for v in value]
        if key == "usage":
            return [v.model_dump() if isinstance(v, Usage) else v for v in value]
        return value

    return {k: convert(k, v) for k, v in update.items()}


def _sse(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload)}\n\n"


def _run_events(problem: str, rounds: int | None) -> Iterator[str]:
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
            graph = build_graph()
            state: dict[str, Any] = {}
            last_ts = time.perf_counter()
            for chunk in graph.stream(
                {"problem": problem, "max_rounds": effective_rounds},
                stream_mode="updates",
            ):
                for node, update in chunk.items():
                    now = time.perf_counter()
                    duration_ms = round((now - last_ts) * 1000)
                    last_ts = now
                    update = _jsonable(update)
                    state.update(
                        {
                            k: (
                                state.get(k, []) + v
                                if k in ("proposals", "reviews", "usage")
                                else v
                            )
                            for k, v in update.items()
                        }
                    )
                    q.put(
                        {
                            "type": "node",
                            "node": node,
                            "update": update,
                            "duration_ms": duration_ms,
                        }
                    )
            q.put({"type": "result", "state": state})
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


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return INDEX_HTML


@app.get("/api/config")
def get_config() -> JSONResponse:
    try:
        return JSONResponse(config.settings())
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
        _run_events(problem, req.rounds), media_type="text/event-stream"
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


INDEX_HTML = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Agentic Consensus</title>
<style>
:root { color-scheme: light dark; --fg:#111; --muted:#666; --bg:#fff; --card:#f6f6f7;
        --line:#e2e2e5; --ok:#0a7d33; --warn:#a2500a; --err:#c0392b; --accent:#3b5bdb; }
@media (prefers-color-scheme: dark) {
  :root { --fg:#e8e8ea; --muted:#9a9aa2; --bg:#131316; --card:#1c1c21;
          --line:#2c2c33; --ok:#4ac16f; --warn:#e0a458; --err:#f28b82; --accent:#8fa4ff; }
}
* { box-sizing: border-box; }
body { margin:0; padding:2.5rem 1.25rem 5rem; background:var(--bg); color:var(--fg);
       font:16px/1.6 ui-sans-serif,-apple-system,"Segoe UI",Roboto,sans-serif; }
main { max-width: 78rem; margin: 0 auto; }
h1 { font-size:1.75rem; margin:0 0 .4rem; }
h2 { font-size:1rem; margin:0 0 .85rem; text-transform:uppercase; letter-spacing:.04em;
     color:var(--muted); }
.sub { color:var(--muted); margin:0 0 1.5rem; }
.meta { display:flex; flex-wrap:wrap; gap:.5rem; margin:0 0 1.5rem; padding:0; list-style:none; }
.meta li { background:var(--card); border:1px solid var(--line); border-radius:999px;
           padding:.25rem .75rem; font-size:.85rem; }
.meta b { font-weight:600; }
code { background:var(--bg); padding:.1rem .35rem; border-radius:4px; font-size:.9em; }
textarea { width:100%; min-height:7rem; resize:vertical; font:inherit; padding:.75rem;
           background:var(--card); color:var(--fg); border:1px solid var(--line);
           border-radius:8px; }
label { display:block; font-size:.85rem; font-weight:600; margin:0 0 .35rem; }
.field { margin:0 0 1rem; }
.row { display:flex; gap:1rem; align-items:flex-end; flex-wrap:wrap; }
.row .field { flex:1 1 auto; margin:0; }
.row .field.narrow { flex:0 0 8rem; }
input[type=number] { width:100%; font:inherit; padding:.6rem .75rem; background:var(--card);
                      color:var(--fg); border:1px solid var(--line); border-radius:8px; }
button { font:inherit; font-weight:600; padding:.7rem 1.4rem; border-radius:8px; border:none;
         background:var(--accent); color:#fff; cursor:pointer; }
button:disabled { opacity:.5; cursor:default; }
button.ghost { background:transparent; color:var(--accent); border:1px solid var(--accent);
               padding:.4rem .9rem; font-size:.8rem; }
.status { display:flex; align-items:center; gap:.6rem; color:var(--muted); margin:1rem 0; }
.spinner, .mini-spinner { border-radius:50%; border:2px solid var(--line);
           border-top-color:var(--accent); animation:spin .7s linear infinite; display:inline-block; }
.spinner { width:1rem; height:1rem; }
.mini-spinner { width:.65rem; height:.65rem; margin-right:.3rem; vertical-align:-1px; }
@keyframes spin { to { transform:rotate(360deg); } }
.error { border:1px solid var(--err); color:var(--err); border-radius:8px; padding:.75rem 1rem;
         margin:1rem 0; white-space:pre-wrap; }
.badge { font-size:.72rem; font-weight:700; letter-spacing:.03em; padding:.12rem .45rem;
         border-radius:999px; border:1px solid currentColor; }
.badge.ok { color:var(--ok); } .badge.warn { color:var(--warn); }
pre { white-space:pre-wrap; word-wrap:break-word; background:var(--bg);
      border:1px solid var(--line); border-radius:8px; padding:.85rem;
      margin:.6em 0; font:13.5px/1.55 ui-monospace,SFMono-Regular,Menlo,monospace; }
.hidden { display:none; }

.layout { display:grid; grid-template-columns: minmax(260px, 22rem) 1fr; gap:1.5rem;
          align-items:start; margin-top:2rem; }
@media (max-width: 860px) { .layout { grid-template-columns: 1fr; } }
.panel { border:1px solid var(--line); border-radius:12px; background:var(--card);
         padding:1.1rem 1.2rem; }
.flow-panel { position:sticky; top:1.5rem; max-height: calc(100vh - 3rem); overflow:auto; }
.flow-list { list-style:none; margin:0; padding:0; }
.flow-node { position:relative; padding-left:1.4rem; padding-bottom:1.1rem; }
.flow-node:last-child { padding-bottom:0; }
.flow-node::before { content:''; position:absolute; left:.28rem; top:1.4rem; bottom:-.1rem;
                      width:2px; background:var(--line); }
.flow-node:last-child::before { display:none; }
.flow-dot { position:absolute; left:0; top:.3rem; width:.6rem; height:.6rem; border-radius:50%;
            background:var(--line); border:2px solid var(--card); }
.flow-node.done .flow-dot { background:var(--ok); }
.flow-node.selected .flow-btn { border-color:var(--accent); background:rgba(59,91,219,.1); }
.flow-btn { width:100%; text-align:left; background:transparent; border:1px solid transparent;
            border-radius:8px; padding:.45rem .55rem; color:var(--fg); cursor:pointer; font:inherit; }
.flow-btn:hover { background:rgba(128,128,128,.1); }
.flow-placeholder { display:flex; align-items:center; padding:.45rem .55rem; color:var(--muted);
                     font-size:.9rem; }
.flow-label { font-weight:600; font-size:.92rem; }
.flow-sub { font-size:.76rem; color:var(--muted); margin-top:.2rem; display:flex; gap:.4rem;
            align-items:center; flex-wrap:wrap; }
.exports { display:flex; flex-wrap:wrap; gap:.5rem; margin-top:1.1rem; padding-top:1rem;
           border-top:1px solid var(--line); }
.details-panel { min-height:20rem; }
.details-title { font-size:1.15rem; font-weight:700; margin:0 0 .75rem; }
.details-meta { display:flex; flex-wrap:wrap; gap:.5rem; margin:0 0 1.1rem; padding:0; list-style:none; }
.details-meta li { background:var(--bg); border:1px solid var(--line); border-radius:999px;
                    padding:.2rem .65rem; font-size:.8rem; }
.details-content :is(h1,h2,h3,h4) { margin:1.1em 0 .4em; text-transform:none; letter-spacing:normal;
                                     color:var(--fg); font-weight:700; }
.details-content h1 { font-size:1.3rem; } .details-content h2 { font-size:1.15rem; }
.details-content h3 { font-size:1.05rem; } .details-content h4 { font-size:1rem; }
.details-content :first-child { margin-top:0; }
.details-content p { margin:.6em 0; }
.details-content ul, .details-content ol { padding-left:1.4rem; margin:.6em 0; }
.details-content pre code { background:none; padding:0; }
.empty-hint { color:var(--muted); }
</style></head>
<body><main>
<h1>Agentic Consensus</h1>
<p class="sub">Moderator frames the problem, Agent A proposes, Agent B critiques, until consensus.</p>
<ul class="meta" id="model-meta"></ul>

<form id="run-form">
  <div class="field">
    <label for="problem">Problem statement</label>
    <textarea id="problem" placeholder="Design a rate limiter for a multi-tenant API&#10;&#10;(Cmd/Ctrl+Enter to run)" required></textarea>
  </div>
  <div class="row">
    <div class="field narrow">
      <label for="rounds">Max rounds</label>
      <input type="number" id="rounds" min="1" placeholder="default">
    </div>
    <div class="field" style="flex:0 0 auto;">
      <button type="submit" id="run-btn">Run</button>
    </div>
  </div>
</form>

<div id="status" class="status hidden"><span class="spinner"></span><span id="status-text"></span></div>
<div id="error" class="error hidden"></div>

<div id="layout" class="layout hidden">
  <div class="panel flow-panel">
    <h2>Flow</h2>
    <ul class="flow-list" id="flow-list"></ul>
    <div class="exports hidden" id="exports">
      <button class="ghost" data-fmt="md">Download .md</button>
      <button class="ghost" data-fmt="html">Download .html</button>
      <button class="ghost" data-fmt="json">Download .json</button>
    </div>
  </div>
  <div class="panel details-panel">
    <div class="details-title" id="details-title">Details</div>
    <ul class="details-meta" id="details-meta"></ul>
    <div class="details-content" id="details-content">
      <p class="empty-hint">Run a problem, then click a node on the left once it completes.</p>
    </div>
  </div>
</div>
</main>

<script>
const VERDICT_LABELS = {
  consensus: "Consensus reached",
  no_consensus: "No consensus — round limit reached",
  stalled: "No consensus — review stalled",
};
const ROLE_LABELS = { moderator: "Moderator", agent_a: "Agent A — author", agent_b: "Agent B — reviewer" };

const form = document.getElementById("run-form");
const problemEl = document.getElementById("problem");
const roundsEl = document.getElementById("rounds");
const runBtn = document.getElementById("run-btn");
const statusEl = document.getElementById("status");
const statusText = document.getElementById("status-text");
const errorEl = document.getElementById("error");
const layoutEl = document.getElementById("layout");
const flowListEl = document.getElementById("flow-list");
const exportsEl = document.getElementById("exports");
const detailsTitleEl = document.getElementById("details-title");
const detailsMetaEl = document.getElementById("details-meta");
const detailsContentEl = document.getElementById("details-content");

let cfgRoles = {};
let finalState = null;
let flowData = {};       // id -> entry
let selectedId = null;
let pendingLi = null;    // the "Working…" placeholder awaiting the next node event
let currentRound = 0;

fetch("/api/config").then(r => r.json()).then(cfg => {
  if (cfg.error) return;
  cfgRoles = cfg.roles;
  const meta = document.getElementById("model-meta");
  const rows = [["Moderator", cfg.roles.moderator], ["Author", cfg.roles.agent_a], ["Reviewer", cfg.roles.agent_b]];
  meta.innerHTML = rows.map(([label, r]) =>
    `<li><b>${label}:</b> <code>${r.model}</code> (${r.effort})</li>`
  ).join("") + `<li><b>Max rounds:</b> ${cfg.max_rounds}</li>`;
  roundsEl.placeholder = `default ${cfg.max_rounds}`;
}).catch(() => {});

// --- Tiny markdown renderer -------------------------------------------------
// Covers what LLM output actually uses: headers, bold/italic, inline/fenced code,
// lists, links, paragraphs. Not CommonMark — no tables, no nested lists.

function escapeHtml(s) {
  const d = document.createElement("div");
  d.textContent = s ?? "";
  return d.innerHTML;
}

function renderInline(text) {
  text = escapeHtml(text);
  text = text.replace(/`([^`]+)`/g, "<code>$1</code>");
  text = text.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  text = text.replace(/(^|[^*])\*([^*\n]+)\*(?!\*)/g, "$1<em>$2</em>");
  text = text.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
  return text;
}

function renderBlock(block) {
  const heading = block.match(/^(#{1,4})\s+(.*)$/);
  if (heading && !block.includes("\n")) {
    const tag = `h${heading[1].length}`;
    return `<${tag}>${renderInline(heading[2])}</${tag}>`;
  }
  const lines = block.split("\n");
  if (lines.every(l => /^[-*]\s+/.test(l))) {
    return "<ul>" + lines.map(l => `<li>${renderInline(l.replace(/^[-*]\s+/, ""))}</li>`).join("") + "</ul>";
  }
  if (lines.every(l => /^\d+\.\s+/.test(l))) {
    return "<ol>" + lines.map(l => `<li>${renderInline(l.replace(/^\d+\.\s+/, ""))}</li>`).join("") + "</ol>";
  }
  return `<p>${lines.map(renderInline).join("<br>")}</p>`;
}

function renderMarkdown(md) {
  if (!md || !md.trim()) return '<p class="empty-hint">(none)</p>';
  let out = "";
  let lastIndex = 0;
  const codeRe = /```(\w*)\n?([\s\S]*?)```/g;
  let m;
  while ((m = codeRe.exec(md))) {
    out += md.slice(lastIndex, m.index).split(/\n{2,}/).map(c => c.trim()).filter(Boolean).map(renderBlock).join("\n");
    out += `<pre><code>${escapeHtml(m[2].replace(/\n$/, ""))}</code></pre>`;
    lastIndex = codeRe.lastIndex;
  }
  out += md.slice(lastIndex).split(/\n{2,}/).map(c => c.trim()).filter(Boolean).map(renderBlock).join("\n");
  return out;
}

// --- Flow panel --------------------------------------------------------------

function pushPending() {
  const li = document.createElement("li");
  li.className = "flow-node";
  li.innerHTML = '<span class="flow-dot"></span><div class="flow-placeholder"><span class="mini-spinner"></span>Working…</div>';
  flowListEl.appendChild(li);
  return li;
}

function formatUsageChip(usage) {
  if (!usage) return "";
  const total = usage.total_tokens ?? "?";
  return `<span>${total.toLocaleString ? total.toLocaleString() : total} tok</span>`;
}

function resolvePending(li, entry) {
  li.id = `flow-${entry.id}`;
  li.className = "flow-node done";
  const sub = [
    entry.badgeHtml || "",
    entry.duration_ms != null ? `<span>${(entry.duration_ms / 1000).toFixed(1)}s</span>` : "",
    formatUsageChip(entry.usage),
  ].filter(Boolean).join("");
  li.innerHTML = `<span class="flow-dot"></span>
    <button type="button" class="flow-btn">
      <div class="flow-label">${entry.label}</div>
      <div class="flow-sub">${sub}</div>
    </button>`;
  li.querySelector("button").addEventListener("click", () => selectFlowNode(entry.id));
  flowData[entry.id] = entry;
  return li;
}

function buildEntry(node, update, duration_ms) {
  const usage = (update.usage && update.usage[0]) || null;
  const base = { duration_ms, usage };
  if (node === "intake") {
    const md = `## Restated problem\n\n${update.restated_problem}\n\n## Acceptance criteria\n\n` +
      update.criteria.map((c, i) => `${i + 1}. ${c}`).join("\n");
    return { ...base, id: "intake", label: "Intake", roleKey: "moderator", contentMd: md };
  }
  if (node === "agent_a") {
    currentRound = update.round;
    const r = update.round;
    return {
      ...base, id: `agent_a-${r}`, roleKey: "agent_a", contentMd: update.proposal,
      label: `Agent A · Round ${r}${r > 1 ? " (revise)" : ""}`,
    };
  }
  if (node === "agent_b") {
    const review = update.reviews[update.reviews.length - 1];
    const cls = review.approved ? "ok" : "warn";
    const badgeHtml = `<span class="badge ${cls}">${review.approved ? "APPROVED" : "CHANGES"}</span><span class="badge ${cls}">${review.score}/10</span>`;
    let md = `**Critique**\n\n${review.critique}`;
    if (review.required_changes && review.required_changes.length) {
      md += `\n\n**Required changes**\n\n` + review.required_changes.map(c => `- ${c}`).join("\n");
    }
    return { ...base, id: `agent_b-${currentRound}`, roleKey: "agent_b", label: `Agent B · Round ${currentRound}`, badgeHtml, contentMd: md };
  }
  // finalize
  const cls = update.verdict === "consensus" ? "ok" : "warn";
  const badgeHtml = `<span class="badge ${cls}">${VERDICT_LABELS[update.verdict] || update.verdict}</span>`;
  return { ...base, id: "finalize", roleKey: "moderator", label: "Finalize", badgeHtml, contentMd: update.final_answer };
}

function selectFlowNode(id) {
  selectedId = id;
  flowListEl.querySelectorAll(".flow-node").forEach(li => li.classList.remove("selected"));
  const li = document.getElementById(`flow-${id}`);
  if (li) li.classList.add("selected");
  renderDetails(flowData[id]);
}

function renderDetails(entry) {
  if (!entry) {
    detailsTitleEl.textContent = "Details";
    detailsMetaEl.innerHTML = "";
    detailsContentEl.innerHTML = '<p class="empty-hint">Run a problem, then click a node on the left once it completes.</p>';
    return;
  }
  detailsTitleEl.textContent = entry.label;
  const role = cfgRoles[entry.roleKey];
  const u = entry.usage;
  const chips = [`<li><b>Role:</b> ${ROLE_LABELS[entry.roleKey] || entry.roleKey}</li>`];
  if (u) chips.push(`<li><b>Model:</b> <code>${u.model}</code></li>`);
  if (role) chips.push(`<li><b>Effort:</b> ${role.effort}</li>`);
  if (entry.duration_ms != null) chips.push(`<li><b>Duration:</b> ${(entry.duration_ms / 1000).toFixed(2)}s</li>`);
  if (u) {
    const parts = [
      u.input_tokens != null ? `${u.input_tokens.toLocaleString()} in` : null,
      u.output_tokens != null ? `${u.output_tokens.toLocaleString()} out` : null,
      u.total_tokens != null ? `${u.total_tokens.toLocaleString()} total` : null,
    ].filter(Boolean).join(" / ");
    if (parts) chips.push(`<li><b>Tokens:</b> ${parts}</li>`);
  }
  detailsMetaEl.innerHTML = chips.join("");
  detailsContentEl.innerHTML = renderMarkdown(entry.contentMd);
}

// --- Run ----------------------------------------------------------------------

function resetUI() {
  errorEl.classList.add("hidden");
  layoutEl.classList.remove("hidden");
  flowListEl.innerHTML = "";
  exportsEl.classList.add("hidden");
  detailsTitleEl.textContent = "Details";
  detailsMetaEl.innerHTML = "";
  detailsContentEl.innerHTML = '<p class="empty-hint">Waiting for the first node to finish…</p>';
  finalState = null;
  flowData = {};
  selectedId = null;
  currentRound = 0;
  pendingLi = pushPending();
}

async function runConsensus(problem, rounds) {
  resetUI();
  runBtn.disabled = true;
  statusEl.classList.remove("hidden");
  statusText.textContent = "Starting…";

  try {
    const resp = await fetch("/api/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ problem, rounds }),
    });
    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      const parts = buf.split("\n\n");
      buf = parts.pop();
      for (const part of parts) {
        const line = part.trim();
        if (!line.startsWith("data:")) continue;
        const evt = JSON.parse(line.slice(5).trim());

        if (evt.type === "error") {
          if (pendingLi) { pendingLi.remove(); pendingLi = null; }
          errorEl.textContent = evt.message;
          errorEl.classList.remove("hidden");
          statusEl.classList.add("hidden");
          runBtn.disabled = false;
          return;
        }

        if (evt.type === "node") {
          const { node, update, duration_ms } = evt;
          const entry = buildEntry(node, update, duration_ms);
          resolvePending(pendingLi, entry);
          if (!selectedId) selectFlowNode(entry.id);

          if (node === "intake") {
            statusText.textContent = `${update.criteria.length} criteria set — drafting round 1…`;
          } else if (node === "agent_a") {
            statusText.textContent = `Round ${update.round}: Agent A proposed — reviewing…`;
          } else if (node === "agent_b") {
            const review = update.reviews[update.reviews.length - 1];
            const mark = review.approved ? "APPROVED" : "changes requested";
            statusText.textContent = `Round ${currentRound}: Agent B — ${mark} (${review.score}/10)`;
          } else if (node === "finalize") {
            statusText.textContent = VERDICT_LABELS[update.verdict] || update.verdict;
          }

          pendingLi = node === "finalize" ? null : pushPending();
        } else if (evt.type === "result") {
          if (pendingLi) { pendingLi.remove(); pendingLi = null; }
          finalState = evt.state;
          exportsEl.classList.remove("hidden");
        }
      }
    }
  } catch (err) {
    if (pendingLi) { pendingLi.remove(); pendingLi = null; }
    errorEl.textContent = String(err);
    errorEl.classList.remove("hidden");
  } finally {
    statusEl.classList.add("hidden");
    runBtn.disabled = false;
  }
}

form.addEventListener("submit", (e) => {
  e.preventDefault();
  const problem = problemEl.value.trim();
  if (!problem) return;
  const rounds = roundsEl.value ? parseInt(roundsEl.value, 10) : null;
  runConsensus(problem, rounds);
});

problemEl.addEventListener("keydown", (e) => {
  if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
    form.requestSubmit();
  }
});

exportsEl.addEventListener("click", async (e) => {
  const fmt = e.target?.dataset?.fmt;
  if (!fmt || !finalState) return;
  const resp = await fetch(`/api/export/${fmt}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ state: finalState }),
  });
  const blob = await resp.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `consensus-run.${fmt}`;
  a.click();
  URL.revokeObjectURL(url);
});
</script>
</body></html>
"""


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
