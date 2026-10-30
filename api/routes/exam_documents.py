"""Exam-scoped document extraction, reviewed questions and version lifecycle."""
import json
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from api.auth.dependencies import require_teacher
from api.database.session import get_db
from api.database.models import AnswerAnswer, AnswerKeyFile, ExamQuestion, QuestionPaperFile
from api.routes.teacher_documents import _verify_teacher_exam_access
from api.schemas.academic import ExamQuestionCreate
from api.services import question_extraction_service as extraction
from api.services import question_paper_service as papers
from api.services import answer_key_service as keys
from evaluation import Rubric

router = APIRouter(prefix="/api/teacher", tags=["Exam Documents"])


def validated_questions(rows):
    if not isinstance(rows, list) or not 1 <= len(rows) <= 250:
        raise HTTPException(400, "Provide between 1 and 250 questions.")
    result, seen = [], set()
    for row in rows:
        try:
            q = ExamQuestionCreate(**row)
            if not q.question_text.strip() or q.question_number in seen:
                raise ValueError("Question text is required and numbers must be unique.")
            seen.add(q.question_number)
            if q.rubric_json:
                rubric = Rubric.from_dict(json.loads(q.rubric_json))
                if sum(c.marks for c in rubric.criteria) > q.max_marks + .01:
                    raise ValueError("Rubric total exceeds question maximum marks.")
                warnings = rubric.validate()
                if warnings or abs(rubric.max_marks - q.max_marks) > .01:
                    raise ValueError("Invalid rubric: " + "; ".join(warnings))
            result.append(q)
        except (ValueError, TypeError, KeyError) as error:
            raise HTTPException(400, str(error))
    return result


@router.post("/exams/{exam_id}/upload-question-paper")
def upload_paper(exam_id: int, file: UploadFile = File(...), user=Depends(require_teacher), db: Session=Depends(get_db)):
    exam = _verify_teacher_exam_access(db, user, exam_id)
    content = file.file.read(extraction.MAX_QP_FILE_SIZE + 1)
    valid, message, meta = extraction.validate_question_paper_file(file, content)
    if not valid:
        raise HTTPException(400, message)
    text, pages, warnings = extraction.extract_text_from_document(file, content)
    questions, preamble, parser_warnings = extraction.parse_questions_from_text(text)
    record = papers.save_and_register_question_paper(db, exam, file, content, user, meta, len(questions))
    return {"status": "success", "exam_id": exam_id, "questions": questions,
            "preamble": preamble, "warnings": warnings + parser_warnings,
            "pages": pages, "page_count": meta['page_count'], "version": record.version,
            "question_paper": record.to_dict()}


@router.post("/exams/{exam_id}/questions/confirm")
def confirm_questions(exam_id: int, payload: dict, user=Depends(require_teacher), db: Session=Depends(get_db)):
    _verify_teacher_exam_access(db, user, exam_id)
    rows = validated_questions(payload.get('questions'))
    existing = db.query(ExamQuestion).filter_by(exam_id=exam_id).all()
    if payload.get('replace_existing'):
        ids = [q.id for q in existing]
        if ids and db.query(AnswerAnswer).filter(AnswerAnswer.question_id.in_(ids)).first():
            raise HTTPException(409, "Evaluated questions cannot be replaced. Preserve the examination audit trail.")
        for q in existing:
            db.delete(q)
        db.flush()
        existing = []
    by_number = {q.question_number: q for q in existing}
    for row in rows:
        record = by_number.get(row.question_number)
        if record is None:
            record = ExamQuestion(exam_id=exam_id)
            db.add(record)
        for key, value in row.model_dump().items():
            setattr(record, key, value)
    db.commit()
    return {"status": "success", "exam_id": exam_id, "saved_count": len(rows)}


@router.get("/exams/{exam_id}/question-papers")
def list_papers(exam_id: int, user=Depends(require_teacher), db: Session=Depends(get_db)):
    _verify_teacher_exam_access(db, user, exam_id)
    return papers.get_exam_question_papers_info(db, exam_id)


@router.get("/exams/{exam_id}/question-paper/preview")
def preview_paper(exam_id: int, user=Depends(require_teacher), db: Session=Depends(get_db)):
    _verify_teacher_exam_access(db, user, exam_id)
    record = db.query(QuestionPaperFile).filter_by(exam_id=exam_id, is_active=True, status="ACTIVE").first()
    if not record or not Path(record.file_path).is_file():
        raise HTTPException(404, "Question paper not found.")
    return FileResponse(record.file_path)


@router.get("/question-papers/{paper_id}/file")
def download_paper(paper_id: int, user=Depends(require_teacher), db: Session=Depends(get_db)):
    record = db.get(QuestionPaperFile, paper_id)
    if not record or record.status == "DELETED":
        raise HTTPException(404, "Question paper not found.")
    _verify_teacher_exam_access(db, user, record.exam_id)
    if not Path(record.file_path).is_file():
        raise HTTPException(404, "Question paper file is unavailable.")
    return FileResponse(record.file_path, filename=record.original_filename)


@router.post("/exams/{exam_id}/answer-key")
def upload_key(exam_id: int, file: UploadFile | None = File(None), questions_json: str | None = Form(None),
               user=Depends(require_teacher), db: Session=Depends(get_db)):
    exam = _verify_teacher_exam_access(db, user, exam_id)
    if not file and not questions_json:
        raise HTTPException(400, "Provide a marking document or structured answer key.")
    record = keys.save_and_register_answer_key(db, exam, user, file, questions_json)
    return {"status": "success", "version": record.version, "answer_key": record.to_dict()}


@router.get("/exams/{exam_id}/answer-key")
def get_key(exam_id: int, user=Depends(require_teacher), db: Session=Depends(get_db)):
    _verify_teacher_exam_access(db, user, exam_id)
    return keys.get_exam_answer_key_info(db, exam_id)


@router.get("/answer-keys/{key_id}/file")
def download_key(key_id: int, user=Depends(require_teacher), db: Session=Depends(get_db)):
    record = db.get(AnswerKeyFile, key_id)
    if not record or record.status == 'DELETED':
        raise HTTPException(404, 'Answer key not found.')
    _verify_teacher_exam_access(db, user, record.exam_id)
    if not Path(record.file_path).is_file():
        raise HTTPException(404, 'Answer key file is unavailable.')
    return FileResponse(record.file_path, filename=record.original_filename)


def lifecycle(document, action, service):
    # Bind each route in a factory so action/service are not request parameters.
    def endpoint(exam_id: int, document_id: int, user=Depends(require_teacher), db: Session=Depends(get_db)):
        _verify_teacher_exam_access(db, user, exam_id)
        result = service(db, exam_id, document_id, user)
        return result if isinstance(result, dict) else {document: result.to_dict()}
    endpoint.__name__ = f'{action}_{document}'
    return endpoint


for path, document, module, singular in [('question-papers', 'question_paper', papers, 'question_paper'),
                                          ('answer-keys', 'answer_key', keys, 'answer_key')]:
    for action in ('activate', 'archive', 'restore', 'delete'):
        service = getattr(module, f'{action}_{singular}_version')
        suffix = '' if action == 'delete' else '/' + action
        router.add_api_route('/exams/{exam_id}/' + path + '/{document_id}' + suffix,
                             lifecycle(document, action, service), methods=['DELETE' if action == 'delete' else 'POST'])
