#!/usr/bin/env node
/*
 * run_newman.js - runs ONE folder (suite) of the Postman collection with the
 * Newman library and prints every interesting event as ONE JSON LINE on stdout.
 *
 * The FastAPI "Test Control Center" starts this script, reads its stdout
 * line by line and forwards each line to the browser (Server-Sent Events).
 * That is how the dashboard shows tests appearing one by one in real time.
 *
 * Usage:
 *   node runner/run_newman.js --folder Boundary [--data postman/data/students.csv]
 *        [--report reports/runs/x/Boundary.html] [--base-url http://localhost:8000]
 *        [--delay 250]
 *
 * Event lines printed (field "type"):
 *   start   - run started
 *   phase   - which pipeline step is active (request, prerequest, api, response, tests, report)
 *   result  - one finished request with its request, response and assertions
 *   done    - totals for the whole folder
 *   error   - something went wrong before or while running
 */

process.noDeprecation = true;   // hide a harmless Node 24 warning from a dependency
const path = require('path');
const newman = require('newman');

const ROOT = path.join(__dirname, '..');
const COLLECTION = path.join(ROOT, 'postman', 'Student_Management_API.postman_collection.json');
const ENVIRONMENT = path.join(ROOT, 'postman', 'Local.postman_environment.json');

// ---- tiny argument parser: --key value -------------------------------------
const args = {};
for (let i = 2; i < process.argv.length; i += 2) {
  args[process.argv[i].replace(/^--/, '')] = process.argv[i + 1];
}
if (!args.folder) {
  console.error('usage: run_newman.js --folder <name> [--data file.csv] [--report out.html]');
  process.exit(2);
}

/** Print one event as a JSON line (this is the "protocol" to the dashboard). */
function emit(type, data) {
  process.stdout.write(JSON.stringify({ type, suite: args.folder, ...data }) + '\n');
}

/** Keep large bodies from flooding the browser. */
function clip(text, max = 4000) {
  if (text == null) return '';
  text = String(text);
  return text.length > max ? text.slice(0, max) + '\n... (truncated)' : text;
}

/** The source code of an item's test or pre-request script, as one string. */
function scriptSource(item, listen) {
  const ev = (item.events && item.events.members || []).find(e => e.listen === listen);
  if (!ev || !ev.script) return '';
  const exec = ev.script.exec;
  return Array.isArray(exec) ? exec.join('\n') : String(exec || '');
}

// Results are built up across several newman events and keyed by "cursor.ref",
// which is unique for each (item, iteration) pair.
const pending = {};
let counter = 0;

// ---- newman options --------------------------------------------------------
const options = {
  collection: require(COLLECTION),
  environment: require(ENVIRONMENT),
  folder: args.folder,
  reporters: [],
  delayRequest: Number(args.delay || 0),   // "presenter pace": pause between requests
  timeoutRequest: 10000,
};
if (args['base-url']) {
  options.envVar = [{ key: 'baseUrl', value: args['base-url'] }];
}
if (args.data) {
  options.iterationData = path.resolve(ROOT, args.data);
}
if (args.report) {
  options.reporters = ['htmlextra'];
  options.reporter = {
    htmlextra: {
      export: path.resolve(ROOT, args.report),
      title: `Student API - ${args.folder} suite`,
      browserTitle: `${args.folder} - Newman report`,
      logs: false,
    },
  };
}

// ---- run and listen to events ------------------------------------------------
newman.run(options)
  .on('start', () => emit('start', { folder: args.folder }))

  .on('beforeItem', (err, a) => {
    const item = a.item;
    const kind = item.name.startsWith('[setup]') ? 'setup' : 'test';
    pending[a.cursor.ref] = {
      id: ++counter,
      name: item.name,
      kind,
      description: item.request && item.request.description
        ? String(item.request.description.content || item.request.description) : '',
      iteration: a.cursor.iteration + 1,
      iterations: a.cursor.cycles,
      testScript: scriptSource(item, 'test'),
      prerequestScript: scriptSource(item, 'prerequest'),
      assertions: [],
    };
    emit('phase', { step: 'request', name: item.name, kind });
  })

  .on('beforePrerequest', (err, a) => {
    const r = pending[a.cursor.ref];
    if (r && r.prerequestScript) emit('phase', { step: 'prerequest', name: r.name, kind: r.kind });
  })

  .on('beforeRequest', (err, a) => {
    const r = pending[a.cursor.ref];
    if (r) emit('phase', { step: 'api', name: r.name, kind: r.kind });
  })

  .on('request', (err, a) => {
    const r = pending[a.cursor.ref];
    if (!r) return;
    const req = a.request;
    r.method = req.method;
    r.url = req.url.toString();
    r.path = req.url.getPath();
    r.requestHeaders = (req.headers.members || [])
      .filter(h => !h.disabled)
      .map(h => ({ key: h.key, value: h.value }));
    r.requestBody = clip(req.body && req.body.raw);
    if (err) {
      r.networkError = err.message;
    } else {
      const res = a.response;
      r.code = res.code;
      r.status = res.status;
      r.time = res.responseTime;
      r.size = res.responseSize;
      r.responseBody = clip(res.stream ? res.stream.toString() : '');
    }
    emit('phase', { step: 'response', name: r.name, kind: r.kind });
  })

  .on('beforeTest', (err, a) => {
    const r = pending[a.cursor.ref];
    if (r && r.testScript) emit('phase', { step: 'tests', name: r.name, kind: r.kind });
  })

  .on('assertion', (err, a) => {
    const r = pending[a.cursor.ref];
    if (!r) return;
    r.assertions.push({
      name: a.assertion,
      passed: !err,
      skipped: !!a.skipped,
      error: err ? err.message : null,
    });
  })

  .on('item', (err, a) => {
    const r = pending[a.cursor.ref];
    if (!r) return;
    delete pending[a.cursor.ref];
    if (!r.method && !r.networkError) return;   // request was skipped (pm.execution.skipRequest)
    // A request passes when it reached the server and every assertion passed.
    r.passed = !r.networkError && r.assertions.every(x => x.passed || x.skipped);
    emit('result', r);
  })

  .on('done', (err, summary) => {
    if (err) {
      emit('error', { message: err.message });
      process.exitCode = 1;
      return;
    }
    const s = summary.run.stats;
    emit('phase', { step: 'report' });
    emit('done', {
      requests: s.requests.total,
      requestsFailed: s.requests.failed,
      assertions: s.assertions.total,
      assertionsFailed: s.assertions.failed,
      iterations: s.iterations.total,
      durationMs: summary.run.timings.completed - summary.run.timings.started,
      report: args.report || null,
    });
    process.exitCode = summary.run.failures.length ? 1 : 0;
  });
