"""
Student Management API - the SYSTEM UNDER TEST (SUT).

This is the application our Postman collection tests. It is deliberately small
so that every rule can be explained in the viva:

  * Validation : name 1-50 chars, USN like 1BM23AD028, age 17-30, marks 0-100
  * Auth       : POST / PUT / DELETE need "Authorization: Bearer <token>"
                 (401 when the header is missing, 403 when the token is wrong)
  * Errors     : 404 unknown id, 409 duplicate USN, 422 invalid data
  * Storage    : a plain Python dict in memory (POST /reset restores seed data)

It also has a "planted bug" mode (BUG_MODE) that the dashboard can switch on
at runtime, so we can show the tests catching a real defect live.
"""

from typing import Dict, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from pydantic import BaseModel, Field, field_validator

router = APIRouter()

# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------
API_TOKEN = "demo-token-123"            # the one valid bearer token
APP_ID = "student-mgmt-aat"             # used by start.sh to recognise this app
USN_PATTERN = r"^[1-4][A-Z]{2}\d{2}[A-Z]{2}\d{3}$"   # e.g. 1BM23AD028

# Planted bugs that can be toggled from the dashboard:
#   marks_over_100 -> marks above 100 (up to 150) are wrongly accepted
#   wrong_status   -> POST /students returns 200 instead of 201
BUG_TYPES = {
    "marks_over_100": "Marks above 100 accepted",
    "wrong_status": "POST returns 200, not 201",
}
BUG_MODE = {"enabled": False, "type": "marks_over_100"}


def bug_active(bug_type: str) -> bool:
    """True when bug mode is on AND the selected bug is `bug_type`."""
    return BUG_MODE["enabled"] and BUG_MODE["type"] == bug_type


# --------------------------------------------------------------------------
# Data model + validation rules
# --------------------------------------------------------------------------
class StudentIn(BaseModel):
    """Body for POST / PUT. Pydantic turns rule violations into HTTP 422."""

    name: str = Field(..., min_length=1, max_length=50, examples=["Kaustubh"])
    usn: str = Field(..., pattern=USN_PATTERN, examples=["1BM23AD028"])
    age: int = Field(..., ge=17, le=30, examples=[20])
    marks: int = Field(..., examples=[88])

    # The marks rule is written by hand (not with ge/le) so that the planted
    # bug lives in exactly one visible place.
    @field_validator("marks")
    @classmethod
    def check_marks(cls, value: int) -> int:
        upper_limit = 150 if bug_active("marks_over_100") else 100   # <-- BUG
        if value < 0 or value > upper_limit:
            raise ValueError("marks must be between 0 and 100")
        return value


class Student(StudentIn):
    id: int


# --------------------------------------------------------------------------
# In-memory "database"
# --------------------------------------------------------------------------
SEED = [
    {"name": "Aayush Jalan", "usn": "1BM23AD001", "age": 20, "marks": 91},
    {"name": "Utsav Adhikari", "usn": "1BM23AD002", "age": 21, "marks": 84},
    {"name": "Kaustubh", "usn": "1BM23AD028", "age": 20, "marks": 88},
]
students: Dict[int, dict] = {}
next_id = 1


def reset_store() -> None:
    """Wipe the store and load the three seed students (ids 1, 2, 3)."""
    global next_id
    students.clear()
    next_id = 1
    for row in SEED:
        students[next_id] = {"id": next_id, **row}
        next_id += 1


reset_store()


# --------------------------------------------------------------------------
# Auth: Bearer token check, used as a FastAPI dependency
# --------------------------------------------------------------------------
def require_token(authorization: Optional[str] = Header(None)) -> None:
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing bearer token")
    if authorization != f"Bearer {API_TOKEN}":
        raise HTTPException(status_code=403, detail="Invalid token")


def find_or_404(student_id: int) -> dict:
    if student_id not in students:
        raise HTTPException(status_code=404, detail=f"Student {student_id} not found")
    return students[student_id]


def ensure_unique_usn(usn: str, ignore_id: Optional[int] = None) -> None:
    for s in students.values():
        if s["usn"] == usn and s["id"] != ignore_id:
            raise HTTPException(status_code=409, detail=f"USN {usn} already exists")


# --------------------------------------------------------------------------
# Endpoints
# --------------------------------------------------------------------------
@router.get("/health", tags=["System"])
def health():
    """Liveness check. Also reports whether bug mode is on."""
    return {"status": "ok", "app": APP_ID, "students": len(students), "bug_mode": BUG_MODE}


@router.post("/reset", tags=["System"])
def reset():
    """Restore the seed data. Every test suite calls this first."""
    reset_store()
    return {"message": "Data reset", "count": len(students)}


@router.get("/students", response_model=list[Student], tags=["Students"])
def list_students():
    return list(students.values())


@router.get("/students/{student_id}", response_model=Student, tags=["Students"])
def get_student(student_id: int):
    return find_or_404(student_id)


@router.post("/students", response_model=Student, status_code=201, tags=["Students"],
             dependencies=[Depends(require_token)])
def create_student(body: StudentIn, response: Response):
    global next_id
    ensure_unique_usn(body.usn)
    student = {"id": next_id, **body.model_dump()}
    students[next_id] = student
    next_id += 1
    if bug_active("wrong_status"):
        response.status_code = 200          # <-- BUG: should be 201 Created
    return student


@router.put("/students/{student_id}", response_model=Student, tags=["Students"],
            dependencies=[Depends(require_token)])
def update_student(student_id: int, body: StudentIn):
    find_or_404(student_id)
    ensure_unique_usn(body.usn, ignore_id=student_id)
    students[student_id] = {"id": student_id, **body.model_dump()}
    return students[student_id]


@router.delete("/students/{student_id}", tags=["Students"],
               dependencies=[Depends(require_token)])
def delete_student(student_id: int):
    find_or_404(student_id)
    del students[student_id]
    return {"message": f"Student {student_id} deleted"}
