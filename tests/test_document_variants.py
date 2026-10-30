"""Document-level coverage beyond the original handwritten sample."""
import io
import zipfile
from types import SimpleNamespace
import cv2
import numpy as np
import pymupdf
from fastapi.testclient import TestClient
from api.app import app
from api.services import question_extraction_service as extraction


def word_bytes():
    output = io.BytesIO()
    with zipfile.ZipFile(output,'w') as archive:
        archive.writestr('word/document.xml', '''<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>
        <w:p><w:r><w:t>Q1. Define data. [2 Marks]</w:t></w:r></w:p>
        <w:tbl><w:tr><w:tc><w:p><w:r><w:t>Q2. Explain metadata. [3 Marks]</w:t></w:r></w:p></w:tc></w:tr></w:tbl>
        </w:body></w:document>''')
    return output.getvalue()


def test_word_paragraphs_and_tables_extract_in_order():
    response = TestClient(app).post('/api/extract-questions',files={'file':('exam.docx',word_bytes(),
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document')})
    assert response.status_code == 200
    assert [q['question_number'] for q in response.json()['questions']] == [1,2]
    assert [q['max_marks'] for q in response.json()['questions']] == [2,3]


def test_word_answer_text_skips_handwriting_models():
    client = TestClient(app)
    uploaded = client.post('/api/upload',files={'file':('answers.docx',word_bytes())})
    assert uploaded.status_code == 200
    result = client.post('/api/recognize/'+uploaded.json()['session_id'])
    assert result.status_code == 200
    assert result.json()['metadata']['method'] == 'direct_text'


def test_mixed_pdf_does_not_skip_scan_below_selectable_header(monkeypatch):
    image=np.full((300,400,3),255,np.uint8)
    cv2.putText(image,'Question',(10,100),cv2.FONT_HERSHEY_SIMPLEX,1,(0,0,0),2)
    _, png=cv2.imencode('.png',image)
    document=pymupdf.open()
    page=document.new_page()
    page.insert_text((40,40),'Examination header')
    page.insert_image(pymupdf.Rect(20,70,570,800),stream=png.tobytes())
    called=[]
    def optical(content):
        called.append(True)
        return 'Q1. Scanned question [5 Marks]'
    monkeypatch.setattr(extraction,'extract_text_from_image_bytes',optical)
    text,pages,warnings=extraction.extract_text_from_pdf(document.tobytes())
    document.close()
    assert called and pages[0]['used_ocr']
    assert 'Scanned question' in text


def test_corrupted_word_and_empty_upload_rejected():
    client=TestClient(app)
    assert client.post('/api/upload',files={'file':('broken.docx',b'not a Word archive')}).status_code == 400
    assert client.post('/api/upload',files={'file':('empty.pdf',b'')}).status_code == 400
    image_document=io.BytesIO(word_bytes())
    with zipfile.ZipFile(image_document,'a') as archive:
        archive.writestr('word/media/image1.png',b'embedded image placeholder')
    response=client.post('/api/upload',files={'file':('with_images.docx',image_document.getvalue())})
    assert response.status_code == 422
    assert 'Export it as PDF' in response.json()['detail']


def test_word_answer_key_preview_and_original_download():
    output=io.BytesIO()
    with zipfile.ZipFile(output,'w') as archive:
        archive.writestr('word/document.xml', '''<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>
        <w:p><w:r><w:t>1. B</w:t></w:r></w:p>
        <w:p><w:r><w:t>2. Data represents observations.</w:t></w:r></w:p>
        </w:body></w:document>''')
    content=output.getvalue()
    client=TestClient(app)
    response=client.post('/api/answer-key-files',data={'exam_id':'word-exam'},files={'file':('key.docx',content)})
    assert response.status_code == 200
    assert response.json()['answers'][0]['correct_option'] == 'B'
    downloaded=client.get(response.json()['download_url'])
    assert downloaded.content == content
