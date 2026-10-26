# Automated API Testing with Postman & Newman

Software Testing AAT · BMS College of Engineering
Team: **Kaustubh · Aayush Jalan · Utsav Adhikari**

The project tests a REST API at the API level, with no browser UI involved. It has three parts:

| Part | What it is | Where |
|------|------------|-------|
| System under test | FastAPI **Student Management API** with validation, auth and a toggleable planted bug | `app/student_api.py` |
| Test suite | **Postman collection** (v2.1) with 53 test cases in 6 folders, plus an environment and a CSV data file | `postman/` |
| Test Control Center | Web dashboard that runs the suites with **Newman** and streams the results live | `app/control_center.py`, `runner/`, `dashboard/` |

---

## 1. Quick start (one command)

Requirements: **Python 3.9+** and **Node.js 18+** (`python3 --version`, `node --version`).

```bash
./start.sh
```

`start.sh` does the following:
1. creates `.venv` and installs FastAPI/Uvicorn, but only if they are missing
2. runs `npm install` for `newman`, `newman-reporter-htmlextra` and `chart.js`, but only if they are missing
3. starts the server on **port 8000**. If 8000 is taken by another program it uses 8001, 8002 and so on, and it never kills anything.
   If the app is already running, it just opens the browser.
4. opens **http://localhost:8000/**

Stop the server with **Ctrl+C**.

