"""
build_collection.py - generates the Postman collection, the environment and
TEST_CASES.md from ONE list of test cases defined below.

Why generate instead of hand-writing JSON?
  * A Postman collection is a large JSON file, so one missing comma breaks it.
  * Every test case lives here once, and the collection and TEST_CASES.md are
    always in sync.
The generated JSON is a normal Postman v2.1 collection. Import it into the
Postman app like any other collection.

Run:   python3 tools/build_collection.py
       python3 tools/build_collection.py --results reports/runs/<id>/results.json
       (the second form also fills the "Actual" and "Result" columns of
        TEST_CASES.md from a real dashboard run)
"""

import argparse
import csv
import json
import os
import uuid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
POSTMAN_DIR = os.path.join(ROOT, "postman")
CSV_PATH = os.path.join(POSTMAN_DIR, "data", "students.csv")

# --------------------------------------------------------------------------
# Reusable pm.test() snippets (JavaScript, as lists of lines)
# --------------------------------------------------------------------------
STUDENT_SCHEMA = [
    "const studentSchema = {",
    "    type: 'object',",
    "    required: ['id', 'name', 'usn', 'age', 'marks'],",
    "    properties: {",
    "        id:    { type: 'integer' },",
    "        name:  { type: 'string', minLength: 1, maxLength: 50 },",
    "        usn:   { type: 'string', pattern: '^[1-4][A-Z]{2}\\\\d{2}[A-Z]{2}\\\\d{3}$' },",
    "        age:   { type: 'integer', minimum: 17, maximum: 30 },",
    "        marks: { type: 'integer', minimum: 0, maximum: 100 }",
    "    }",
    "};",
]

STATUS_TEXT = {200: "OK", 201: "Created", 401: "Unauthorized", 403: "Forbidden",
               404: "Not Found", 409: "Conflict", 422: "Unprocessable Entity"}


def t_status(code):
    return [f'pm.test("Status code is {code} {STATUS_TEXT[code]}", function () {{',
            f"    pm.response.to.have.status({code});",
            "});"]


def t_time(ms=500):
    return [f'pm.test("Response time is below {ms} ms", function () {{',
            f"    pm.expect(pm.response.responseTime).to.be.below({ms});",
            "});"]


def t_schema():
    return STUDENT_SCHEMA + [
        'pm.test("Body matches the Student JSON schema", function () {',
        "    pm.response.to.have.jsonSchema(studentSchema);",
        "});"]


def t_detail(text):
    """Error responses look like {"detail": "..."}; check the message."""
    return [f'pm.test("Error message mentions \\"{text}\\"", function () {{',
            f'    pm.expect(pm.response.json().detail).to.include("{text}");',
            "});"]


def t_field_error(field):
    """422 responses list which field was invalid."""
    return [f'pm.test("Validation error points at the \'{field}\' field", function () {{',
            "    const body = pm.response.json();",
            '    pm.expect(body.message).to.eql("Validation failed");',
            "    const fields = body.errors.map(e => e.field);",
            f'    pm.expect(fields).to.include("{field}");',
            "});"]


def t_not_created():
    return ['pm.test("No student was created (no id in body)", function () {',
            "    pm.expect(pm.response.json()).to.not.have.property('id');",
            "});"]


def t_echo(body):
    """The created/updated student echoes every submitted field."""
    lines = ['pm.test("Body echoes the submitted data", function () {',
             "    const s = pm.response.json();"]
    for key, value in body.items():
        lines.append(f"    pm.expect(s.{key}).to.eql({json.dumps(value)});")
    return lines + ["});"]


# --------------------------------------------------------------------------
# Test case definitions
# --------------------------------------------------------------------------
# Each case: id, name, method, path, body, auth ("token" | "wrong" | "none"),
#            expected (human text), tests (JS lines), pre (pre-request JS lines),
#            invalid (True = error scenario: deliberately invalid input that
#                     PASSES when the API correctly rejects it)

def case(cid, name, method, path, expected, tests, body=None, auth="none",
         pre=None, about="", invalid=False):
    return dict(id=cid, name=name, method=method, path=path, body=body, auth=auth,
                expected=expected, tests=tests, pre=pre or [], about=about, invalid=invalid)


def valid_body(usn, **over):
    body = {"name": "Test Student", "usn": usn, "age": 20, "marks": 75}
    body.update(over)
    return body


