import importlib
from copy import deepcopy
from types import SimpleNamespace
import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient
from htr.result import HTRResult, RecognizedLine
from htr.local_segmenter import LineRegion
from htr.review import split_column_regions, numbering_issues
from htr.ink import assess_line_ink

api = importlib.import_module('api.app')


@pytest.fixture
def session(tmp_path):
    path=tmp_path/'scan.png'
    cv2.imwrite(str(path),np.full((100,200,3),255,np.uint8))
    previous={'full_text':'1. B','lines':[], 'average_confidence':.8,
              'metadata':{'ocr_version':'local-ensemble-v9','recognition_mode':'standard',
                          'pages':[{'page_number':1,'regions':[{'line_number':1,'bounding_box':[10,10,70,30]}]}]}}
    api._sessions['retry-test']={'original_path':str(path),'htr_result':deepcopy(previous),'eval_result':{'old':True},
                                 'script_evaluation':{'old':True},'status':'recognized'}
    yield api._sessions['retry-test'],previous
    api._sessions.pop('retry-test',None)


def test_force_bypasses_cache_and_invalidates_old_scores(session,monkeypatch):
    state,previous=session
    called=[]
    def reader(value,enhanced=False):
        called.append(enhanced)
        return HTRResult('1. C',[RecognizedLine(1,'1. C',.9)],.9,
                         {'ocr_version':'local-ensemble-v9','recognition_mode':'enhanced'})
    monkeypatch.setattr(api,'_recognize_demo_session',reader)
    client=TestClient(api.app)
    assert client.post('/api/recognize/retry-test').json()['cached']
    assert not called
    response=client.post('/api/recognize/retry-test?force=true&enhanced=true')
    assert response.status_code==200
    assert response.json()['text']=='1. C' and not response.json()['cached']
    assert called==[True]
    assert state['recognition_history'][0]['full_text']==previous['full_text']
    assert state['recognition_history'][0]['previous_evaluation']=={'old':True}
    assert 'eval_result' not in state and 'script_evaluation' not in state


def test_failed_retry_preserves_previous_result_and_scores(session,monkeypatch):
    state,previous=session
    def broken(*args,**kwargs):raise RuntimeError('reader unavailable')
    monkeypatch.setattr(api,'_recognize_demo_session',broken)
    response=TestClient(api.app).post('/api/recognize/retry-test?force=true')
    assert response.status_code==500
    assert state['htr_result']==previous and state['eval_result']=={'old':True}
    assert state['recognition_in_progress'] is False


def test_retry_rejects_overlapping_work(session):
    state,_=session
    state['line_recheck_in_progress']=True
    assert TestClient(api.app).post('/api/recognize/retry-test?force=true').status_code==409


def test_line_recheck_uses_original_crop_without_overwriting_text(session,monkeypatch):
    state,previous=session
    crops=[]
    def reread(image):
        crops.append(image.shape)
        return {'readings':[{'source':'Handwriting','text':'1. C','support':.8}], 'needs_review':True}
    monkeypatch.setattr(api,'_get_htr',lambda:SimpleNamespace(reread_region=reread))
    response=TestClient(api.app).post('/api/recognize/retry-test/page/1/line/1/recheck')
    assert response.status_code==200 and response.json()['needs_review']
    assert crops==[(46,86,3)]
    assert state['htr_result']==previous
    assert not state['line_recheck_in_progress']
    assert TestClient(api.app).post('/api/recognize/retry-test/page/99/line/1/recheck').status_code==404


def test_failed_line_recheck_can_be_retried(session,monkeypatch):
    state,previous=session
    def broken():raise RuntimeError('model unavailable')
    monkeypatch.setattr(api,'_get_htr',broken)
    assert TestClient(api.app).post('/api/recognize/retry-test/page/1/line/1/recheck').status_code==503
    assert not state['line_recheck_in_progress'] and state['htr_result']==previous


def test_repeated_table_gutter_splits_cells_without_splitting_mcqs():
    rows=[]
    for number in range(3):
        image=np.full((40,1000,3),255,np.uint8)
        cv2.putText(image,'Structured data',(5,28),cv2.FONT_HERSHEY_SIMPLEX,.7,(0,0,0),2)
        cv2.putText(image,'Semi structured data',(600,28),cv2.FONT_HERSHEY_SIMPLEX,.7,(0,0,0),2)
        rows.append(LineRegion(number+1,(0,number*60,1000,40),image))
    split=split_column_regions(rows)
    assert len(split)==6
    assert all(region.bounding_box[2]<500 for region in split)
    compact=LineRegion(1,(0,0,100,40),np.full((40,100,3),255,np.uint8))
    assert split_column_regions([compact])==[compact]
    assert len(split_column_regions(rows[:1]))==1


