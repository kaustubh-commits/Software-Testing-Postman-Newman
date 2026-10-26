/* =====================================================================
   Test Control Center - frontend logic (vanilla JS + Chart.js)

   Flow:  click Run → POST /control/run → open an EventSource on
          /control/stream/<runId> → every Newman event arrives as JSON →
          it goes into a small queue → the queue "plays" events so the
          pipeline animation is visible → the feed, counters, charts and
          table update.
   ===================================================================== */

'use strict';

// ------------------------------------------------------------------ helpers
const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

function esc(text) {
  return String(text ?? '').replace(/[&<>"']/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json' }, ...options,
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.detail || `HTTP ${res.status}`);
  return body;
}

function toast(message, ms = 2600) {
  const el = $('#toast');
  el.textContent = message;
  el.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => { el.hidden = true; }, ms);
}

function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

/** Compact one-line request body, e.g. {"name":"A","age":17} */
function compactBody(raw) {
  if (!raw) return '';
  try { return JSON.stringify(JSON.parse(raw)); } catch (e) { return raw.replace(/\s+/g, ' '); }
}

function prettyJson(raw) {
  if (!raw) return '';
  try { return JSON.stringify(JSON.parse(raw), null, 2); } catch (e) { return raw; }
}

// Small icons for the suite cards
const ICONS = {
  'Positive': '<path d="M20 6 9 17l-5-5"/>',
  'Negative': '<circle cx="12" cy="12" r="9"/><path d="m15 9-6 6M9 9l6 6"/>',
  'Boundary': '<path d="M3 17h18M6 17v-4M10 17v-6M14 17v-6M18 17v-4"/><path d="M3 7h18" stroke-dasharray="2 3"/>',
  'Auth': '<rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/>',
  'Chaining': '<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1"/><path d="M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/>',
  'Data-Driven': '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 10h18M3 15h18M9 4v16"/>',
};
const PLAY = '<svg viewBox="0 0 24 24"><path d="M7 4.5v15l12.5-7.5z"/></svg>';

// ------------------------------------------------------------------ state
const state = {
  suites: [],
  running: false,
  runSuites: [],
  expectedTotal: 0,
  pace: 250,
  results: [],            // test results only (setup steps excluded)
  assertions: 0,
  assertionsFailed: 0,
  filter: 'all',
  bug: { enabled: false, type: 'marks_over_100', types: {} },
  eventSource: null,
  received: 0,
};

// ================================================================== SUITES
async function loadSuites() {
  state.suites = await api('/control/suites');
  $('#suiteList').innerHTML = state.suites.map((s) => `
    <div class="suite" data-suite="${esc(s.name)}">
      <div class="ic"><svg viewBox="0 0 24 24">${ICONS[s.name] || ''}</svg></div>
      <div>
        <div class="name">${esc(s.name)} <span class="count">${s.count} tests</span></div>
        <div class="desc">${esc(s.description)}</div>
        <div class="verdict"></div>
      </div>
      <button class="run-btn" title="Run the ${esc(s.name)} suite" aria-label="Run ${esc(s.name)}">${PLAY}</button>
    </div>`).join('');
  $$('.suite .run-btn').forEach((btn) => {
    btn.addEventListener('click', () => startRun(btn.closest('.suite').dataset.suite));
  });
}

function setRunningUI(running, activeSuite) {
  state.running = running;
  $('#runAllBtn').disabled = running;
  $$('.suite').forEach((card) => {
    const isActive = running && card.dataset.suite === activeSuite;
    card.classList.toggle('running', isActive);
    const btn = card.querySelector('.run-btn');
    btn.disabled = running;
    btn.innerHTML = isActive ? '<span class="spinner"></span>' : PLAY;
  });
}

// ================================================================== RUNNING
async function startRun(suite) {
  if (state.running) return;
  try {
    const { runId, suites } = await api('/control/run', {
      method: 'POST', body: JSON.stringify({ suite, pace_ms: state.pace }),
    });
    resetView(suites);
    openStream(runId);
  } catch (err) {
    toast('Could not start: ' + err.message);
  }
}

