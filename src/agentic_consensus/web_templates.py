"""Self-contained HTML/CSS/JS templates for runs, experiments, and replay.

Every page ships as one self-contained response — inline ``<style>``/``<script>``,
no CDN, no build step — same "no external assets" convention as ``transcript.py``'s
standalone HTML export. That convention is about what the *browser* fetches; nothing
stops the *Python source* from sharing string constants across pages, which is what
this module does: ``_SHARED_CSS``/``_SHARED_JS`` hold everything Home, History, and
Replay all need (the flow/details panels, the hand-rolled Markdown renderer, the nav
bar), so a visual or behavioural tweak is made once instead of drifting across three
copies.

Home streams a run live over SSE and renders it node by node. Replay does the same
rendering with none of the streaming: it fetches a finished run's full state and
reconstructs the identical sequence of flow entries in one shot
(``buildEntriesFromState``), then calls the exact same ``buildEntry``/``makeFlowLi``
functions Home's live path uses — so a replayed run looks pixel-identical to how it
looked live.
"""

from __future__ import annotations

_SHARED_CSS = """
:root { color-scheme: light dark; --fg:#111; --muted:#666; --bg:#fff; --card:#f6f6f7;
        --line:#e2e2e5; --ok:#0a7d33; --warn:#a2500a; --err:#c0392b; --accent:#3b5bdb; }
@media (prefers-color-scheme: dark) {
  :root { --fg:#e8e8ea; --muted:#9a9aa2; --bg:#131316; --card:#1c1c21;
          --line:#2c2c33; --ok:#4ac16f; --warn:#e0a458; --err:#f28b82; --accent:#8fa4ff; }
}
/* Explicit choice from the theme toggle wins over the OS preference above —
   higher-specificity attribute selectors, applied via JS as data-theme on <html>. */
:root[data-theme="light"] { color-scheme: light; --fg:#111; --muted:#666; --bg:#fff;
      --card:#f6f6f7; --line:#e2e2e5; --ok:#0a7d33; --warn:#a2500a; --err:#c0392b; --accent:#3b5bdb; }
:root[data-theme="dark"] { color-scheme: dark; --fg:#e8e8ea; --muted:#9a9aa2; --bg:#131316;
      --card:#1c1c21; --line:#2c2c33; --ok:#4ac16f; --warn:#e0a458; --err:#f28b82; --accent:#8fa4ff; }
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
.meta.compact { margin-bottom:.75rem; }
code { background:var(--bg); padding:.1rem .35rem; border-radius:4px; font-size:.9em; }
textarea { width:100%; min-height:7rem; resize:vertical; font:inherit; padding:.75rem;
           background:var(--card); color:var(--fg); border:1px solid var(--line);
           border-radius:8px; }
label { display:block; font-size:.85rem; font-weight:600; margin:0 0 .35rem; }
.field { margin:0 0 1rem; }
.row { display:flex; gap:1rem; align-items:flex-end; flex-wrap:wrap; }
.row .field { flex:1 1 auto; margin:0; }
.row .field.narrow { flex:0 0 8rem; }
input[type=number], select { width:100%; font:inherit; padding:.6rem .75rem;
                      background:var(--card); color:var(--fg); border:1px solid var(--line);
                      border-radius:8px; }
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
.badge.err { color:var(--err); }
pre { white-space:pre-wrap; word-wrap:break-word; background:var(--bg);
      border:1px solid var(--line); border-radius:8px; padding:.85rem;
      margin:.6em 0; font:13.5px/1.55 ui-monospace,SFMono-Regular,Menlo,monospace; }
.hidden { display:none !important; }

.topnav { display:flex; justify-content:space-between; align-items:center;
          margin:0 0 1.75rem; padding-bottom:1rem; border-bottom:1px solid var(--line); }
.topnav-links { display:flex; gap:1.25rem; }
.topnav a { color:var(--muted); text-decoration:none; font-weight:600; font-size:.9rem;
            padding:.3rem 0; border-bottom:2px solid transparent; }
.topnav a:hover { color:var(--fg); }
.topnav a.active { color:var(--accent); border-bottom-color:var(--accent); }
.theme-toggle { background:transparent; color:var(--fg); border:1px solid var(--line);
                border-radius:8px; width:2.2rem; height:2.2rem; padding:0; font-size:1rem;
                line-height:1; display:flex; align-items:center; justify-content:center; }
.theme-toggle:hover { background:rgba(128,128,128,.1); }
.back-link { display:inline-block; color:var(--accent); text-decoration:none;
             font-size:.85rem; font-weight:600; margin:0 0 .85rem; }
.back-link:hover { text-decoration:underline; }

.replay-header { display:grid; grid-template-columns:minmax(0, 1fr) max-content;
                 gap:1.5rem; align-items:start; }
.replay-header .sub { margin-bottom:0; }
.replay-meta { display:flex; flex-direction:column; align-items:stretch; margin:0;
               min-width:13rem; }
.replay-meta li { border-radius:8px; }
@media (max-width: 860px) {
  .replay-header { grid-template-columns:1fr; }
  .replay-meta { min-width:0; }
}

.history-toolbar { display:flex; gap:1rem; align-items:center; margin:0 0 .5rem; }
.history-toolbar input[type=search] { flex:1 1 auto; font:inherit; padding:.55rem .75rem;
      background:var(--card); color:var(--fg); border:1px solid var(--line); border-radius:8px; }
table.runs-table { width:100%; border-collapse:collapse; margin-top:1rem; }
table.runs-table th, table.runs-table td { text-align:left; padding:.6rem .7rem;
      border-bottom:1px solid var(--line); font-size:.9rem; }
table.runs-table th { cursor:pointer; color:var(--muted); font-weight:600;
      text-transform:uppercase; font-size:.72rem; letter-spacing:.04em; user-select:none; }
table.runs-table th:hover { color:var(--fg); }
table.runs-table tbody tr { cursor:pointer; }
table.runs-table tbody tr:hover { background:rgba(128,128,128,.08); }
table.runs-table td.problem-cell { max-width:28rem; overflow:hidden; text-overflow:ellipsis;
                                    white-space:nowrap; }
.metric-stack { display:flex; flex-direction:column; gap:.05rem; white-space:nowrap; }
.metric-stack strong { color:var(--fg); }
.metric-stack span { color:var(--muted); font-size:.78rem; }

.architecture-list { display:grid; grid-template-columns:repeat(3,minmax(0,1fr));
                     gap:.8rem; margin:1.25rem 0; }
.architecture-card { border:1px solid var(--line); border-radius:10px; padding:.85rem 1rem;
                     background:var(--card); }
.architecture-card h3 { font-size:.92rem; margin:0 0 .25rem; }
.architecture-card p { color:var(--muted); font-size:.8rem; margin:0; }
.architecture-card .run-status { display:block; margin-top:.65rem; font-size:.8rem;
                                  font-weight:600; color:var(--muted); }
.architecture-card.running { border-color:var(--accent); }
.architecture-card.completed { border-color:var(--ok); }
.architecture-card.failed { border-color:var(--err); }
.evaluation-placeholder { border:1px dashed var(--line); border-radius:10px; padding:1rem;
                          margin:1.25rem 0; background:var(--card); }
.evaluation-placeholder strong { display:block; margin-bottom:.2rem; }
.evaluation-placeholder p { margin:0; color:var(--muted); }
.tab-shell { margin-top:1.5rem; border:1px solid var(--line); border-radius:12px;
             background:var(--card); overflow:hidden; box-shadow:0 4px 18px rgba(0,0,0,.08); }
.tabs { display:flex; gap:.35rem; padding:.65rem .75rem 0; border-bottom:1px solid var(--line);
        background:rgba(128,128,128,.07); overflow-x:auto; }
.tab-button { border:1px solid transparent; border-bottom:0; border-radius:8px 8px 0 0;
              background:transparent; color:var(--muted); padding:.7rem 1rem; }
.tab-button:hover { color:var(--fg); background:rgba(128,128,128,.08); }
.tab-button.active { color:var(--accent); background:var(--card); border-color:var(--line);
                     box-shadow:inset 0 3px 0 var(--accent); font-weight:700;
                     position:relative; bottom:-1px; }
.tab-panel { padding:1.25rem; }
.tab-status { display:inline-block; margin-left:.4rem; padding:.15rem .45rem; border-radius:999px;
              font-size:.7rem; line-height:1.2; font-weight:700; }
.tab-status.done { color:var(--ok); background:rgba(46,160,67,.13); }
.tab-status.waiting { color:var(--warn); background:rgba(210,153,34,.15); }
.evaluation-header { display:flex; align-items:center; justify-content:space-between;
                     gap:1rem; flex-wrap:wrap; }
.evaluation-controls { display:flex; align-items:center; gap:.75rem; flex-wrap:wrap; }
.evaluation-controls #evaluation-status { white-space:nowrap; }
.criteria-list { margin:.6rem 0 1rem; padding-left:1.5rem; }
.evaluation-actions { display:flex; }
.criterion-status { font-weight:700; text-transform:capitalize; }
.criterion-status.satisfied { color:var(--ok); }
.criterion-status.partial { color:var(--warn); }
.criterion-status.violated { color:var(--err); }
.field-help { color:var(--muted); font-size:.8rem; margin:.3rem 0 0; }
.comparison-table-wrap { overflow-x:auto; margin:1.25rem 0; }
.comparison-table { width:100%; border-collapse:collapse; }
.comparison-table th,.comparison-table td { border-bottom:1px solid var(--line);
                    padding:.65rem .75rem; text-align:left; vertical-align:top; }
.comparison-table th { color:var(--muted); font-size:.78rem; text-transform:uppercase; }
.answers-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:1rem;
                align-items:start; }
.answer-card { min-width:0; border:1px solid var(--line); border-radius:12px;
               padding:1rem; background:var(--card); }
.answer-card h3 { margin:0 0 .2rem; font-size:1rem; }
.answer-card .answer-meta { color:var(--muted); font-size:.8rem; margin-bottom:.9rem; }
.answer-card .details-content { overflow-wrap:anywhere; }
.answer-actions { display:flex; gap:.5rem; margin-top:1rem; }
.answer-actions a { color:var(--accent); font-size:.82rem; font-weight:600;
                    text-decoration:none; }
@media (max-width: 900px) {
  .architecture-list,.answers-grid { grid-template-columns:1fr; }
}

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
"""

