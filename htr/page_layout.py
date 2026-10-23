"""Conservative foreground extraction without language or answer-key corrections."""
from __future__ import annotations
import cv2
import numpy as np

def prepare_handwriting_page(image: np.ndarray):
    """Keep foreground strokes; never contrast-enhance faint reverse-side writing.

    Returns original-size colour pixels on white, with diagnostic metadata.
    Faint-only pages are deferred, rather than interpreted as zero-score answers.
    """
    if not isinstance(image,np.ndarray) or image.size == 0:
        raise ValueError('A non-empty page image is required')
    if image.ndim==2:
        colour=cv2.cvtColor(image,cv2.COLOR_GRAY2BGR)
    elif image.ndim==3 and image.shape[2] in (3,4):
        colour=image[:,:,:3].copy()
    else: raise ValueError('Expected grayscale, BGR or BGRA page pixels')
    scale=min(1.,1800/colour.shape[1])
    small=cv2.resize(colour,None,fx=scale,fy=scale,interpolation=cv2.INTER_AREA) if scale<1 else colour.copy()
    gray=cv2.cvtColor(small,cv2.COLOR_BGR2GRAY)
    hsv=cv2.cvtColor(small,cv2.COLOR_BGR2HSV)
    chromatic=(hsv[:,:,1]>=60)&(hsv[:,:,2]<245)
    dark=gray<155
    # Saturated blue/red/green ink can be separated from grey show-through.
    # Refuse colour isolation on photographs or coloured paper backgrounds.
    colour_fraction=float(chromatic.mean())
    dark_fraction=float(dark.mean())
    use_colour=.0004 <= colour_fraction < .20 and np.count_nonzero(chromatic) >= np.count_nonzero(dark)*.6
    mask=(chromatic if use_colour else dark).astype(np.uint8)*255
    # Remove full-page rules before locating text. Dilate just the detected rule
    # width; original letter pixels outside that rule remain intact.
    rules=cv2.HoughLinesP(mask,1,np.pi/720,threshold=90,
        minLineLength=max(100,int(min(mask.shape)*.45)),maxLineGap=25)
    if rules is not None:
        for x1,y1,x2,y2 in rules.reshape(-1,4):
            dx,dy=abs(int(x2-x1)),abs(int(y2-y1))
            if dx > max(1,dy)*15 or dy > max(1,dx)*15:
                cv2.line(mask,(x1,y1),(x2,y2),0,9)
    count,labels,stats,_=cv2.connectedComponentsWithStats(mask,8)
    keep=np.zeros(count,np.uint8)
    if count>1:
        w,h,area=stats[1:,cv2.CC_STAT_WIDTH],stats[1:,cv2.CC_STAT_HEIGHT],stats[1:,cv2.CC_STAT_AREA]
        long_rule=((h > max(200,mask.shape[0]*.4))&(h > w*20))|((w > max(120,mask.shape[1]*.2))&(w > h*20))
        keep[1:]=((area>=4)&~long_rule).astype(np.uint8)*255
    mask=keep[labels]
    foreground_pixels=int(np.count_nonzero(mask))
    has_foreground=foreground_pixels>=max(35,int(mask.size*.00005))
    # Allow a small fringe so anti-aliased pen edges retain their original colour.
    mask=cv2.dilate(mask,np.ones((3,3),np.uint8))
    mask=cv2.resize(mask,(colour.shape[1],colour.shape[0]),interpolation=cv2.INTER_NEAREST)
    cleaned=np.full_like(colour,255)
    cleaned[mask>0]=colour[mask>0]
    metadata={'foreground_mode':'coloured_ink' if use_colour else 'dark_ink',
        'foreground_pixels':foreground_pixels,'has_foreground':has_foreground,
        'page_warning':None if has_foreground else 'No strong foreground writing detected. This may be blank, faint writing, or reverse-side show-through; inspect the original page.'}
    return cleaned,metadata
