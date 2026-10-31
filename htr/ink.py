"""Conservative pixel checks before invoking a generative handwriting reader."""
import cv2
import numpy as np


def assess_line_ink(image):
    """Exclude empty pixels, isolated scan specks and long thin ruling only.

    A single substantive glyph remains readable input. This is not a test of
    whether the handwriting forms a word and never depends on OCR output.
    """
    if not isinstance(image,np.ndarray) or image.size == 0:
        return {'has_ink':False,'ink_pixels':0,'reason':'Empty image crop.'}
    gray=cv2.cvtColor(image[:,:,:3],cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    mask=(gray < 200).astype(np.uint8)
    _,_,stats,_=cv2.connectedComponentsWithStats(mask,8)
    pixels=0
    for x,y,w,h,area in stats[1:]:
        ruling=(w>=40 and w>h*12) or (h>=40 and h>w*20)
        if not ruling and area>=8 and h>=5 and w>=2:
            pixels+=int(area)
    return {'has_ink':pixels>=24,'ink_pixels':pixels,
            'reason':None if pixels>=24 else 'No substantive handwriting strokes; blank pixels, scan specks or ruling only.'}
