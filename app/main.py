"""
main.py - wires everything into ONE FastAPI app on one port:

  /                 -> Test Control Center dashboard (dashboard/index.html)
  /students, ...    -> Student Management API (the system under test)
  /control/...      -> endpoints the dashboard uses to run Newman
  /reports/...      -> generated Newman htmlextra reports
  /docs             -> Swagger UI for the API

Start with:  uvicorn app.main:app --port 8000     (or just ./start.sh)
"""

import os

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import control_center, student_api

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DASHBOARD = os.path.join(ROOT, "dashboard")
REPORTS = os.path.join(ROOT, "reports")
CHARTJS = os.path.join(ROOT, "node_modules", "chart.js", "dist")
os.makedirs(REPORTS, exist_ok=True)

app = FastAPI(
    title="Student Management API",
    description="System under test for the Postman + Newman AAT demo. "
                "POST/PUT/DELETE need `Authorization: Bearer demo-token-123`.",
    version="1.0.0",
)


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    """Turn Pydantic's 422 into a short, readable error list:
       {"message": "Validation failed", "errors": [{"field": "marks", "error": "..."}]}"""
    errors = [{"field": str(e["loc"][-1]), "error": e["msg"].replace("Value error, ", "")}
              for e in exc.errors()]
    return JSONResponse(status_code=422, content={"message": "Validation failed", "errors": errors})


@app.middleware("http")
async def no_cache_dashboard(request: Request, call_next):
    """Always serve the newest dashboard files (no stale CSS/JS during the demo)."""
    response = await call_next(request)
    if request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-cache"
    return response


app.include_router(student_api.router)
app.include_router(control_center.router)

app.mount("/static", StaticFiles(directory=DASHBOARD), name="static")
app.mount("/reports", StaticFiles(directory=REPORTS, html=True), name="reports")
if os.path.isdir(CHARTJS):          # Chart.js served locally: works without internet
    app.mount("/vendor/chartjs", StaticFiles(directory=CHARTJS), name="chartjs")


@app.get("/", include_in_schema=False)
def dashboard():
    return FileResponse(os.path.join(DASHBOARD, "index.html"), headers={"Cache-Control": "no-cache"})