# --- Shared JS ----------------------------------------------------------------
# DOM refs, globals, the markdown renderer, and the flow/details primitives every
# page needs. A page that lacks one of these elements (e.g. History has no
# #flow-list) just gets `null` back from `getElementById` — harmless as long as
# nothing unconditionally calls a function that touches it, which none of these do.

_SHARED_JS = r"""
// --- Theme toggle -------------------------------------------------------------
// `_THEME_INIT_SCRIPT` (in <head>) already applied any stored choice before this
// ran, so the page never flashes the wrong theme; this just wires the button and
// keeps localStorage in sync with it.
(function () {
  const btn = document.getElementById("theme-toggle");
  if (!btn) return;
  const systemPrefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
  const current = () => document.documentElement.getAttribute("data-theme") || (systemPrefersDark ? "dark" : "light");
  const paint = () => { btn.textContent = current() === "dark" ? "☀️" : "🌙"; };
  paint();
  btn.addEventListener("click", () => {
    const next = current() === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", next);
    localStorage.setItem("theme", next);
    paint();
  });
})();

const VERDICT_LABELS = {
  consensus: "Consensus reached",
  no_consensus: "No consensus — round limit reached",
  stalled: "No consensus — review stalled",
};
const ROLE_LABELS = { moderator: "Moderator", agent_a: "Agent A — author", agent_b: "Agent B — reviewer", evaluator: "Independent evaluator" };
const VARIANT_LABELS = {
  "v1-moderated-criteria": "V1 — Moderated criteria",
  "v2-posthoc-reviewer": "V2 — Post-hoc reviewer",
  "v3-adversarial-reviewer": "V3 — Adversarial reviewer",
};

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
let currentRound = 0;

function onConfigLoaded(cfg) {}  // pages override this to react to /api/config

fetch("/api/config").then(r => r.json()).then(cfg => {
  if (cfg.error) return;
  cfgRoles = cfg.roles;
  onConfigLoaded(cfg);
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
  const parts = [];
  if (usage.total_tokens != null) parts.push(`<span>${usage.total_tokens.toLocaleString()} tok</span>`);
  if (usage.cost != null) parts.push(`<span>${formatCost(usage.cost)}</span>`);
  return parts.join("");
}

function formatCost(cost) {
  if (cost == null) return "—";
  const digits = cost === 0 || Math.abs(cost) < 0.01 ? 6 : Math.abs(cost) < 1 ? 4 : 2;
  return `$${Number(cost).toFixed(digits)}`;
}

function formatDuration(durationMs) {
  if (durationMs == null) return "—";
  const seconds = Number(durationMs) / 1000;
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  const minutes = Math.floor(seconds / 60);
  return `${minutes}m ${(seconds % 60).toFixed(0)}s`;
}

function statusBadge(status) {
  const value = status || "unknown";
  const cls = value === "completed" ? "ok" : value === "failed" ? "err" : "warn";
  return `<span class="badge ${cls}">${escapeHtml(value.replaceAll("_", " "))}</span>`;
}

function usageTotals(state) {
  const usage = state?.usage || [];
  const tokens = usage.filter(u => u.total_tokens != null).map(u => Number(u.total_tokens));
  const costs = usage.filter(u => u.cost != null).map(u => Number(u.cost));
  return {
    calls: usage.length,
    tokens: usage.length && tokens.length === usage.length ? tokens.reduce((a, b) => a + b, 0) : null,
    cost: usage.length && costs.length === usage.length ? costs.reduce((a, b) => a + b, 0) : null,
  };
}

function renderRunTotals(state, element) {
  if (!element) return;
  const totals = usageTotals(state);
  element.innerHTML = [
    `<li><b>Model calls:</b> ${totals.calls}</li>`,
    `<li><b>Total tokens:</b> ${totals.tokens != null ? totals.tokens.toLocaleString() : "—"}</li>`,
    `<li><b>Total cost:</b> ${formatCost(totals.cost)}</li>`,
  ].join("");
  element.classList.remove("hidden");
}

function makeFlowLi(entry) {
  const li = document.createElement("li");
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

function resolvePending(li, entry) {
  const built = makeFlowLi(entry);
  li.id = built.id;
  li.className = built.className;
  li.innerHTML = built.innerHTML;
  li.querySelector("button").addEventListener("click", () => selectFlowNode(entry.id));
  return li;
}

function buildEntry(node, update, duration_ms) {
  const usage = (update.usage && update.usage[0]) || null;
  const base = { duration_ms, usage };
  if (node === "intake") {
    const md = `## Restated problem\n\n${update.restated_problem}\n\n## Acceptance criteria\n\n` +
      (update.criteria || []).map((c, i) => `${i + 1}. ${c}`).join("\n");
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
    const adversarial = Object.hasOwn(review, "missing_requirements");
    const categories = [
      ["Missing requirements", review.missing_requirements || []],
      ["Violated acceptance criteria", review.violated_acceptance_criteria || []],
      ["Edge cases", review.edge_cases || []],
      ["Ambiguities", review.ambiguities || []],
      ["Risks", review.risks || []],
    ];
    const blockingCount = categories.flatMap(([, findings]) => findings)
      .filter(f => f.severity === "blocking").length;
    const metric = adversarial ? `${blockingCount} blocking` : `${review.score}/10`;
    const badgeHtml = `<span class="badge ${cls}">${review.approved ? "APPROVED" : "CHANGES"}</span><span class="badge ${cls}">${metric}</span>`;
    let md = "";
    if (review.criteria && review.criteria.length) {
      md += `**Reviewer criteria**\n\n` + review.criteria.map((c, i) => `${i + 1}. ${c}`).join("\n") + "\n\n";
    }
    if (adversarial) {
      md += `**Adversarial conclusion**\n\n${review.summary}`;
      for (const [category, findings] of categories) {
        md += `\n\n**${category}**\n\n`;
        md += findings.length ? findings.map(f =>
          `- [${f.severity.replaceAll("_", " ").toUpperCase()}] ${f.description} — Evidence: ${f.evidence} — Required correction: ${f.required_correction || "None"}`
        ).join("\n") : "- None";
      }
    } else {
      md += `**Critique**\n\n${review.critique}`;
      if (review.required_changes && review.required_changes.length) {
        md += `\n\n**Required changes**\n\n` + review.required_changes.map(c => `- ${c}`).join("\n");
      }
    }
    const outcome = update.verdict ? `<span class="badge ${update.verdict === "consensus" ? "ok" : "warn"}">${VERDICT_LABELS[update.verdict]}</span>` : "";
    return { ...base, id: `agent_b-${currentRound}`, roleKey: "agent_b", label: `Agent B · Round ${currentRound}`, badgeHtml: badgeHtml + outcome, contentMd: md };
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
    const detailParts = [
      u.reasoning_tokens != null ? `${u.reasoning_tokens.toLocaleString()} reasoning` : null,
      u.cached_input_tokens != null ? `${u.cached_input_tokens.toLocaleString()} cache read` : null,
      u.cache_write_tokens != null ? `${u.cache_write_tokens.toLocaleString()} cache write` : null,
    ].filter(Boolean).join(" / ");
    if (detailParts) chips.push(`<li><b>Token details:</b> ${detailParts}</li>`);
    chips.push(`<li><b>Cost:</b> ${formatCost(u.cost)} (${(u.cost_source || "unavailable").replaceAll("_", " ")})</li>`);
    if (u.upstream_inference_cost != null) {
      chips.push(`<li><b>Upstream cost:</b> ${formatCost(u.upstream_inference_cost)}</li>`);
    }
  }
  detailsMetaEl.innerHTML = chips.join("");
  detailsContentEl.innerHTML = renderMarkdown(entry.contentMd);
}

// --- Replay: reconstruct a finished run's flow entries from its saved state --
// usage/timings are flat lists mixing all four node types in chronological call
// order (one entry per node execution — see web.py, where `timings` is built).
// Filtering by `.node` then consuming sequentially recovers per-execution pairing,
// the same index-based convention transcript.py's `_rounds()` uses for
// proposals/reviews. This only stays correct as long as each node makes exactly
// one LLM call, which is currently guaranteed by nodes.py.

function groupByNode(list) {
  const map = {};
  for (const item of (list || [])) {
    (map[item.node] = map[item.node] || []).push(item);
  }
  return map;
}

function buildEntriesFromState(state) {
  currentRound = 0;
  const usageByNode = groupByNode(state.usage);
  const timingByNode = groupByNode(state.timings);
  const cursor = {};
  const takeUsage = (node) => {
    const i = cursor[node] = (cursor[node] || 0) + 1;
    const item = (usageByNode[node] || [])[i - 1];
    return item ? [item] : [];
  };
  const takeDuration = (node) => {
    const i = cursor[`${node}:t`] = (cursor[`${node}:t`] || 0) + 1;
    const item = (timingByNode[node] || [])[i - 1];
    return item ? item.duration_ms : null;
  };

  const entries = [];
  const hasModerator = state.variant !== "v2-posthoc-reviewer";
  if (hasModerator) {
    entries.push(buildEntry("intake", {
      restated_problem: state.restated_problem,
      criteria: state.criteria || [],
      usage: takeUsage("intake"),
    }, takeDuration("intake")));
  }

  const proposals = state.proposals || [];
  const reviews = state.reviews || [];
  for (let i = 0; i < proposals.length; i++) {
    entries.push(buildEntry("agent_a", {
      round: i + 1,
      proposal: proposals[i],
      usage: takeUsage("agent_a"),
    }, takeDuration("agent_a")));

    if (i < reviews.length) {
      entries.push(buildEntry("agent_b", {
        reviews: reviews.slice(0, i + 1),
        verdict: !hasModerator && i === reviews.length - 1 ? state.verdict : null,
        usage: takeUsage("agent_b"),
      }, takeDuration("agent_b")));
    }
  }

  if (hasModerator) {
    entries.push(buildEntry("finalize", {
      verdict: state.verdict,
      final_answer: state.final_answer,
      usage: takeUsage("finalize"),
    }, takeDuration("finalize")));
  }

  return entries;
}

function renderFlowFromEntries(entries) {
  flowListEl.innerHTML = "";
  flowData = {};
  selectedId = null;
  entries.forEach(entry => flowListEl.appendChild(makeFlowLi(entry)));
  if (entries.length) selectFlowNode(entries[0].id);
}

if (exportsEl) {
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
}
"""


