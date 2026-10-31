"""Independent local optical readers; reference answers are never inputs."""
import re
import cv2
import numpy as np
from .numbering import question_number, corroborated_number

def readings_agree(handwriting, optical, handwriting_support, optical_support):
    """Independent readers may corroborate a line, never repair its spelling.

    Compare words, numeric values and mathematical operators. Cosmetic sentence
    punctuation can differ, but conflicting words, digits or signs cannot.
    """
    normalize = lambda text: re.findall(r'\d+(?:[.,]\d+)*|[^\W\d_]+|[=+<>/%-]', text.casefold())
    return bool(normalize(handwriting) and normalize(handwriting) == normalize(optical)
                and handwriting_support >= .5 and optical_support >= .8)

def optical_details(pipeline,image):
    h,w=image.shape[:2];width=max(8,int(np.ceil(w*48/h)))
    data=cv2.resize(image,(width,48)).astype(np.float32)/127.5-1
    padded=np.zeros((48,max(320,width),3),np.float32);padded[:,:width]=data
    probs=pipeline.model.run(None,{'x':padded.transpose(2,0,1)[None]})[0][0]
    ids=probs.argmax(-1);letters=[];supports=[];positions=[];previous=-1
    for t,c in enumerate(ids):
        if c and c!=previous:
            letters.append(pipeline.chars[c]);supports.append(float(probs[t,c]));positions.append(max(0,(t-.5)*padded.shape[1]/len(ids)*h/48))
        previous=c
    text=''.join(letters)
    words=[]
    for m in re.finditer(r'[A-Za-z]+|[0-9]+',text):
        words.append({'text':m.group(),'start':m.start(),'end':m.end(),'support':min(supports[m.start():m.end()]),'x':positions[m.start()]})
    return {'text':text.strip(),'mean':float(np.mean(supports)) if supports else 0.,'words':words}

def prefix_details(detail,image):
    # Locate the margin gap from pixels, rather than treating a misread digit
    # such as the G in "2G." as the start of the written answer.
    if re.match(r'^\s*\d',detail['text']):
        gray=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY)
        ink=(gray<200).astype(np.uint8)*255
        vertical=cv2.morphologyEx(ink,cv2.MORPH_OPEN,np.ones((max(20,int(image.shape[0]*.75)),1),np.uint8))
        ink=cv2.subtract(ink,vertical)
        active=(ink>0).sum(axis=0)>1
        changes=np.diff(np.r_[True,active,True].astype(int))
        gaps=[(a,b) for a,b in zip(np.where(changes==-1)[0],np.where(changes==1)[0])
              if a>3 and b<image.shape[1]*.25 and b-a>=max(8,image.shape[0]*.25)
              and np.count_nonzero(ink[:,:a])>=15]
        if gaps:
            start,end=max(gaps,key=lambda gap:gap[1]-gap[0])
            cut=max(start+1,end-3)
            alpha=next((word for word in detail['words'] if word['text'].isalpha() and word['x']>=cut-image.shape[0]*.3),None)
            if alpha:
                number_image=image[:,:cut].copy()
                number_image[vertical[:,:cut]>0]=255
                number=next((word for word in detail['words'] if word['text'].isdigit()),None)
                return question_number(detail['text']),number['support'] if number else 0,image[:,cut:].copy(),number_image,detail['text'][alpha['start']:]
    words=detail['words']
    alpha=next((word for word in words if word['text'].isalpha()),None)
    number=next((word for word in words if word['text'].isdigit()),None)
    if not alpha or not number:return None
    leading=detail['text'][:alpha['start']].strip()
    if not re.fullmatch(r'[\d\s.():\-]+',leading):return None
    cut=int(max(0,alpha['x']-image.shape[0]*.12))
    if cut<5 or cut>image.shape[1]*.2:return None
    return question_number(leading),number['support'],image[:,cut:].copy(),image[:,:cut].copy(),detail['text'][alpha['start']:]