SETUP = case("SETUP", "[setup] Reset data", "POST", "/reset", "200, seed data restored",
             [], about="Restores the 3 seed students so this suite starts from a known state. "
                       "Shown as a 'setup' step, not as a test.")

# ---------------- Positive ----------------
POSITIVE = [
    case("POS-01", "Health check", "GET", "/health", "200, status is ok",
         t_status(200) + t_time() + [
             'pm.test("API reports status ok", function () {',
             '    pm.expect(pm.response.json().status).to.eql("ok");',
             "});"],
         about="The API is up and reachable."),
    case("POS-02", "List all students", "GET", "/students", "200, array of 3 seed students",
         t_status(200) + t_time() + STUDENT_SCHEMA + [
             'pm.test("Returns an array of 3 students", function () {',
             "    const list = pm.response.json();",
             "    pm.expect(list).to.be.an('array').with.lengthOf(3);",
             "});",
             'pm.test("Every student matches the schema", function () {',
             "    pm.response.to.have.jsonSchema({ type: 'array', items: studentSchema });",
             "});"],
         about="GET /students returns the full list."),
    case("POS-03", "Get student by id", "GET", "/students/1", "200, student 1 is Aayush Jalan",
         t_status(200) + t_time() + t_schema() + [
             'pm.test("Returns the right student", function () {',
             "    const s = pm.response.json();",
             "    pm.expect(s.id).to.eql(1);",
             '    pm.expect(s.name).to.eql("Aayush Jalan");',
             "});"],
         about="GET /students/{id} returns one student."),
    case("POS-04", "Create a valid student", "POST", "/students",
         "201 Created, body echoes data with a new id",
         t_status(201) + t_time() + t_schema() + [
             'pm.test("Body echoes the submitted data", function () {',
             "    const s = pm.response.json();",
             '    pm.expect(s.name).to.eql("Riya Sharma");',
             '    pm.expect(s.usn).to.eql(pm.variables.get("randomUsn"));',
             "    pm.expect(s.age).to.eql(19);",
             "    pm.expect(s.marks).to.eql(87);",
             "});",
             'pm.test("A new id was assigned", function () {',
             "    pm.expect(pm.response.json().id).to.be.above(3);",
             "});"],
         body={"name": "Riya Sharma", "usn": "{{randomUsn}}", "age": 19, "marks": 87},
         auth="token",
         pre=["// Pre-request script: build a unique USN so this test never hits a duplicate",
              "const n = Math.floor(Math.random() * 900) + 100;   // 100-999",
              'pm.variables.set("randomUsn", "1BM23AD" + n);'],
         about="POST /students with valid data and a valid token."),
    case("POS-05", "Update a student", "PUT", "/students/2", "200, marks updated to 95",
         t_status(200) + t_time() + t_echo(valid_body("1BM23AD002", name="Utsav Adhikari", marks=95, age=21)),
         body=valid_body("1BM23AD002", name="Utsav Adhikari", marks=95, age=21), auth="token",
         about="PUT /students/{id} replaces the student's data."),
    case("POS-06", "Delete a student", "DELETE", "/students/3", "200, deletion message",
         t_status(200) + t_time() + [
             'pm.test("Confirms the deletion", function () {',
             '    pm.expect(pm.response.json().message).to.include("deleted");',
             "});"],
         auth="token", about="DELETE /students/{id} removes the student."),
]

# ---------------- Negative ----------------
NEGATIVE = [
    case("NEG-01", "Get a non-existent student", "GET", "/students/9999", "404 Not Found",
         t_status(404) + t_time() + t_detail("not found"), about="Unknown ids return 404."),
    case("NEG-02", "Update a non-existent student", "PUT", "/students/9999", "404 Not Found",
         t_status(404) + t_detail("not found"), body=valid_body("1BM23AD300"), auth="token",
         about="PUT on an unknown id returns 404."),
    case("NEG-03", "Delete a non-existent student", "DELETE", "/students/9999", "404 Not Found",
         t_status(404) + t_detail("not found"), auth="token",
         about="DELETE on an unknown id returns 404."),
    case("NEG-04", "Create with a duplicate USN", "POST", "/students", "409 Conflict",
         t_status(409) + t_detail("already exists"), body=valid_body("1BM23AD001"), auth="token",
         about="1BM23AD001 already belongs to a seed student."),
    case("NEG-05", "Create with an invalid USN format", "POST", "/students", "422, error on 'usn'",
         t_status(422) + t_field_error("usn") + t_not_created(), body=valid_body("ABC123"),
         auth="token", about="USN must look like 1BM23AD028."),
    case("NEG-06", "Create with a missing field", "POST", "/students", "422, error on 'marks'",
         t_status(422) + t_field_error("marks"),
         body={"name": "No Marks", "usn": "1BM23AD301", "age": 20}, auth="token",
         about="All four fields are required."),
    case("NEG-07", "Create with a wrong data type", "POST", "/students", "422, error on 'age'",
         t_status(422) + t_field_error("age"),
         body={"name": "Wrong Type", "usn": "1BM23AD302", "age": "twenty", "marks": 70},
         auth="token", about="age must be an integer."),
    case("NEG-08", "Non-numeric id in the URL", "GET", "/students/abc", "422, error on 'student_id'",
         t_status(422) + t_field_error("student_id"), about="Path ids must be integers."),
]
for c in NEGATIVE:          # every Negative test sends invalid input on purpose
    c["invalid"] = True