def _nav_html(active: str) -> str:
    def cls(page: str) -> str:
        return ' class="active"' if page == active else ""

    return (
        '<nav class="topnav">'
        '<div class="topnav-links">'
        f'<a href="/"{cls("home")}>Run</a>'
        f'<a href="/experiments/new"{cls("experiment-new")}>New Experiment</a>'
        f'<a href="/experiments"{cls("experiments")}>Experiments</a>'
        f'<a href="/history"{cls("history")}>History</a>'
        "</div>"
        '<button type="button" id="theme-toggle" class="theme-toggle" '
        'aria-label="Toggle light/dark theme"></button>'
        "</nav>"
    )


# Applied before <body> renders, so the page never flashes the wrong theme while
# the shared <script> (loaded after `body` further down) sets up the toggle.
_THEME_INIT_SCRIPT = """
(function() {
  var stored = localStorage.getItem("theme");
  if (stored === "light" || stored === "dark") {
    document.documentElement.setAttribute("data-theme", stored);
  }
})();
"""


def _page(*, active: str, body: str, script: str) -> str:
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Agentic Consensus</title>
<style>{_SHARED_CSS}</style>
<script>{_THEME_INIT_SCRIPT}</script>
</head>
<body><main>
{_nav_html(active)}
{body}
</main>
<script>
{_SHARED_JS}
{script}
</script>
</body></html>
"""


# --- Home -----------------------------------------------------------------

_HOME_BODY = """
<h1>Agentic Consensus</h1>
<p class="sub">Run and inspect alternative author/reviewer workflow designs.</p>
<ul class="meta" id="model-meta"></ul>
<ul class="meta compact hidden" id="run-totals"></ul>