| URL | What |
|-----|------|
| `http://localhost:8000/` | Test Control Center (dashboard) |
| `http://localhost:8000/docs` | Swagger UI for the API |
| `http://localhost:8000/control/report` | HTML report of the latest run (index page linking each suite's report) |

> Everything is served locally, including Chart.js, so the demo works **without internet**.

---

## 2. Using the dashboard

- **Run All Suites**: runs all 6 folders one after another. Each suite card also has its own ▶ button.
- **Pace**: *Presenter* adds a 250 ms pause between requests so the audience can follow. *Full speed* runs without pauses.
- **Bug Mode**: plants a real defect in the running API. A red banner appears while it is on, and the line
  under the dropdown says which tests should catch it. Each bug is one line in `app/student_api.py` (search for `<-- BUG`).

  | Bug | Fails |
  |-----|-------|
  | Marks above 100 accepted | BVA-08, DD-11 |
  | POST returns 200, not 201 | every "create" test (15) |
  | Wrong token accepted | AUTH-02, AUTH-04 |
  | Names over 50 chars accepted | BVA-12 |
  | Duplicate USN allowed | NEG-04, DD-15 |
  | GET /students takes 800 ms | POS-02, AUTH-06 (response-time checks) |
  | GET by id renames the 'age' field | POS-03, CHN-02 (JSON schema checks) |
  | **ALL bugs at once** | all 26 of the above |
- **Purple "Invalid input → rejected" badge**: marks error scenarios (Negative, invalid Boundary values,
  Auth 401/403 checks and the invalid CSV rows). They send bad input on purpose and **PASS when the API correctly rejects it**.
  A legend above the feed explains PASS / FAIL / this badge.
- **How it works**: the 6-step pipeline lights up as Newman processes each request.
- **Live results**: click any row to open the request, response, every `pm.test()` result and the test script itself.
  The failing lines of the script are highlighted.
- **Test case table**: ID | Type | Input | Expected | Actual | Pass/Fail. You can filter it and export it to CSV.
- **HTML report**: opens an index page for the latest run, with one Newman *htmlextra* report per suite.
- `[setup] Reset data` requests appear as small grey "setup" lines. They are **not** counted as tests.

---

## 3. Running from the terminal (backup / CI)

```bash
./run_tests.sh                 # all suites with the Newman CLI
./run_tests.sh Boundary Auth   # only some suites
./run_bug_demo.sh              # bug mode ON → the suite that catches it → bug mode OFF
./run_bug_demo.sh auth_bypass  # any bug: wrong_status, auth_bypass, name_length,
                               #   duplicate_usn, slow_response, wrong_body, all
```

Reports are saved to `reports/cli/<timestamp>/index.html`. If the server isn't running, the scripts start a temporary one.

The underlying Newman command is the one you would put in a CI pipeline (GitHub Actions, Jenkins, …):

```bash
npx newman run postman/Student_Management_API.postman_collection.json \
    -e postman/Local.postman_environment.json \
    --folder "Data-Driven" -d postman/data/students.csv \
    -r cli,htmlextra --reporter-htmlextra-export report.html
```

Newman exits with a **non-zero code when any test fails**, which makes the CI build fail.

---

## 4. Importing into the Postman desktop app

1. Start the server (`./start.sh`).
2. Postman → **Import** → drag in both files:
   - `postman/Student_Management_API.postman_collection.json`
   - `postman/Local.postman_environment.json`
3. In the top-right environment dropdown, choose **Student API - Local**.
4. Send any request, for example *Positive → POS-03 Get student by id*, and look at the **Test Results** tab.
5. To run a whole folder: right-click the folder → **Run folder** → **Run**.
6. **Data-Driven** folder: in the Runner, click **Select File** → choose `postman/data/students.csv` → it runs 15 iterations.
   Without the CSV, its test is skipped instead of failing.

> If you changed the port (e.g. 8001), edit `baseUrl` in the environment.

---

## 5. The API (system under test)

| Method | Path | Auth | Success | Errors |
|--------|------|------|---------|--------|
| GET | `/health` | - | 200 | |
| POST | `/reset` | - | 200 (restores 3 seed students) | |
| GET | `/students` | - | 200 | |
| GET | `/students/{id}` | - | 200 | 404, 422 |
| POST | `/students` | Bearer | 201 | 401, 403, 409, 422 |
| PUT | `/students/{id}` | Bearer | 200 | 401, 403, 404, 409, 422 |
| DELETE | `/students/{id}` | Bearer | 200 | 401, 403, 404 |

Rules: `name` 1–50 chars · `usn` like `1BM23AD028` · `age` 17–30 · `marks` 0–100.
Token: `Authorization: Bearer demo-token-123` (none → **401**, wrong → **403**).

---

## 6. Test suites (53 test cases)

| Folder | Cases | Technique |
|--------|------:|-----------|
| Positive | 6 | Happy path, response schema, response time |
| Negative | 8 | 404 / 409 / 422, error messages |
| Boundary | 12 | Boundary Value Analysis on age (16/17/30/31), marks (-1/0/100/101), name (0/1/50/51 chars) |
| Auth | 6 | Missing token (401), wrong token (403), valid token |
| Chaining | 6 | `pm.environment.set("createdId")`, then reuse `{{createdId}}` |
| Data-Driven | 15 | One request × 15 rows of `students.csv` (with `expected_status`) |

See **TEST_CASES.md** for the full table.

---

## 7. Project structure

```
app/
  student_api.py       System under test (validation, auth, planted bug)
  control_center.py    /control/* endpoints: run Newman, SSE stream, bug mode, history, reports
  main.py              Wires the API, dashboard and reports into one FastAPI app
runner/run_newman.js   newman.run() + event listeners → one JSON line per event
dashboard/             index.html, styles.css, app.js (vanilla JS + Chart.js, no build step)
postman/               Collection, environment, data/students.csv
tools/build_collection.py   Generates the collection, environment and TEST_CASES.md
start.sh  run_tests.sh  run_bug_demo.sh  scripts/common.sh
reports/               Generated reports (git-ignored)
```

### How the live dashboard works

```
Browser ──POST /control/run──▶ FastAPI ──spawns──▶ node run_newman.js ──HTTP──▶ Student API
   ▲                              │                    │ newman.run().on('request' | 'assertion' | …)
   └──── Server-Sent Events ◀─────┴──── JSON lines ◀───┘
```

### Editing the tests

The collection is generated from `tools/build_collection.py`, so every test case is defined in one readable place.
After changing it, run:

```bash
.venv/bin/python tools/build_collection.py
```

---

## 8. Troubleshooting

| Problem | Fix |
|---------|-----|
| `node: command not found` | Install Node.js LTS from nodejs.org |
| Dashboard says *API offline* | The server stopped. Run `./start.sh` again. |
| "A run is already in progress" | Wait for the current run to finish (a few seconds) |
| Postman requests fail to connect | Make sure the server is running and `baseUrl` matches the port |
