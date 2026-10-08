"""Sections management routes."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from api.auth.dependencies import get_current_user, require_hod
from api.database.models import Department, Section, User
from api.database.session import get_db
from api.schemas.academic import SectionCreate, SectionResponse, SectionUpdate

router = APIRouter(prefix="/api/sections", tags=["Sections"])


@router.get("", response_model=list[SectionResponse])
def list_sections(
    department_id: int | None = Query(None, description="Filter by department"),
    semester: int | None = Query(None, description="Filter by semester"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List sections."""
    query = db.query(Section)
    if department_id is not None:
        query = query.filter(Section.department_id == department_id)
    if semester is not None:
        query = query.filter(Section.semester == semester)
    sections = query.all()
    return [SectionResponse(**s.to_dict()) for s in sections]


@router.post("", response_model=SectionResponse)
def create_section(
    req: SectionCreate,
    current_user: User = Depends(require_hod),
    db: Session = Depends(get_db),
):
    """Create a new section (HOD only)."""
    dept = db.query(Department).filter(Department.id == req.department_id).first()
    if not dept:
        raise HTTPException(status_code=400, detail="Department does not exist.")

    section = Section(
        department_id=req.department_id,
        name=req.name.strip(),
        semester=req.semester,
        academic_year=req.academic_year.strip(),
        is_active=True,
    )
    db.add(section)
    db.commit()
    db.refresh(section)
    return SectionResponse(**section.to_dict())


@router.put("/{section_id}", response_model=SectionResponse)
def update_section(
    section_id: int,
    req: SectionUpdate,
    current_user: User = Depends(require_hod),
    db: Session = Depends(get_db),
):
    """Update section details (HOD only)."""
    section = db.query(Section).filter(Section.id == section_id).first()
    if not section:
        raise HTTPException(status_code=404, detail="Section not found.")

    if req.name is not None:
        section.name = req.name.strip()
    if req.semester is not None:
        section.semester = req.semester
    if req.academic_year is not None:
        section.academic_year = req.academic_year.strip()
    if req.is_active is not None:
        section.is_active = req.is_active

    db.commit()
    db.refresh(section)
    return SectionResponse(**section.to_dict())


@router.delete("/{section_id}")
def delete_section(
    section_id: int,
    current_user: User = Depends(require_hod),
    db: Session = Depends(get_db),
):
    """Deactivate section (HOD only)."""
    section = db.query(Section).filter(Section.id == section_id).first()
    if not section:
        raise HTTPException(status_code=404, detail="Section not found.")

    section.is_active = False
    db.commit()
    return {"message": f"Section '{section.name}' deactivated."}
