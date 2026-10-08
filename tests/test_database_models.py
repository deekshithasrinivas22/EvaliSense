"""Unit tests for EvaliSense relational database models and schema."""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from api.database.models import (
    AIEvaluation,
    AnswerAnswer,
    AnswerScript,
    Base,
    Department,
    Exam,
    ExamQuestion,
    FinalMark,
    Notification,
    Role,
    ScanIssue,
    Section,
    Student,
    Subject,
    TeacherAssignment,
    TeacherSubject,
    User,
)


@pytest.fixture
def db_session():
    """Create a fresh in-memory SQLite database for testing."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()


def test_role_and_user_creation(db_session):
    """Test role creation and user foreign key relationship."""
    role = Role(name="TEST_ROLE", description="Test Role", is_system_role=False, is_active=True)
    db_session.add(role)
    db_session.commit()

    user = User(
        role_id=role.id,
        username="testuser",
        password_hash="hash123",
        full_name="Test User",
        email="test@evalisense.edu",
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()

    assert user.id is not None
    assert user.role.name == "TEST_ROLE"
    assert len(role.users) == 1


def test_academic_hierarchy(db_session):
    """Test Department -> Section -> Student and Department -> Subject -> Exam."""
    dept = Department(name="Computer Science", code="CS", is_active=True)
    db_session.add(dept)
    db_session.commit()

    section = Section(department_id=dept.id, name="CS-1", semester=1, academic_year="2026-2027")
    db_session.add(section)
    db_session.commit()

    student = Student(usn="1CS001", name="Student One", section_id=section.id)
    db_session.add(student)
    db_session.commit()

    subject = Subject(code="CS101", name="Intro to CS", semester=1, department_id=dept.id, max_marks=50.0)
    db_session.add(subject)
    db_session.commit()

    exam = Exam(
        subject_id=subject.id,
        section_id=section.id,
        name="Midterm 1",
        academic_year="2026-2027",
        total_marks=50.0,
    )
    db_session.add(exam)
    db_session.commit()

    question = ExamQuestion(
        exam_id=exam.id,
        question_number=1,
        question_text="What is a binary tree?",
        max_marks=10.0,
    )
    db_session.add(question)
    db_session.commit()

    assert student.section.name == "CS-1"
    assert student.section.department.code == "CS"
    assert exam.subject.code == "CS101"
    assert len(exam.questions) == 1
    assert exam.questions[0].max_marks == 10.0


def test_evaluation_and_final_mark_models(db_session):
    """Test AnswerScript -> AnswerAnswer -> AIEvaluation and FinalMark."""
    role = Role(name="TCH", description="TCH", is_system_role=True)
    db_session.add(role)
    db_session.commit()

    teacher = User(role_id=role.id, username="tch1", password_hash="h", full_name="T1", email="t1@e.edu")
    dept = Department(name="D", code="D1")
    db_session.add_all([teacher, dept])
    db_session.commit()

    sub = Subject(code="S1", name="S1", semester=1, department_id=dept.id)
    db_session.add(sub)
    db_session.commit()

    exam = Exam(subject_id=sub.id, name="E1", academic_year="2026")
    db_session.add(exam)
    db_session.commit()

    q = ExamQuestion(exam_id=exam.id, question_number=1, question_text="Q1", max_marks=10.0)
    db_session.add(q)
    db_session.commit()

    script = AnswerScript(
        exam_id=exam.id,
        uploaded_by=teacher.id,
        original_filename="scan.png",
        original_path="/tmp/scan.png",
        status="UPLOADED",
    )
    db_session.add(script)
    db_session.commit()

    answer = AnswerAnswer(script_id=script.id, question_id=q.id, status="PROCESSING")
    db_session.add(answer)
    db_session.commit()

    ai_eval = AIEvaluation(
        answer_id=answer.id,
        ai_mark=8.5,
        max_marks=10.0,
        semantic_similarity=0.82,
        rubric_coverage=0.9,
        evaluation_confidence=0.88,
        risk_label="LOW",
        risk_probability=0.15,
    )
    db_session.add(ai_eval)
    db_session.commit()

    final = FinalMark(
        answer_id=answer.id,
        teacher_id=teacher.id,
        final_mark=9.0,
        teacher_notes="Good answer",
        decision="MODIFIED",
    )
    db_session.add(final)
    db_session.commit()

    assert answer.ai_evaluation.ai_mark == 8.5
    assert answer.final_mark.final_mark == 9.0
    assert answer.final_mark.decision == "MODIFIED"
