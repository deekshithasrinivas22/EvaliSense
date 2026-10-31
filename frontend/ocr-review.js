/* Pure review-state helpers, shared by the browser and regression tests. */
(function(root) {
    function reconcile(current, previousReading, newReading) {
        const edited = current !== previousReading;
        return {text: edited ? current : newReading, candidate: newReading,
                previous: current, keptCorrections: edited};
    }
    function cleanText(text) {
        return String(text || '').replace(/\[Unclear(?: page \d+)? line \d+[^\]\r\n]*\]/g,'')
            .split('\n').map(line=>line.trimEnd()).join('\n').replace(/\n{3,}/g,'\n\n').trim();
    }
    function cleanRecognition(data) {
        return {...data,text:cleanText(data.text),lines:(data.lines || []).map(line=>({...line,text:cleanText(line.text)})).filter(line=>line.text)};
    }
    const api = {reconcile,cleanText,cleanRecognition};
    if (typeof module !== 'undefined' && module.exports) module.exports = api;
    if (root) root.EvaliSenseOCRReview = api;
})(typeof window !== 'undefined' ? window : null);