<form id="run-form">
  <div class="field">
    <label for="problem">Problem statement</label>
    <textarea id="problem" placeholder="Design a rate limiter for a multi-tenant API&#10;&#10;(Cmd/Ctrl+Enter to run)" required></textarea>
  </div>
  <div class="row">
    <div class="field" style="min-width:18rem;">
      <label for="variant">Workflow variant</label>
      <select id="variant"></select>
    </div>
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
"""

_HOME_SCRIPT = r"""
const form = document.getElementById("run-form");
const problemEl = document.getElementById("problem");
const roundsEl = document.getElementById("rounds");
const variantEl = document.getElementById("variant");
const runBtn = document.getElementById("run-btn");
const statusEl = document.getElementById("status");
const statusText = document.getElementById("status-text");
const runTotalsEl = document.getElementById("run-totals");

let pendingLi = null;    // the "Working…" placeholder awaiting the next node event

function onConfigLoaded(cfg) {
  variantEl.innerHTML = cfg.variants.map(v =>
    `<option value="${v.id}">${v.label}</option>`
  ).join("");
  variantEl.value = cfg.default_variant;
  const paintModels = () => {
  const meta = document.getElementById("model-meta");
  const rows = [["Author", cfg.roles.agent_a], ["Reviewer", cfg.roles.agent_b]];
  if (variantEl.value !== "v2-posthoc-reviewer") rows.unshift(["Moderator", cfg.roles.moderator]);
  meta.innerHTML = rows.map(([label, r]) =>
    `<li><b>${label}:</b> <code>${r.model}</code> (${r.effort})</li>`
  ).join("") + `<li><b>Variant:</b> ${VARIANT_LABELS[variantEl.value]}</li><li><b>Max rounds:</b> ${cfg.max_rounds}</li>`;
  };
  variantEl.addEventListener("change", paintModels);
  paintModels();
  roundsEl.placeholder = `default ${cfg.max_rounds}`;
}

function resetUI() {
  errorEl.classList.add("hidden");
  layoutEl.classList.remove("hidden");
  flowListEl.innerHTML = "";
  exportsEl.classList.add("hidden");
  runTotalsEl.classList.add("hidden");
  detailsTitleEl.textContent = "Details";
  detailsMetaEl.innerHTML = "";
  detailsContentEl.innerHTML = '<p class="empty-hint">Waiting for the first node to finish…</p>';
  finalState = null;
  flowData = {};
  selectedId = null;
  currentRound = 0;
  pendingLi = pushPending();
}

async function runConsensus(problem, rounds, variant) {
  resetUI();
  runBtn.disabled = true;
  statusEl.classList.remove("hidden");
  statusText.textContent = "Starting…";

  try {
    const resp = await fetch("/api/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ problem, rounds, variant }),
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
            const metric = Object.hasOwn(review, "missing_requirements")
              ? `${review.required_changes.length} blocking defects`
              : `${review.score}/10`;
            statusText.textContent = update.verdict
              ? (VERDICT_LABELS[update.verdict] || update.verdict)
              : `Round ${currentRound}: Agent B — ${mark} (${metric})`;
          } else if (node === "finalize") {
            statusText.textContent = VERDICT_LABELS[update.verdict] || update.verdict;
          }

          pendingLi = node === "finalize" || update.verdict ? null : pushPending();
        } else if (evt.type === "result") {
          if (pendingLi) { pendingLi.remove(); pendingLi = null; }
          finalState = evt.state;
          renderRunTotals(finalState, runTotalsEl);
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
  runConsensus(problem, rounds, variantEl.value);
});

problemEl.addEventListener("keydown", (e) => {
  if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
    form.requestSubmit();
  }
});
"""

INDEX_HTML = _page(active="home", body=_HOME_BODY, script=_HOME_SCRIPT)


# --- New experiment -----------------------------------------------------------

_NEW_EXPERIMENT_BODY = """
<h1>New Experiment</h1>
<p class="sub">Run one problem through all three workflow architectures with the same saved configuration.</p>
<ul class="meta" id="experiment-models"></ul>

<form id="experiment-form">
  <div class="field">
    <label for="problem">Problem statement</label>
    <textarea id="problem" placeholder="Design an AI coding skill that generates a pull request description."
              required></textarea>
  </div>
  <div class="field">
    <label for="evaluation-criteria">Evaluation criteria (optional)</label>
    <textarea id="evaluation-criteria" placeholder="Handles edge cases explicitly&#10;Defines inputs and outputs&#10;Includes security considerations"></textarea>
    <p class="field-help">One criterion per line. These criteria are frozen with the experiment and hidden from all three workflows.</p>
  </div>
  <div class="row">
    <div class="field narrow">
      <label for="rounds">Max rounds</label>
      <input type="number" id="rounds" min="1" placeholder="default">
    </div>
    <div class="field" style="flex:0 0 auto;">
      <button type="submit" id="experiment-btn">Run V1, V2 &amp; V3</button>
    </div>
  </div>
</form>

