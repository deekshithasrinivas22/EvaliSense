"""Layout-aware retry helpers; no answer keys or inferred question digits."""
import re
from collections import Counter
import cv2
import numpy as np
from .local_segmenter import LineRegion


def split_column_regions(regions):
    """Separate side-by-side text only with repeated gutter evidence.

    A normal word space, or the gap between an MCQ number and option, must
    never split a line. Keep row order so table relationships remain visible.
    """
    candidates = []
    for index, region in enumerate(regions):
        image = region.image
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
        h, w = gray.shape
        if w < h * 10:
            continue
        active = (gray < 180).sum(axis=0) > max(1, h * .02)
        changes = np.diff(np.r_[True, active, True].astype(int))
        for start, end in zip(np.where(changes == -1)[0], np.where(changes == 1)[0]):
            if (end - start >= max(h * 1.8, w * .08) and start > w * .1 and end < w * .9
                    and w * .2 < (start + end) / 2 < w * .8):
                candidates.append((index, region.bounding_box[0] + (start + end) // 2))
    output = []
    for index, region in enumerate(regions):
        x,y,w,h = region.bounding_box
        cuts = [cut for row,cut in candidates if row == index and
                sum(abs(other-cut) <= max(h*2,30) for _,other in candidates) >= 3]
        if not cuts:
            output.append(region)
            continue
        cut = min(cuts, key=lambda value: abs(value - (x+w/2))) - x
        for left,right in ((0,cut),(cut,w)):
            crop = region.image[:,left:right]
            gray = cv2.cvtColor(crop,cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop
            ys,xs = np.where(gray < 180)
            if len(xs) < 15:
                continue
            a,b = max(0,int(xs.min())-3), min(crop.shape[1],int(xs.max())+4)
            output.append(LineRegion(0,(x+left+a,y,b-a,h),crop[:,a:b].copy()))
    for number,region in enumerate(output,1):
        region.line_number = number
    return output


def numbering_issues(text):
    """Flag repeated readable numbers; never rewrite or fill a missing digit."""
    entries = []
    for line in text.splitlines():
        match = re.fullmatch(r'\s*(\d{1,3})[.):]?\s+([A-H])[.)]?(?:\s+\[Unclear.*)?\s*',line,re.I)
        if match:
            entries.append(int(match.group(1)))
    issues = [f'Answer number {number} appears {count} times. Compare its original crops before grading.'
              for number,count in Counter(entries).items() if count > 1]
    if len(entries) >= 5:
        gaps = sorted(set(range(min(entries),max(entries)+1)) - set(entries))
        if gaps:
            issues.append('No readable compact entry for number(s) ' + ', '.join(map(str,gaps[:30])) +
                          '. These may be unanswered or misread; check the scan. No numbers were filled in.')
    return issues
