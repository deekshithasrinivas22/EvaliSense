"""Routes package for EvaliSense."""
from api.routes.auth import router as auth_router
from api.routes.roles import router as roles_router
from api.routes.users import router as users_router
from api.routes.departments import router as departments_router
from api.routes.sections import router as sections_router
from api.routes.students import router as students_router
from api.routes.subjects import router as subjects_router
from api.routes.teacher_assignments import router as teacher_assignments_router
from api.routes.exams import router as exams_router
from api.routes.questions import router as questions_router
from api.routes.scripts import router as scripts_router
from api.routes.evaluation import router as evaluation_router
from api.routes.teacher import router as teacher_router
from api.routes.scanner import router as scanner_router
from api.routes.results import router as results_router
from api.routes.notifications import router as notifications_router
from api.routes.analytics import router as analytics_router

all_routers = [
    auth_router,
    roles_router,
    users_router,
    departments_router,
    sections_router,
    students_router,
    subjects_router,
    teacher_assignments_router,
    exams_router,
    questions_router,
    scripts_router,
    evaluation_router,
    teacher_router,
    scanner_router,
    results_router,
    notifications_router,
    analytics_router,
]

__all__ = ["all_routers"]
