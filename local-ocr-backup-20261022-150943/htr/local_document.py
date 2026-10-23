from pathlib import Path
import time, re
from types import SimpleNamespace
import cv2
import numpy as np
import onnxruntime as ort
from rapidocr import RapidOCR, LangDet, ModelType, OCRVersion
from .local_segmenter import HandwritingLineSegmenter
from .page_layout import prepare_handwriting_page
from .pipeline import HTRPipeline
from .result import HTRResult, RecognizedLine

def fields(image):
    gray=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY);mask=(gray<210).astype(np.uint8)
    count,labels,stats,_=cv2.connectedComponentsWithStats(mask,8)
    parts=[]
    for x,y,w,h,area in stats[1:]:
        if h>max(5,image.shape[0]*.25) and area>8:parts.append([int(x),int(y),int(x+w),int(y+h)])
    parts.sort();groups=[]
    for p in parts:
        if groups and p[0]<=groups[-1][2]:
            g=groups[-1];g[:]=[min(g[0],p[0]),min(g[1],p[1]),max(g[2],p[2]),max(g[3],p[3])]
        else:groups.append(p)
    if len(groups)<2:return None
    letter=groups[-1];number=[min(g[0] for g in groups[:-1]),min(g[1] for g in groups[:-1]),max(g[2] for g in groups[:-1]),max(g[3] for g in groups[:-1])]
    def crop(b):
        x1,y1,x2,y2=b
        return cv2.copyMakeBorder(image[max(0,y1-2):y2+2,max(0,x1-2):x2+2],4,4,4,4,cv2.BORDER_CONSTANT,value=(255,255,255))
    return crop(number),crop(letter)

def straighten(image, detector):
    found=detector(image,use_rec=False,use_cls=False);angles=[]
    if found.boxes is not None:
        for b in found.boxes:
            dx,dy=b[1]-b[0];height=max(np.linalg.norm(b[0]-b[3]),1)
            angle=np.degrees(np.arctan2(dy,dx))
            if dx/height>3 and abs(angle)<10:angles.append((float(angle),float(min(dx,500))))
    angle=0
    if len(angles)>=4:
        angles.sort();total=sum(w for a,w in angles);cumulative=0
        for a,w in angles:
            cumulative+=w
            if cumulative>=total/2:angle=a;break
    if abs(angle)<.25:return image,0,np.array([[1,0,0],[0,1,0]],np.float64)
    h,w=image.shape[:2];matrix=cv2.getRotationMatrix2D((w/2,h/2),angle,1)
    sine,cosine=abs(matrix[0,1]),abs(matrix[0,0]);nw=int(np.ceil(w*cosine+h*sine));nh=int(np.ceil(h*cosine+w*sine))
    matrix[0,2]+=(nw-w)/2;matrix[1,2]+=(nh-h)/2
    return cv2.warpAffine(image,matrix,(nw,nh),borderValue=(255,255,255)),angle,cv2.invertAffineTransform(matrix)

