"""Pydantic schemas for Academic structures (Departments, Sections, Students, Subjects, Exams)."""
from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field


# ─── Department ───
class DepartmentCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    code: str = Field(..., min_length=2, max_length=20)


class DepartmentUpdate(BaseModel):
    name: str | None = None
    code: str | None = None
    is_active: bool | None = None


class DepartmentResponse(BaseModel):
    id: int
    name: str
    code: str
    is_active: bool
    created_at: str | None = None


# ─── Section ───
class SectionCreate(BaseModel):
    department_id: int
    name: str = Field(..., max_length=50)
    semester: int = Field(..., ge=1, le=12)
    academic_year: str = Field(..., max_length=20)


class SectionUpdate(BaseModel):
    name: str | None = None
    semester: int | None = None
    academic_year: str | None = None
    is_active: bool | None = None


class SectionResponse(BaseModel):
    id: int
    department_id: int
    department_code: str | None = None
    name: str
    semester: int
    academic_year: str
    is_active: bool
    created_at: str | None = None


# ─── Student ───
class StudentCreate(BaseModel):
    usn: str = Field(..., min_length=3, max_length=50)
    name: str = Field(..., min_length=2, max_length=100)
    section_id: int
    roll_number: str | None = None
    email: str | None = None


class StudentUpdate(BaseModel):
    name: str | None = None
    section_id: int | None = None
    roll_number: str | None = None
    email: str | None = None
    is_active: bool | None = None


class StudentResponse(BaseModel):
    id: int
    usn: str
    name: str
    section_id: int
    section_name: str | None = None
    roll_number: str | None = None
    email: str | None = None
    is_active: bool
    created_at: str | None = None


# ─── Subject ───
class SubjectCreate(BaseModel):
    code: str = Field(..., min_length=2, max_length=30)
    name: str = Field(..., min_length=2, max_length=100)
    semester: int = Field(..., ge=1, le=12)
    department_id: int
    max_marks: float = 100.0


class SubjectUpdate(BaseModel):
    name: str | None = None
    semester: int | None = None
    department_id: int | None = None
    max_marks: float | None = None
    is_active: bool | None = None


class SubjectResponse(BaseModel):
    id: int
    code: str
    name: str
    semester: int
    department_id: int
    department_code: str | None = None
    max_marks: float
    is_active: bool
    created_at: str | None = None


# ─── Teacher Subject Mapping ───
class TeacherSubjectCreate(BaseModel):
    teacher_id: int
    subject_id: int
    section_id: int | None = None
    academic_year: str | None = None


class TeacherSubjectResponse(BaseModel):
    id: int
    teacher_id: int
    teacher_name: str | None = None
    subject_id: int
    subject_name: str | None = None
    subject_code: str | None = None
    section_id: int | None = None
    section_name: str | None = None
    academic_year: str | None = None
    is_active: bool
    created_at: str | None = None


# ─── Exam ───
class ExamCreate(BaseModel):
    subject_id: int
    section_id: int | None = None
    name: str = Field(..., min_length=2, max_length=100)
    exam_type: str = "INTERNAL"
    exam_date: str | None = None
    academic_year: str = Field(..., max_length=20)
    total_marks: float = 100.0


class ExamUpdate(BaseModel):
    name: str | None = None
    exam_type: str | None = None
    exam_date: str | None = None
    academic_year: str | None = None
    total_marks: float | None = None
    status: str | None = None


class ExamResponse(BaseModel):
    id: int
    subject_id: int
    subject_name: str | None = None
    subject_code: str | None = None
    section_id: int | None = None
    section_name: str | None = None
    name: str
    exam_type: str
    exam_date: str | None = None
    academic_year: str
    total_marks: float
    status: str
    question_count: int = 0
    created_at: str | None = None


# ─── Exam Question ───
class ExamQuestionCreate(BaseModel):
    question_number: int = Field(..., ge=1)
    question_text: str = Field(..., min_length=3)
    max_marks: float = Field(..., gt=0)
    reference_answer: str | None = None
    rubric_json: str | None = None


class ExamQuestionUpdate(BaseModel):
    question_number: int | None = None
    question_text: str | None = None
    max_marks: float | None = None
    reference_answer: str | None = None
    rubric_json: str | None = None


class ExamQuestionResponse(BaseModel):
    id: int
    exam_id: int
    question_number: int
    question_text: str
    max_marks: float
    reference_answer: str | None = None
    rubric_json: str | None = None
    created_at: str | None = None
