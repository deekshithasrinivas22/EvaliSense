"""Students management routes."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from api.auth.dependencies import get_current_user, require_hod
from api.database.models import Section, Student, User
from api.database.session import get_db
from api.schemas.academic import StudentCreate, StudentResponse, StudentUpdate

router = APIRouter(prefix="/api/students", tags=["Students"])


@router.get("", response_model=list[StudentResponse])
def list_students(
    section_id: int | None = Query(None, description="Filter by section ID"),
    search: str | None = Query(None, description="Search by USN or name"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List students with optional filtering."""
    query = db.query(Student)
    if section_id is not None:
        query = query.filter(Student.section_id == section_id)
    if search:
        s_filter = f"%{search.strip()}%"
        query = query.filter((Student.usn.ilike(s_filter)) | (Student.name.ilike(s_filter)))
    students = query.order_by(Student.usn).all()
    return [StudentResponse(**s.to_dict()) for s in students]


@router.post("", response_model=StudentResponse)
def create_student(
    req: StudentCreate,
    current_user: User = Depends(require_hod),
    db: Session = Depends(get_db),
):
    """Register a new student (HOD only)."""
    usn = req.usn.strip().upper()
    if db.query(Student).filter(Student.usn == usn).first():
        raise HTTPException(status_code=400, detail=f"Student with USN '{usn}' already exists.")

    section = db.query(Section).filter(Section.id == req.section_id).first()
    if not section:
        raise HTTPException(status_code=400, detail="Invalid section ID specified.")

    student = Student(
        usn=usn,
        name=req.name.strip(),
        section_id=section.id,
        roll_number=req.roll_number.strip() if req.roll_number else None,
        email=req.email.strip().lower() if req.email else None,
        is_active=True,
    )
    db.add(student)
    db.commit()
    db.refresh(student)
    return StudentResponse(**student.to_dict())


@router.get("/{student_id}", response_model=StudentResponse)
def get_student(
    student_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get student details by ID."""
    student = db.query(Student).filter(Student.id == student_id).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found.")
    return StudentResponse(**student.to_dict())


@router.put("/{student_id}", response_model=StudentResponse)
def update_student(
    student_id: int,
    req: StudentUpdate,
    current_user: User = Depends(require_hod),
    db: Session = Depends(get_db),
):
    """Update student details (HOD only)."""
    student = db.query(Student).filter(Student.id == student_id).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found.")

    if req.name is not None:
        student.name = req.name.strip()
    if req.section_id is not None:
        section = db.query(Section).filter(Section.id == req.section_id).first()
        if not section:
            raise HTTPException(status_code=400, detail="Invalid section specified.")
        student.section_id = req.section_id
    if req.roll_number is not None:
        student.roll_number = req.roll_number.strip()
    if req.email is not None:
        student.email = req.email.strip().lower()
    if req.is_active is not None:
        student.is_active = req.is_active

    db.commit()
    db.refresh(student)
    return StudentResponse(**student.to_dict())


@router.delete("/{student_id}")
def delete_student(
    student_id: int,
    current_user: User = Depends(require_hod),
    db: Session = Depends(get_db),
):
    """Deactivate student (HOD only)."""
    student = db.query(Student).filter(Student.id == student_id).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found.")

    student.is_active = False
    db.commit()
    return {"message": f"Student '{student.usn}' deactivated."}
