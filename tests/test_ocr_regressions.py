"""Safety and layout regressions without downloading recognition models."""
import json
import cv2
import numpy as np
import pytest
import jwt

from htr.ensemble import readings_agree
from htr.page_layout import prepare_handwriting_page
from htr.local_segmenter import HandwritingLineSegmenter
from api.script_evaluation import evaluate_script
from api.auth.security import decode_access_token
from evaluation import Rubric


def test_printed_letter_baselines_are_not_page_rules():
    image = np.full((400, 800, 3), 255, np.uint8)
    cv2.putText(image, '1. State Newton second law of motion [5 Marks]',
                (30,150), cv2.FONT_HERSHEY_SIMPLEX, .7, (0,0,0), 2)
    prepared, metadata = prepare_handwriting_page(image)
    assert metadata['has_foreground']
    assert np.count_nonzero(prepared < 155) > 1500


def test_rule_remnant_does_not_widen_mcq_crop():
    image = np.full((150,1000,3),255,np.uint8)
    cv2.putText(image,'1. D',(30,85),cv2.FONT_HERSHEY_SIMPLEX,1,(0,0,0),2)
    cv2.line(image,(720,62),(999,65),(0,0,0),2)
    regions = HandwritingLineSegmenter().segment(image)
    assert regions
    assert regions[0].bounding_box[2] < 150


def test_agreement_never_changes_digits_or_words():
    assert readings_agree('Photosynthesis converts light', 'photosynthesis converts light', .6, .95)
    assert not readings_agree('14. C', '4. C', .9, .99)
    assert not readings_agree('incorrect data', 'correct data', .9, .99)
    assert not readings_agree('word', 'word', .2, .99)


def test_uncertain_mcq_and_missing_answers_are_not_zero():
    questions = [dict(question_number=i, question_type='MCQ', max_marks=1,
                      reference_answer='B',correct_option='B') for i in (1,2,3)]
    result = evaluate_script('1. B\n2. D [Unclear page 1 line 2 — review scan]', questions,
                             lambda: pytest.fail('MCQs must not load semantic models'))
    assert [row['score'] for row in result['results']] == [1, None, None]


def test_unsigned_or_wrongly_signed_tokens_cannot_authorize_admin():
    for key, algorithm in [('', 'none'), ('attacker-controlled', 'HS256')]:
        token = jwt.encode({'sub':'1', 'email':'hod@evalisense.edu', 'aud':'evalisense'},key,algorithm=algorithm)
        assert decode_access_token(token) is None


def test_firebase_signature_audience_expiry_and_verified_email(monkeypatch):
    from cryptography.hazmat.primitives.asymmetric import rsa
    from types import SimpleNamespace
    import time
    from api.auth import security
    private = rsa.generate_private_key(public_exponent=65537,key_size=2048)
    monkeypatch.setattr(security._firebase_keys,'get_signing_key_from_jwt',
                        lambda token: SimpleNamespace(key=private.public_key()))
    payload={'sub':'teacher-uid','email':'teacher@evalisense.edu','email_verified':True,
             'aud':'evalisense','iss':'https://securetoken.google.com/evalisense',
             'iat':int(time.time()),'exp':int(time.time())+120}
    assert decode_access_token(jwt.encode(payload,private,algorithm='RS256'))['is_firebase']
    for altered in [{'aud':'other-project'},{'email_verified':False},{'exp':1},
                    {'iss':'https://attacker.invalid'}]:
        assert decode_access_token(jwt.encode({**payload,**altered},private,algorithm='RS256')) is None


@pytest.mark.parametrize('marks',[float('nan'),float('inf'),-1])
def test_nonfinite_and_negative_rubric_marks_rejected(marks):
    rubric = Rubric.from_dict({'question':'Define data', 'max_marks':5,
        'criteria':[{'id':'c1','description':'Definition','marks':marks}]})
    assert rubric.validate()
