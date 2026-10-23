"""Independent optical readings for short MCQs, without reference-answer hints."""
from pathlib import Path
import hashlib
import re
from threading import Lock
from .recognizer import HandwritingRecognizer

MCQ=re.compile(r'^\s*(\d{1,3})\s*[.):\-]?\s*([A-H])\s*[.)]?\s*$',re.I)
def optical_mcq(text):
    match=MCQ.fullmatch(text)
    return (int(match.group(1)),match.group(2).upper()) if match else None

class HybridHandwritingRecognizer(HandwritingRecognizer):
    """TrOCR for handwriting, with an independent PP-OCRv5 line reading.

    Scores are model-specific confidence signals, not calibrated probabilities.
    Conflicting MCQ readings are deferred instead of guessing a digit or option.
    """
    def __init__(self,*args,secondary_model_path=None,**kwargs):
        super().__init__(*args,**kwargs)
        self.secondary_model_path=Path(secondary_model_path) if secondary_model_path else Path(__file__).resolve().parents[1]/'data/models/handwriting/rec.onnx'
        self._secondary=None
        self._secondary_lock=Lock()
        self.display_name='TrOCR + PP-OCRv5 verification'

    def _secondary_readings(self,images):
        from rapidocr import RapidOCR,LangRec,ModelType,OCRVersion
        if not self.secondary_model_path.is_file():
            raise RuntimeError('Missing local PP-OCRv5 model. Install data/models/handwriting/rec.onnx.')
        with self._secondary_lock:
            if self._secondary is None:
                expected='c3461add59bb4323ecba96a492ab75e06dda42467c9e3d0c18db5d1d21924be8'
                if hashlib.sha256(self.secondary_model_path.read_bytes()).hexdigest()!=expected:
                    raise RuntimeError('The local verification model checksum does not match the tested model.')
                self._secondary=RapidOCR(params={'Rec.model_path':str(self.secondary_model_path),
                    'Rec.lang_type':LangRec.EN,'Rec.model_type':ModelType.MOBILE,'Rec.ocr_version':OCRVersion.PPOCRV5,
                    'EngineConfig.onnxruntime.intra_op_num_threads':4,'EngineConfig.onnxruntime.inter_op_num_threads':1})
            return self._secondary.recognize_txt(images)

    def recognize_batch(self,line_images,line_numbers=None,bounding_boxes=None):
        images=list(line_images)
        if not images:return []
        primary=super().recognize_batch(images,line_numbers,bounding_boxes)
        try: secondary=self._secondary_readings(images)
        except Exception as error:
            # Keep an explicit diagnostic rather than claiming independent verification.
            for line in primary: line.secondary_error=str(error)
            return primary
        for line,alt,score in zip(primary,secondary.txts,secondary.scores):
            line.ocr_alternatives={'trocr':line.text,'ppocr':str(alt),'ppocr_confidence':float(score)}
            a,b=optical_mcq(line.text),optical_mcq(str(alt))
            line.ocr_verified=bool(a and b and a==b)
            if a and b and a!=b:
                line.review_reason='The OCR engines disagree on this answer number or option.'
            elif not a and b and float(score)>=.8:
                line.text=str(alt).strip()
                line.confidence=float(score)
                line.ocr_source='ppocr'
                line.review_reason='Only the second recognizer could read this MCQ number and option. Check its crop.'
            elif not a and not b and re.fullmatch(r'\s*[0-9Il|SOs]+\s*[.):\-]\s*[A-H0-9][.)]?\s*',line.text,re.I):
                line.review_reason='This looks like an MCQ entry, but its number or option is ambiguous.'
            # No I->1, S->5 or O->C substitution, no use of the official key.
        return primary
