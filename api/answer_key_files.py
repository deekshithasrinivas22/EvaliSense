"""Durable answer-key files and conservative extraction for the local teacher UI."""
from pathlib import Path
import json
import csv
import io
import re
import uuid

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse


def parse_csv_answer_key(text: str):
    """Read CSV-formatted TXT without splitting quoted commas or newlines."""
    def normalize(value):
        return re.sub(r'[^a-z0-9]', '', str(value or '').casefold())

    stream = io.StringIO(text.lstrip('\ufeff \t\r\n'), newline='')
    try:
        reader = csv.DictReader(stream, strict=True)
        fields = reader.fieldnames or []
        names = [normalize(field) for field in fields]
        expected = {'questionnumber', 'type', 'correctanswer'}
        if not expected.intersection(names):
            return None
        if not expected.issubset(names):
            raise ValueError('CSV keys need Question_Number, Type, and Correct_Answer columns.')
        if len(names) != len(set(names)):
            raise ValueError('CSV answer-key column names must be unique.')
        columns = dict(zip(names, fields))
        answers, warnings, seen = [], [], set()
        for row in reader:
            line = reader.line_num
            if None in row:
                raise ValueError(f'CSV line {line} has extra values. Put answers containing commas inside double quotes.')
            if not any(str(value or '').strip() for value in row.values()):
                continue
            if any(value is None for value in row.values()):
                raise ValueError(f'CSV line {line} is missing a column value.')
            number_text = row[columns['questionnumber']].strip()
            if not re.fullmatch(r'[1-9]\d*', number_text):
                raise ValueError(f'CSV line {line} needs a positive whole Question_Number.')
            number = int(number_text)
            kind = normalize(row[columns['type']])
            if kind in {'mcq', 'multiplechoice', 'multiplechoicequestion'}:
                answer_type = 'MCQ'
            elif kind in {'shortanswer', 'longanswer', 'written', 'writtenanswer', 'descriptive', 'essay', 'qa'}:
                answer_type = 'WRITTEN'
            else:
                raise ValueError(f'CSV line {line} has an unsupported Type. Use MCQ, Short_Answer, or Long_Answer.')
            answer = row[columns['correctanswer']].strip()
            if not answer:
                raise ValueError(f'CSV line {line} has an empty Correct_Answer.')
            option = None
            if answer_type == 'MCQ':
                option = re.fullmatch(r'(?:option\s+)?(?:\(([A-H])\)|([A-H])[.)]?)', answer, re.I)
                if len(answer) == 1 and answer.isalpha() and not option:
                    raise ValueError(f'CSV line {line} needs an MCQ letter A–H or the exact option text.')
            letter = (option.group(1) or option.group(2)).upper() if option else ''
            section = row[columns['section']].strip().upper() if 'section' in columns else ''
            identity = (section, number)
            if identity in seen:
                warnings.append(f'Duplicate answer number {section + "." if section else ""}{number}. Correct the preview before saving.')
            seen.add(identity)
            answers.append({'question_number': number, 'section': section,
                            'answer_type': answer_type, 'correct_option': letter,
                            'answer_text': '' if letter else answer, 'raw_answer': answer})
    except csv.Error as error:
        raise ValueError(f'Malformed CSV answer key: {error}. Check double quotes and commas.') from error
    return {'answers': answers, 'warnings': warnings}


