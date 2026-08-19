"""Read-only HTML view for the authoritative release-truth API."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

_PAGE = r'''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta http-equiv="Cache-Control" content="no-store">
  <title>SharipovAI Truth / Release Center</title>
  <style>
    :root { color-scheme: dark; font-family: Inter, ui-sans-serif, system-ui, sans-serif; }
    body { margin: 0; background: #0b0f14; color: #e7edf5; }
    main { max-width: 1180px; margin: 0 auto; padding: 28px 18px 48px; }
    header { display: flex; gap: 16px; align-items: center; justify-content: space-between; flex-wrap: wrap; }
    h1 { margin: 0; font-size: clamp(24px, 4vw, 38px); }
    .muted { color: #9aa8b7; }
    button { border: 1px solid #344151; background: #151c25; color: inherit; border-radius: 10px; padding: 9px 13px; cursor: pointer; }
    .grid { display: grid; grid-template-columns: repeat(auto-fit,minmax(250px,1fr)); gap: 12px; margin-top: 18px; }
    .card { border: 1px solid #25303d; background: #10161e; border-radius: 14px; padding: 15px; min-width: 0; }
    .card h2 { font-size: 14px; text-transform: uppercase; letter-spacing: .08em; color: #9fb0c2; margin: 0 0 10px; }
    .value { font-size: 18px; font-weight: 700; overflow-wrap: anywhere; }
    .PASS { color: #73d99d; } .WAIT, .UNKNOWN, .STALE { color: #f1c56d; } .BLOCK { color: #ff8585; }
    dl { display: grid; grid-template-columns: minmax(90px, 1fr) 2fr; gap: 7px 10px; margin: 0; }
    dt { color: #8e9cab; } dd { margin: 0; overflow-wrap: anywhere; }
    ul { margin: 8px 0 0; padding-left: 20px; }
    details { margin-top: 14px; }
    pre { white-space: pre-wrap; word-break: break-word; background: #080c11; border-radius: 10px; padding: 12px; overflow: auto; }
    #error { color: #ff8585; margin-top: 12px; }
  </style>
</head>
<body>
<main>
  <header>
    <div><h1>Truth / Release Center</h1><div class="muted">Read-only view of <code>/api/system/release-truth</code>. UNKNOWN and STALE are preserved.</div></div>
    <button id="refresh" type="button">Refresh evidence</button>
  </header>
  <div id="error" role="alert"></div>
  <section class="grid">
    <article class="card"><h2>Release Gate</h2><div id="gate" class="value UNKNOWN">UNKNOWN</div><ul id="gateReasons"></ul></article>
    <article class="card"><h2>Identity</h2><dl><dt>Main</dt><dd id="mainSha">UNKNOWN</dd><dt>Production</dt><dd id="prodSha">UNKNOWN</dd><dt>Architecture</dt><dd id="arch">UNKNOWN</dd></dl></article>
    <article class="card"><h2>PAPER Runtime</h2><dl><dt>Owner</dt><dd id="owner">UNKNOWN</dd><dt>Action</dt><dd id="action">UNKNOWN</dd><dt>Reason</dt><dd id="reason">UNKNOWN</dd><dt>Category</dt><dd id="category">UNKNOWN</dd></dl></article>
    <article class="card"><h2>Safety</h2><dl><dt>Kill switch</dt><dd id="kill">UNKNOWN</dd><dt>Live</dt><dd id="live">UNKNOWN</dd><dt>Testnet</dt><dd id="testnet">UNKNOWN</dd><dt>Mainnet compiled</dt><dd id="mainnet">UNKNOWN</dd></dl></article>
    <article class="card"><h2>Storage / Backup</h2><dl><dt>Storage</dt><dd id="storage">UNKNOWN</dd><dt>Backup</dt><dd id="backup">UNKNOWN</dd><dt>System</dt><dd id="system">UNKNOWN</dd></dl></article>
    <article class="card"><h2>Runtime Evidence</h2><dl><dt>AI organs</dt><dd id="organs">UNKNOWN</dd><dt>Risk/Security veto</dt><dd id="veto">UNKNOWN</dd><dt>V2 cohort</dt><dd id="cohort">UNKNOWN</dd><dt>Checked</dt><dd id="checked">UNKNOWN</dd></dl></article>
  </section>
  <details><summary>Machine-readable snapshot</summary><pre id="raw">UNKNOWN</pre></details>
</main>
<script>
'use strict';
const $ = (id) => document.getElementById(id);
const text = (id, value) => { $(id).textContent = value === null || value === undefined || value === '' ? 'UNKNOWN' : String(value); };
const bool = (value) => value === true ? 'true' : value === false ? 'false' : 'UNKNOWN';
async function refreshTruth() {
  $('error').textContent = '';
  try {
    const response = await fetch('/api/system/release-truth', {cache: 'no-store', credentials: 'same-origin'});
    if (!response.ok) throw new Error(`release truth HTTP ${response.status}`);
    const data = await response.json();
    const gate = data.release_gate || {};
    const verdict = String(gate.verdict || 'UNKNOWN').toUpperCase();
    $('gate').className = `value ${verdict}`;
    text('gate', verdict);
    $('gateReasons').replaceChildren(...(gate.reasons || ['No reason evidence']).map((reason) => { const li=document.createElement('li'); li.textContent=String(reason); return li; }));
    const identity = data.identity || {}; const paper = data.paper_runtime || {}; const safety = data.safety || {};
    text('mainSha', identity.github_main_sha); text('prodSha', identity.production_release_sha); text('arch', data.architecture_version);
    text('owner', paper.decision_owner); text('action', paper.latest_action); text('reason', paper.latest_reason); text('category', paper.reason_category);
    text('kill', bool(safety.execution_kill_switch)); text('live', bool(safety.live_execution_enabled)); text('testnet', bool(safety.testnet_execution_enabled)); text('mainnet', bool(safety.mainnet_execution_compiled));
    text('storage', (data.storage || {}).status); text('backup', (data.backup || {}).status); text('system', (data.system_health || {}).status);
    text('organs', (data.ai_organs || {}).status); text('veto', (data.risk_security_veto || {}).status); text('cohort', (data.v2_cohort_metrics || {}).status);
    text('checked', data.checked_at_ms ? new Date(Number(data.checked_at_ms)).toISOString() : 'UNKNOWN');
    $('raw').textContent = JSON.stringify(data, null, 2);
  } catch (error) {
    $('error').textContent = `Truth evidence unavailable: ${error instanceof Error ? error.message : String(error)}`;
    $('gate').className = 'value UNKNOWN'; text('gate', 'UNKNOWN');
  }
}
$('refresh').addEventListener('click', refreshTruth);
refreshTruth();
</script>
</body>
</html>'''


def install_release_truth_page(app: FastAPI) -> None:
    """Install a no-store, read-only view over the release-truth endpoint."""
    if getattr(app.state, "release_truth_page_installed", False):
        return
    app.state.release_truth_page_installed = True

    @app.get("/release-truth", response_class=HTMLResponse)
    async def release_truth_page() -> HTMLResponse:
        return HTMLResponse(_PAGE, headers={"Cache-Control": "no-store"})


__all__ = ["install_release_truth_page"]