/** Clear the feed, counters, charts and table for a new run. */
function resetView(suites) {
  state.runSuites = suites;
  state.expectedTotal = suites.reduce((n, name) =>
    n + ((state.suites.find((s) => s.name === name) || {}).count || 0), 0);
  state.results = [];
  state.assertions = 0;
  state.assertionsFailed = 0;
  $('#feed').innerHTML = '';
  $('#feed').classList.remove('no-anim');
  $$('.suite .verdict').forEach((v) => { v.textContent = ''; v.className = 'verdict'; });
  $('#progressBar').className = '';
  $('#progressBar').style.width = '0';
  $('#tableMeta').textContent = '· live run';
  setRunState('Running…', 'running');
  setRunningUI(true, suites[0]);
  renderTable();
  updateStats();
  scheduleCharts();
}

/** Open the Server-Sent Events stream for a run. */
function openStream(runId) {
  if (state.eventSource) state.eventSource.close();
  state.received = 0;
  const es = new EventSource(`/control/stream/${runId}`);
  state.eventSource = es;
  let index = 0;
  // The server replays all events on (re)connect, so skip ones we already have.
  es.onopen = () => { index = 0; };
  es.onmessage = (msg) => {
    index += 1;
    if (index <= state.received) return;
    state.received += 1;
    const event = JSON.parse(msg.data);
    queue.push(event);
    if (event.type === 'run_done') es.close();
    pump();
  };
  es.onerror = () => {
    if (es.readyState === EventSource.CLOSED) toast('Live stream closed');
  };
}

// ------------------------------------------------------------------ event queue
// Newman fires the pipeline events within a few milliseconds of each other.
// The queue plays each "phase" event for a moment so the audience can see
// it light up. If the queue gets long, it catches up instantly, so it is never laggy.
const queue = [];
let pumping = false;
const PHASE_MS = 55;

function pump() {
  if (pumping) return;
  pumping = true;
  (function next() {
    if (!queue.length) { pumping = false; return; }
    const event = queue.shift();
    handleEvent(event);
    const wait = event.type === 'phase' && queue.length < 25 && state.pace > 0 ? PHASE_MS : 0;
    if (wait) setTimeout(next, wait); else next();
  })();
}

function handleEvent(e) {
  switch (e.type) {
    case 'run_start':
      // Also sent when re-attaching after a refresh: know how many tests to expect
      state.runSuites = e.suites;
      state.expectedTotal = e.suites.reduce((n, name) =>
        n + ((state.suites.find((s) => s.name === name) || {}).count || 0), 0);
      break;
    case 'suite_start':
      setRunningUI(true, e.suite);
      appendFeed(`<div class="suite-sep">${esc(e.suite)} suite · ${e.index} of ${e.of}</div>`);
      setCaption(`Starting the <b>${esc(e.suite)}</b> folder of the collection…`);
      break;
    case 'phase':
      onPhase(e);
      break;
    case 'result':
      if (e.kind === 'setup') addSetupRow(e); else addResult(e);
      break;
    case 'done':
      onSuiteDone(e);
      break;
    case 'error':
      appendFeed(`<div class="error-row">⚠ ${esc(e.suite ? e.suite + ': ' : '')}${esc(e.message)}</div>`);
      toast('Newman reported an error. See the live feed.');
      break;
    case 'run_done':
      onRunDone(e);
      break;
  }
}

// ------------------------------------------------------------------ pipeline
const STEPS = ['request', 'prerequest', 'api', 'response', 'tests', 'report'];

function setPipeline(step) {
  const at = STEPS.indexOf(step);
  $$('#pipeline li').forEach((li, i) => {
    li.classList.toggle('active', i === at);
    li.classList.toggle('done', at >= 0 && i < at);
  });
}