def parse_answer_key(text: str) -> dict:
    """Return numbered answers, preserving section labels and written subparts."""
    table = parse_csv_answer_key(text)
    if table is not None:
        return table
    answers = []
    current = None
    section = ''
    warnings = []
    start = re.compile(r'^(?:(?:Q(?:uestion)?\.?|Ans(?:wer)?\.?)\s*)?(\d+)\s*(?:[.):]|[-–])\s*(.*)$', re.I)
    section_start = re.compile(r'^(?:section|part)\s+([A-Z0-9IVX]+)\b', re.I)
    prefix = re.compile(r'^(?:(?:correct\s+)?(?:answer|ans|solution|model\s+answer)\s*[:.\-]\s*)', re.I)

    def finish():
        nonlocal current
        if current is None:
            return
        body = '\n'.join(current.pop('_lines')).strip()
        # When the question is repeated in a model key, prefer its Answer: block.
        answer_block = re.search(r'(?:^|\n)\s*(?:(?:correct\s+)?answer|ans|solution|model\s+answer)\s*[:.\-]\s*', body, re.I)
        if answer_block:
            body = body[answer_block.end():].strip()
        body = prefix.sub('', body).strip()
        option = re.match(r'^(?:\(([A-H])\)|([A-H])[.)]|([A-H])(?=\s*$))\s*(.*)$', body, re.I | re.S)
        # A sole letter, parenthesized letter or explicitly punctuated option is evidence.
        if len(re.findall(r'(?:^|\s)\([a-hA-H]\)\s*', body)) > 1:
            option = None
        if option:
            current['correct_option'] = next(x for x in option.groups()[:3] if x).upper()
            current['answer_text'] = option.group(4).strip()
        else:
            current['correct_option'] = ''
            current['answer_text'] = body
        if body:
            current['raw_answer'] = body
            answers.append(current)
        else:
            warnings.append(f"No answer text found for {section + '.' if section else ''}{current['question_number']}.")
        current = None

    for raw in text.replace('\ufeff', '').splitlines():
        line = raw.strip()
        if not line:
            continue
        heading = section_start.match(line)
        if heading:
            finish()
            section = heading.group(1).upper()
            continue
        if re.match(r'^(?:answer\s+key|marking\s+scheme|model\s+answers?|page\s+\d+(?:\s+of\s+\d+)?|time\s*:|total\s+marks\s*:|maximum\s+marks\s*:)', line, re.I):
            continue
        # Compact MCQ keys: 1. B  2. C  3. A, including 1 B 2 C.
        compact = re.findall(r'(?<!\w)(\d+)\s*[.):\-]?\s*\(?([A-H])\)?(?=\s|[,;]|$)', line, re.I)
        remainder = re.sub(r'(?<!\w)\d+\s*[.):\-]?\s*\(?[A-H]\)?(?=\s|[,;]|$)', '', line, flags=re.I)
        if compact and not remainder.strip(' ,;|'):
            finish()
            for num, letter in compact:
                answers.append({'question_number': int(num), 'section': section,
                                'answer_text': '', 'correct_option': letter.upper(), 'raw_answer': letter.upper()})
            continue
        sub = re.match(r'^(?:Q(?:uestion)?\.?\s*)?(\d+)\s*\(([a-h])\)\s*[:.)-]?\s*(.+)$', line, re.I)
        if sub:
            number = int(sub.group(1))
            if current is None or current['question_number'] != number:
                finish()
                current = {'question_number': number, 'section': section, '_lines': []}
            current['_lines'].append(f"({sub.group(2).lower()}) {sub.group(3)}")
            continue
        line = re.sub(r'^(Q(?:uestion)?\.?|Ans(?:wer)?\.?)\s*(\d+)\s+(?![.):–-])', r'\1\2: ', line, flags=re.I)
        match = start.match(line)
        if match:
            finish()
            current = {'question_number': int(match.group(1)), 'section': section, '_lines': [match.group(2)]}
        elif current:
            current['_lines'].append(line)
    finish()
    seen = set()
    for entry in answers:
        identity = (entry['section'], entry['question_number'])
        if identity in seen:
            warnings.append(f"Duplicate answer number: {entry['section'] + '.' if entry['section'] else ''}{entry['question_number']}. Correct the preview before saving.")
        seen.add(identity)
    if not answers:
        warnings.append('No numbered answers found. Use a format such as 1. B or Q2: followed by the model answer.')
    return {'answers': answers, 'warnings': warnings}


