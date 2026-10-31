import cv2
import numpy as np
from types import SimpleNamespace
from htr.numbering import question_number, corroborated_number, corroborated_mcq, page_label, compact_candidate
from htr.review import split_column_regions
from htr.local_segmenter import LineRegion
import htr.ensemble as ensemble


def test_number_parser_preserves_digits_and_rejects_split_or_ambiguous_digits():
    assert question_number('Question 26: Define data')==26
    assert question_number('(31) Explain clusters')==31
    assert question_number('16.C')==16
    assert question_number('2. 6. Define data') is None
    assert question_number('9O.C') is None
    assert question_number('IS. B') is None


def test_number_correction_needs_independent_visual_agreement():
    assert corroborated_number([('2. 6. Define',.9),('26.',.9)],'26. Define',.95)==26
    assert corroborated_number([('26.',.9)],'28. Define',.95) is None
    assert corroborated_number([('26.',.4)],'26. Define',.95) is None


def test_mcq_15_is_not_forced_to_16_when_independent_readers_agree():
    assert corroborated_mcq([('16. C',.9),('15. C',.86)],'15. c',.94)==(15,'C')
    assert corroborated_mcq([('15. A',.9)],'15. C',.94) is None
    assert corroborated_mcq([('15. C',.4)],'15. C',.94) is None
    assert compact_candidate('20.r.',.7,True)=='20.'
    assert compact_candidate('18. C',.09,True)=='18.'
    assert compact_candidate('9O.C',.3,True)==''


def test_solution_heading_and_page_count_are_excluded_only_in_page_furniture_positions():
    assert page_label('Solution .',(300,100,100,25),(1000,800),True)
    assert not page_label('Solution',(100,400,100,25),(1000,800),False)
    assert page_label('(3)',(750,970,30,20),(1000,800))
    assert not page_label('3. C',(100,970,50,20),(1000,800))
    assert not page_label('31. Data',(100,100,200,30),(1000,800))


def test_footer_does_not_join_the_last_mcq_even_on_a_single_row():
    image=np.full((50,1500,3),255,np.uint8)
    cv2.putText(image,'20. C',(5,35),cv2.FONT_HERSHEY_SIMPLEX,.8,(0,0,0),2)
    cv2.putText(image,'(1)',(1430,35),cv2.FONT_HERSHEY_SIMPLEX,.8,(0,0,0),2)
    rows=split_column_regions([LineRegion(1,(100,1950,1500,50),image)],(2025,1700))
    assert len(rows)==2
    assert rows[0].bounding_box[2]<150 and rows[1].bounding_box[0]>1500


def test_written_split_number_is_recovered_from_crop_agreement(monkeypatch):
    detail={'text':'2. 6. Define data','mean':.95,'words':[
        {'text':'2','start':0,'end':1,'support':.95,'x':0},
        {'text':'6','start':3,'end':4,'support':.95,'x':20},
        {'text':'Define','start':6,'end':12,'support':.95,'x':100}]}
    monkeypatch.setattr(ensemble,'optical_details',lambda *args:detail)
    monkeypatch.setattr(ensemble,'has_crossout',lambda *args:False)
    readings=iter([SimpleNamespace(text='Define data',confidence=.95),SimpleNamespace(text='26. Define data',confidence=.95)])
    recognizer=SimpleNamespace(recognize=lambda *args:next(readings))
    pipeline=SimpleNamespace(read=lambda image:('26.',.95,.9))
    result=ensemble.recognize_written(pipeline,recognizer,np.full((40,1200,3),255,np.uint8))
    assert result['text']=='26. Define data'


def test_margin_gap_does_not_cut_a_digit_misread_as_g_into_the_answer():
    image=np.full((60,1200,3),255,np.uint8)
    cv2.putText(image,'26.',(5,40),cv2.FONT_HERSHEY_SIMPLEX,1,(0,0,0),2)
    cv2.putText(image,'Define data',(170,40),cv2.FONT_HERSHEY_SIMPLEX,1,(0,0,0),2)
    detail={'text':'2G. Define data','mean':.9,'words':[
        {'text':'2','start':0,'end':1,'support':.9,'x':5},
        {'text':'G','start':1,'end':2,'support':.9,'x':25},
        {'text':'Define','start':4,'end':10,'support':.9,'x':170}]}
    prefix=ensemble.prefix_details(detail,image)
    assert prefix and prefix[0] is None
    assert prefix[4]=='Define data'
    assert 70<prefix[3].shape[1]<170
