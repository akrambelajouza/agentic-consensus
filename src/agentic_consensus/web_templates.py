"""Self-contained HTML/CSS/JS templates for runs, experiments, and replay.

Every page ships as one self-contained response — inline ``<style>``/``<script>``,
no CDN, no build step — same "no external assets" convention as ``transcript.py``'s
standalone HTML export. That convention is about what the *browser* fetches; nothing
stops the *Python source* from sharing string constants across pages, which is what
this module does: ``_SHARED_CSS``/``_SHARED_JS`` hold everything Home, History, and
Replay all need (the flow/details panels, the hand-rolled Markdown renderer, the nav
bar), so a visual or behavioural tweak is made once instead of drifting across three
copies.

The New Run page streams a run live over SSE and renders it node by node. Replay does the same
rendering with none of the streaming: it fetches a finished run's full state and
reconstructs the identical sequence of flow entries in one shot
(``buildEntriesFromState``), then calls the exact same ``buildEntry``/``makeFlowLi``
functions Home's live path uses — so a replayed run looks pixel-identical to how it
looked live.
"""

from __future__ import annotations

import json

from .variants.v1_posthoc_reviewer import prompts as v1_prompts
from .variants.v2_moderated_reviewer import prompts as v2_prompts
from .variants.v3_adversarial_reviewer import prompts as v3_prompts

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
input[type=number], input[type=text], input[type=password], select { width:100%; font:inherit; padding:.6rem .75rem;
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

.topnav { display:flex; justify-content:space-between; align-items:center; gap:1rem;
          margin:0 0 1.75rem; padding-bottom:1rem; border-bottom:1px solid var(--line); }
.topnav-links { display:flex; gap:1.25rem; flex-wrap:wrap; }
.topnav-actions { display:flex; align-items:center; gap:1rem; }
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
.page-header { display:flex; justify-content:space-between; align-items:center; gap:1rem;
               margin:0 0 .35rem; }
.page-header h1 { margin:0; }
.link-button { display:inline-block; padding:.55rem 1rem; border-radius:8px;
               background:var(--accent); color:#fff; font-size:.85rem;
               font-weight:700; text-decoration:none; }
.link-button:hover { filter:brightness(1.08); }
@media (max-width: 560px) {
  .page-header { align-items:flex-start; }
}

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
.model-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:1rem;
              margin:0 0 1.25rem; }