# ---------------- Boundary Value Analysis ----------------
def bva(cid, label, field, value, valid, usn):
    body = valid_body(usn, **{field: value})
    if valid:
        expected, tests = "201 Created", t_status(201) + t_echo({field: value})
    else:
        expected = f"422, error on '{field}'"
        tests = t_status(422) + t_field_error(field) + t_not_created()
    shown = f'"{value}" ({len(value)} chars)' if field == "name" else value
    return case(cid, label, "POST", "/students", expected, tests, body=body, auth="token",
                invalid=not valid,
                about=f"Boundary value: {field} = {shown}. "
                      f"{'On the edge but inside' if valid else 'Just outside'} the valid range.")


BOUNDARY = [
    bva("BVA-01", "Age 16 (below minimum)", "age", 16, False, "1BM23AD101"),
    bva("BVA-02", "Age 17 (minimum)", "age", 17, True, "1BM23AD102"),
    bva("BVA-03", "Age 30 (maximum)", "age", 30, True, "1BM23AD103"),
    bva("BVA-04", "Age 31 (above maximum)", "age", 31, False, "1BM23AD104"),
    bva("BVA-05", "Marks -1 (below minimum)", "marks", -1, False, "1BM23AD105"),
    bva("BVA-06", "Marks 0 (minimum)", "marks", 0, True, "1BM23AD106"),
    bva("BVA-07", "Marks 100 (maximum)", "marks", 100, True, "1BM23AD107"),
    bva("BVA-08", "Marks 101 (above maximum)", "marks", 101, False, "1BM23AD108"),
    bva("BVA-09", "Name 0 chars (empty)", "name", "", False, "1BM23AD109"),
    bva("BVA-10", "Name 1 char (minimum)", "name", "A", True, "1BM23AD110"),
    bva("BVA-11", "Name 50 chars (maximum)", "name", "A" * 50, True, "1BM23AD111"),
    bva("BVA-12", "Name 51 chars (above maximum)", "name", "A" * 51, False, "1BM23AD112"),
]

# ---------------- Auth ----------------
AUTH = [
    case("AUTH-01", "Create without a token", "POST", "/students", "401 Unauthorized",
         t_status(401) + t_detail("Missing bearer token"), body=valid_body("1BM23AD401"),
         auth="none", invalid=True, about="No Authorization header at all."),
    case("AUTH-02", "Create with a wrong token", "POST", "/students", "403 Forbidden",
         t_status(403) + t_detail("Invalid token"), body=valid_body("1BM23AD402"),
         auth="wrong", invalid=True, about="Header present but the token is wrong."),
    case("AUTH-03", "Update without a token", "PUT", "/students/1", "401 Unauthorized",
         t_status(401) + t_detail("Missing bearer token"), body=valid_body("1BM23AD001"),
         auth="none", invalid=True, about="PUT is protected too."),
    case("AUTH-04", "Delete with a wrong token", "DELETE", "/students/1", "403 Forbidden",
         t_status(403) + t_detail("Invalid token"), auth="wrong", invalid=True,
         about="DELETE is protected too."),
    case("AUTH-05", "Delete with a valid token", "DELETE", "/students/3", "200 OK",
         t_status(200), auth="token", about="The right token is accepted."),
    case("AUTH-06", "Read endpoints are public", "GET", "/students", "200 OK without a token",
         t_status(200) + t_time(), auth="none", about="GET does not need a token."),
]

