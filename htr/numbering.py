"""Read answer-number evidence without sequence completion or letter substitution."""
import re
from .hybrid_recognizer import optical_mcq


def question_number(text):
    match=re.match(r'^\s*(?:(?:Q(?:uestion)?|Ans(?:wer)?)\s*[.:-]?\s*)?\(?(\d{1,3})\)?(?:\s*[.):\-]\s*|\s+|$)(?=[A-Za-z]|$)',text,re.I)
    return int(match.group(1)) if match and int(match.group(1))>0 else None


def corroborated_number(optical_readings, handwriting_text, handwriting_support):
    """Require the independent handwriting reader to agree with optical pixels."""
    handwritten=question_number(handwriting_text)
    if handwritten is None or (handwriting_support or 0)<.7:
        return None
    for text,support in optical_readings:
        if (support or 0)>=.7 and question_number(text)==handwritten:
            return handwritten
    return None


def page_label(text, box, page_shape, before_first_answer=False):
    normalized=text.casefold().strip(' .:\t\n')
    x,y,w,h=box
    if before_first_answer and y<page_shape[0]*.3 and normalized in {'solution','solutions','answer sheet','answer script','answers'}:
        return True
    return y>page_shape[0]*.92 and bool(re.fullmatch(r'(?:page\s*)?\(?\d{1,3}\)?(?:\s*(?:/|of)\s*(?:total\s*)?\d{1,3})?\.?',text.strip(),re.I))


def corroborated_mcq(readings, handwriting_text, handwriting_support):
    independent=optical_mcq(handwriting_text)
    if not independent or (handwriting_support or 0)<.8:return None
    return next((result for text,support in readings if support>=.8 and
                 (result:=optical_mcq(text))==independent),None)


def compact_candidate(text, support, needs_review):
    """Keep a readable number when its clipped option is not A-H; never invent it."""
    entry=optical_mcq(text)
    if entry and not (needs_review and support<.5):return text
    number=question_number(text)
    return f'{number}.' if number else ''
