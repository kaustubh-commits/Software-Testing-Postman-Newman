# Demo Script (~10 minutes, 3 presenters)

**Before the class:**
- `./start.sh` → the dashboard opens at http://localhost:8000/
- Click **Run All Suites** once, so the report and history are ready.
- Make sure **Bug Mode is OFF** and the **Pace** is set to **Presenter**.
- Open the Postman app with the collection and environment already imported (see README §4).
- Projector: use the theme toggle (☀/☾) to pick whichever looks clearer in the room. Light is usually better on a bright projector.

---

## Presenter 1: What Postman & Newman are and how they work (≈3 min) · *Kaustubh*

1. **The problem (30 s).** "Other groups test code (JUnit, PIT) or the UI (Selenium, Playwright).
   We test the layer in between: the **REST API**. Mobile apps, websites and other services all talk to the backend through it."
2. **The system under test (30 s).** Open **Swagger /docs**. "A FastAPI Student Management API with CRUD, validation rules,
   token auth and the usual error codes: 401, 403, 404, 409 and 422."
3. **Postman (45 s).** Switch to the Postman app. Open *Positive → POS-04 Create a valid student*.
   - **Pre-request script** tab: "This JavaScript runs *before* the request and makes a unique USN."
   - **Tests** tab: "These `pm.test()` blocks run *after* the response: they check the status code, the body, the JSON schema and the response time."
   - Click **Send** and show the **Test Results** tab with all green.
   - "Every request is saved in a **collection**, which is a JSON file that can be versioned in git."
4. **Newman (45 s).** Back to the dashboard, at the **How it works** pipeline.
   "Newman is Postman's command-line runner. It takes the same collection and runs it without the GUI, which is how it runs in CI.
   For every request it goes through these 6 steps: request → pre-request script → API call → response → test scripts → report."
5. Run the **Positive** suite and point at the steps lighting up. Hand over.

## Presenter 2: Running the suites live (≈4 min) · *Aayush*

1. "Our collection has **6 folders, 53 test cases and 123 assertions**, and each folder is a different testing technique."
   Briefly point at the suite cards.
2. Click **Run All Suites**. While it runs:
   - Point at the **live feed**: "Each row is one request finishing. PASS/FAIL, method, endpoint and time."
   - Point at the grey **setup** lines: "Each suite resets the data first, so the tests are independent. This is a setup step, not a test."
   - Point at the **counters, donut and response-time chart** filling in.
3. **Drill into a test.** Click **BVA-08 Marks 101**:
   "Boundary Value Analysis: 100 is the maximum, so we test 101 just outside. The API must answer **422**.
   Here is the request we sent, the response we got and the actual `pm.test()` code that checked it."
4. Click a **Chaining** row (CHN-02): "CHN-01 saved the new id with `pm.environment.set('createdId')`,
   and here the URL reuses `{{createdId}}`. That's request chaining."
5. Click a **Data-Driven** row: "One request and 15 rows of `students.csv`. Newman runs it once per row (`-d students.csv`), and each row has its own expected status."
6. Scroll to the **Test case table**: "ID, type, input, expected, actual and result, all filled from this run. It exports to CSV for our documentation." Hand over.

## Presenter 3: Catching a bug + reports + CI (≈3 min) · *Utsav*

1. "Passing tests aren't impressive if they can't fail. Let's plant a real bug."
   Turn **Bug Mode ON** (*Marks above 100 accepted*). Point at the red banner.
   "The developer accidentally changed the marks limit, so the API now accepts 101 marks."
2. Run the **Boundary** suite. "11 pass, but **BVA-08 fails**: we expected 422, and the API returned 201 Created."
   Open the red row. The failing `pm.test()` lines are highlighted in red. "The test tells us exactly what broke."
   (Optional: also run **Data-Driven**, where **DD-11** catches the same bug.)
3. Turn **Bug Mode OFF**, run Boundary again, and it is green again. "That's a regression test."
4. Click **HTML report**: "Newman's *htmlextra* reporter writes one report per suite. This index links them.
   It shows every request, response and assertion, ready to attach to a test report."
5. **CI (30 s).** Show `run_tests.sh` or the README command:
   "In a CI pipeline like GitHub Actions or Jenkins, this one `newman run` command runs on every commit.
   Newman exits with a non-zero code if any test fails, so a broken API never gets deployed."
6. **Close.** "Postman to design the tests, Newman to automate them, and the same collection everywhere: the app, CLI, CI and this dashboard."

---

## Likely viva questions

1. **What is the difference between Postman and Newman?**
   Postman is the GUI for designing and sending requests and writing tests. Newman is the command-line runner that runs a Postman collection without the GUI, so it can be automated (CI/CD, scripts).

2. **What is a collection and an environment?**
   A collection is a JSON file containing requests, organised in folders, with their scripts. An environment is a set of variables (`baseUrl`, `token`, …), so the same collection can run against local, staging or production by switching environments.

3. **When do pre-request scripts and test scripts run?**
   The pre-request script runs before the request is sent (to set up data, e.g. a random USN). The test script runs after the response arrives and contains the `pm.test()` assertions.

4. **How does request chaining work?**
   A test script stores a value from the response with `pm.environment.set("createdId", id)`, and later requests use it as `{{createdId}}` in the URL or body.

5. **What is data-driven testing and how do you run it in Newman?**
   The same request runs once per row of a CSV/JSON file. Each column is available as `{{column}}` or `pm.iterationData.get()`. In Newman: `newman run collection.json -d students.csv`.

6. **Why test 16, 17, 30 and 31 for age?**
   Boundary Value Analysis: defects cluster at the edges of valid ranges (`>` vs `>=`). We test the minimum and maximum (valid) and the values just outside them (invalid).

7. **What is the difference between 401 and 403?**
   401 Unauthorized means no credentials were sent. 403 Forbidden means credentials were sent but they are wrong or not allowed.

8. **What does JSON schema validation add over checking values?**
   It checks the *structure*: required fields, types and ranges. If the API adds, removes or changes the type of a field, the schema test fails even when the individual values we check still look fine.

9. **How would you use Newman in CI/CD?**
   Add `newman run …` as a pipeline step (GitHub Actions, Jenkins, GitLab CI). A non-zero exit code on failure fails the build. The htmlextra/JUnit reporters produce reports that get archived as build artefacts.

10. **How does your dashboard show results live?**
    FastAPI starts a Node script that uses the Newman *library* (`newman.run()`) and listens to its events (`request`, `assertion`, `item`, …). Each event is printed as one JSON line, and FastAPI forwards each line to the browser with **Server-Sent Events**. The JavaScript then updates the feed, the charts and the pipeline.

**Bonus:**
- *Why reset before every suite?* So each suite is independent and repeatable, and the order doesn't matter.
- *What is the planted bug, technically?* In `student_api.py` the marks validator's upper limit becomes 150 when bug mode is on. It is one line, and the dashboard toggles it at runtime.
- *Limitations of Postman/Newman?* They are not meant for heavy load testing (use JMeter or k6 for that) and not for UI testing. Tests are JavaScript in JSON, so larger suites need good organisation.