# ---------------- Request chaining ----------------
CHAINING = [
    case("CHN-01", "Create a student and save its id", "POST", "/students",
         "201, id saved to environment as createdId",
         t_status(201) + [
             "// Save values from this response for the next requests",
             "const s = pm.response.json();",
             'pm.environment.set("createdId", s.id);',
             'pm.environment.set("createdUsn", s.usn);',
             'pm.test("Saved createdId = " + s.id + " for the next requests", function () {',
             '    pm.expect(pm.environment.get("createdId")).to.eql(s.id);',
             "});"],
         body={"name": "Chain Student", "usn": "{{chainUsn}}", "age": 22, "marks": 70},
         auth="token",
         pre=["// Pre-request script: unique USN for this chain",
              'pm.variables.set("chainUsn", "1BM23CS" + (Math.floor(Math.random() * 900) + 100));'],
         about="Step 1: create and remember the new id."),
    case("CHN-02", "Fetch the created student", "GET", "/students/{{createdId}}",
         "200, same USN as created",
         t_status(200) + t_schema() + [
             'pm.test("Same student that CHN-01 created", function () {',
             '    pm.expect(pm.response.json().usn).to.eql(pm.environment.get("createdUsn"));',
             "});"],
         about="Step 2: reuse {{createdId}} in the URL."),
    case("CHN-03", "Update the created student", "PUT", "/students/{{createdId}}",
         "200, marks now 99",
         t_status(200) + [
             'pm.test("Marks updated to 99", function () {',
             "    pm.expect(pm.response.json().marks).to.eql(99);",
             "});"],
         body={"name": "Chain Student", "usn": "{{createdUsn}}", "age": 22, "marks": 99},
         auth="token", about="Step 3: update it."),
    case("CHN-04", "Verify the update persisted", "GET", "/students/{{createdId}}",
         "200, marks still 99",
         t_status(200) + [
             'pm.test("Update was saved on the server", function () {',
             "    pm.expect(pm.response.json().marks).to.eql(99);",
             "});"],
         about="Step 4: read it back."),
    case("CHN-05", "Delete the created student", "DELETE", "/students/{{createdId}}", "200 OK",
         t_status(200), auth="token", about="Step 5: delete it."),
    case("CHN-06", "Confirm it is gone", "GET", "/students/{{createdId}}", "404 Not Found",
         t_status(404) + t_detail("not found") + [
             "// Clean up the environment at the end of the chain",
             'pm.environment.unset("createdId");',
             'pm.environment.unset("createdUsn");'],
         about="Step 6: the deleted student no longer exists."),
]

# ---------------- Data-driven ----------------
DATA_DRIVEN = [
    case("DDT", "Create student from CSV row", "POST", "/students",
         "{{expected_status}} (from students.csv)",
         [
             "// Each iteration gets one row of students.csv via pm.iterationData",
             "if (!pm.iterationData.has('case_id')) {",
             '    pm.test.skip("Run this folder with students.csv as the data file", function () {});',
             "} else {",
             "    const caseId   = pm.iterationData.get('case_id');",
             "    const scenario = pm.iterationData.get('scenario');",
             "    const expected = Number(pm.iterationData.get('expected_status'));",
             "    pm.test(caseId + ' ' + scenario + ': expect ' + expected, function () {",
             "        pm.response.to.have.status(expected);",
             "    });",
             "    if (expected === 201) {",
             '        pm.test("Body echoes the USN from the CSV row", function () {',
             "            pm.expect(pm.response.json().usn).to.eql(pm.iterationData.get('usn'));",
             "        });",
             "    } else {",
             "        pm.test(\"No student was created\", function () {",
             "            pm.expect(pm.response.json()).to.not.have.property('id');",
             "        });",
             "    }",
             "}",
         ],
         body='{\n    "name": "{{name}}",\n    "usn": "{{usn}}",\n    "age": {{age}},\n    "marks": {{marks}}\n}',
         auth="token",
         about="One request, many inputs: Newman runs it once per CSV row (-d students.csv)."),
]

# Which tests catch each planted bug (verified by running every bug).
# The dashboard shows the same list under the Bug Mode dropdown.
PLANTED_BUGS = {
    "marks_over_100": ("Marks above 100 accepted", "BVA-08, DD-11"),
    "wrong_status": ("POST returns 200 instead of 201",
                     "POS-04, BVA-02/03/06/07/10/11, CHN-01, DD-01…DD-07 (every create)"),
    "auth_bypass": ("A wrong bearer token is accepted", "AUTH-02, AUTH-04"),
    "name_length": ("Names over 50 characters accepted", "BVA-12"),
    "duplicate_usn": ("Duplicate USN allowed (no 409)", "NEG-04, DD-15"),
    "slow_response": ("GET /students takes ~800 ms", "POS-02, AUTH-06 (response-time checks)"),
    "wrong_body": ("GET /students/{id} returns `student_age` instead of `age`", "POS-03, CHN-02 (JSON schema checks)"),
    "all": ("All bugs at once", "All of the above"),
}