<div class="architecture-list" id="architecture-list"></div>
<div id="status" class="status hidden"><span class="spinner"></span><span id="status-text"></span></div>
<div id="error" class="error hidden"></div>
<div id="experiment-result" class="panel hidden"></div>
"""

_NEW_EXPERIMENT_SCRIPT = r"""
const experimentForm = document.getElementById("experiment-form");
const problemEl = document.getElementById("problem");
const roundsEl = document.getElementById("rounds");
const criteriaEl = document.getElementById("evaluation-criteria");
const experimentBtn = document.getElementById("experiment-btn");
const statusEl = document.getElementById("status");
const statusText = document.getElementById("status-text");
const architectureList = document.getElementById("architecture-list");
const resultEl = document.getElementById("experiment-result");
let experimentVariants = [];

function onConfigLoaded(cfg) {
  experimentVariants = cfg.variants;
  roundsEl.placeholder = `default ${cfg.max_rounds}`;
  document.getElementById("experiment-models").innerHTML = [
    ["Moderator", cfg.roles.moderator],
    ["Author", cfg.roles.agent_a],
    ["Reviewer", cfg.roles.agent_b],
    ["Evaluator (used on request)", cfg.roles.evaluator],
  ].map(([label, role]) =>
    `<li><b>${label}:</b> <code>${escapeHtml(role.model)}</code> (${escapeHtml(role.effort)})</li>`
  ).join("");
  resetArchitectureCards();
}

function resetArchitectureCards() {
  architectureList.innerHTML = experimentVariants.map(variant => `
    <div class="architecture-card" id="architecture-${variant.id}">
      <h3>${escapeHtml(variant.label)}</h3>
      <p>${escapeHtml(variant.description)}</p>
      <span class="run-status">Waiting</span>
    </div>`).join("");
}

function setVariantStatus(variant, status, detail = "") {
  const card = document.getElementById(`architecture-${variant}`);
  if (!card) return;
  card.classList.remove("running", "completed", "failed");
  card.classList.add(status);
  const labels = { running: "Running", completed: "Complete", failed: "Failed" };
  card.querySelector(".run-status").textContent = detail || labels[status] || status;
}

async function consumeExperimentStream(resp) {
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
      if (evt.type === "error") throw new Error(evt.message);
      if (evt.type === "experiment_created") {
        statusText.textContent = `Experiment #${evt.experiment_id} created`;
      } else if (evt.type === "variant_started") {
        setVariantStatus(evt.variant, "running");
        statusText.textContent = `${VARIANT_LABELS[evt.variant]} is running…`;
      } else if (evt.type === "variant_progress") {
        setVariantStatus(evt.variant, "running", `Running · ${evt.node.replaceAll("_", " ")}`);
      } else if (evt.type === "variant_completed") {
        setVariantStatus(evt.variant, "completed");
      } else if (evt.type === "variant_failed") {
        setVariantStatus(evt.variant, "failed", `Failed · ${evt.message}`);
      } else if (evt.type === "experiment_completed") {
        statusText.textContent = `Experiment ${evt.status}`;
        resultEl.innerHTML = `<strong>Experiment ${escapeHtml(evt.status)}</strong><br>
          <a class="back-link" style="margin:.5rem 0 0" href="${evt.url}">View comparison results →</a>`;
        resultEl.classList.remove("hidden");
      }
    }
  }
}

experimentForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const problem = problemEl.value.trim();
  if (!problem) return;
  resetArchitectureCards();
  errorEl.classList.add("hidden");
  resultEl.classList.add("hidden");
  experimentBtn.disabled = true;
  statusEl.classList.remove("hidden");
  statusText.textContent = "Creating experiment…";
  try {
    const resp = await fetch("/api/experiments", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        problem,
        rounds: roundsEl.value ? parseInt(roundsEl.value, 10) : null,
        evaluation_criteria: criteriaEl.value,
      }),
    });
    await consumeExperimentStream(resp);
  } catch (error) {
    errorEl.textContent = String(error.message || error);
    errorEl.classList.remove("hidden");
  } finally {
    experimentBtn.disabled = false;
    statusEl.classList.add("hidden");
  }
});
"""

NEW_EXPERIMENT_HTML = _page(
    active="experiment-new", body=_NEW_EXPERIMENT_BODY, script=_NEW_EXPERIMENT_SCRIPT
)


# --- Experiments --------------------------------------------------------------

_EXPERIMENTS_BODY = """
<h1>Experiments</h1>
<p class="sub">One problem per row, compared across V1, V2, and V3.</p>
<div class="history-toolbar">
  <input type="search" id="experiment-search" placeholder="Search problem statements…">
</div>
<div id="error" class="error hidden"></div>
<table class="runs-table" id="experiments-table">
  <thead><tr>
    <th>Created</th><th>Problem</th><th>Status</th><th>Evaluated</th>
    <th>V1</th><th>V2</th><th>V3</th><th>Total cost</th>
  </tr></thead>
  <tbody id="experiments-tbody"><tr><td colspan="8" class="empty-hint">Loading…</td></tr></tbody>
</table>
"""

_EXPERIMENTS_SCRIPT = r"""
const experimentSearch = document.getElementById("experiment-search");
const experimentsBody = document.getElementById("experiments-tbody");
let allExperiments = [];

function variantSummary(item) {
  if (!item) return '<span class="empty-hint">—</span>';
  if (item.status !== "completed") {
    return `<div class="metric-stack">${statusBadge(item.status)}<span>${escapeHtml(item.error_message || "")}</span></div>`;
  }
  return `<div class="metric-stack">
    <strong>${escapeHtml(VERDICT_LABELS[item.verdict] || item.verdict || "Complete")}</strong>
    <span>${formatCost(item.total_cost)} · ${item.total_tokens != null ? item.total_tokens.toLocaleString() + " tok" : "—"}</span>
    <span>${formatDuration(item.duration_ms)}</span>
  </div>`;
}

function renderExperiments() {
  const query = experimentSearch.value.trim().toLowerCase();
  const rows = allExperiments.filter(item => !query || item.problem.toLowerCase().includes(query));
  if (!rows.length) {
    experimentsBody.innerHTML = `<tr><td colspan="8" class="empty-hint">${allExperiments.length ? "No experiments match your search." : "No experiments yet — create one first."}</td></tr>`;
    return;
  }
  experimentsBody.innerHTML = rows.map(experiment => {
    const variants = Object.fromEntries(experiment.variants.map(item => [item.variant, item]));
    const problem = escapeHtml(experiment.problem);
    return `<tr data-id="${experiment.id}">
      <td>${new Date(experiment.created_at).toLocaleString()}</td>
      <td class="problem-cell" title="${problem}">${problem}</td>
      <td>${statusBadge(experiment.status)}</td>
      <td><span class="badge ${experiment.evaluation_status === "completed" ? "ok" : "warn"}"
                title="${escapeHtml(experiment.evaluation_status.replaceAll("_", " "))}">${experiment.evaluation_status === "completed" ? "Done" : "Waiting"}</span></td>
      <td>${variantSummary(variants["v1-moderated-criteria"])}</td>
      <td>${variantSummary(variants["v2-posthoc-reviewer"])}</td>
      <td>${variantSummary(variants["v3-adversarial-reviewer"])}</td>
      <td>${formatCost(experiment.total_cost)}</td>
    </tr>`;
  }).join("");
}

