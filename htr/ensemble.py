"""Independent local optical readers; reference answers are never inputs."""
import re
import cv2
import numpy as np

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
    match=re.match(r'^\s*(\d{1,3})[ .:)]*([A-Za-z])',detail['text'])
    if not match:return None
    words=detail['words']
    alpha=next((word for word in words if word['text'].isalpha()),None)
    number=next((word for word in words if word['text'].isdigit()),None)
    if not alpha or not number:return None
    cut=int(max(0,alpha['x']-image.shape[0]*.12))
    if cut<5 or cut>image.shape[1]*.2:return None
    return number['text'],number['support'],image[:,cut:].copy()

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
    pieces=[optical_details(pipeline,crop) for crop in crop_chunks(image)]
    chunk_text=' '.join(piece['text'] for piece in pieces);chunk_words=[word for piece in pieces for word in piece['words']]
    candidate=handwriting.text
    if prefix:candidate=f'{prefix[0]}. '+candidate
    confidence=handwriting.confidence or 0.
    reason=None
    if confidence<.75:
        candidate=whole['text']
        # A truncated full-line read can be recovered by smaller optical crops.
        if len(chunk_text)>len(candidate)*1.4 and min((piece['mean'] for piece in pieces),default=0)>.85:candidate=chunk_text
        reason='The local readers could not confirm this line. Compare the candidate with the scan.'
    # Two crops of the same optical model are correlated evidence. Do not
    # let their shared spelling errors overrule the handwriting reader.
    if confidence<.85 and not reason:
        reason='The handwriting reading has limited support; compare it with the original image.'
    if prefix and prefix[1]<.8:reason='The written-answer question number needs confirmation.'
    if has_crossout(image):reason='This line contains crossed-out or ruled-through text. Confirm which words belong to the final answer.'
    if not candidate.strip():reason='No reliable text was recovered; inspect the original line.'
    return {'text':candidate,'confidence':confidence,'reason':reason,'alternatives':{'optical_line':whole['text'],'optical_chunks':chunk_text,'handwriting':handwriting.text}}