FOLDERS = [
    ("Positive", "Happy path: valid requests return the right data and status codes.", POSITIVE),
    ("Negative", "Invalid ids, duplicates and bad data are rejected with the right errors.", NEGATIVE),
    ("Boundary", "Boundary Value Analysis: values just inside and just outside each limit.", BOUNDARY),
    ("Auth", "Bearer-token security: 401 when missing, 403 when wrong.", AUTH),
    ("Chaining", "Request chaining: create, then reuse the saved id to read, update and delete.", CHAINING),
    ("Data-Driven", "One request run once per row of students.csv (15 rows).", DATA_DRIVEN),
]

# --------------------------------------------------------------------------
# Postman JSON builders
# --------------------------------------------------------------------------
AUTH_HEADER = {"token": "Bearer {{token}}", "wrong": "Bearer {{wrongToken}}"}


def build_item(c):
    headers = [{"key": "Content-Type", "value": "application/json"}] if c["body"] is not None else []
    if c["auth"] in AUTH_HEADER:
        headers.append({"key": "Authorization", "value": AUTH_HEADER[c["auth"]]})
    title = c["name"] if c["id"] in ("SETUP", "DDT") else f"{c['id']} {c['name']}"
    request = {
        "method": c["method"],
        "header": headers,
        "url": {
            "raw": "{{baseUrl}}" + c["path"],
            "host": ["{{baseUrl}}"],
            "path": [p for p in c["path"].split("/") if p],
        },
        "description": f"{c['about']}\n\n**Expected:** {c['expected']}",
    }
    if c["invalid"]:
        # The dashboard reads this line to show the "Invalid input → rejected" badge
        request["description"] += "\n\n**Scenario:** Invalid input → rejected"
    if c["body"] is not None:
        raw = c["body"] if isinstance(c["body"], str) else json.dumps(c["body"], indent=4)
        request["body"] = {"mode": "raw", "raw": raw, "options": {"raw": {"language": "json"}}}
    events = []
    if c["pre"]:
        events.append({"listen": "prerequest", "script": {"type": "text/javascript", "exec": c["pre"]}})
    if c["tests"]:
        events.append({"listen": "test", "script": {"type": "text/javascript", "exec": c["tests"]}})
    return {"name": title, "event": events, "request": request, "response": []}


# In the Data-Driven folder the reset only needs to run before the FIRST CSV row
SETUP_FIRST_ITERATION = dict(SETUP, pre=[
    "// Data-driven runs repeat the whole folder once per CSV row.",
    "// Reset only before the first row; later rows skip this request.",
    "if (pm.info.iteration > 0) {",
    "    pm.execution.skipRequest();",
    "}",
])


def build_collection():
    folders = []
    for name, description, cases in FOLDERS:
        setup = SETUP_FIRST_ITERATION if name == "Data-Driven" else SETUP
        folders.append({
            "name": name,
            "description": description,
            "item": [build_item(setup)] + [build_item(c) for c in cases],
        })
    return {
        "info": {
            "_postman_id": str(uuid.uuid5(uuid.NAMESPACE_URL, "student-mgmt-aat")),
            "name": "Student Management API",
            "description": (
                "Software Testing AAT: Automated API Testing with Postman and Newman.\n"
                "Team: Kaustubh Dwivedi, Aayush Jalan, Utsav Adhikari (BMSCE).\n\n"
                "Each folder is a test suite and starts with a `[setup] Reset data` request. "
                "Run the Data-Driven folder with `postman/data/students.csv` as the data file."
            ),
            "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
        },
        "item": folders,
        # Defaults so the collection also works in Postman without the environment
        "variable": [
            {"key": "baseUrl", "value": "http://localhost:8000"},
            {"key": "token", "value": "demo-token-123"},
            {"key": "wrongToken", "value": "not-the-right-token"},
        ],
    }