function onPhase(e) {
  setPipeline(e.step);
  const name = `<code>${esc(e.name || '')}</code>`;
  const setup = e.kind === 'setup';
  const text = {
    request: setup ? '⚙ Setup step: reset the data so the suite starts clean' : `Picked request ${name}`,
    prerequest: `Running the pre-request script of ${name}`,
    api: `Sending the HTTP request for ${name} to the API`,
    response: `Response received for ${name}`,
    tests: `Running the pm.test() assertions of ${name}`,
    report: 'Writing the reports (CLI · htmlextra · this dashboard)',
  }[e.step];
  if (text) setCaption(text);
}

function setCaption(html) { $('#pipeCaption').innerHTML = html; }

function setRunState(text, cls) {
  const el = $('#runState');
  el.textContent = text;
  el.className = 'run-state ' + (cls || '');
}

// ------------------------------------------------------------------ feed
let feedBuffer = [];
let feedFrame = 0;

/** Append HTML to the feed in batches (one DOM write per animation frame). */
function appendFeed(html) {
  feedBuffer.push(html);
  if (feedFrame) return;
  feedFrame = requestAnimationFrame(() => {
    const feed = $('#feed');
    const nearBottom = feed.scrollHeight - feed.scrollTop - feed.clientHeight < 80;
    const empty = feed.querySelector('.empty');
    if (empty) empty.remove();
    feed.insertAdjacentHTML('beforeend', feedBuffer.join(''));
    feedBuffer = [];
    feedFrame = 0;
    if (nearBottom || state.running) feed.scrollTop = feed.scrollHeight;
  });
}

function addSetupRow(r) {
  appendFeed(`<div class="setup-row">setup · ${esc(r.method)} ${esc(r.path)} · reset seed data · ${r.time ?? '-'} ms</div>`);
}

/** Purple badge for error scenarios: invalid input that the API should reject. */
const INVALID_TIP = 'Error scenario: this test sends invalid input on purpose and PASSES when the API correctly rejects it';
function invalidBadge(r) {
  return r.invalidInput ? `<span class="badge-invalid" title="${INVALID_TIP}">Invalid input → rejected</span>` : '';
}

function rowHtml(r, i) {
  const failed = r.assertions.filter((a) => !a.passed && !a.skipped);
  const status = r.code ? `${r.code} ${esc(r.status)}` : 'no response';
  return `
    <div class="row ${r.passed ? 'pass' : 'fail'}" data-i="${i}" title="Click to inspect">
      <span class="pill ${r.passed ? 'pass' : 'fail'}">${r.passed ? 'PASS' : 'FAIL'}</span>
      <span class="method ${esc(r.method)}">${esc(r.method)}</span>
      <div class="what">
        <div class="title"><span class="id">${esc(r.caseId)}</span>${esc(r.title)}</div>
        ${failed.length
          ? `<div class="err">${invalidBadge(r)}✗ ${esc(failed[0].name)}: ${esc(failed[0].error)}</div>`
          : `<div class="endpoint">${invalidBadge(r)}${esc(r.path)} → ${status}</div>`}
      </div>
      <span class="ms">${r.time ?? '-'} ms<small>${r.assertions.length} checks</small></span>
    </div>`;
}

function addResult(r) {
  const i = state.results.push(r) - 1;
  state.assertions += r.assertions.length;
  state.assertionsFailed += r.assertions.filter((a) => !a.passed && !a.skipped).length;
  appendFeed(rowHtml(r, i));
  appendTableRow(r, i);
  updateStats(true);
  scheduleCharts();
}

$('#feed').addEventListener('click', (ev) => {
  const row = ev.target.closest('.row');
  if (row) openDrawer(state.results[Number(row.dataset.i)]);
});
$('#onlyFails').addEventListener('change', (ev) => {
  $('#feed').classList.toggle('only-fails', ev.target.checked);
});

function onSuiteDone(e) {
  const tests = state.results.filter((r) => r.suite === e.suite);
  const failed = tests.filter((r) => !r.passed).length;
  const card = $(`.suite[data-suite="${CSS.escape(e.suite)}"] .verdict`);
  if (card) {
    card.textContent = failed ? `✗ ${failed} failed` : '✓ passed';
    card.className = 'verdict ' + (failed ? 'bad' : 'ok');
  }
}