experimentsBody.addEventListener("click", event => {
  const row = event.target.closest("tr[data-id]");
  if (row) location.href = `/experiments/${row.dataset.id}`;
});
experimentSearch.addEventListener("input", renderExperiments);
fetch("/api/experiments").then(response => response.json()).then(experiments => {
  allExperiments = experiments;
  renderExperiments();
}).catch(error => {
  errorEl.textContent = String(error);
  errorEl.classList.remove("hidden");
});
"""

EXPERIMENTS_HTML = _page(
    active="experiments", body=_EXPERIMENTS_BODY, script=_EXPERIMENTS_SCRIPT
)


# --- Experiment details -------------------------------------------------------

_EXPERIMENT_DETAIL_BODY = """
<a class="back-link" href="/experiments">&larr; Back to experiments</a>
<h1>Experiment comparison</h1>
<p class="sub" id="experiment-problem">Loading…</p>
<ul class="meta" id="experiment-meta"></ul>
<div id="error" class="error hidden"></div>

<div class="tab-shell">
<div class="tabs" role="tablist" aria-label="Experiment report sections">
  <button type="button" class="tab-button active" id="experiment-tab"
          role="tab" aria-selected="true" aria-controls="experiment-panel">
    Experiment details
  </button>
  <button type="button" class="tab-button" id="evaluation-tab"
          role="tab" aria-selected="false" aria-controls="evaluation-panel">
    Evaluation <span class="tab-status waiting" id="evaluation-tab-status">Waiting</span>
  </button>
</div>

<section id="experiment-panel" class="tab-panel" role="tabpanel" aria-labelledby="experiment-tab">
  <div class="comparison-table-wrap">
    <table class="comparison-table">
      <thead><tr><th>Metric</th><th>V1</th><th>V2</th><th>V3</th></tr></thead>
      <tbody id="comparison-body"><tr><td colspan="4" class="empty-hint">Loading…</td></tr></tbody>
    </table>
  </div>

  <h2>Final responses</h2>
  <div class="answers-grid" id="answers-grid"></div>
</section>

<section id="evaluation-panel" class="tab-panel hidden" role="tabpanel" aria-labelledby="evaluation-tab">
  <div class="evaluation-placeholder">
    <div class="evaluation-header">
      <strong>Quality evaluation</strong>
      <div class="evaluation-controls">
        <div class="evaluation-actions" id="evaluation-actions"></div>
        <p id="evaluation-status">Not evaluated</p>
      </div>
    </div>
    <ol class="criteria-list" id="criteria-list"></ol>
  </div>

  <div class="comparison-table-wrap hidden" id="evaluation-results">
    <table class="comparison-table">
      <thead><tr><th>Criterion</th><th>V1</th><th>V2</th><th>V3</th></tr></thead>
      <tbody id="evaluation-body"></tbody>
    </table>
  </div>
</section>
</div>
"""

_EXPERIMENT_DETAIL_SCRIPT = r"""
const experimentId = location.pathname.split("/").filter(Boolean).pop();
const problemDisplay = document.getElementById("experiment-problem");
const experimentMeta = document.getElementById("experiment-meta");
const comparisonBody = document.getElementById("comparison-body");
const answersGrid = document.getElementById("answers-grid");
const criteriaList = document.getElementById("criteria-list");
const evaluationActions = document.getElementById("evaluation-actions");
const evaluationResults = document.getElementById("evaluation-results");
const evaluationBody = document.getElementById("evaluation-body");
let currentExperiment = null;

function selectTab(name) {
  const evaluationSelected = name === "evaluation";
  document.getElementById("experiment-panel").classList.toggle("hidden", evaluationSelected);
  document.getElementById("evaluation-panel").classList.toggle("hidden", !evaluationSelected);
  document.getElementById("experiment-tab").classList.toggle("active", !evaluationSelected);
  document.getElementById("evaluation-tab").classList.toggle("active", evaluationSelected);
  document.getElementById("experiment-tab").setAttribute("aria-selected", String(!evaluationSelected));
  document.getElementById("evaluation-tab").setAttribute("aria-selected", String(evaluationSelected));
}

document.getElementById("experiment-tab").addEventListener("click", () => selectTab("experiment"));
document.getElementById("evaluation-tab").addEventListener("click", () => selectTab("evaluation"));

function valueFor(item, key) {
  if (!item || item.status !== "completed") return item ? item.status : "—";
  if (key === "verdict") return VERDICT_LABELS[item.verdict] || item.verdict;
  if (key === "rounds") return `${item.rounds ?? "?"} / ${item.max_rounds ?? "?"}`;
  if (key === "model_calls") return item.model_calls ?? "—";
  if (key === "total_tokens") return item.total_tokens != null ? item.total_tokens.toLocaleString() : "—";
  if (key === "total_cost") return formatCost(item.total_cost);
  if (key === "duration_ms") return formatDuration(item.duration_ms);
  return "—";
}

function answerCard(item) {
  const label = VARIANT_LABELS[item.variant] || item.variant;
  if (item.status === "failed") {
    return `<article class="answer-card">
      <h3>${escapeHtml(label)}</h3>
      <div class="answer-meta">${statusBadge(item.status)}</div>
      <div class="error">${escapeHtml(item.error_message || "Unknown execution error")}</div>
      <div class="answer-actions"><button class="ghost retry-variant" data-variant="${item.variant}">Retry failed variant</button></div>
    </article>`;
  }
  if (item.status !== "completed") {
    return `<article class="answer-card"><h3>${escapeHtml(label)}</h3><p class="empty-hint">${escapeHtml(item.status)}</p></article>`;
  }
  return `<article class="answer-card">
    <h3>${escapeHtml(label)}</h3>
    <div class="answer-meta">${escapeHtml(VERDICT_LABELS[item.verdict] || item.verdict)} · ${formatCost(item.total_cost)} · ${formatDuration(item.duration_ms)}</div>
    <div class="details-content">${renderMarkdown(item.final_answer || "")}</div>
    <div class="answer-actions"><a href="/history/${item.id}">Open full replay →</a></div>
  </article>`;
}