def build_environment():
    values = [("baseUrl", "http://localhost:8000"), ("token", "demo-token-123"),
              ("wrongToken", "not-the-right-token"), ("createdId", ""), ("createdUsn", "")]
    return {
        "id": str(uuid.uuid5(uuid.NAMESPACE_URL, "student-mgmt-aat-env")),
        "name": "Student API - Local",
        "values": [{"key": k, "value": v, "type": "default", "enabled": True} for k, v in values],
        "_postman_variable_scope": "environment",
    }


# --------------------------------------------------------------------------
# TEST_CASES.md
# --------------------------------------------------------------------------
def md_input(c):
    text = f"`{c['method']} {c['path']}`"
    if isinstance(c["body"], dict):
        body = {k: (v if not (isinstance(v, str) and len(v) > 12) else f"{v[:6]}…({len(v)})")
                for k, v in c["body"].items()}
        text += " " + ", ".join(f"{k}={json.dumps(v)}" for k, v in body.items())
    if c["auth"] == "wrong":
        text += " (wrong token)"
    elif c["auth"] == "none" and c["method"] != "GET":
        text += " (no token)"
    return text.replace("|", "\\|")


def build_test_cases_md(results=None):
    """results: {case_id: (actual, passed)} from a real run, or None."""
    results = results or {}
    lines = [
        "# Test Cases: Student Management API",
        "",
        "Generated by `tools/build_collection.py` from the same definitions as the Postman collection.",
        "Every suite first sends `[setup] POST /reset` (a setup step, not counted as a test).",
        "",
    ]
    if results:
        lines += ["The *Actual* and *Result* columns come from a real Newman run (normal mode).", ""]
    total = 0
    for folder, description, cases in FOLDERS:
        lines += [f"## {folder}", "", description, ""]
        lines += ["| ID | Type | Scenario | Test case | Input | Expected | Actual | Pass/Fail |",
                  "|----|------|----------|-----------|-------|----------|--------|-----------|"]
        rows = []
        if folder == "Data-Driven":
            with open(CSV_PATH, newline="") as f:
                for r in csv.DictReader(f):
                    rows.append((r["case_id"], r["scenario"],
                                 f"name={json.dumps(r['name'])}, usn={r['usn']}, age={r['age']}, marks={r['marks']}",
                                 r["expected_status"], int(r["expected_status"]) >= 400))
        else:
            rows = [(c["id"], c["name"], md_input(c), c["expected"], c["invalid"]) for c in cases]
        for cid, name, inp, expected, invalid in rows:
            actual, passed = results.get(cid, ("-", None))
            verdict = "-" if passed is None else ("✅ PASS" if passed else "❌ FAIL")
            scenario = "⛔ Invalid input → rejected" if invalid else "Valid input"
            lines.append(f"| {cid} | {folder} | {scenario} | {name} | {inp} | {expected} | {actual} | {verdict} |")
            total += 1
        lines.append("")
    lines.insert(4, f"**Total: {total} test cases in 6 suites.**\n")
    lines.insert(5, "**⛔ Invalid input → rejected** marks an error scenario: the request is invalid on "
                    "purpose, and the test PASSES when the API correctly rejects it.\n")
    lines += ["## Planted bugs (Bug Mode)", "",
              "Each bug is one marked line in `app/student_api.py` (search for `<-- BUG`). "
              "The tests listed are the ones that fail when it is switched on; every other test still passes.", "",
              "| Bug | What goes wrong | Caught by |", "|-----|-----------------|-----------|"]
    for key, (label, caught) in PLANTED_BUGS.items():
        lines.append(f"| `{key}` | {label} | {caught} |")
    return "\n".join(lines) + "\n"


def load_results(path):
    """Read results.json written by the Test Control Center."""
    with open(path) as f:
        data = json.load(f)
    out = {}
    for r in data["results"]:
        out[r["caseId"]] = (f"{r.get('code', '-')} {r.get('status', '')}".strip(), r["passed"])
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--results", help="results.json from a dashboard run, to fill Actual/Result")
    args = parser.parse_args()

    def write(path, content):
        with open(path, "w") as f:
            f.write(content)
        print("wrote", os.path.relpath(path, ROOT))

    write(os.path.join(POSTMAN_DIR, "Student_Management_API.postman_collection.json"),
          json.dumps(build_collection(), indent=2) + "\n")
    write(os.path.join(POSTMAN_DIR, "Local.postman_environment.json"),
          json.dumps(build_environment(), indent=2) + "\n")
    write(os.path.join(ROOT, "TEST_CASES.md"),
          build_test_cases_md(load_results(args.results) if args.results else None))


if __name__ == "__main__":
    main()