function onRunDone(e) {
  setRunningUI(false);
  setPipeline('report');
  setTimeout(() => { if (!state.running) setPipeline(null); }, 1600);
  const ok = e.failed === 0 && e.total > 0;
  setRunState(ok ? `All ${e.total} passed` : `${e.failed} of ${e.total} failed`, ok ? 'ok' : 'bad');
  setCaption(ok
    ? `✓ Run finished: <b>${e.passed}/${e.total}</b> test cases passed in ${(e.durationMs / 1000).toFixed(1)} s. Open the HTML report for the full Newman output.`
    : `✗ Run finished: <b>${e.failed}</b> test case(s) failed. Click a red row to see exactly which pm.test() caught it.`);
  $('#progressBar').className = ok ? 'ok' : 'bad';
  $('#progressBar').style.width = '100%';
  $('#statTime').textContent = (e.durationMs / 1000).toFixed(1) + ' s';
  $('#reportBtn').disabled = false;
  $('#tableMeta').textContent = `· latest run (${e.label}, ${e.started})`;
  loadHistory();
}

// ================================================================== STATS + CHARTS
function updateStats(bump) {
  const total = state.results.length;
  const passed = state.results.filter((r) => r.passed).length;
  const failed = total - passed;
  setNumber('#statPassed', passed, bump);
  setNumber('#statFailed', failed, bump);
  setNumber('#statTotal', total, bump);
  $('.stat.fail').classList.toggle('has', failed > 0);
  $('#statAssert').textContent = `${state.assertions - state.assertionsFailed}/${state.assertions} assertions`;
  $('#passRate').textContent = total ? Math.round((passed / total) * 100) + '%' : '-';
  const times = state.results.map((r) => r.time).filter((t) => t != null);
  $('#statAvg').textContent = times.length
    ? `avg response ${Math.round(times.reduce((a, b) => a + b, 0) / times.length)} ms` : 'avg response -';
  if (state.running && state.expectedTotal) {
    $('#progressBar').style.width = Math.min(100, (total / state.expectedTotal) * 100) + '%';
  }
  if (state.running) $('#statTime').textContent = '…';
}

function setNumber(sel, value, bump) {
  const el = $(sel);
  if (el.textContent === String(value)) return;
  el.textContent = value;
  if (bump) { el.classList.remove('bump'); void el.offsetWidth; el.classList.add('bump'); }
}

let donut, timeChart, chartTimer = 0;

function makeCharts() {
  Chart.defaults.font.family = cssVar('--font');
  Chart.defaults.font.size = 13;
  donut = new Chart($('#donut'), {
    type: 'doughnut',
    data: { labels: ['Passed', 'Failed'], datasets: [{ data: [0, 0], borderWidth: 0 }] },
    options: {
      cutout: '74%', responsive: false, animation: { duration: 250 },
      plugins: { legend: { display: false }, tooltip: { enabled: true } },
    },
  });
  timeChart = new Chart($('#timeChart'), {
    type: 'bar',
    data: { labels: [], datasets: [{ data: [], borderRadius: 4, maxBarThickness: 26 }] },
    options: {
      responsive: true, maintainAspectRatio: false, animation: { duration: 200 },
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: { title: (items) => {
          const r = state.results[items[0].dataIndex];
          return r ? `${r.caseId} ${r.title}` : '';
        }, label: (item) => ` ${item.raw} ms` } },
      },
      scales: {
        x: { grid: { display: false }, ticks: { autoSkip: true, maxRotation: 0, font: { size: 11 } } },
        y: { beginAtZero: true, title: { display: true, text: 'ms' } },
      },
      onClick: (ev, els) => { if (els.length) openDrawer(state.results[els[0].index]); },
    },
  });
  applyChartTheme();
}