class LocalDocumentPipeline(HTRPipeline):
    """Offline optical recognition. No reference answers or network requests."""
    def __init__(self, model_dir=None):
        directory=Path(model_dir) if model_dir else Path(__file__).resolve().parents[1]/'data/models/handwriting'
        for name in ('rec.onnx','det.onnx'):
            if not (directory/name).is_file():
                raise RuntimeError(f'Local OCR model missing: {directory/name}')
        options=ort.SessionOptions()
        options.intra_op_num_threads=4;options.inter_op_num_threads=1
        options.graph_optimization_level=ort.GraphOptimizationLevel.ORT_ENABLE_BASIC
        self.model=ort.InferenceSession(str(directory/'rec.onnx'),sess_options=options,providers=['CPUExecutionProvider'])
        self.chars=['blank']+self.model.get_modelmeta().custom_metadata_map['character'].splitlines()+[' ']
        self.detector=RapidOCR(params={'Det.model_path':str(directory/'det.onnx'),'Det.lang_type':LangDet.CH,
            'Det.model_type':ModelType.MOBILE,'Det.ocr_version':OCRVersion.PPOCRV5,'Det.limit_side_len':1600,
            'EngineConfig.onnxruntime.intra_op_num_threads':4,'EngineConfig.onnxruntime.inter_op_num_threads':1})
        self.segmenter=HandwritingLineSegmenter(minimum_gap=5)
        self.recognizer=SimpleNamespace(device='cpu',display_name='Local PP-OCRv5 with separate MCQ fields')

    def read(self,image,allowed=None):
        h,w=image.shape[:2];width=max(8,int(np.ceil(w*48/h)))
        im=cv2.resize(image,(width,48)).astype(np.float32)/127.5-1
        padded=np.zeros((48,max(320,width),3),np.float32);padded[:,:width]=im
        probs=self.model.run(None,{'x':padded.transpose(2,0,1)[None]})[0][0]
        if allowed:
            ids=np.array([i for i,c in enumerate(self.chars) if i==0 or c in allowed])
            chosen=ids[probs[:,ids].argmax(-1)]
        else:chosen=probs.argmax(-1)
        text=[];support=[];prev=-1
        for t,c in enumerate(chosen):
            if c and c!=prev:text.append(self.chars[c]);support.append(float(probs[t,c]))
            prev=c
        return ''.join(text).strip(),float(np.mean(support)) if support else 0.,min(support) if support else 0.

    @staticmethod
    def source_box(box,inverse,shape):
        x,y,w,h=box
        corners=np.array([[x,y],[x+w,y],[x+w,y+h],[x,y+h]],np.float64)
        points=corners@inverse[:,:2].T+inverse[:,2]
        low=np.maximum(np.floor(points.min(axis=0)).astype(int),0)
        high=np.minimum(np.ceil(points.max(axis=0)).astype(int),[shape[1],shape[0]])
        return (int(low[0]),int(low[1]),max(1,int(high[0]-low[0])),max(1,int(high[1]-low[1])))

    def recognize_image(self,image,debug_dir=None,on_progress=None):
        started=time.perf_counter()
        def report(phase,n=0,total=0):
            if on_progress:on_progress({'phase':phase,'completed_lines':n,'total_lines':total,'elapsed_seconds':round(time.perf_counter()-started,2)})
        report('segmenting')
        prepared,foreground=prepare_handwriting_page(image)
        if not foreground['has_foreground']:
            report('completed')
            return HTRResult('',[],None,{'model':self.recognizer.display_name,'foreground':foreground,'quality_warnings':[], 'regions':[],'number_of_lines':0})
        prepared,angle,inverse=straighten(prepared,self.detector)
        regions=self.segmenter.segment(prepared);candidates=[]
        for i,region in enumerate(regions):
            text,mean,minimum=self.read(region.image)
            candidates.append({'text':text,'mean':mean,'minimum':minimum})
            report('recognizing',i+1,len(regions))
        # A compact answer column must contain several short optical entries.
        # Do not reinterpret prose or individual bullet points as MCQs.
        short=[i for i,r in enumerate(regions) if r.bounding_box[0]<prepared.shape[1]*.4
               and r.bounding_box[2]/max(1,r.bounding_box[3])<5
               and re.fullmatch(r'[0-9IlOSlo., :()\-]*[A-Ha-h][. )]*',candidates[i]['text'])]
        clustered=set()
        for i in short:
            x,y,w,h=regions[i].bounding_box
            neighbours=[j for j in short if abs(regions[j].bounding_box[0]-x)<max(w,80)
                        and abs(regions[j].bounding_box[1]-y)<max(h*12,300)]
            if len(neighbours)>=4:clustered.update(neighbours)
        lines=[];warnings=[];records=[]
        for i,(region,candidate) in enumerate(zip(regions,candidates)):
            text=candidate['text'];support=candidate['mean'];reason=None;alternatives={'whole_line':text}
            pair=fields(region.image) if i in clustered else None
            if pair:
                number,ns,nmin=self.read(pair[0],set('0123456789'))
                option,os,omin=self.read(pair[1],set('ABCDEFGHabcdefgh'))
                if number and len(number)<=3 and len(option)==1:
                    text=f'{number}. {option.upper()}';support=min(ns,os)
                    if min(nmin,omin)<.80:reason='The question number or option has weak visual support. Confirm the candidate against the scan.'
                    alternatives.update(number_support=ns,option_support=os)
                else:reason='The short answer fields could not be separated reliably.'
            elif candidate['mean']<.90 or candidate['minimum']<.35 or not text:
                reason='Some handwriting is incomplete or uncertain. Compare this candidate with the original line.'
            box=self.source_box(region.bounding_box,inverse,image.shape)
            # Keep footer text in the audit record, but not inside the last answer.
            footer=bool(region.bounding_box[1]>prepared.shape[0]*.93 and re.fullmatch(r'/?\d*\s*/?\s*total\s*\d+',text,re.I))
            records.append({'line_number':i+1,'text':text,'confidence':support,'bounding_box':box,
                            'alternatives':alternatives,'review_reason':reason,'excluded_footer':footer})
            if footer:continue
            if reason:
                warnings.append({'line_number':i+1,'raw_text':text,'bounding_box':box,'reason':reason})
                text=f'[Unclear line {i+1} — review scan]'
            lines.append(RecognizedLine(i+1,text,support,box))
        report('completed',len(regions),len(regions))
        return HTRResult('\n'.join(line.text for line in lines),lines,None,{
            'model':self.recognizer.display_name,'foreground':foreground,'regions':records,'quality_warnings':warnings,
            'number_of_lines':len(lines),'deskew_degrees':angle,'confidence_note':'Optical support is not a calibrated accuracy probability.',
            'elapsed_seconds':round(time.perf_counter()-started,3)})
