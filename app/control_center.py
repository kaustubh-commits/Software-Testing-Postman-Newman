"""
Test Control Center backend: the endpoints the dashboard uses to run Newman.

How a run works:
  1. The browser calls POST /control/run {"suite": "Boundary"} and gets a run_id.
  2. We start `node runner/run_newman.js --folder Boundary ...` as a subprocess.
     The runner uses the Newman library and prints one JSON event per line.
  3. The browser opens GET /control/stream/{run_id} (Server-Sent Events).
     Every line the runner prints is forwarded to the browser right away,
     so tests appear one by one in real time.
  4. Each suite writes its own htmlextra report, and we write an index.html
     that links all of them. "Open HTML report" opens that index.
"""

import asyncio
import csv
import html
import json
import os
import re
import shutil
import time
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import RedirectResponse, StreamingResponse
from pydantic import BaseModel

from . import student_api

router = APIRouter(prefix="/control", tags=["Test Control Center"])

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNNER = os.path.join(ROOT, "runner", "run_newman.js")
COLLECTION = os.path.join(ROOT, "postman", "Student_Management_API.postman_collection.json")
CSV_FILE = os.path.join("postman", "data", "students.csv")
REPORTS = os.path.join(ROOT, "reports")
HISTORY_FILE = os.path.join(REPORTS, "history.json")

# The port this server listens on (start.sh sets APP_PORT if 8000 was busy)
APP_PORT = int(os.environ.get("APP_PORT", "8000"))
BASE_URL = f"http://127.0.0.1:{APP_PORT}"

SUITE_ORDER = ["Positive", "Negative", "Boundary", "Auth", "Chaining", "Data-Driven"]
DATA_FILES = {"Data-Driven": CSV_FILE}      # suites that need `-d <csv>`


def load_csv_rows():
    with open(os.path.join(ROOT, CSV_FILE), newline="") as f:
        return list(csv.DictReader(f))


def load_suites():
    """Suite names, descriptions and test counts, read from the collection."""
    with open(COLLECTION) as f:
        collection = json.load(f)
    suites = []
    for folder in collection["item"]:
        tests = [i for i in folder["item"] if not i["name"].startswith("[setup]")]
        count = len(load_csv_rows()) if folder["name"] in DATA_FILES else len(tests)
        suites.append({"name": folder["name"], "description": folder.get("description", ""),
                       "count": count})
    return suites


# --------------------------------------------------------------------------
# Run state (only one run at a time)
# --------------------------------------------------------------------------
class Run:
    def __init__(self, run_id: str, suites: list, pace_ms: int):
        self.id = run_id
        self.suites = suites
        self.pace_ms = pace_ms
        self.events: list = []            # every event so far (late subscribers replay these)
        self.new_event = asyncio.Event()  # wakes up the SSE streams
        self.finished = False
        self.results: list = []           # test results (setup steps excluded)
        self.suite_summaries: list = []
        self.dir = os.path.join(REPORTS, "runs", run_id)
        self.started = time.time()

    def publish(self, event: dict):
        self.events.append(event)
        self.new_event.set()
        self.new_event = asyncio.Event()


RUNS: dict = {}
current_run: Optional[Run] = None