function applyChartTheme() {
  const text = cssVar('--text-2');
  const grid = cssVar('--border');
  Chart.defaults.color = text;
  timeChart.options.scales.y.grid.color = grid;
  timeChart.options.scales.x.ticks.color = text;
  timeChart.options.scales.y.ticks.color = text;
  timeChart.options.scales.y.title.color = text;
  drawCharts();
}

/** Redraw the charts at most every 150 ms, so the page never stutters. */
function scheduleCharts() {
  if (chartTimer) return;
  chartTimer = setTimeout(() => { chartTimer = 0; drawCharts(); }, 150);
}

function drawCharts() {
  if (!donut) return;
  const pass = cssVar('--pass');
  const fail = cssVar('--fail');
  const passed = state.results.filter((r) => r.passed).length;
  const failed = state.results.length - passed;
  const ds = donut.data.datasets[0];
  if (passed + failed === 0) {               // empty grey ring
    ds.data = [1]; ds.backgroundColor = [cssVar('--surface-2')];
    donut.options.plugins.tooltip.enabled = false;
  } else {
    ds.data = [passed, failed]; ds.backgroundColor = [pass, fail];
    donut.options.plugins.tooltip.enabled = true;
  }
  donut.update();

  timeChart.data.labels = state.results.map((r) => r.caseId);
  const bar = timeChart.data.datasets[0];
  bar.data = state.results.map((r) => r.time ?? 0);
  bar.backgroundColor = state.results.map((r) => (r.passed ? pass : fail));
  timeChart.update();
}

// ================================================================== TABLE
/** Readable input for the table, e.g. POST /students · name="A", age=17 */
function inputText(r) {
  let body = '';
  try {
    const obj = r.requestBody ? JSON.parse(r.requestBody) : null;
    if (obj && typeof obj === 'object') {
      body = Object.entries(obj).map(([k, v]) => `${k}=${JSON.stringify(v)}`).join(', ');
    }
  } catch (e) { body = compactBody(r.requestBody); }
  return `${r.method} ${r.path}${body ? ' · ' + body : ''}`;
}

function tableRowHtml(r, i) {
  const input = inputText(r);
  const shortInput = input.length > 110 ? input.slice(0, 107) + '…' : input;
  return `
    <tr class="${r.passed ? 'pass' : 'fail'}" data-i="${i}">
      <td class="id">${esc(r.caseId)}</td>
      <td><span class="tag">${esc(r.suite)}</span></td>
      <td>${esc(r.title)}${r.invalidInput ? `<div class="cell-badge">${invalidBadge(r)}</div>` : ''}</td>
      <td class="input" title="${esc(input)}">${esc(shortInput)}</td>
      <td>${esc(r.expected)}</td>
      <td class="actual">${esc(r.actual)}</td>
      <td class="res"><span class="pill ${r.passed ? 'pass' : 'fail'}" style="padding:3px 10px">${r.passed ? 'PASS' : 'FAIL'}</span></td>
    </tr>`;
}

function visible(r) {
  return state.filter === 'all' || (state.filter === 'pass' ? r.passed : !r.passed);
}

function renderTable() {
  const rows = state.results.map((r, i) => (visible(r) ? tableRowHtml(r, i) : '')).join('');
  $('#caseBody').innerHTML = rows ||
    `<tr><td colspan="7" class="empty">${state.results.length ? 'No test cases match this filter.' : 'The table fills in from the latest run.'}</td></tr>`;
  $('#csvBtn').disabled = !state.results.length;
}

function appendTableRow(r, i) {
  if (i === 0) $('#caseBody').innerHTML = '';
  if (visible(r)) $('#caseBody').insertAdjacentHTML('beforeend', tableRowHtml(r, i));
  $('#csvBtn').disabled = false;
}

$('#caseBody').addEventListener('click', (ev) => {
  const tr = ev.target.closest('tr[data-i]');
  if (tr) openDrawer(state.results[Number(tr.dataset.i)]);
});
$$('.filters .seg').forEach((btn) => btn.addEventListener('click', () => {
  $$('.filters .seg').forEach((b) => b.classList.toggle('active', b === btn));
  state.filter = btn.dataset.filter;
  renderTable();
}));