function renderExperiment(experiment) {
  currentExperiment = experiment;
  problemDisplay.textContent = experiment.problem;
  const roles = experiment.config.roles || {};
  experimentMeta.innerHTML = [
    `<li><b>Status:</b> ${escapeHtml(experiment.status)}</li>`,
    `<li><b>Evaluation:</b> ${escapeHtml(experiment.evaluation_status.replaceAll("_", " "))}</li>`,
    `<li><b>Created:</b> ${new Date(experiment.created_at).toLocaleString()}</li>`,
    `<li><b>Max rounds:</b> ${experiment.max_rounds}</li>`,
    `<li><b>Total cost:</b> ${formatCost(experiment.total_cost)}</li>`,
    ...Object.entries(roles).map(([role, settings]) =>
      `<li><b>${escapeHtml(ROLE_LABELS[role] || role)}:</b> <code>${escapeHtml(settings.model)}</code> (${escapeHtml(settings.effort)})</li>`
    ),
  ].join("");
  renderEvaluation(experiment);
  const variants = Object.fromEntries(experiment.variants.map(item => [item.variant, item]));
  const ordered = [
    variants["v1-moderated-criteria"],
    variants["v2-posthoc-reviewer"],
    variants["v3-adversarial-reviewer"],
  ];
  const metrics = [
    ["Verdict", "verdict"], ["Rounds", "rounds"], ["Model calls", "model_calls"],
    ["Tokens", "total_tokens"], ["Cost", "total_cost"], ["Duration", "duration_ms"],
  ];
  comparisonBody.innerHTML = metrics.map(([label, key]) =>
    `<tr><th>${label}</th>${ordered.map(item => `<td>${escapeHtml(String(valueFor(item, key)))}</td>`).join("")}</tr>`
  ).join("");
  answersGrid.innerHTML = ordered.map(answerCard).join("");
}

function evaluationCell(record, criterionId) {
  if (!record) return '<span class="empty-hint">Not evaluated</span>';
  if (record.status === "failed") return `<span class="criterion-status violated">Failed</span><br><small>${escapeHtml(record.error_message || "")}</small>`;
  if (record.status !== "completed") return escapeHtml(record.status);
  const item = record.result.criteria.find(value => value.criterion_id === criterionId);
  if (!item) return "—";
  return `<span class="criterion-status ${item.status}">${escapeHtml(item.status)}</span><br><small><b>Evidence:</b> ${escapeHtml(item.evidence)}</small><br><small>${escapeHtml(item.explanation)}</small>`;
}

function renderEvaluation(experiment) {
  const statusEl = document.getElementById("evaluation-status");
  const criteria = experiment.evaluation_criteria || [];
  criteriaList.innerHTML = criteria.map(item => `<li><b>${escapeHtml(item.id)}</b> — ${escapeHtml(item.text)}</li>`).join("");
  const records = Object.fromEntries((experiment.evaluations || []).map(item => [item.variant, item]));
  const order = ["v1-moderated-criteria", "v2-posthoc-reviewer", "v3-adversarial-reviewer"];
  const tabStatus = document.getElementById("evaluation-tab-status");
  const evaluationDone = experiment.evaluation_status === "completed";
  tabStatus.textContent = evaluationDone ? "Done" : "Waiting";
  tabStatus.classList.toggle("done", evaluationDone);
  tabStatus.classList.toggle("waiting", !evaluationDone);
  tabStatus.title = `Evaluation status: ${experiment.evaluation_status.replaceAll("_", " ")}`;
  if (!criteria.length) {
    statusEl.textContent = "Not evaluated — no criteria were supplied.";
    evaluationActions.innerHTML = "";
    evaluationResults.classList.add("hidden");
    return;
  }
  statusEl.textContent = experiment.evaluation_status.replaceAll("_", " ");
  const canEvaluate = experiment.status === "completed" && experiment.evaluation_status !== "completed";
  evaluationActions.innerHTML = canEvaluate
    ? `<button id="evaluate-btn">${["partial", "failed"].includes(experiment.evaluation_status) ? "Retry failed evaluations" : "Evaluate outputs"}</button>`
    : (experiment.status !== "completed" ? '<span class="empty-hint">Complete all workflow variants before evaluating.</span>' : "");
  const completed = Object.values(records).filter(item => item.status === "completed");
  if (!completed.length && !Object.keys(records).length) {
    evaluationResults.classList.add("hidden");
    return;
  }
  evaluationResults.classList.remove("hidden");
  const summary = `<tr><th>Result</th>${order.map(id => {
    const record = records[id];
    if (!record || record.status !== "completed") return `<td>${record ? escapeHtml(record.status) : "—"}</td>`;
    return `<td><b>${record.result.passed ? "Pass" : "Fail"}</b><br>${Math.round(record.result.coverage * 100)}% coverage<br>${record.total_tokens != null ? record.total_tokens.toLocaleString() + " tokens" : "—"} · ${formatDuration(record.duration_ms)} · ${formatCost(record.total_cost)}</td>`;
  }).join("")}</tr>`;
  evaluationBody.innerHTML = summary + criteria.map(criterion =>
    `<tr><th>${escapeHtml(criterion.id)} — ${escapeHtml(criterion.text)}</th>${order.map(id => `<td>${evaluationCell(records[id], criterion.id)}</td>`).join("")}</tr>`
  ).join("");
}

async function evaluateOutputs(button) {
  button.disabled = true;
  button.textContent = "Evaluating…";
  try {
    const response = await fetch(`/api/experiments/${experimentId}/evaluate`, { method: "POST" });
    if (!response.ok) {
      const body = await response.json();
      throw new Error(body.error || `Evaluation failed (${response.status})`);
    }
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const parts = buffer.split("\n\n"); buffer = parts.pop();
      for (const part of parts) {
        const line = part.trim(); if (!line.startsWith("data:")) continue;
        const event = JSON.parse(line.slice(5).trim());
        document.getElementById("evaluation-status").textContent = event.type === "evaluation_started"
          ? `Evaluating ${VARIANT_LABELS[event.variant]}…`
          : (event.type === "evaluation_failed" ? `${VARIANT_LABELS[event.variant]} failed: ${event.message}` : "Evaluating…");
        if (event.type === "evaluation_finished") location.reload();
      }
    }
  } catch (error) {
    errorEl.textContent = String(error.message || error); errorEl.classList.remove("hidden");
    button.disabled = false; button.textContent = "Evaluate outputs";
  }
}

evaluationActions.addEventListener("click", event => {
  const button = event.target.closest("#evaluate-btn");
  if (button) evaluateOutputs(button);
});

async function retryVariant(variant, button) {
  button.disabled = true;
  button.textContent = "Retrying…";
  try {
    const response = await fetch(`/api/experiments/${experimentId}/retry/${variant}`, { method: "POST" });
    if (!response.ok) {
      const body = await response.json();
      throw new Error(body.error || `Retry failed (${response.status})`);
    }
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const parts = buffer.split("\n\n");
      buffer = parts.pop();
      for (const part of parts) {
        const line = part.trim();
        if (!line.startsWith("data:")) continue;
        const event = JSON.parse(line.slice(5).trim());
        if (event.type === "experiment_completed") location.reload();
      }
    }
  } catch (error) {
    errorEl.textContent = String(error.message || error);
    errorEl.classList.remove("hidden");
    button.disabled = false;
    button.textContent = "Retry failed variant";
  }
}

answersGrid.addEventListener("click", event => {
  const button = event.target.closest(".retry-variant");
  if (button) retryVariant(button.dataset.variant, button);
});