def test_duplicate_number_alert_never_renumbers_the_reading():
    text='1. C\n2. A\n3. D\n4. B\n6. C\n6. C'
    issues=numbering_issues(text)
    assert any('6 appears 2 times' in issue for issue in issues)
    assert any('number(s) 5.' in issue for issue in issues)
    assert '5.' not in text


def test_blank_space_scan_specks_and_rules_are_not_handwriting():
    blank=np.full((100,500,3),255,np.uint8)
    assert not assess_line_ink(blank)['has_ink']
    specks=blank.copy()
    for x in range(20,450,40):cv2.circle(specks,(x,50),1,(0,0,0),-1)
    assert not assess_line_ink(specks)['has_ink']
    rules=blank.copy();cv2.line(rules,(0,40),(499,40),(0,0,0),2)
    assert not assess_line_ink(rules)['has_ink']
    letter=blank.copy();cv2.putText(letter,'C',(20,70),cv2.FONT_HERSHEY_SIMPLEX,1.5,(0,0,0),2)
    assert assess_line_ink(letter)['has_ink']


def test_blank_recheck_never_invokes_a_text_model():
    from htr.local_document import LocalDocumentPipeline
    pipeline=object.__new__(LocalDocumentPipeline)
    pipeline.read=lambda image:pytest.fail('Blank crops must not be sent to a recognition model')
    result=pipeline.reread_region(np.full((100,400,3),255,np.uint8))
    assert result['blank_region'] and not result['needs_review'] and result['readings']==[]


def test_segmentation_artifact_is_ignored_without_unclear_marker(monkeypatch):
    import htr.local_document as document
    pipeline=object.__new__(document.LocalDocumentPipeline)
    pipeline.recognizer=SimpleNamespace(display_name='test')
    pipeline.detector=None
    blank=np.full((40,200,3),255,np.uint8)
    pipeline.segmenter=SimpleNamespace(segment=lambda image:[LineRegion(1,(0,0,200,40),blank)])
    pipeline.read=lambda image:pytest.fail('Blank segmentation artifacts must never generate text')
    monkeypatch.setattr(document,'prepare_handwriting_page',lambda image:(image,{'has_foreground':True}))
    monkeypatch.setattr(document,'straighten',lambda image,detector:(image,0,np.array([[1,0,0],[0,1,0]],np.float64)))
    result=pipeline.recognize_image(blank)
    assert result.full_text=='' and result.metadata['quality_warnings']==[]
    assert result.metadata['ignored_regions'][0]['classification']=='blank_or_scan_artifact'


def test_blank_rescan_clears_old_unclear_result_without_assigning_zero(session,monkeypatch):
    state,_=session
    pipeline=SimpleNamespace(recognizer=SimpleNamespace(device='cpu'),recognize_path=lambda *args,**kwargs:
        HTRResult('',[],None,{'number_of_lines':0,'quality_warnings':[],'foreground':{'has_foreground':False}}))
    monkeypatch.setattr(api,'_get_htr',lambda:pipeline)
    response=TestClient(api.app).post('/api/recognize/retry-test?force=true')
    assert response.status_code==200
    assert response.json()['text']=='' and response.json()['metadata']['blank_document']
    assert 'eval_result' not in state
    evaluated=TestClient(api.app).post('/api/evaluate/retry-test',data={'rubric_json':'{}'})
    assert evaluated.status_code==422


def test_display_omits_internal_labels_but_review_is_still_required(session):
    state,_=session
    text='[Unclear page 2 line 16 — review scan]\n21. Actual candidate [Unclear page 2 line 17 — review scan]'
    state['htr_result']['full_text']=text
    state['htr_result']['lines']=[{'line_number':1,'text':text}]
    client=TestClient(api.app)
    response=client.post('/api/recognize/retry-test')
    assert response.json()['text']=='21. Actual candidate'
    assert state['htr_result']['full_text']==text
    assert client.post('/api/evaluate-script/retry-test',json={'text':'21. Actual candidate','questions':[]}).status_code==422
