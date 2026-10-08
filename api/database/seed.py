"""Database seeding script for EvaliSense.

Initialises the three system roles:
- HOD (Head of Department / Admin)
- TEACHER (Examiner / Teacher)
- SCANNER (Scanning Operator)

Creates an initial HOD user if one does not exist, and seeds initial academic
structures for ready-to-test demonstration.
"""
from __future__ import annotations

import json
import os
from api.auth.security import hash_password
from api.database.models import (
    Department,
    Exam,
    ExamQuestion,
    Role,
    Section,
    Student,
    Subject,
    TeacherSubject,
    User,
)
from api.database.session import SessionLocal
from utils.logging import get_logger

logger = get_logger(__name__)


def seed_initial_data() -> None:
    """Safely seed initial roles, admin user, and sample academic hierarchy."""
    db = SessionLocal()
    try:
        # 1. System Roles
        roles_data = [
            ("HOD", "Head of Department / administrator with complete academic and user-management privileges.", True),
            ("TEACHER", "Teacher/examiner who reviews only the risky/high-risk answers assigned to them.", True),
            ("SCANNER", "Operator who uploads handwritten answer scripts and handles scan-quality or OCR-related problems.", True),
        ]

        roles_by_name: dict[str, Role] = {}
        for name, desc, is_sys in roles_data:
            role = db.query(Role).filter(Role.name == name).first()
            if not role:
                role = Role(name=name, description=desc, is_system_role=is_sys, is_active=True)
                db.add(role)
                db.flush()
                logger.info("Created system role: %s", name)
            roles_by_name[name] = role

        db.commit()

        # 2. Seed Default HOD User
        hod_role = roles_by_name["HOD"]
        admin_user = db.query(User).filter(User.username == "admin").first()
        if not admin_user:
            admin_pwd = os.environ.get("EVALISENSE_ADMIN_PASSWORD", "Admin@123")
            admin_user = User(
                role_id=hod_role.id,
                employee_id="EMP-HOD-001",
                username="admin",
                password_hash=hash_password(admin_pwd),
                full_name="Prof. Eleanor Vance (HOD)",
                email="admin@evalisense.edu",
                phone="+91 9876543210",
                is_active=True,
            )
            db.add(admin_user)
            db.flush()
            logger.info("Created initial HOD user: admin (employee_id: EMP-HOD-001)")

        # 3. Seed Default Teacher and Scanner for testing/demo
        teacher_role = roles_by_name["TEACHER"]
        teacher_user = db.query(User).filter(User.username == "teacher1").first()
        if not teacher_user:
            teacher_user = User(
                role_id=teacher_role.id,
                employee_id="EMP-TCH-001",
                username="teacher1",
                password_hash=hash_password("Teacher@123"),
                full_name="Dr. Alan Turing",
                email="turing@evalisense.edu",
                phone="+91 9876543211",
                is_active=True,
            )
            db.add(teacher_user)
            db.flush()

        teacher2_user = db.query(User).filter(User.username == "teacher2").first()
        if not teacher2_user:
            teacher2_user = User(
                role_id=teacher_role.id,
                employee_id="EMP-TCH-002",
                username="teacher2",
                password_hash=hash_password("Teacher@123"),
                full_name="Dr. Ada Lovelace",
                email="lovelace@evalisense.edu",
                phone="+91 9876543212",
                is_active=True,
            )
            db.add(teacher2_user)
            db.flush()

        scanner_role = roles_by_name["SCANNER"]
        scanner_user = db.query(User).filter(User.username == "scanner1").first()
        if not scanner_user:
            scanner_user = User(
                role_id=scanner_role.id,
                employee_id="EMP-SCN-001",
                username="scanner1",
                password_hash=hash_password("Scanner@123"),
                full_name="Mark Scanwell",
                email="scanner@evalisense.edu",
                phone="+91 9876543213",
                is_active=True,
            )
            db.add(scanner_user)
            db.flush()

        # 4. Seed Department
        dept = db.query(Department).filter(Department.code == "CSE").first()
        if not dept:
            dept = Department(name="Computer Science & Engineering", code="CSE", is_active=True)
            db.add(dept)
            db.flush()

        # 5. Seed Section
        section = db.query(Section).filter(Section.name == "CSE-A", Section.department_id == dept.id).first()
        if not section:
            section = Section(department_id=dept.id, name="CSE-A", semester=5, academic_year="2026-2027", is_active=True)
            db.add(section)
            db.flush()

        # 6. Seed Students
        sample_students = [
            ("1MS22CS001", "Aarav Sharma", "01", "aarav@student.evalisense.edu"),
            ("1MS22CS002", "Diya Patel", "02", "diya@student.evalisense.edu"),
            ("1MS22CS003", "Rohan Gupta", "03", "rohan@student.evalisense.edu"),
            ("1MS22CS004", "Ananya Reddy", "04", "ananya@student.evalisense.edu"),
        ]
        for usn, s_name, roll, email in sample_students:
            st = db.query(Student).filter(Student.usn == usn).first()
            if not st:
                db.add(Student(usn=usn, name=s_name, section_id=section.id, roll_number=roll, email=email, is_active=True))

        # 7. Seed Subject
        subject = db.query(Subject).filter(Subject.code == "CS501").first()
        if not subject:
            subject = Subject(
                code="CS501",
                name="Natural Science & Biology for Engineers",
                semester=5,
                department_id=dept.id,
                max_marks=10.0,
                is_active=True,
            )
            db.add(subject)
            db.flush()

        # 8. Seed Teacher-Subject Mapping
        mapping = db.query(TeacherSubject).filter(
            TeacherSubject.teacher_id == teacher_user.id,
            TeacherSubject.subject_id == subject.id,
        ).first()
        if not mapping:
            db.add(TeacherSubject(
                teacher_id=teacher_user.id,
                subject_id=subject.id,
                section_id=section.id,
                academic_year="2026-2027",
                is_active=True,
            ))

        mapping2 = db.query(TeacherSubject).filter(
            TeacherSubject.teacher_id == teacher2_user.id,
            TeacherSubject.subject_id == subject.id,
        ).first()
        if not mapping2:
            db.add(TeacherSubject(
                teacher_id=teacher2_user.id,
                subject_id=subject.id,
                section_id=section.id,
                academic_year="2026-2027",
                is_active=True,
            ))

        # 9. Seed Exam & Question with Rubric
        exam = db.query(Exam).filter(Exam.name == "Midterm Examination 1", Exam.subject_id == subject.id).first()
        if not exam:
            exam = Exam(
                subject_id=subject.id,
                section_id=section.id,
                name="Midterm Examination 1",
                exam_type="INTERNAL",
                exam_date="2026-10-15",
                academic_year="2026-2027",
                total_marks=10.0,
                status="SCHEDULED",
            )
            db.add(exam)
            db.flush()

            # Rubric from Photosynthesis sample in repo
            photosynthesis_rubric = {
                "question": "Explain the process of photosynthesis, including the light-dependent and light-independent reactions.",
                "max_marks": 10.0,
                "reference_answer": "Photosynthesis is the biological process by which green plants convert light energy into chemical energy. It occurs in chloroplasts and consists of light-dependent reactions in thylakoids producing ATP and NADPH, and light-independent reactions (Calvin cycle) in the stroma synthesizing glucose from CO2.",
                "criteria": [
                    {
                        "id": "c1",
                        "description": "Definition and overall purpose: conversion of light energy to chemical energy by autotrophs.",
                        "marks": 2.0,
                        "keywords": ["photosynthesis", "light energy", "chemical energy", "glucose", "chloroplast"],
                    },
                    {
                        "id": "c2",
                        "description": "Light-dependent reactions: absorption of sunlight in thylakoids, water splitting (photolysis), ATP and NADPH generation.",
                        "marks": 3.0,
                        "keywords": ["light-dependent", "thylakoid", "chlorophyll", "ATP", "NADPH", "photolysis", "water"],
                    },
                    {
                        "id": "c3",
                        "description": "Light-independent reactions (Calvin cycle): carbon fixation in stroma using ATP and NADPH to form sugars.",
                        "marks": 3.0,
                        "keywords": ["Calvin cycle", "light-independent", "stroma", "carbon dioxide", "carbon fixation", "RuBisCO"],
                    },
                    {
                        "id": "c4",
                        "description": "Overall chemical equation or input/output balance (6CO2 + 6H2O -> C6H12O6 + 6O2).",
                        "marks": 2.0,
                        "keywords": ["equation", "CO2", "H2O", "oxygen", "glucose"],
                    },
                ],
                "metadata": {"subject": "Biology", "difficulty": "intermediate"},
            }

            question = ExamQuestion(
                exam_id=exam.id,
                question_number=1,
                question_text="Explain the process of photosynthesis, including the light-dependent and light-independent reactions.",
                max_marks=10.0,
                reference_answer=photosynthesis_rubric["reference_answer"],
                rubric_json=json.dumps(photosynthesis_rubric),
            )
            db.add(question)

        db.commit()
        logger.info("Initial database seeding completed successfully.")
    except Exception as exc:
        db.rollback()
        logger.error("Database seeding encountered error: %s", exc)
        raise
    finally:
        db.close()
