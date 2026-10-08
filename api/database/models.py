"""SQLAlchemy models for EvaliSense.

Implements the relational database schema supporting:
- RBAC (Roles, Users)
- Academic hierarchy (Departments, Sections, Students, Subjects, TeacherSubjects)
- Examinations and Questions (Exams, ExamQuestions, Rubrics)
- Evaluation pipeline (AnswerScripts, AnswerAnswers, AIEvaluations)
- Teacher workflow (TeacherAssignments, FinalMarks)
- Scanner workflow (ScanIssues)
- Notifications
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from api.database.session import Base


class Role(Base):
    """Stores system and custom roles."""
    __tablename__ = "roles"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    name = Column(String(50), unique=True, nullable=False, index=True)
    description = Column(String(255), nullable=True)
    is_system_role = Column(Boolean, default=False, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    users = relationship("User", back_populates="role")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "is_system_role": self.is_system_role,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class User(Base):
    """Stores HODs, teachers, scanners, and custom role users."""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    role_id = Column(Integer, ForeignKey("roles.id", ondelete="RESTRICT"), nullable=False, index=True)
    employee_id = Column(String(50), unique=True, nullable=True, index=True)
    username = Column(String(50), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    full_name = Column(String(100), nullable=False)
    email = Column(String(120), unique=True, nullable=False, index=True)
    phone = Column(String(30), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    role = relationship("Role", back_populates="users")
    teacher_subjects = relationship("TeacherSubject", back_populates="teacher")
    assignments = relationship("TeacherAssignment", back_populates="teacher")
    final_marks = relationship("FinalMark", back_populates="teacher")
    uploaded_scripts = relationship("AnswerScript", back_populates="uploader")
    notifications = relationship("Notification", back_populates="user", cascade="all, delete-orphan")

    def to_dict(self, include_role: bool = True) -> dict[str, Any]:
        res: dict[str, Any] = {
            "id": self.id,
            "role_id": self.role_id,
            "employee_id": self.employee_id,
            "username": self.username,
            "full_name": self.full_name,
            "email": self.email,
            "phone": self.phone,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
        if include_role and self.role:
            res["role_name"] = self.role.name
        return res


class Department(Base):
    """Stores academic departments."""
    __tablename__ = "departments"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    code = Column(String(20), unique=True, nullable=False, index=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    sections = relationship("Section", back_populates="department")
    subjects = relationship("Subject", back_populates="department")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "code": self.code,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class Section(Base):
    """Stores classes/sections such as CSE-A, CSE-B, etc."""
    __tablename__ = "sections"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    department_id = Column(Integer, ForeignKey("departments.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(50), nullable=False)
    semester = Column(Integer, nullable=False)
    academic_year = Column(String(20), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    department = relationship("Department", back_populates="sections")
    students = relationship("Student", back_populates="section")
    exams = relationship("Exam", back_populates="section")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "department_id": self.department_id,
            "department_code": self.department.code if self.department else None,
            "name": self.name,
            "semester": self.semester,
            "academic_year": self.academic_year,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class Student(Base):
    """Stores students whose evaluated marks will be associated with their records."""
    __tablename__ = "students"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    usn = Column(String(50), unique=True, nullable=False, index=True)
    name = Column(String(100), nullable=False)
    section_id = Column(Integer, ForeignKey("sections.id", ondelete="RESTRICT"), nullable=False, index=True)
    roll_number = Column(String(50), nullable=True)
    email = Column(String(120), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    section = relationship("Section", back_populates="students")
    answer_scripts = relationship("AnswerScript", back_populates="student")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "usn": self.usn,
            "name": self.name,
            "section_id": self.section_id,
            "section_name": self.section.name if self.section else None,
            "roll_number": self.roll_number,
            "email": self.email,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class Subject(Base):
    """Stores academic subjects."""
    __tablename__ = "subjects"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    code = Column(String(30), unique=True, nullable=False, index=True)
    name = Column(String(100), nullable=False)
    semester = Column(Integer, nullable=False)
    department_id = Column(Integer, ForeignKey("departments.id", ondelete="RESTRICT"), nullable=False, index=True)
    max_marks = Column(Float, default=100.0, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    department = relationship("Department", back_populates="subjects")
    teacher_subjects = relationship("TeacherSubject", back_populates="subject")
    exams = relationship("Exam", back_populates="subject")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "code": self.code,
            "name": self.name,
            "semester": self.semester,
            "department_id": self.department_id,
            "department_code": self.department.code if self.department else None,
            "max_marks": self.max_marks,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class TeacherSubject(Base):
    """Maps teachers to subjects and optionally sections/academic years."""
    __tablename__ = "teacher_subjects"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    teacher_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    subject_id = Column(Integer, ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False, index=True)
    section_id = Column(Integer, ForeignKey("sections.id", ondelete="SET NULL"), nullable=True, index=True)
    academic_year = Column(String(20), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    teacher = relationship("User", back_populates="teacher_subjects")
    subject = relationship("Subject", back_populates="teacher_subjects")
    section = relationship("Section")

    __table_args__ = (
        UniqueConstraint("teacher_id", "subject_id", "section_id", "academic_year", name="uq_teacher_subject_section"),
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "teacher_id": self.teacher_id,
            "teacher_name": self.teacher.full_name if self.teacher else None,
            "subject_id": self.subject_id,
            "subject_name": self.subject.name if self.subject else None,
            "subject_code": self.subject.code if self.subject else None,
            "section_id": self.section_id,
            "section_name": self.section.name if self.section else None,
            "academic_year": self.academic_year,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class Exam(Base):
    """Represents an examination for a subject and section."""
    __tablename__ = "exams"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    subject_id = Column(Integer, ForeignKey("subjects.id", ondelete="RESTRICT"), nullable=False, index=True)
    section_id = Column(Integer, ForeignKey("sections.id", ondelete="SET NULL"), nullable=True, index=True)
    name = Column(String(100), nullable=False)
    exam_type = Column(String(50), default="INTERNAL", nullable=False)
    exam_date = Column(String(30), nullable=True)
    academic_year = Column(String(20), nullable=False)
    total_marks = Column(Float, default=100.0, nullable=False)
    status = Column(String(30), default="SCHEDULED", nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    subject = relationship("Subject", back_populates="exams")
    section = relationship("Section", back_populates="exams")
    questions = relationship("ExamQuestion", back_populates="exam", cascade="all, delete-orphan", order_by="ExamQuestion.question_number")
    answer_scripts = relationship("AnswerScript", back_populates="exam")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "subject_id": self.subject_id,
            "subject_name": self.subject.name if self.subject else None,
            "subject_code": self.subject.code if self.subject else None,
            "section_id": self.section_id,
            "section_name": self.section.name if self.section else None,
            "name": self.name,
            "exam_type": self.exam_type,
            "exam_date": self.exam_date,
            "academic_year": self.academic_year,
            "total_marks": self.total_marks,
            "status": self.status,
            "question_count": len(self.questions) if self.questions else 0,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class ExamQuestion(Base):
    """Stores questions, maximum marks, answer keys, and rubric information."""
    __tablename__ = "exam_questions"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    exam_id = Column(Integer, ForeignKey("exams.id", ondelete="CASCADE"), nullable=False, index=True)
    question_number = Column(Integer, nullable=False)
    question_text = Column(Text, nullable=False)
    max_marks = Column(Float, nullable=False)
    reference_answer = Column(Text, nullable=True)
    rubric_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    exam = relationship("Exam", back_populates="questions")
    answers = relationship("AnswerAnswer", back_populates="question")

    __table_args__ = (
        UniqueConstraint("exam_id", "question_number", name="uq_exam_question_number"),
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "exam_id": self.exam_id,
            "question_number": self.question_number,
            "question_text": self.question_text,
            "max_marks": self.max_marks,
            "reference_answer": self.reference_answer,
            "rubric_json": self.rubric_json,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class AnswerScript(Base):
    """Stores each uploaded handwritten answer sheet."""
    __tablename__ = "answer_scripts"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    exam_id = Column(Integer, ForeignKey("exams.id", ondelete="RESTRICT"), nullable=False, index=True)
    student_id = Column(Integer, ForeignKey("students.id", ondelete="SET NULL"), nullable=True, index=True)
    uploaded_by = Column(Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    original_filename = Column(String(255), nullable=False)
    original_path = Column(String(500), nullable=False)
    status = Column(String(50), default="UPLOADED", nullable=False, index=True)
    scan_quality = Column(String(50), default="ACCEPTABLE", nullable=False)
    student_identifier_confidence = Column(Float, default=1.0, nullable=False)
    uploaded_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    processed_at = Column(DateTime, nullable=True)

    exam = relationship("Exam", back_populates="answer_scripts")
    student = relationship("Student", back_populates="answer_scripts")
    uploader = relationship("User", back_populates="uploaded_scripts")
    answers = relationship("AnswerAnswer", back_populates="script", cascade="all, delete-orphan")
    scan_issues = relationship("ScanIssue", back_populates="script", cascade="all, delete-orphan")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "exam_id": self.exam_id,
            "exam_name": self.exam.name if self.exam else None,
            "student_id": self.student_id,
            "student_name": self.student.name if self.student else None,
            "student_usn": self.student.usn if self.student else None,
            "uploaded_by": self.uploaded_by,
            "uploader_name": self.uploader.full_name if self.uploader else None,
            "original_filename": self.original_filename,
            "original_path": self.original_path,
            "status": self.status,
            "scan_quality": self.scan_quality,
            "student_identifier_confidence": self.student_identifier_confidence,
            "uploaded_at": self.uploaded_at.isoformat() if self.uploaded_at else None,
            "processed_at": self.processed_at.isoformat() if self.processed_at else None,
            "issues_count": len(self.scan_issues) if self.scan_issues else 0,
            "answers_count": len(self.answers) if self.answers else 0,
        }


class AnswerAnswer(Base):
    """Stores individual question answers extracted from an answer script."""
    __tablename__ = "answer_answers"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    script_id = Column(Integer, ForeignKey("answer_scripts.id", ondelete="CASCADE"), nullable=False, index=True)
    question_id = Column(Integer, ForeignKey("exam_questions.id", ondelete="RESTRICT"), nullable=False, index=True)
    image_path = Column(String(500), nullable=True)
    extracted_text = Column(Text, nullable=True)
    ocr_confidence = Column(Float, nullable=True)
    status = Column(String(50), default="PROCESSING", nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    script = relationship("AnswerScript", back_populates="answers")
    question = relationship("ExamQuestion", back_populates="answers")
    ai_evaluation = relationship("AIEvaluation", back_populates="answer", uselist=False, cascade="all, delete-orphan")
    teacher_assignment = relationship("TeacherAssignment", back_populates="answer", uselist=False, cascade="all, delete-orphan")
    final_mark = relationship("FinalMark", back_populates="answer", uselist=False, cascade="all, delete-orphan")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "script_id": self.script_id,
            "question_id": self.question_id,
            "question_number": self.question.question_number if self.question else None,
            "image_path": self.image_path,
            "extracted_text": self.extracted_text,
            "ocr_confidence": self.ocr_confidence,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "ai_evaluation": self.ai_evaluation.to_dict() if self.ai_evaluation else None,
            "final_mark": self.final_mark.to_dict() if self.final_mark else None,
        }


class AIEvaluation(Base):
    """Stores AI-generated marks, evaluation confidence, risk predictions, and risk features."""
    __tablename__ = "ai_evaluations"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    answer_id = Column(Integer, ForeignKey("answer_answers.id", ondelete="CASCADE"), unique=True, nullable=False, index=True)
    ai_mark = Column(Float, nullable=False)
    max_marks = Column(Float, nullable=False)
    semantic_similarity = Column(Float, nullable=False)
    rubric_coverage = Column(Float, nullable=False)
    evaluation_confidence = Column(Float, nullable=False)
    risk_label = Column(String(20), nullable=False, index=True)  # "HIGH", "LOW"
    risk_probability = Column(Float, nullable=False)
    risk_factors = Column(Text, nullable=True)  # JSON list
    model_name = Column(String(100), nullable=True)
    evaluated_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    answer = relationship("AnswerAnswer", back_populates="ai_evaluation")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "answer_id": self.answer_id,
            "ai_mark": self.ai_mark,
            "max_marks": self.max_marks,
            "semantic_similarity": self.semantic_similarity,
            "rubric_coverage": self.rubric_coverage,
            "evaluation_confidence": self.evaluation_confidence,
            "risk_label": self.risk_label,
            "risk_probability": self.risk_probability,
            "risk_factors": self.risk_factors,
            "model_name": self.model_name,
            "evaluated_at": self.evaluated_at.isoformat() if self.evaluated_at else None,
        }


class TeacherAssignment(Base):
    """Assigns risky answers to teachers for human review."""
    __tablename__ = "teacher_assignments"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    answer_id = Column(Integer, ForeignKey("answer_answers.id", ondelete="CASCADE"), nullable=False, index=True)
    teacher_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    assignment_status = Column(String(30), default="ASSIGNED", nullable=False, index=True)  # ASSIGNED, IN_REVIEW, COMPLETED, REASSIGNED
    assigned_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    reviewed_at = Column(DateTime, nullable=True)

    answer = relationship("AnswerAnswer", back_populates="teacher_assignment")
    teacher = relationship("User", back_populates="assignments")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "answer_id": self.answer_id,
            "teacher_id": self.teacher_id,
            "teacher_name": self.teacher.full_name if self.teacher else None,
            "assignment_status": self.assignment_status,
            "assigned_at": self.assigned_at.isoformat() if self.assigned_at else None,
            "reviewed_at": self.reviewed_at.isoformat() if self.reviewed_at else None,
        }


class FinalMark(Base):
    """Stores the final teacher-approved mark for an answer."""
    __tablename__ = "final_marks"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    answer_id = Column(Integer, ForeignKey("answer_answers.id", ondelete="CASCADE"), unique=True, nullable=False, index=True)
    teacher_id = Column(Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    final_mark = Column(Float, nullable=False)
    teacher_notes = Column(Text, nullable=True)
    decision = Column(String(50), default="APPROVED", nullable=False)  # APPROVED, MODIFIED, AUTO_ACCEPTED
    reviewed_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    answer = relationship("AnswerAnswer", back_populates="final_mark")
    teacher = relationship("User", back_populates="final_marks")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "answer_id": self.answer_id,
            "teacher_id": self.teacher_id,
            "teacher_name": self.teacher.full_name if self.teacher else None,
            "final_mark": self.final_mark,
            "teacher_notes": self.teacher_notes,
            "decision": self.decision,
            "reviewed_at": self.reviewed_at.isoformat() if self.reviewed_at else None,
        }


class ScanIssue(Base):
    """Tracks problems that require the scanner to rescan or correct a script."""
    __tablename__ = "scan_issues"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    script_id = Column(Integer, ForeignKey("answer_scripts.id", ondelete="CASCADE"), nullable=False, index=True)
    reported_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    issue_type = Column(String(60), nullable=False, index=True)
    description = Column(Text, nullable=False)
    severity = Column(String(20), default="HIGH", nullable=False)
    status = Column(String(30), default="OPEN", nullable=False, index=True)  # OPEN, RESOLVED, DISMISSED
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    resolved_at = Column(DateTime, nullable=True)

    script = relationship("AnswerScript", back_populates="scan_issues")
    reporter = relationship("User")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "script_id": self.script_id,
            "script_filename": self.script.original_filename if self.script else None,
            "reported_by": self.reported_by,
            "reporter_name": self.reporter.full_name if self.reporter else None,
            "issue_type": self.issue_type,
            "description": self.description,
            "severity": self.severity,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
        }


class Notification(Base):
    """Stores role-specific application notifications."""
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    type = Column(String(50), nullable=False, index=True)
    title = Column(String(150), nullable=False)
    message = Column(Text, nullable=False)
    reference_type = Column(String(50), nullable=True)
    reference_id = Column(Integer, nullable=True)
    is_read = Column(Boolean, default=False, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="notifications")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "type": self.type,
            "title": self.title,
            "message": self.message,
            "reference_type": self.reference_type,
            "reference_id": self.reference_id,
            "is_read": self.is_read,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