def extract_answer_key_text(content: bytes, suffix: str) -> str:
    if suffix == '.txt':
        try:
            return content.decode('utf-16' if content.startswith((b'\xff\xfe', b'\xfe\xff')) else 'utf-8-sig')
        except UnicodeError:
            raise HTTPException(400, 'Save the TXT answer key using UTF-8 or UTF-16 encoding.')
    if suffix == '.pdf':
        import fitz
        try:
            with fitz.open(stream=content, filetype='pdf') as doc:
                if doc.needs_pass:
                    raise HTTPException(400, 'Upload an unlocked PDF answer key.')
                pages = []
                for number, page in enumerate(doc, 1):
                    text = page.get_text(sort=True)
                    if not text.strip() and page.get_images():
                        raise HTTPException(400, f'Page {number} is scanned without readable text. Upload an OCR text PDF or TXT answer key.')
                    pages.append(text)
                return '\n'.join(pages)
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(400, 'The PDF could not be read. Check that it is valid and unlocked.')
    raise HTTPException(400, 'Answer keys currently support PDF and TXT files.')


def build_answer_key_router(storage_root: Path) -> APIRouter:
    """Files are retained independently of browser refreshes and API restarts."""
    router = APIRouter(prefix='/api/answer-key-files', tags=['Teacher answer key files'])
    storage_root = storage_root.resolve()

    @router.post('')
    async def upload_key_file(file: UploadFile = File(...), exam_id: str = Form(...)):
        exam_id = exam_id.strip()
        if not exam_id or len(exam_id) > 200:
            raise HTTPException(400, 'Select a valid examination before uploading.')
        filename = (file.filename or '').replace('\\', '/').rsplit('/', 1)[-1]
        suffix = Path(filename).suffix.lower()
        if suffix not in {'.pdf', '.txt'}:
            raise HTTPException(400, 'Answer keys support PDF and TXT files.')
        content = await file.read(50 * 1024 * 1024 + 1)
        if not content:
            raise HTTPException(400, 'The answer key file is empty.')
        if len(content) > 50 * 1024 * 1024:
            raise HTTPException(413, 'The answer key must be smaller than 50 MB.')
        text = extract_answer_key_text(content, suffix)
        if not text.strip():
            raise HTTPException(400, 'No readable text found. Supply a text PDF or TXT answer key.')
        try:
            parsed = parse_answer_key(text)
        except ValueError as error:
            raise HTTPException(400, str(error))
        if not parsed['answers']:
            raise HTTPException(400, parsed['warnings'][0])
        if len(text.encode('utf-8')) > 500_000:
            raise HTTPException(413, 'The extracted key is too large. Split it into a smaller exam-specific key.')
        file_id = uuid.uuid4().hex
        folder = storage_root / file_id
        folder.mkdir(parents=True)
        result = {'file_id': file_id, 'exam_id': exam_id, 'original_filename': filename,
                  'file_size': len(content), 'mime_type': 'application/pdf' if suffix == '.pdf' else 'text/plain',
                  'extracted_text': text, 'answers': parsed['answers'], 'parse_warnings': parsed['warnings'],
                  'download_url': f'/api/answer-key-files/{file_id}'}
        try:
            (folder / ('original' + suffix)).write_bytes(content)
            # Persist metadata last, so a download never sees a partially written upload.
            (folder / 'metadata.json').write_text(json.dumps({**result, 'suffix': suffix}, ensure_ascii=False), encoding='utf-8')
        except OSError:
            raise HTTPException(500, 'The answer key could not be stored on the server. Retry the upload.')
        return result

    @router.get('/{file_id}')
    async def download_key_file(file_id: str):
        if not re.fullmatch(r'[a-f0-9]{32}', file_id):
            raise HTTPException(404, 'Answer key file not found.')
        folder = storage_root / file_id
        try:
            metadata = json.loads((folder / 'metadata.json').read_text(encoding='utf-8'))
            suffix = metadata['suffix']
            if suffix not in {'.pdf', '.txt'}:
                raise ValueError('Invalid stored suffix')
            path = folder / ('original' + suffix)
            if not path.is_file():
                raise FileNotFoundError
        except (OSError, ValueError, KeyError):
            raise HTTPException(404, 'The stored answer key file is unavailable.')
        return FileResponse(path, filename=metadata['original_filename'], media_type=metadata['mime_type'])

    return router