def crop_chunks(image):
    gray=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY);ink=gray<200;h,w=gray.shape
    active=ink.sum(axis=0)>1;runs=[];last=0
    for x in range(1,w):
        if active[x] and not active[x-1] and x-last>max(4,h*.12):runs.append((last,x))
        if active[x-1] and not active[x]:last=x
    cuts=[0];target=h*4.5
    while w-cuts[-1]>target*1.4:
        choices=[(a+b)//2 for a,b in runs if cuts[-1]+target*.55<(a+b)//2<cuts[-1]+target*1.35]
        if not choices:break
        cuts.append(min(choices,key=lambda x:abs(x-cuts[-1]-target)))
    cuts.append(w);result=[]
    for a,b in zip(cuts,cuts[1:]):
        crop=image[:,a:b];mask=cv2.cvtColor(crop,cv2.COLOR_BGR2GRAY)<200
        _,_,stats,_=cv2.connectedComponentsWithStats(mask.astype(np.uint8),8)
        valid=stats[1:][stats[1:,cv2.CC_STAT_AREA]>10]
        if len(valid):
            y=max(0,int(valid[:,1].min())-2);yy=min(h,int((valid[:,1]+valid[:,3]).max())+2);crop=crop[y:yy]
        result.append(cv2.copyMakeBorder(crop,4,4,4,4,cv2.BORDER_CONSTANT,value=(255,255,255)))
    return result

def has_crossout(image):
    gray=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY);mask=(gray<170).astype(np.uint8)*255;h,w=gray.shape
    if w<500:return False
    found=cv2.HoughLinesP(mask,1,np.pi/180,threshold=max(30,int(w*.15)),minLineLength=max(150,int(w*.3)),maxLineGap=10)
    return bool(found is not None and any(abs(y2-y1)<max(3,h*.08) and h*.2<((y1+y2)/2)<h*.8 for x1,y1,x2,y2 in found.reshape(-1,4)))

def recognize_written(pipeline,recognizer,image):
    whole=optical_details(pipeline,image);prefix=prefix_details(whole,image);body=prefix[2] if prefix else image
    padded=cv2.copyMakeBorder(body,8,8,8,8,cv2.BORDER_CONSTANT,value=(255,255,255))
    handwriting=recognizer.recognize(padded)
    number_reading=None;whole_handwriting=None;number_handwriting=None;confirmed_number=None
    if prefix:
        number_reading=pipeline.read(prefix[3])
        whole_handwriting=recognizer.recognize(cv2.copyMakeBorder(image,8,8,8,8,cv2.BORDER_CONSTANT,value=(255,255,255)))
        confirmed_number=corroborated_number([(whole['text'],whole['mean']),number_reading[:2]],whole_handwriting.text,whole_handwriting.confidence)
        if confirmed_number is None:
            number_handwriting=recognizer.recognize(cv2.copyMakeBorder(prefix[3],8,8,8,8,cv2.BORDER_CONSTANT,value=(255,255,255)))
            confirmed_number=corroborated_number([(whole['text'],whole['mean']),number_reading[:2]],number_handwriting.text,number_handwriting.confidence)
    pieces=[optical_details(pipeline,crop) for crop in crop_chunks(image)]
    chunk_text=' '.join(piece['text'] for piece in pieces);chunk_words=[word for piece in pieces for word in piece['words']]
    candidate=handwriting.text
    if prefix and (confirmed_number or prefix[0]):candidate=f'{confirmed_number or prefix[0]}. '+candidate
    elif prefix:candidate=whole['text']
    confidence=handwriting.confidence or 0.
    reason=None
    agreement = readings_agree(handwriting.text, whole['text'] if not prefix else
                              prefix[4],
                              confidence, whole['mean'])
    if confidence<.75 and not agreement:
        candidate=whole['text']
        if prefix and confirmed_number:candidate=f'{confirmed_number}. '+prefix[4]
        # A truncated full-line read can be recovered by smaller optical crops.
        if len(chunk_text)>len(candidate)*1.4 and min((piece['mean'] for piece in pieces),default=0)>.85:candidate=chunk_text
        reason='The local readers could not confirm this line. Compare the candidate with the scan.'
    # Two crops of the same optical model are correlated evidence. Do not
    # let their shared spelling errors overrule the handwriting reader.
    if confidence<.85 and not reason and not agreement:
        reason='The handwriting reading has limited support; compare it with the original image.'
    if prefix and not confirmed_number and (prefix[0] is None or prefix[1]<.8 or
        (whole_handwriting and question_number(whole_handwriting.text) not in (None,prefix[0]))):
        reason='The written-answer question number needs confirmation.'
    if has_crossout(image):reason='This line contains crossed-out or ruled-through text. Confirm which words belong to the final answer.'
    if not candidate.strip():reason='No reliable text was recovered; inspect the original line.'
    if prefix and confirmed_number:
        candidate=re.sub(r'^\s*[\d\s.():\-]+(?=[A-Za-z])',f'{confirmed_number}. ',candidate)
    alternatives={'optical_line':whole['text'],'optical_chunks':chunk_text,'handwriting':handwriting.text}
    if number_reading:alternatives['number_crop']=number_reading[0]
    if whole_handwriting:alternatives['handwriting_numbered_line']=whole_handwriting.text
    if number_handwriting:alternatives['handwriting_number_crop']=number_handwriting.text
    return {'text':candidate,'confidence':confidence,'reason':reason,'alternatives':alternatives}