def read_history() -> list:
    try:
        with open(HISTORY_FILE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return []


def enrich(event: dict, suite: str, csv_rows: list) -> dict:
    """Add the test-case-table fields (caseId, expected, actual, input) to a result."""
    description = event.get("description", "")
    match = re.search(r"\*\*Expected:\*\*\s*(.+)", description)
    expected = match.group(1).strip() if match else ""
    name = event["name"]
    if suite in DATA_FILES and event["kind"] == "test":
        row = csv_rows[event["iteration"] - 1] if event["iteration"] <= len(csv_rows) else {}
        case_id = row.get("case_id", f"DD-{event['iteration']:02d}")
        name = f"{row.get('scenario', name)}"
        expected = row.get("expected_status", expected)
    elif event["kind"] == "setup":
        case_id = "SETUP"
    else:
        case_id, _, name = name.partition(" ")
    actual = f"{event.get('code', 'ERR')} {event.get('status', '')}".strip()
    if event.get("networkError"):
        actual = "No response: " + event["networkError"]
    failed = [a for a in event.get("assertions", []) if not a["passed"] and not a["skipped"]]
    event.update(caseId=case_id, title=name, suite=suite, expected=expected, actual=actual,
                 failedAssertions=len(failed))
    return event


async def run_one_suite(run: Run, suite: str, index: int):
    """Run one Newman folder and forward its events. Returns the 'done' summary."""
    report_rel = f"reports/runs/{run.id}/{suite}.html"
    cmd = [shutil.which("node") or "node", RUNNER, "--folder", suite,
           "--report", report_rel, "--base-url", BASE_URL, "--delay", str(run.pace_ms)]
    if suite in DATA_FILES:
        cmd += ["--data", DATA_FILES[suite]]
    csv_rows = load_csv_rows() if suite in DATA_FILES else []

    run.publish({"type": "suite_start", "suite": suite, "index": index, "of": len(run.suites)})
    proc = await asyncio.create_subprocess_exec(
        *cmd, cwd=ROOT, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        limit=1024 * 1024)                              # allow long JSON lines

    summary = None
    async for raw in proc.stdout:                       # one JSON event per line
        line = raw.decode().strip()
        if not line.startswith("{"):
            continue
        event = json.loads(line)
        if event["type"] == "result":
            event = enrich(event, suite, csv_rows)
            if event["kind"] == "test":
                run.results.append(event)
        elif event["type"] == "done":
            summary = event
        run.publish(event)

    stderr = (await proc.stderr.read()).decode().strip()
    await proc.wait()
    if summary is None:
        run.publish({"type": "error", "suite": suite,
                     "message": stderr[-800:] or f"Newman exited with code {proc.returncode}"})
    tests = [r for r in run.results if r["suite"] == suite]
    run.suite_summaries.append({
        "suite": suite, "report": f"{suite}.html" if summary else None,
        "tests": len(tests), "passed": sum(r["passed"] for r in tests),
        "failed": sum(not r["passed"] for r in tests),
        "assertions": summary["assertions"] if summary else 0,
        "assertionsFailed": summary["assertionsFailed"] if summary else 0,
        "durationMs": summary["durationMs"] if summary else 0,
    })
    write_index(run)        # refreshed after every suite, so the report is never partial-only


async def execute(run: Run):
    global current_run
    os.makedirs(run.dir, exist_ok=True)
    run.publish({"type": "run_start", "runId": run.id, "suites": run.suites,
                 "bugMode": dict(student_api.BUG_MODE)})
    try:
        for i, suite in enumerate(run.suites, start=1):
            await run_one_suite(run, suite, i)
    except Exception as exc:                            # never leave the UI hanging
        run.publish({"type": "error", "message": str(exc)})
    finally:
        passed = sum(r["passed"] for r in run.results)
        entry = {
            "id": run.id, "suites": run.suites,
            "label": "All suites" if len(run.suites) > 1 else run.suites[0],
            "started": datetime.fromtimestamp(run.started).strftime("%H:%M:%S"),
            "durationMs": int((time.time() - run.started) * 1000),
            "total": len(run.results), "passed": passed, "failed": len(run.results) - passed,
            "bugMode": dict(student_api.BUG_MODE),
            "report": f"/reports/runs/{run.id}/index.html",
        }
        with open(os.path.join(run.dir, "results.json"), "w") as f:
            json.dump({"run": entry, "results": run.results}, f, indent=2)
        history = [entry] + read_history()
        os.makedirs(REPORTS, exist_ok=True)
        with open(HISTORY_FILE, "w") as f:
            json.dump(history[:20], f, indent=2)
        run.finished = True
        run.publish({"type": "run_done", **entry})
        current_run = None


def write_index(run: Run):
    """One page that links every suite report of this run."""
    rows = []
    for s in run.suite_summaries:
        ok = s["failed"] == 0 and s["report"]
        link = (f'<a href="{html.escape(s["report"])}">Open report →</a>' if s["report"]
                else "<em>no report (run error)</em>")
        rows.append(
            f'<tr><td><b>{html.escape(s["suite"])}</b></td>'
            f'<td class="{"ok" if ok else "bad"}">{"PASS" if ok else "FAIL"}</td>'
            f'<td>{s["passed"]} / {s["tests"]}</td>'
            f'<td>{s["assertions"] - s["assertionsFailed"]} / {s["assertions"]}</td>'
            f'<td>{s["durationMs"]} ms</td><td>{link}</td></tr>')
    total = sum(s["tests"] for s in run.suite_summaries)
    passed = sum(s["passed"] for s in run.suite_summaries)
    bug = student_api.BUG_MODE
    bug_note = (f'<p class="bug">⚠ Bug mode was ON during this run: '
                f'{html.escape(student_api.BUG_TYPES[bug["type"]])}</p>' if bug["enabled"] else "")
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Newman Run {run.id}</title>
<style>
 body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Inter,sans-serif;background:#0f141b;color:#e6edf3;margin:0;padding:40px 16px}}
 main{{max-width:960px;margin:0 auto}} h1{{margin:0 0 4px;font-size:28px}} .sub{{color:#8b98a5;margin:0 0 28px}}
 .big{{font-size:20px;margin:0 0 20px}} table{{width:100%;border-collapse:collapse;background:#161d26;border-radius:12px;overflow:hidden}}
 th,td{{padding:14px 16px;text-align:left;border-bottom:1px solid #243041;font-size:16px}} th{{color:#8b98a5;font-weight:600;font-size:13px;text-transform:uppercase;letter-spacing:.05em}}
 .ok{{color:#3fb950;font-weight:700}} .bad{{color:#f85149;font-weight:700}} a{{color:#58a6ff}}
 .bug{{background:#3d1d20;border:1px solid #f85149;color:#ffb3ad;padding:12px 16px;border-radius:10px}}
</style></head><body><main>
<h1>Student Management API: Newman run</h1>
<p class="sub">Run {run.id} · {len(run.suite_summaries)} of {len(run.suites)} suite(s) · generated by the Test Control Center</p>
{bug_note}
<p class="big"><span class="{'ok' if passed == total else 'bad'}">{passed} / {total}</span> test cases passed</p>
<table><thead><tr><th>Suite</th><th>Result</th><th>Test cases</th><th>Assertions</th><th>Time</th><th>Report</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table>
</main></body></html>"""
    with open(os.path.join(run.dir, "index.html"), "w") as f:
        f.write(page)


# --------------------------------------------------------------------------
# Endpoints
# --------------------------------------------------------------------------
class RunRequest(BaseModel):
    suite: str = "all"
    pace_ms: int = 250        # pause between requests so the audience can follow


class BugRequest(BaseModel):
    enabled: bool
    type: Optional[str] = None


@router.get("/suites")
def suites():
    return load_suites()


@router.post("/run")
async def start_run(req: RunRequest):
    global current_run
    if current_run is not None:
        raise HTTPException(409, f"A run is already in progress ({current_run.id})")
    if req.suite == "all":
        chosen = SUITE_ORDER
    elif req.suite in SUITE_ORDER:
        chosen = [req.suite]
    else:
        raise HTTPException(404, f"Unknown suite {req.suite}")
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S-%f")[:-3]   # e.g. 20261027-101500-123
    run = Run(run_id, chosen, max(0, min(req.pace_ms, 2000)))
    RUNS[run_id] = run
    current_run = run
    run.task = asyncio.create_task(execute(run))   # keep a reference so it isn't garbage-collected
    return {"runId": run_id, "suites": chosen}


@router.get("/status")
def status():
    return {"running": current_run.id if current_run else None}


@router.get("/stream/{run_id}")
async def stream(run_id: str):
    """Server-Sent Events: replay what happened so far, then push new events live."""
    run = RUNS.get(run_id)
    if run is None:
        raise HTTPException(404, "Unknown run")

    async def event_source():
        sent = 0
        while True:
            while sent < len(run.events):
                yield f"data: {json.dumps(run.events[sent])}\n\n"
                sent += 1
            if run.finished:
                return
            try:
                await asyncio.wait_for(run.new_event.wait(), timeout=15)
            except asyncio.TimeoutError:
                yield ": keep-alive\n\n"          # SSE comment, keeps the connection open

    return StreamingResponse(event_source(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/bug-mode")
def get_bug_mode():
    return {**student_api.BUG_MODE, "types": student_api.BUG_TYPES}


@router.post("/bug-mode")
def set_bug_mode(req: BugRequest):
    if req.type is not None:
        if req.type not in student_api.BUG_TYPES:
            raise HTTPException(422, f"Unknown bug type {req.type}")
        student_api.BUG_MODE["type"] = req.type
    student_api.BUG_MODE["enabled"] = req.enabled
    return {**student_api.BUG_MODE, "types": student_api.BUG_TYPES}


@router.get("/history")
def history():
    return read_history()


@router.get("/report")
def latest_report():
    """Opens the index page of the latest run, which links every suite report."""
    entries = read_history()
    if not entries:
        raise HTTPException(404, "No report yet. Run a suite first.")
    return RedirectResponse(entries[0]["report"])