fetch(`/api/experiments/${experimentId}`).then(response => {
  if (!response.ok) throw new Error(`Experiment ${experimentId} not found`);
  return response.json();
}).then(renderExperiment).catch(error => {
  errorEl.textContent = String(error.message || error);
  errorEl.classList.remove("hidden");
});
"""

EXPERIMENT_DETAIL_HTML = _page(
    active="experiments", body=_EXPERIMENT_DETAIL_BODY, script=_EXPERIMENT_DETAIL_SCRIPT
)


# --- History ----------------------------------------------------------------

_HISTORY_BODY = """
<h1>History</h1>
<p class="sub">Every completed run, most recent first. Click a row to replay it.</p>
<div class="history-toolbar">
  <input type="search" id="history-search" placeholder="Search problem statements…">
</div>
<div id="error" class="error hidden"></div>
<table class="runs-table" id="runs-table">
  <thead>
    <tr>
      <th data-key="created_at">Timestamp</th>
      <th data-key="variant">Variant</th>
      <th data-key="problem">Problem</th>
      <th data-key="verdict">Verdict</th>
      <th data-key="rounds">Rounds</th>
      <th data-key="last_score">Score</th>
      <th data-key="total_cost">Cost</th>
      <th data-key="total_tokens">Tokens</th>
      <th data-key="duration_ms">Duration</th>
    </tr>
  </thead>
  <tbody id="runs-tbody"><tr><td colspan="9" class="empty-hint">Loading…</td></tr></tbody>
</table>
"""

_HISTORY_SCRIPT = r"""
let allRuns = [];
let sortKey = "id", sortDir = -1;
const searchEl = document.getElementById("history-search");
const tbodyEl = document.getElementById("runs-tbody");

function renderRunsTable() {
  const q = searchEl.value.trim().toLowerCase();
  const rows = allRuns
    .filter(r => !q || (r.problem || "").toLowerCase().includes(q) || (r.restated_problem || "").toLowerCase().includes(q) || (r.variant || "").toLowerCase().includes(q))
    .slice()
    .sort((a, b) => {
      const av = a[sortKey], bv = b[sortKey];
      if (av == null && bv == null) return 0;
      if (av == null) return 1;
      if (bv == null) return -1;
      return sortDir * (av > bv ? 1 : av < bv ? -1 : 0);
    });

  if (!rows.length) {
    tbodyEl.innerHTML = `<tr><td colspan="9" class="empty-hint">${allRuns.length ? "No runs match your search." : "No runs yet — go run something on Home."}</td></tr>`;
    return;
  }

  tbodyEl.innerHTML = rows.map(r => {
    const verdictCls = r.verdict === "consensus" ? "ok" : "warn";
    const problem = escapeHtml(r.problem);
    return `<tr data-id="${r.id}">
      <td>${new Date(r.created_at).toLocaleString()}</td>
      <td>${VARIANT_LABELS[r.variant] || r.variant}</td>
      <td class="problem-cell" title="${problem}">${problem}</td>
      <td><span class="badge ${verdictCls}">${VERDICT_LABELS[r.verdict] || r.verdict}</span></td>
      <td>${r.rounds ?? "?"} / ${r.max_rounds ?? "?"}</td>
      <td>${r.last_score != null ? `${r.last_score}/10` : "—"}</td>
      <td>${formatCost(r.total_cost)}</td>
      <td>${r.total_tokens != null ? r.total_tokens.toLocaleString() : "—"}</td>
      <td>${formatDuration(r.duration_ms)}</td>
    </tr>`;
  }).join("");
}

document.querySelectorAll("#runs-table th[data-key]").forEach(th => {
  th.addEventListener("click", () => {
    const key = th.dataset.key;
    sortDir = sortKey === key ? -sortDir : -1;
    sortKey = key;
    renderRunsTable();
  });
});

tbodyEl.addEventListener("click", (e) => {
  const tr = e.target.closest("tr[data-id]");
  if (tr) location.href = `/history/${tr.dataset.id}`;
});

searchEl.addEventListener("input", renderRunsTable);

fetch("/api/history").then(r => r.json()).then(runs => {
  allRuns = runs;
  renderRunsTable();
}).catch(err => {
  errorEl.textContent = String(err);
  errorEl.classList.remove("hidden");
});
"""

HISTORY_HTML = _page(active="history", body=_HISTORY_BODY, script=_HISTORY_SCRIPT)


# --- Replay -------------------------------------------------------------------

_REPLAY_BODY = """
<a class="back-link" href="/history">&larr; Back to history</a>
<div class="replay-header">
  <div>
    <h1>Replay</h1>
    <p class="sub" id="run-subtitle">Loading…</p>
  </div>
  <ul class="meta replay-meta" id="run-meta"></ul>
</div>

<div id="error" class="error hidden"></div>

<div id="layout" class="layout hidden">
  <div class="panel flow-panel">
    <h2>Flow</h2>
    <ul class="flow-list" id="flow-list"></ul>
    <div class="exports" id="exports">
      <button class="ghost" data-fmt="md">Download .md</button>
      <button class="ghost" data-fmt="html">Download .html</button>
      <button class="ghost" data-fmt="json">Download .json</button>
    </div>
  </div>
  <div class="panel details-panel">
    <div class="details-title" id="details-title">Details</div>
    <ul class="details-meta" id="details-meta"></ul>
    <div class="details-content" id="details-content">
      <p class="empty-hint">Loading…</p>
    </div>
  </div>
</div>
"""

_REPLAY_SCRIPT = r"""
const runId = location.pathname.split("/").filter(Boolean).pop();
const subtitleEl = document.getElementById("run-subtitle");
const runMetaEl = document.getElementById("run-meta");

fetch(`/api/history/${runId}`).then(r => {
  if (!r.ok) throw new Error(`Run ${runId} not found`);
  return r.json();
}).then(run => {
  subtitleEl.textContent = run.problem;
  runMetaEl.innerHTML = [
    `<li><b>Variant:</b> ${VARIANT_LABELS[run.variant] || run.variant}</li>`,
    `<li><b>Verdict:</b> ${VERDICT_LABELS[run.verdict] || run.verdict}</li>`,
    `<li><b>Rounds:</b> ${run.rounds ?? "?"} of ${run.max_rounds ?? "?"}</li>`,
    `<li><b>Run at:</b> ${new Date(run.created_at).toLocaleString()}</li>`,
    `<li><b>Duration:</b> ${formatDuration(run.duration_ms)}</li>`,
  ].join("");
  finalState = run.state;
  const totals = usageTotals(run.state);
  runMetaEl.innerHTML += [
    `<li><b>Model calls:</b> ${totals.calls}</li>`,
    `<li><b>Total tokens:</b> ${totals.tokens != null ? totals.tokens.toLocaleString() : "—"}</li>`,
    `<li><b>Total cost:</b> ${formatCost(totals.cost)}</li>`,
  ].join("");
  renderFlowFromEntries(buildEntriesFromState(run.state));
  layoutEl.classList.remove("hidden");
}).catch(err => {
  errorEl.textContent = String(err.message || err);
  errorEl.classList.remove("hidden");
});
"""

REPLAY_HTML = _page(active="history", body=_REPLAY_BODY, script=_REPLAY_SCRIPT)