.model-field { min-width:0; }
.model-field .field-help { white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.ts-wrapper.single .ts-control,.ts-dropdown { background:var(--card); color:var(--fg);
    border-color:var(--line); }
.ts-control input { color:var(--fg); }
.ts-dropdown .active { background:rgba(59,91,219,.14); color:var(--fg); }
.model-option { display:flex; flex-direction:column; line-height:1.35; }
.model-option small { color:var(--muted); }
.settings-summary { display:flex; gap:.75rem; flex-wrap:wrap; margin:1rem 0; }
.settings-summary .panel { min-width:11rem; }
.settings-summary strong { display:block; font-size:1.25rem; }
.settings-controls { display:flex; justify-content:space-between; align-items:flex-end;
                     gap:1.25rem; flex-wrap:wrap; margin-bottom:1rem; }
.settings-controls > .row { flex:1 1 25rem; }
.settings-controls .settings-summary { margin:0; justify-content:flex-end; }
.settings-form { max-width:48rem; }
.settings-form .field-help { margin-bottom:1rem; }
.case-header { padding:1.25rem 0 2.75rem; border-bottom:1px solid var(--line); }
.case-header .eyebrow { color:var(--accent); font-size:.78rem; font-weight:800;
                        letter-spacing:.1em; text-transform:uppercase; margin-bottom:.7rem; }
.case-header h1 { font-size:clamp(2rem,5vw,3.6rem); line-height:1.1;
                  margin-bottom:1rem; }
.case-header .subtitle { color:var(--muted); font-size:1.12rem; margin:0; }
.case-section { padding:2.75rem 0; border-bottom:1px solid var(--line); }
.case-section h2 { color:var(--fg); font-size:1.4rem; text-transform:none;
                   letter-spacing:0; margin-bottom:.8rem; }
.case-section > p { max-width:55rem; color:var(--muted); }
.case-section .lead { color:var(--fg); font-size:1.05rem; }
.case-two-column { display:grid; grid-template-columns:repeat(2,minmax(0,1fr));
                   gap:2.5rem; border-bottom:1px solid var(--line); }
.case-two-column .case-section { border-bottom:0; }
.case-two-column .case-section:last-child { border-left:1px solid var(--line);
                                            padding-left:2.5rem; }
.case-stack { display:flex; flex-wrap:wrap; gap:.55rem; margin-top:1.2rem; }
.case-tag { border:1px solid var(--line); border-radius:999px; background:var(--card);
            padding:.35rem .75rem; font-size:.8rem; font-weight:700; }
.case-architectures { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:1rem;
                      margin-top:1.4rem; }
.case-card { border:1px solid var(--line); border-radius:12px; background:var(--card);
             overflow:hidden; min-width:0; }
.case-card-content { padding:1rem 1.1rem 1.2rem; }
.case-card .version { color:var(--accent); font-size:.75rem; font-weight:800; }
.case-card h3 { margin:.3rem 0 .4rem; font-size:1.05rem; }
.case-card p { margin:0; color:var(--muted); font-size:.9rem; }
.case-card .run-details-link { margin-top:1rem; }
.workflow-image { display:block; width:100%; height:22rem; object-fit:contain;
                  border-bottom:1px solid var(--line); background:#111722; }
.case-metrics { display:grid; grid-template-columns:repeat(5,minmax(0,1fr)); gap:.75rem;
                margin-top:1.3rem; }
.case-metric { border:1px solid var(--line); border-radius:10px; padding:.9rem;
               background:var(--card); }
.case-metric strong,.case-metric span { display:block; }
.case-metric span { color:var(--muted); font-size:.8rem; margin-top:.25rem; }
.case-questions { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:.75rem;
                  margin-top:1.2rem; }
.case-question { border-left:3px solid var(--accent); background:var(--card);
                 border-radius:0 8px 8px 0; padding:.8rem 1rem; font-size:.9rem; }
.case-footer { padding:2rem 0 .5rem; color:var(--muted); font-size:.85rem; }
.workflow-detail { scroll-margin-top:1rem; }
.workflow-detail > p { max-width:none; }
.workflow-detail .version { color:var(--accent); font-size:.78rem; font-weight:800; }
.workflow-detail-content { display:grid; grid-template-columns:minmax(0,1fr) minmax(0,2fr);
                           gap:2rem; align-items:start; margin-top:1.25rem; }
.workflow-detail-content > img { display:block; width:100%; max-height:24rem;
                                 object-fit:contain; border-radius:10px;
                                 background:#111722; }
.workflow-detail-content .role-grid { grid-template-columns:1fr; margin-top:0; }
.role-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:1rem;
             margin-top:1.25rem; }
.role-grid.two-roles { grid-template-columns:repeat(2,minmax(0,1fr)); }
.role-card { border:1px solid var(--line); border-radius:10px; background:var(--card);
             padding:1rem; }
.role-card-header { display:flex; align-items:flex-start; justify-content:space-between;
                    gap:1rem; margin-bottom:.4rem; }
.role-prompt-actions { display:flex; flex-wrap:wrap; justify-content:flex-end; gap:.35rem; }
.role-card h3 { margin:0; font-size:1rem; }
.role-card p { margin:0; color:var(--muted); font-size:.9rem; }
.show-prompt { flex:0 0 auto; padding:.25rem .55rem; border:1px solid var(--accent);
               border-radius:6px; background:transparent; color:var(--accent);
               font:inherit; font-size:.72rem; font-weight:700; cursor:pointer; }
.show-prompt:hover { background:var(--accent); color:white; }
.prompt-modal { width:min(48rem,calc(100% - 2rem)); max-height:85vh; padding:0;
                border:1px solid var(--line); border-radius:12px;
                background:var(--bg); color:var(--fg); box-shadow:0 20px 60px #0008; }
.prompt-modal::backdrop { background:#0009; }
.prompt-modal-header { display:flex; align-items:center; justify-content:space-between;
                       gap:1rem; padding:1rem 1.25rem; border-bottom:1px solid var(--line); }
.prompt-modal-header h2 { margin:0; }
.prompt-modal-close { border:0; background:transparent; color:var(--muted);
                      font-size:1.6rem; line-height:1; cursor:pointer; }
.prompt-modal pre { max-height:65vh; margin:0; padding:1.25rem; overflow:auto;
                    border:0; border-radius:0; background:var(--card); }
.workflow-path { color:var(--accent); font-weight:700; font-size:.88rem; }
.comparison-table-wrap { overflow-x:auto; margin:1.25rem 0; }
.comparison-table { width:100%; border-collapse:collapse; }
.comparison-table th,.comparison-table td { border-bottom:1px solid var(--line);
                    padding:.65rem .75rem; text-align:left; vertical-align:top; }
.comparison-table th { color:var(--muted); font-size:.78rem; text-transform:uppercase; }
.run-details-link { display:inline-block; padding:.45rem .7rem; border:1px solid var(--accent);
                    border-radius:7px; color:var(--accent); font-size:.78rem;
                    font-weight:700; text-decoration:none; white-space:nowrap; }
.run-details-link:hover { background:var(--accent); color:white; }
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
  .architecture-list,.answers-grid,.model-grid,.case-architectures,.role-grid { grid-template-columns:1fr; }
  .role-grid.two-roles { grid-template-columns:1fr; }
  .case-metrics { grid-template-columns:repeat(2,minmax(0,1fr)); }
}
@media (max-width: 680px) {
  .case-questions,.case-metrics { grid-template-columns:1fr; }
  .case-two-column { grid-template-columns:1fr; gap:0; }
  .case-two-column .case-section:first-child { padding-bottom:1.5rem; }
  .case-two-column .case-section:last-child { border-left:0; padding:1.5rem 0 2.75rem; }
  .workflow-detail-content { grid-template-columns:1fr; }
  .workflow-detail-content > img { width:auto; max-width:100%; justify-self:center; }
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
  "v1-posthoc-reviewer": "V1 — Post-hoc reviewer",
  "v2-moderated-reviewer": "V2 — Moderated reviewer",
  "v3-adversarial-reviewer": "V3 — Adversarial reviewer",
};
const modelCatalogPromise = fetch("/api/models").then(async response => {
  const payload = await response.json();
  if (!response.ok || payload.error) throw new Error(payload.error || "Could not load models");
  return payload;
});

function perMillion(value) {
  if (value == null || value === "") return "price unavailable";
  const amount = Number(value) * 1000000;
  return Number.isFinite(amount) ? `$${amount.toLocaleString(undefined, {maximumFractionDigits: 2})}/M` : "price unavailable";
}

function initModelSelect(element, role, catalog, options = {}) {
  element.innerHTML = "";
  const choices = catalog.models.map(model => ({...model}));
  const control = new TomSelect(element, {
    valueField: "id", labelField: "name", searchField: ["name", "provider", "id"],
    options: choices, maxOptions: null, create: false,
    render: {
      option(data, escape) {
        return `<div class="model-option"><strong>${escape(data.name)}</strong><small>${escape(data.provider)} · ${escape(data.id)} · input ${escape(perMillion(data.prompt_price))} · output ${escape(perMillion(data.completion_price))}</small></div>`;
      },
      item(data, escape) { return `<div title="${escape(data.id)}">${escape(data.name)}</div>`; },
    },
  });
  const selected = options.value || catalog.defaults[role];
  if (selected) control.setValue(selected, true);
  if (options.disabled) control.disable();
  return control;
}

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
  const hasModerator = state.variant !== "v1-posthoc-reviewer";
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
        f'<a href="/"{cls("home")}>Home</a>'
        f'<a href="/experiments"{cls("consensus")}>Consensus</a>'
        f'<a href="/history"{cls("single-run")}>Single Run</a>'
        "</div>"
        '<div class="topnav-actions">'
        f'<a href="/workflow-details"{cls("workflow-details")}>Workflow details</a>'
        f'<a href="/settings"{cls("settings")}>Settings</a>'
        '<button type="button" id="theme-toggle" class="theme-toggle" '
        'aria-label="Toggle light/dark theme"></button></div>'
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
<link rel="stylesheet" href="/assets/tom-select/tom-select.default.min.css">
<style>{_SHARED_CSS}</style>
<script>{_THEME_INIT_SCRIPT}</script>
</head>
<body><main>
{_nav_html(active)}
{body}
</main>
<script src="/assets/tom-select/tom-select.complete.min.js"></script>
<script>
{_SHARED_JS}
{script}
</script>
</body></html>
"""


# --- Home -----------------------------------------------------------------

_HOME_BODY = """
<a class="back-link" href="/run">&larr; Back to runs</a>
<h1>Agentic Consensus</h1>
<p class="sub">Run and inspect alternative author/reviewer workflow designs.</p>
<div class="row field">
  <div class="field" style="min-width:18rem;">
    <label for="variant">Workflow variant</label>
    <select id="variant"></select>
  </div>
</div>
<div class="model-grid" id="model-meta">
  <div class="model-field hidden" id="moderator-model-field"><label for="moderator-model">Moderator</label><select id="moderator-model"></select></div>
  <div class="model-field"><label for="author-model">Author</label><select id="author-model"></select></div>
  <div class="model-field"><label for="reviewer-model">Reviewer</label><select id="reviewer-model"></select></div>
</div>
<ul class="meta compact hidden" id="run-totals"></ul>

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
const moderatorModelEl = document.getElementById("moderator-model");
const authorModelEl = document.getElementById("author-model");
const reviewerModelEl = document.getElementById("reviewer-model");
let modelControls = {};

let pendingLi = null;    // the "Working…" placeholder awaiting the next node event

async function onConfigLoaded(cfg) {
  variantEl.innerHTML = cfg.variants.map(v =>
    `<option value="${v.id}">${v.label}</option>`
  ).join("");
  variantEl.value = cfg.default_variant;
  try {
    const catalog = await modelCatalogPromise;
    modelControls = {
      moderator: initModelSelect(moderatorModelEl, "moderator", catalog),
      agent_a: initModelSelect(authorModelEl, "agent_a", catalog),
      agent_b: initModelSelect(reviewerModelEl, "agent_b", catalog),
    };
  } catch (error) {
    errorEl.textContent = String(error.message || error);
    errorEl.classList.remove("hidden");
    runBtn.disabled = true;
  }
  const paintVariant = () => document.getElementById("moderator-model-field").classList.toggle("hidden", variantEl.value === "v1-posthoc-reviewer");
  variantEl.addEventListener("change", paintVariant);
  paintVariant();
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

async function runConsensus(problem, rounds, variant, models) {
  resetUI();
  runBtn.disabled = true;
  statusEl.classList.remove("hidden");
  statusText.textContent = "Starting…";

  try {
    const resp = await fetch("/api/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ problem, rounds, variant, models }),
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
  const models = {
    agent_a: authorModelEl.value,
    agent_b: reviewerModelEl.value,
  };
  if (variantEl.value !== "v1-posthoc-reviewer") models.moderator = moderatorModelEl.value;
  runConsensus(problem, rounds, variantEl.value, models);
});

problemEl.addEventListener("keydown", (e) => {
  if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
    form.requestSubmit();
  }
});
"""

RUN_HTML = _page(active="single-run", body=_HOME_BODY, script=_HOME_SCRIPT)

_LANDING_BODY = """
<header class="case-header">
  <div class="eyebrow">AI Engineering Case Study</div>
  <h1>Evaluating Agentic Consensus Workflows</h1>
  <p class="subtitle">I built and compared different AI review workflows to see when extra agents improve quality and when the extra cost is worth it.</p>
</header>

<div class="case-two-column">
  <section class="case-section">
    <h2>Why I built it</h2>
    <p class="lead">I built this project after seeing the same pattern many times: one AI agent creates an answer, but a second agent finds missing details, edge cases, or problems. The first agent then improves its answer. The second agent checks it again.</p>
    <p>This happened when reviewing pull requests, creating AI skills, and building evaluation frameworks. I sometimes had to move an answer back and forth between different models until the result was good enough.</p>
  </section>

  <section class="case-section">
    <h2>How I built it</h2>
    <p>I use <strong>LangGraph</strong> to build the workflows and manage the steps between agents. I use <strong>LangSmith</strong> to trace runs and inspect what each agent does. The app also evaluates final answers against saved criteria.</p>
    <div class="case-stack">
      <span class="case-tag">LangGraph</span>
      <span class="case-tag">LangSmith</span>
      <span class="case-tag">LLM Evaluation</span>
      <span class="case-tag">Multi-Agent Workflows</span>
      <span class="case-tag">Cost Analysis</span>
      <span class="case-tag">Tracing &amp; Observability</span>
    </div>
  </section>
</div>

<section class="case-section workflow-detail">
  <h2>Three ways to reach consensus</h2>
  <p>The small workflow became an experiment. I created three versions to compare their answers, cost, tokens, and speed.</p>
  <div class="case-architectures">
    <article class="case-card">
      <img class="workflow-image" src="/assets/workflows/v1.jpg" alt="V1 graph: Agent A and Agent B review loop">
      <div class="case-card-content">
        <span class="version">V1 — Two agents</span>
        <h3>Post-hoc Review</h3>
        <p>Agent A writes the answer first. Agent B then creates review criteria and checks the answer. If changes are needed, it sends feedback to Agent A.</p>
        <a class="run-details-link" href="/workflow-details#v1">More details</a>
      </div>
    </article>
    <article class="case-card">
      <img class="workflow-image" src="/assets/workflows/v2.jpg" alt="V2 graph: intake, Agent A and Agent B review loop, then finalize">
      <div class="case-card-content">
        <span class="version">V2 — With a moderator</span>
        <h3>Moderated Review</h3>
        <p>A moderator first makes the user's problem clearer and creates fixed criteria. Agent A writes the answer, and Agent B reviews it against those criteria.</p>
        <a class="run-details-link" href="/workflow-details#v2">More details</a>
      </div>
    </article>
    <article class="case-card">
      <img class="workflow-image" src="/assets/workflows/v3.jpg" alt="V3 graph: intake, Agent A and adversarial Agent B review loop, then finalize">
      <div class="case-card-content">
        <span class="version">V3 — with an adversarial reviewer</span>
        <h3>Adversarial Review</h3>
        <p>This version also starts with a moderator. But Agent B tries to prove that the answer is not ready. It approves only when it cannot find a real blocker.</p>
        <a class="run-details-link" href="/workflow-details#v3">More details</a>
      </div>
    </article>
  </div>
</section>

<section class="case-section">
  <h2>What I compare</h2>
  <p>I run the same tasks through different workflows and model combinations, then compare the results.</p>
  <div class="case-metrics">
    <div class="case-metric"><strong>Quality</strong><span>How well the final answer meets the criteria</span></div>
    <div class="case-metric"><strong>Iterations</strong><span>How many revisions were needed</span></div>
    <div class="case-metric"><strong>Tokens</strong><span>Total input and output usage</span></div>
    <div class="case-metric"><strong>Cost</strong><span>Provider-reported model cost</span></div>
    <div class="case-metric"><strong>Latency</strong><span>Total time for the workflow</span></div>
  </div>
</section>

<section class="case-section">
  <h2>Questions I want to answer</h2>
  <div class="case-questions">
    <div class="case-question">Does an intake moderator improve the result enough to justify its extra cost?</div>
    <div class="case-question">Does an adversarial reviewer find more useful problems than a normal reviewer?</div>
    <div class="case-question">Can a cheaper model review almost as well as an expensive model?</div>
    <div class="case-question">When does another review round stop being useful?</div>
    <div class="case-question">Which workflow gives the best balance between quality, cost, and speed?</div>
  </div>
</section>

<footer class="case-footer">AI engineering project: orchestration, evaluation, tracing, and cost-quality trade-offs.</footer>
"""

HOME_HTML = _page(active="home", body=_LANDING_BODY, script="")
# Backwards-compatible template name for code importing the old home/run page.
INDEX_HTML = RUN_HTML


# --- Workflow details ---------------------------------------------------------

_WORKFLOW_DETAILS_BODY = """
<a class="back-link" href="/">&larr; Back to home</a>
<h1>How the workflows work</h1>
<p class="sub">All versions repeat the same basic idea: Agent A writes, Agent B reviews, and Agent A revises when needed. The difference is when criteria are created and how Agent B reviews the answer.</p>

<section class="case-section workflow-detail" id="v1">
  <div class="workflow-detail-header">
    <span class="version">V1 — Two agents</span>
    <h2>Post-hoc Review</h2>
    <p class="workflow-path">Agent A → Agent B → revise or finish</p>
    <p>This is the simplest and cheapest version. There is no moderator. Agent B creates the criteria only after Agent A has written the first answer.</p>
  </div>
  <div class="workflow-detail-content">
    <img src="/assets/workflows/v1.jpg" alt="V1 author and reviewer graph">
    <div class="role-grid">
      <article class="role-card"><div class="role-card-header"><h3>Agent A — Author</h3><button class="show-prompt" type="button" data-prompt="v1_agent_a">Show prompt</button></div><p>Receives the original user problem and writes a complete answer. After a rejection, it receives Agent B's criteria, feedback, and required changes, then writes a complete revised answer.</p></article>
      <article class="role-card"><div class="role-card-header"><h3>Agent B — Reviewer</h3><button class="show-prompt" type="button" data-prompt="v1_agent_b">Show prompt</button></div><p>Creates three to six checkable criteria from the original problem and reviews the answer in the same call. It gives a score, explains problems, requests changes, and decides whether to approve.</p></article>
    </div>
  </div>
  <p>If Agent B approves, the workflow ends. Otherwise Agent A tries again until approval, the round limit, or the stall limit is reached.</p>
</section>

<section class="case-section workflow-detail" id="v2">
  <div class="workflow-detail-header">
    <span class="version">V2 — With a moderator</span>
    <h2>Moderated Review</h2>
    <p class="workflow-path">Moderator → Agent A → Agent B → Moderator</p>
    <p>This version creates the criteria before the first answer. The criteria stay fixed, so the reviewer cannot change the goal after seeing the proposal.</p>
  </div>
  <div class="workflow-detail-content">
    <img src="/assets/workflows/v2.jpg" alt="V2 moderated author and reviewer graph">
    <div class="role-grid">
      <article class="role-card"><div class="role-card-header"><h3>Moderator — Intake and final answer</h3><div class="role-prompt-actions"><button class="show-prompt" type="button" data-prompt="v2_moderator_intake">Intake prompt</button><button class="show-prompt" type="button" data-prompt="v2_moderator_success">Success prompt</button><button class="show-prompt" type="button" data-prompt="v2_moderator_failure">Failure prompt</button></div></div><p>First, it rewrites the user's problem clearly and creates three to six fixed acceptance criteria. At the end, it prepares the final result and clearly reports any criteria that are still not satisfied.</p></article>
      <article class="role-card"><div class="role-card-header"><h3>Agent A — Author</h3><button class="show-prompt" type="button" data-prompt="v2_agent_a">Show prompt</button></div><p>Receives the clearer problem and fixed criteria before writing. On later rounds, it also receives the previous review and must return a full revised answer.</p></article>
      <article class="role-card"><div class="role-card-header"><h3>Agent B — Reviewer</h3><button class="show-prompt" type="button" data-prompt="v2_agent_b">Show prompt</button></div><p>Checks the answer only against the fixed criteria. It gives a score, explains what is wrong, lists required changes, and approves when the answer is ready.</p></article>
    </div>
  </div>
  <p>A deterministic routing rule—not another LLM—chooses whether to return to Agent A or continue to the moderator's final step.</p>
</section>

<section class="case-section workflow-detail" id="v3">
  <div class="workflow-detail-header">
    <span class="version">V3 — With an adversarial reviewer</span>
    <h2>Adversarial Review</h2>
    <p class="workflow-path">Moderator → Agent A → Adversarial Agent B → Moderator</p>
    <p>V3 keeps the same moderator and fixed criteria as V2. The difference is Agent B: its main goal is to prove that the answer is not ready.</p>
  </div>
  <div class="workflow-detail-content">
    <img src="/assets/workflows/v3.jpg" alt="V3 moderated graph with an adversarial reviewer">
    <div class="role-grid">
      <article class="role-card"><div class="role-card-header"><h3>Moderator — Intake and final answer</h3><div class="role-prompt-actions"><button class="show-prompt" type="button" data-prompt="v3_moderator_intake">Intake prompt</button><button class="show-prompt" type="button" data-prompt="v3_moderator_success">Success prompt</button><button class="show-prompt" type="button" data-prompt="v3_moderator_failure">Failure prompt</button></div></div><p>Creates the clear problem and fixed criteria before Agent A starts. At the end, it presents the best result and any remaining blockers.</p></article>
      <article class="role-card"><div class="role-card-header"><h3>Agent A — Author</h3><button class="show-prompt" type="button" data-prompt="v3_agent_a">Show prompt</button></div><p>Writes against the fixed criteria. When Agent B finds a blocker, Agent A receives the evidence and requested correction, then writes the complete answer again.</p></article>
      <article class="role-card"><div class="role-card-header"><h3>Agent B — Adversarial reviewer</h3><button class="show-prompt" type="button" data-prompt="v3_agent_b">Show prompt</button></div><p>Looks for missing requirements, violated criteria, edge cases, ambiguities, and risks. It must provide evidence for real blockers. It does not give a numeric score and approves only when no blocking defect remains.</p></article>
    </div>
  </div>
  <p>The routing rule repeats the author/reviewer loop while blocking findings remain, unless the round or stall limit ends the process.</p>
</section>

<section class="case-section">
  <h2>Evaluation happens after the workflows</h2>
  <p>The optional experiment evaluator is separate from the moderator and reviewers above. It receives one anonymized final answer at a time and checks it against the evaluation criteria supplied by the user.</p>
</section>

<dialog class="prompt-modal" id="prompt-modal" aria-labelledby="prompt-modal-title">
  <div class="prompt-modal-header">
    <h2 id="prompt-modal-title">Agent prompt</h2>
    <button class="prompt-modal-close" id="prompt-modal-close" type="button" aria-label="Close prompt">&times;</button>
  </div>
  <pre id="prompt-modal-content"></pre>
</dialog>
"""

_WORKFLOW_PROMPTS = {
    "v1_agent_a": {"title": "V1 · Agent A — Author", "prompt": v1_prompts.AGENT_A},
    "v1_agent_b": {"title": "V1 · Agent B — Reviewer", "prompt": v1_prompts.AGENT_B},
    "v2_moderator_intake": {"title": "V2 · Moderator — Intake", "prompt": v2_prompts.MODERATOR_INTAKE},
    "v2_moderator_success": {"title": "V2 · Moderator — Successful finalization", "prompt": v2_prompts.FINALIZE_CONSENSUS},
    "v2_moderator_failure": {"title": "V2 · Moderator — Unsuccessful finalization", "prompt": v2_prompts.FINALIZE_NO_CONSENSUS},
    "v2_agent_a": {"title": "V2 · Agent A — Author", "prompt": v2_prompts.AGENT_A},
    "v2_agent_b": {"title": "V2 · Agent B — Reviewer", "prompt": v2_prompts.AGENT_B},
    "v3_moderator_intake": {"title": "V3 · Moderator — Intake", "prompt": v3_prompts.MODERATOR_INTAKE},
    "v3_moderator_success": {"title": "V3 · Moderator — Successful finalization", "prompt": v3_prompts.FINALIZE_CONSENSUS},
    "v3_moderator_failure": {"title": "V3 · Moderator — Unsuccessful finalization", "prompt": v3_prompts.FINALIZE_NO_CONSENSUS},
    "v3_agent_a": {"title": "V3 · Agent A — Author", "prompt": v3_prompts.AGENT_A},
    "v3_agent_b": {"title": "V3 · Agent B — Adversarial reviewer", "prompt": v3_prompts.AGENT_B},
}

_WORKFLOW_DETAILS_SCRIPT = f"""
const workflowPrompts = {json.dumps(_WORKFLOW_PROMPTS)};
const promptModal = document.getElementById("prompt-modal");
const promptTitle = document.getElementById("prompt-modal-title");
const promptContent = document.getElementById("prompt-modal-content");

document.querySelectorAll(".show-prompt").forEach(button => {{
  button.addEventListener("click", () => {{
    const item = workflowPrompts[button.dataset.prompt];
    if (!item) return;
    promptTitle.textContent = item.title;
    promptContent.textContent = item.prompt.trim();
    promptModal.showModal();
  }});
}});

document.getElementById("prompt-modal-close").addEventListener("click", () => promptModal.close());
promptModal.addEventListener("click", event => {{
  if (event.target === promptModal) promptModal.close();
}});
"""

WORKFLOW_DETAILS_HTML = _page(
    active="workflow-details", body=_WORKFLOW_DETAILS_BODY, script=_WORKFLOW_DETAILS_SCRIPT
)


# --- New experiment -----------------------------------------------------------

_NEW_EXPERIMENT_BODY = """
<a class="back-link" href="/experiments">&larr; Back to experiments</a>
<h1>New Experiment</h1>
<p class="sub">Run one problem through all three workflow architectures with the same saved configuration.</p>
<div class="model-grid" id="experiment-models">
  <div class="model-field"><label for="experiment-moderator-model">Moderator</label><select id="experiment-moderator-model"></select></div>
  <div class="model-field"><label for="experiment-author-model">Author</label><select id="experiment-author-model"></select></div>
  <div class="model-field"><label for="experiment-reviewer-model">Reviewer</label><select id="experiment-reviewer-model"></select></div>
</div>

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
const experimentModeratorEl = document.getElementById("experiment-moderator-model");
const experimentAuthorEl = document.getElementById("experiment-author-model");
const experimentReviewerEl = document.getElementById("experiment-reviewer-model");

async function onConfigLoaded(cfg) {
  experimentVariants = cfg.variants;
  roundsEl.placeholder = `default ${cfg.max_rounds}`;
  try {
    const catalog = await modelCatalogPromise;
    initModelSelect(experimentModeratorEl, "moderator", catalog);
    initModelSelect(experimentAuthorEl, "agent_a", catalog);
    initModelSelect(experimentReviewerEl, "agent_b", catalog);
  } catch (error) {
    errorEl.textContent = String(error.message || error);
    errorEl.classList.remove("hidden");
    experimentBtn.disabled = true;
  }
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
        models: {
          moderator: experimentModeratorEl.value,
          agent_a: experimentAuthorEl.value,
          agent_b: experimentReviewerEl.value,
        },
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
    active="consensus", body=_NEW_EXPERIMENT_BODY, script=_NEW_EXPERIMENT_SCRIPT
)


# --- Experiments --------------------------------------------------------------

_EXPERIMENTS_BODY = """
<div class="page-header">
  <h1>Experiments</h1>
  <a class="link-button" href="/experiments/new">New experiment</a>
</div>
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
      <td>${variantSummary(variants["v1-posthoc-reviewer"])}</td>
      <td>${variantSummary(variants["v2-moderated-reviewer"])}</td>
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
    active="consensus", body=_EXPERIMENTS_BODY, script=_EXPERIMENTS_SCRIPT
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
        <div class="model-field" id="evaluation-model-field">
          <label for="evaluator-model">Evaluator model</label>
          <select id="evaluator-model"></select>
        </div>
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
const evaluatorModelEl = document.getElementById("evaluator-model");
const evaluatorModelField = document.getElementById("evaluation-model-field");
let evaluatorModelControl = null;
let evaluatorModelReady = Promise.resolve();

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

function runDetailsAction(item) {
  if (!item || item.status !== "completed" || item.id == null) {
    return '<span class="empty-hint">Unavailable</span>';
  }
  return `<a class="run-details-link" href="/history/${item.id}">View run details</a>`;
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
    ...Object.entries(roles).filter(([role]) => role !== "evaluator").map(([role, settings]) =>
      `<li><b>${escapeHtml(ROLE_LABELS[role] || role)}:</b> <code>${escapeHtml(settings.model)}</code> (${escapeHtml(settings.effort)})</li>`
    ),
  ].join("");
  renderEvaluation(experiment);
  const variants = Object.fromEntries(experiment.variants.map(item => [item.variant, item]));
  const ordered = [
    variants["v1-posthoc-reviewer"],
    variants["v2-moderated-reviewer"],
    variants["v3-adversarial-reviewer"],
  ];
  const metrics = [
    ["Verdict", "verdict"], ["Rounds", "rounds"], ["Model calls", "model_calls"],
    ["Tokens", "total_tokens"], ["Cost", "total_cost"], ["Duration", "duration_ms"],
  ];
  comparisonBody.innerHTML = metrics.map(([label, key]) =>
    `<tr><th>${label}</th>${ordered.map(item => `<td>${escapeHtml(String(valueFor(item, key)))}</td>`).join("")}</tr>`
  ).join("") + `<tr><th>Run details</th>${ordered.map(item => `<td>${runDetailsAction(item)}</td>`).join("")}</tr>`;
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
  const order = ["v1-posthoc-reviewer", "v2-moderated-reviewer", "v3-adversarial-reviewer"];
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
    evaluatorModelField.classList.add("hidden");
    return;
  }
  evaluatorModelField.classList.remove("hidden");
  if (!evaluatorModelControl) {
    evaluatorModelReady = modelCatalogPromise.then(catalog => {
      const frozen = experiment.evaluation_config?.model?.replace(/^openrouter:/, "");
      evaluatorModelControl = initModelSelect(
        evaluatorModelEl, "evaluator", catalog,
        {value: frozen || catalog.defaults.evaluator, disabled: Boolean(frozen)}
      );
    }).catch(error => {
      errorEl.textContent = String(error.message || error);
      errorEl.classList.remove("hidden");
    });
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
    await evaluatorModelReady;
    const response = await fetch(`/api/experiments/${experimentId}/evaluate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({model: evaluatorModelEl.value}),
    });
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
    active="consensus", body=_EXPERIMENT_DETAIL_BODY, script=_EXPERIMENT_DETAIL_SCRIPT
)


# --- History ----------------------------------------------------------------

_HISTORY_BODY = """
<div class="page-header">
  <h1>History</h1>
  <a class="link-button" href="/run/new">New run</a>
</div>
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
    const problem = escapeHtml(r.problem);
    return `<tr data-id="${r.id}">
      <td>${new Date(r.created_at).toLocaleString()}</td>
      <td>${VARIANT_LABELS[r.variant] || r.variant}</td>
      <td class="problem-cell" title="${problem}">${problem}</td>
      <td>${VERDICT_LABELS[r.verdict] || r.verdict}</td>
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

HISTORY_HTML = _page(active="single-run", body=_HISTORY_BODY, script=_HISTORY_SCRIPT)


# --- Settings -----------------------------------------------------------------

_SETTINGS_BODY = """
<h1>Settings</h1>
<p class="sub">Manage local provider and tracing configuration. Saved values override the environment.</p>
<div class="tab-shell">
  <div class="tabs" role="tablist" aria-label="Settings sections">
    <button type="button" class="tab-button active" id="models-tab" role="tab" aria-selected="true" aria-controls="models-panel">Models</button>
    <button type="button" class="tab-button" id="langsmith-tab" role="tab" aria-selected="false" aria-controls="langsmith-panel">LangSmith</button>
  </div>
  <section id="models-panel" class="tab-panel" role="tabpanel" aria-labelledby="models-tab">
    <div class="settings-form">
      <div class="field">
        <label for="openrouter-api-key">OpenRouter API key</label>
        <input type="password" id="openrouter-api-key" autocomplete="new-password" placeholder="Use OPENROUTER_API_KEY from environment">
        <p class="field-help" id="openrouter-key-help">Leave empty and save to use the environment value.</p>
      </div>
      <button type="button" id="save-openrouter">Save OpenRouter key</button>
    </div>
    <hr>
    <div class="settings-controls">
      <div class="row">
        <div class="field narrow">
          <label for="model-count">Number of models</label>
          <input type="number" id="model-count" min="1" max="100" value="30">
        </div>
        <div class="field" style="flex:0 0 auto;">
          <button type="button" id="refresh-models">Update models from OpenRouter</button>
        </div>
      </div>
      <div class="settings-summary">
        <div class="panel"><span class="empty-hint">Saved models</span><strong id="catalog-count">—</strong></div>
        <div class="panel"><span class="empty-hint">Last updated</span><strong id="catalog-updated">Never</strong></div>
      </div>
    </div>
    <p class="field-help">Manual metadata refresh only. It does not run a model or consume inference tokens.</p>
    <div class="history-toolbar"><input type="search" id="models-search" placeholder="Search models, providers, or IDs…" aria-label="Search models"></div>
    <table class="runs-table" id="models-table">
      <thead><tr><th data-key="popularity_rank">Rank</th><th data-key="name">Model</th><th data-key="provider">Provider</th><th data-key="prompt_price">Input</th><th data-key="completion_price">Output</th><th data-key="context_length">Context</th></tr></thead>
      <tbody id="models-body"><tr><td colspan="6" class="empty-hint">Loading…</td></tr></tbody>
    </table>
  </section>
  <section id="langsmith-panel" class="tab-panel hidden" role="tabpanel" aria-labelledby="langsmith-tab">
    <div class="settings-form">
      <div class="field"><label for="langsmith-api-key">LangSmith API key</label><input type="password" id="langsmith-api-key" autocomplete="new-password" placeholder="Use LANGSMITH_API_KEY from environment"><p class="field-help" id="langsmith-key-help">Leave empty and save to use the environment value.</p></div>
      <div class="field"><label for="langsmith-endpoint">Endpoint</label><input type="text" id="langsmith-endpoint" placeholder="https://eu.api.smith.langchain.com"></div>
      <div class="field"><label for="langsmith-tracing">Tracing</label><select id="langsmith-tracing"><option value="">Use environment default</option><option value="true">Enabled</option><option value="false">Disabled</option></select></div>
      <div class="field"><label for="langsmith-project">Project</label><input type="text" id="langsmith-project" placeholder="agentic-consensus"></div>
      <button type="button" id="save-langsmith">Save LangSmith settings</button>
    </div>
  </section>
</div>
<div id="status" class="status hidden"><span class="spinner"></span><span id="status-text">Saving…</span></div>
<div id="success" class="status hidden"><span class="badge ok">Saved</span><span id="success-text"></span></div>
<div id="error" class="error hidden"></div>
"""

_SETTINGS_SCRIPT = r"""
const refreshButton = document.getElementById("refresh-models");
const modelsBody = document.getElementById("models-body");
const catalogCount = document.getElementById("catalog-count");
const catalogUpdated = document.getElementById("catalog-updated");
const statusEl = document.getElementById("status");
const statusTextEl = document.getElementById("status-text");
const successEl = document.getElementById("success");
const successTextEl = document.getElementById("success-text");
const modelCountEl = document.getElementById("model-count");
const modelsSearchEl = document.getElementById("models-search");
const openRouterKeyEl = document.getElementById("openrouter-api-key");
const langsmithKeyEl = document.getElementById("langsmith-api-key");
let allCatalogModels = [];
let modelsSortKey = "popularity_rank", modelsSortDir = 1;

function selectSettingsTab(name) {
  const modelsSelected = name === "models";
  document.getElementById("models-tab").classList.toggle("active", modelsSelected);
  document.getElementById("models-tab").setAttribute("aria-selected", String(modelsSelected));
  document.getElementById("models-panel").classList.toggle("hidden", !modelsSelected);
  document.getElementById("langsmith-tab").classList.toggle("active", !modelsSelected);
  document.getElementById("langsmith-tab").setAttribute("aria-selected", String(!modelsSelected));
  document.getElementById("langsmith-panel").classList.toggle("hidden", modelsSelected);
}
document.getElementById("models-tab").addEventListener("click", () => selectSettingsTab("models"));
document.getElementById("langsmith-tab").addEventListener("click", () => selectSettingsTab("langsmith"));

function showSaved(message) {
  successTextEl.textContent = message;
  successEl.classList.remove("hidden");
}

function renderApplicationSettings(settings) {
  const openrouter = settings.OPENROUTER_API_KEY;
  document.getElementById("openrouter-key-help").textContent = openrouter.configured
    ? `A key is configured from ${openrouter.source}. Leave empty and save to fall back to the environment.`
    : "No key is configured. Runs using OpenRouter require one.";
  const langsmithKey = settings.LANGSMITH_API_KEY;
  document.getElementById("langsmith-key-help").textContent = langsmithKey.configured
    ? `A key is configured from ${langsmithKey.source}. Leave empty and save to fall back to the environment.`
    : "No LangSmith API key is configured.";
  const endpointEl = document.getElementById("langsmith-endpoint");
  endpointEl.value = settings.LANGSMITH_ENDPOINT.value || "";
  endpointEl.placeholder = settings.LANGSMITH_ENDPOINT.effective_value || "https://eu.api.smith.langchain.com";
  document.getElementById("langsmith-tracing").value = settings.LANGSMITH_TRACING.value || "";
  const projectEl = document.getElementById("langsmith-project");
  projectEl.value = settings.LANGSMITH_PROJECT.value || "";
  projectEl.placeholder = settings.LANGSMITH_PROJECT.effective_value || "agentic-consensus";
}

async function saveApplicationSettings(values, message) {
  errorEl.classList.add("hidden"); successEl.classList.add("hidden");
  statusTextEl.textContent = "Saving settings…"; statusEl.classList.remove("hidden");
  try {
    const response = await fetch("/api/settings", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({values}),
    });
    const payload = await response.json();
    if (!response.ok || payload.error) throw new Error(payload.error || `Save failed (${response.status})`);
    renderApplicationSettings(payload); showSaved(message);
  } catch (error) {
    errorEl.textContent = String(error.message || error); errorEl.classList.remove("hidden");
  } finally { statusEl.classList.add("hidden"); }
}

document.getElementById("save-openrouter").addEventListener("click", () => {
  saveApplicationSettings({OPENROUTER_API_KEY: openRouterKeyEl.value}, "OpenRouter setting saved.");
  openRouterKeyEl.value = "";
});
document.getElementById("save-langsmith").addEventListener("click", () => {
  saveApplicationSettings({
    LANGSMITH_API_KEY: langsmithKeyEl.value,
    LANGSMITH_ENDPOINT: document.getElementById("langsmith-endpoint").value,
    LANGSMITH_TRACING: document.getElementById("langsmith-tracing").value,
    LANGSMITH_PROJECT: document.getElementById("langsmith-project").value,
  }, "LangSmith settings saved.");
  langsmithKeyEl.value = "";
});

fetch("/api/settings").then(async response => {
  const payload = await response.json();
  if (!response.ok || payload.error) throw new Error(payload.error || "Could not load settings");
  renderApplicationSettings(payload);
}).catch(error => {
  errorEl.textContent = String(error.message || error); errorEl.classList.remove("hidden");
});

function renderCatalog(catalog) {
  catalogCount.textContent = catalog.saved_count.toLocaleString();
  catalogUpdated.textContent = catalog.refreshed_at ? new Date(catalog.refreshed_at).toLocaleString() : "Never";
  allCatalogModels = catalog.models;
  renderModelsTable();
}

function renderModelsTable() {
  const query = modelsSearchEl.value.trim().toLowerCase();
  const models = allCatalogModels.filter(model => !query ||
    [model.name, model.provider, model.id].some(value => (value || "").toLowerCase().includes(query))
  ).slice().sort((left, right) => {
    const a = left[modelsSortKey], b = right[modelsSortKey];
    if (a == null && b == null) return 0;
    if (a == null) return 1;
    if (b == null) return -1;
    const av = typeof a === "string" && modelsSortKey !== "name" && modelsSortKey !== "provider" ? Number(a) : a;
    const bv = typeof b === "string" && modelsSortKey !== "name" && modelsSortKey !== "provider" ? Number(b) : b;
    return modelsSortDir * (av > bv ? 1 : av < bv ? -1 : 0);
  });
  if (!models.length) {
    modelsBody.innerHTML = `<tr><td colspan="6" class="empty-hint">${allCatalogModels.length ? "No models match your search." : "No models available."}</td></tr>`;
    return;
  }
  modelsBody.innerHTML = models.map(model => `<tr>
    <td>${model.popularity_rank ?? "—"}</td>
    <td><strong>${escapeHtml(model.name)}</strong><br><code>${escapeHtml(model.id)}</code>${model.configured_default ? '<br><span class="badge warn">Configured default</span>' : ""}</td>
    <td>${escapeHtml(model.provider)}</td>
    <td>${escapeHtml(perMillion(model.prompt_price))}</td>
    <td>${escapeHtml(perMillion(model.completion_price))}</td>
    <td>${model.context_length != null ? model.context_length.toLocaleString() : "—"}</td>
  </tr>`).join("");
}

document.querySelectorAll("#models-table th[data-key]").forEach(header => {
  header.addEventListener("click", () => {
    const key = header.dataset.key;
    modelsSortDir = modelsSortKey === key ? -modelsSortDir : 1;
    modelsSortKey = key;
    renderModelsTable();
  });
});
modelsSearchEl.addEventListener("input", renderModelsTable);

modelCatalogPromise.then(renderCatalog).catch(error => {
  errorEl.textContent = String(error.message || error); errorEl.classList.remove("hidden");
});

refreshButton.addEventListener("click", async () => {
  refreshButton.disabled = true; statusTextEl.textContent = "Updating catalog…"; statusEl.classList.remove("hidden"); errorEl.classList.add("hidden"); successEl.classList.add("hidden");
  try {
    const count = Number.parseInt(modelCountEl.value, 10);
    if (!Number.isInteger(count) || count < 1 || count > 100) throw new Error("Number of models must be between 1 and 100.");
    const response = await fetch("/api/models/refresh", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({count}),
    });
    const payload = await response.json();
    if (!response.ok || payload.error) throw new Error(payload.error || `Refresh failed (${response.status})`);
    renderCatalog(payload); showSaved("Model catalog updated.");
  } catch (error) {
    errorEl.textContent = String(error.message || error); errorEl.classList.remove("hidden");
  } finally {
    refreshButton.disabled = false; statusEl.classList.add("hidden");
  }
});
"""

SETTINGS_HTML = _page(active="settings", body=_SETTINGS_BODY, script=_SETTINGS_SCRIPT)


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
  if (run.config?.roles) {
    const selectedRoles = Object.entries(run.config.roles).filter(([role]) =>
      role !== "evaluator" && !(role === "moderator" && run.variant === "v1-posthoc-reviewer")
    );
    runMetaEl.innerHTML += selectedRoles.map(([role, settings]) =>
      `<li><b>${escapeHtml(ROLE_LABELS[role] || role)}:</b> <code>${escapeHtml(settings.model)}</code></li>`
    ).join("");
  }
  renderFlowFromEntries(buildEntriesFromState(run.state));
  layoutEl.classList.remove("hidden");
}).catch(err => {
  errorEl.textContent = String(err.message || err);
  errorEl.classList.remove("hidden");
});
"""

REPLAY_HTML = _page(active="single-run", body=_REPLAY_BODY, script=_REPLAY_SCRIPT)
