"""Whole-script matching: explicit answer numbers only; uncertainty never becomes zero."""
import re
from collections import defaultdict
from fastapi import APIRouter, HTTPException
from starlette.concurrency import run_in_threadpool

START = re.compile(r'^\s*(?:(?:Q(?:uestion)?|Ans(?:wer)?)\s*[.:-]?\s*(\d{1,3})\s*[.):\-]?|(?:\(?(\d{1,3})\)?)[.):])\s*(.*)$', re.I)
SECTION = re.compile(r'^\s*(?:section|part)\s+([A-Z]+|\d+)\s*(?:[:\-—].*)?$', re.I)

def split_script(text):
    blocks, ignored, current, section = [], [], None, ''
    for line in text.splitlines():
        heading = SECTION.match(line)
        if heading:
            current = None
            section = heading.group(1).upper()
            continue
        match = START.match(line)
        if match:
            current = {'number':int(match.group(1) or match.group(2)), 'section':section, 'lines':[match.group(3)]}
            blocks.append(current)
        elif current is not None:
            current['lines'].append(line)
        elif line.strip():
            ignored.append(line)
    for block in blocks:
        block['text'] = '\n'.join(block.pop('lines')).strip()
    return blocks, '\n'.join(ignored)

def evaluate_script(text, questions, evaluator_factory):
    from evaluation import Rubric
    if not isinstance(questions, list) or not questions or len(questions) > 250:
        raise ValueError('Provide between 1 and 250 exam questions.')
    blocks, ignored = split_script(text)
    index = defaultdict(list)
    for b in blocks:
        index[b['number']].append(b)
    number_counts = defaultdict(int)
    for q in questions:
        number_counts[int(q.get('source_question_number') or q['question_number'])] += 1
    results, used = [], set()
    evaluator = None
    for q in questions:
        number = int(q.get('source_question_number') or q['question_number'])
        row = {'question_id':q.get('id'), 'question_number':q['question_number'], 'max_marks':q.get('max_marks'),
               'status':'needs_review', 'score':None, 'answer':''}
        results.append(row)
        candidates = index[number]
        section = str(q.get('section') or '').upper()
        exact = [b for b in candidates if b['section'] == section] if section else []
        if exact: candidates = exact
        elif number_counts[number] > 1: candidates = []
        if not candidates:
            row['reason'] = 'No unambiguous numbered answer found. Not scored.'; continue
        if len(candidates) != 1:
            row['reason'] = 'Repeated answer number; check the extracted text. Not scored.'; continue
        block = candidates[0]
        # An explicitly different section is never assigned by number alone.
        if section and block['section'] and section != block['section']:
            row['reason'] = 'Answer section does not match the question. Not scored.'; continue
        used.add(id(block)); answer = block['text']; row['answer'] = answer
        if '[Unclear line' in answer:
            row['reason'] = 'Unreliable OCR remains in this answer. Correct the extracted script before scoring.'; continue
        if not answer:
            row['reason'] = 'Empty answer block. Not scored.'; continue
        reference = str(q.get('reference_answer') or '').strip()
        try: marks = float(q.get('max_marks') or 0)
        except (ValueError,TypeError): marks = 0
        if not reference or marks <= 0:
            row['reason'] = 'Missing reference answer or maximum marks. Update the exam answer key.'; continue
        if q.get('question_type') == 'MCQ':
            correct = str(q.get('correct_option') or '').upper().strip()
            if not re.fullmatch('[A-H]', correct):
                m = re.match(r'^\s*([A-H])(?:[.):\s]|$)',reference,re.I)
                correct = m.group(1).upper() if m else ''
            selected = re.fullmatch(r'\s*(?:(?:answer|option)\s*[:\-]?\s*)?\(?([A-H])\)?[.)]?\s*',answer,re.I)
            if not correct or not selected:
                row['reason'] = 'MCQ answer is not a single readable option letter. Check this answer.'; continue
            row.update(status='scored', score=marks if selected.group(1).upper()==correct else 0,
                       reason='Exact option comparison with the stored answer key.')
            continue
        try:
            criteria = q.get('criteria') or []
            if not criteria and q.get('rubric_json'):
                import json
                criteria = json.loads(q['rubric_json']).get('criteria',[])
            # Explicitly label holistic reference scoring; never invent partial-mark rules.
            holistic = not criteria
            if holistic:
                criteria=[{'id':'reference','description':reference,'marks':marks,'keywords':[]}]
            rubric = Rubric.from_dict({'question':q.get('question_text',''), 'max_marks':marks,
                'reference_answer':reference,'criteria':criteria})
            if rubric.validate() or any(c.marks <= 0 or not c.description.strip() for c in rubric.criteria):
                row['reason']='Invalid marking criteria. Check the saved rubric.'; continue
            evaluator = evaluator or evaluator_factory()
            evaluation = evaluator.evaluate(answer,rubric).to_dict()
            row.update(status='scored',score=evaluation['total_score'],evaluation=evaluation,
                       reason='Preliminary reference-answer similarity score; no detailed rubric provided.' if holistic else 'Preliminary score using the saved rubric.')
        except Exception as error:
            row['reason']=f'Evaluation unavailable: {error}'
    return {'results':results, 'scored_count':sum(r['status']=='scored' for r in results),
            'review_count':sum(r['status']!='scored' for r in results),
            'scored_subtotal':sum(r['score'] for r in results if r['score'] is not None),
            'ignored_preamble':ignored, 'unmatched_blocks':[b for b in blocks if id(b) not in used],
            'note':'Subtotal covers scored answers only. Unmatched or uncertain answers are not marked zero. Teacher review is required.'}

def build_script_router(sessions, evaluator_factory):
    router=APIRouter()
    @router.post('/api/evaluate-script/{session_id}')
    async def whole_script(session_id:str, payload:dict):
        session=sessions.get(session_id)
        if not session: raise HTTPException(404,'Session not found. Upload the answer script again.')
        if session.get('script_evaluation_busy'): raise HTTPException(409,'This script is already being evaluated.')
        recognized=session.get('htr_result')
        if not recognized: raise HTTPException(400,'Recognize the script first.')
        metadata=recognized.get('metadata',{})
        if metadata.get('method') != 'direct_text' and payload.get('text_reviewed') is not True:
            raise HTTPException(422,'Review and correct the recognized handwriting before grading. OCR confidence cannot guarantee correctness.')
        text=payload.get('text',recognized.get('full_text',''))
        if not isinstance(text,str) or len(text)>500000: raise HTTPException(400,'Invalid or oversized script text.')
        session['script_evaluation_busy']=True
        try:
            result=await run_in_threadpool(evaluate_script,text,payload.get('questions'),evaluator_factory)
            session['script_evaluation']=result
            return result
        except (ValueError,TypeError,KeyError) as error: raise HTTPException(400,str(error))
        finally: session['script_evaluation_busy']=False
    return router