/** Download the test case table as a CSV file. */
$('#csvBtn').addEventListener('click', () => {
  const quote = (v) => `"${String(v ?? '').replace(/"/g, '""')}"`;
  const lines = [['ID', 'Type', 'Scenario', 'Test case', 'Input', 'Expected', 'Actual', 'Pass/Fail'].join(',')];
  state.results.forEach((r) => lines.push([
    r.caseId, r.suite, r.invalidInput ? 'Invalid input -> rejected' : 'Valid input',
    r.title, inputText(r), r.expected, r.actual, r.passed ? 'PASS' : 'FAIL',
  ].map(quote).join(',')));
  const blob = new Blob([lines.join('\n') + '\n'], { type: 'text/csv' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `test-cases-${new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-')}.csv`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  toast(`Exported ${state.results.length} test cases to CSV`);
});

// ================================================================== DRAWER
/** Very small JavaScript syntax highlighter for the pm.test() code. */
function highlight(code, failingNames) {
  const TOKEN = /(\/\/.*$)|("(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*'|`(?:[^`\\]|\\.)*`)|\b(const|let|var|function|if|else|return|new|true|false|null|undefined)\b|\b(pm|test|expect|response|environment|variables|iterationData)\b|\b(\d+)\b/g;
  return code.split('\n').map((line) => {
    let out = '';
    let last = 0;
    line.replace(TOKEN, (m, comment, str, kw, pmWord, num, offset) => {
      out += esc(line.slice(last, offset));
      const cls = comment ? 'c' : str ? 's' : kw ? 'k' : pmWord ? 'f' : 'n';
      out += `<span class="${cls}">${esc(m)}</span>`;
      last = offset + m.length;
      return m;
    });
    out += esc(line.slice(last));
    const isFailing = failingNames.some((n) => n && line.includes('pm.test(') && line.includes(n));
    return isFailing ? `<span class="hl">${out}</span>` : out;
  }).join('\n');
}

function openDrawer(r) {
  if (!r) return;
  const failedNames = r.assertions.filter((a) => !a.passed && !a.skipped).map((a) => a.name);
  $('#dMeta').innerHTML = `
    <span class="pill ${r.passed ? 'pass' : 'fail'}">${r.passed ? 'PASS' : 'FAIL'}</span>
    <span class="tag">${esc(r.suite)}</span>
    <span class="tag">${esc(r.caseId)}</span>
    ${invalidBadge(r)}
    ${r.iterations > 1 ? `<span class="tag">CSV row ${r.iteration} of ${r.iterations}</span>` : ''}`;
  $('#dTitle').textContent = r.title;

  const headers = (r.requestHeaders || [])
    .filter((h) => !/^(user-agent|accept|cache-control|postman-token|host|accept-encoding|connection|content-length)$/i.test(h.key))
    .map((h) => `${h.key}: ${h.value}`).join('\n');

  $('#dBody').innerHTML = `
    <div class="d-section">
      <div class="kv">
        <div><small>Expected</small><b>${esc(r.expected)}</b></div>
        <div class="${r.passed ? 'pass' : 'fail'}"><small>Actual</small><b>${esc(r.actual)}</b></div>
        <div><small>Response time</small><b>${r.time ?? '-'} ms</b></div>
        <div><small>Assertions</small><b>${r.assertions.length - failedNames.length} / ${r.assertions.length} passed</b></div>
      </div>
    </div>
    ${r.description ? `<div class="d-section"><h3>What this test checks</h3><div>${esc(r.description.replace(/\*\*Expected:\*\*.*$/s, '').trim())}</div></div>` : ''}
    ${r.invalidInput ? `<div class="d-section invalid-note"><b>Error scenario.</b> This request is invalid on purpose.
      ${r.passed ? 'It PASSES because the API correctly rejected it.' : 'It FAILS because the API accepted it or rejected it the wrong way. That is a bug.'}</div>` : ''}
    <div class="d-section">
      <h3>Request</h3>
      <div class="reqline"><span class="method ${esc(r.method)}">${esc(r.method)}</span> ${esc(r.url)}</div>
      ${headers ? `<pre class="code">${esc(headers)}</pre>` : ''}
      ${r.requestBody ? `<pre class="code">${esc(prettyJson(r.requestBody))}</pre>` : ''}
    </div>
    <div class="d-section">
      <h3>Response · ${esc(r.actual)}</h3>
      <pre class="code">${esc(prettyJson(r.responseBody)) || '(empty)'}</pre>
    </div>
    <div class="d-section">
      <h3>pm.test() results</h3>
      <ul class="asserts">${r.assertions.map((a) => `
        <li class="${a.passed || a.skipped ? 'ok' : 'bad'}">
          <span class="mark">${a.skipped ? '–' : a.passed ? '✓' : '✗'}</span>
          <span>${esc(a.name)}${a.error ? `<span class="msg">${esc(a.error)}</span>` : ''}</span>
        </li>`).join('') || '<li>No assertions</li>'}
      </ul>
    </div>
    <div class="d-section">
      <h3>Test script (the actual code that checked it)</h3>
      <pre class="code">${highlight(r.testScript || '// no test script', failedNames)}</pre>
    </div>
    ${r.prerequestScript ? `
    <div class="d-section">
      <h3>Pre-request script</h3>
      <pre class="code">${highlight(r.prerequestScript, [])}</pre>
    </div>` : ''}`;

  $('#drawerBackdrop').hidden = false;
  $('#drawer').classList.add('open');
  $('#drawer').setAttribute('aria-hidden', 'false');
  $('#dBody').scrollTop = 0;
  $('#drawerClose').focus();
}

function closeDrawer() {
  $('#drawer').classList.remove('open');
  $('#drawer').setAttribute('aria-hidden', 'true');
  $('#drawerBackdrop').hidden = true;
}
$('#drawerClose').addEventListener('click', closeDrawer);
$('#drawerBackdrop').addEventListener('click', closeDrawer);
document.addEventListener('keydown', (ev) => { if (ev.key === 'Escape') closeDrawer(); });

// ================================================================== BUG MODE
async function loadBug() {
  state.bug = await api('/control/bug-mode');
  $('#bugType').innerHTML = Object.entries(state.bug.types)
    .map(([key, label]) => `<option value="${key}">${esc(label)}</option>`).join('');
  renderBug();
}

function renderBug() {
  const { enabled, type, types } = state.bug;
  $('#bugToggle').checked = enabled;
  $('#bugType').value = type;
  document.body.classList.toggle('bug-on', enabled);
  $('#bugBanner').hidden = !enabled;
  $('#bugBannerText').textContent = types[type] || '';
  const caught = (state.bug.caughtBy || {})[type];
  $('#bugHint').innerHTML = caught ? `Caught by: <b>${esc(caught)}</b>` : '';
}

async function setBug(enabled, type) {
  try {
    state.bug = await api('/control/bug-mode', {
      method: 'POST', body: JSON.stringify({ enabled, type }),
    });
    renderBug();
    pollHealth();
    toast(enabled ? `Bug planted: ${state.bug.types[state.bug.type]}` : 'Bug removed: API is back to normal');
  } catch (err) {
    toast('Could not change bug mode: ' + err.message);
    renderBug();
  }
}
$('#bugToggle').addEventListener('change', (ev) => setBug(ev.target.checked, $('#bugType').value));
$('#bugType').addEventListener('change', (ev) => setBug(state.bug.enabled, ev.target.value));

// ================================================================== HEALTH + HISTORY
async function pollHealth() {
  const pill = $('#apiStatus');
  try {
    const h = await api('/health');
    const bugOn = h.bug_mode && h.bug_mode.enabled;
    pill.className = 'status-pill ' + (bugOn ? 'bug' : 'online');
    pill.querySelector('.label').textContent = bugOn ? 'API online · BUG MODE' : `API online · ${h.students} students`;
    // Keep the toggle in sync if bug mode was changed from a script (run_bug_demo.sh)
    if (bugOn !== state.bug.enabled || h.bug_mode.type !== state.bug.type) {
      state.bug = { ...state.bug, ...h.bug_mode };
      renderBug();
    }
  } catch (err) {
    pill.className = 'status-pill offline';
    pill.querySelector('.label').textContent = 'API offline';
  }
}

async function loadHistory() {
  const list = await api('/control/history').catch(() => []);
  $('#reportBtn').disabled = !list.length;
  $('#history').innerHTML = list.length ? list.map((h) => `
    <li>
      <span class="time">${esc(h.started)}</span>
      <span>${esc(h.label)}${h.bugMode && h.bugMode.enabled ? '<span class="bugtag">BUG</span>' : ''}</span>
      <span class="score ${h.failed ? 'bad' : 'ok'}">${h.passed}/${h.total}</span>
      <a href="${esc(h.report)}" target="_blank" rel="noopener">Report ↗</a>
    </li>`).join('') : '<li class="empty">No runs yet.</li>';
  return list;
}

/** After a page refresh, show the latest run again (without animations). */
async function restoreLatest(history) {
  if (!history.length) return;
  try {
    const res = await fetch(history[0].report.replace('index.html', 'results.json'));
    if (!res.ok) return;
    const data = await res.json();
    state.results = data.results;
    state.assertions = data.results.reduce((n, r) => n + r.assertions.length, 0);
    state.assertionsFailed = data.results.reduce((n, r) => n + r.assertions.filter((a) => !a.passed && !a.skipped).length, 0);
    $('#feed').classList.add('no-anim');
    $('#feed').innerHTML = data.results.map(rowHtml).join('') || '<div class="empty">No results.</div>';
    renderTable();
    updateStats(false);
    drawCharts();
    const e = data.run;
    $('#statTime').textContent = (e.durationMs / 1000).toFixed(1) + ' s';
    setRunState(e.failed ? `${e.failed} of ${e.total} failed` : `All ${e.total} passed`, e.failed ? 'bad' : 'ok');
    $('#tableMeta').textContent = `· latest run (${e.label}, ${e.started})`;
  } catch (err) { /* nothing to restore */ }
}

// ================================================================== THEME + PACE + BUTTONS
$('#themeBtn').addEventListener('click', () => {
  const isDark = cssVar('color-scheme') === 'dark';
  const next = isDark ? 'light' : 'dark';
  document.documentElement.dataset.theme = next;
  try { localStorage.setItem('theme', next); } catch (e) { /* private mode */ }
  applyChartTheme();
});

$$('.pace .seg').forEach((btn) => btn.addEventListener('click', () => {
  $$('.pace .seg').forEach((b) => b.classList.toggle('active', b === btn));
  state.pace = Number(btn.dataset.pace);
  try { localStorage.setItem('pace', btn.dataset.pace); } catch (e) { /* ignore */ }
}));
try {
  const savedPace = localStorage.getItem('pace');
  if (savedPace !== null) $(`.pace .seg[data-pace="${savedPace}"]`)?.click();
} catch (e) { /* ignore */ }

$('#runAllBtn').addEventListener('click', () => startRun('all'));
$('#reportBtn').addEventListener('click', () => window.open('/control/report', '_blank'));

// ================================================================== START
(async function init() {
  makeCharts();
  pollHealth();
  setInterval(pollHealth, 3000);
  try {
    await Promise.all([loadSuites(), loadBug()]);
  } catch (err) {
    toast('Could not reach the server: ' + err.message, 5000);
  }
  const history = await loadHistory();
  // If a run is already in progress (e.g. the page was refreshed), re-attach to it.
  const { running } = await api('/control/status').catch(() => ({}));
  if (running) {
    resetView(state.suites.map((s) => s.name));
    openStream(running);
  } else {
    await restoreLatest(history);
  }
})();
