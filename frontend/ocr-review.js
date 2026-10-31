/* Pure review-state helpers, shared by the browser and regression tests. */
(function(root) {
    function reconcile(current, previousReading, newReading) {
        const edited = current !== previousReading;
        return {text: edited ? current : newReading, candidate: newReading,
                previous: current, keptCorrections: edited};
    }
    const api = {reconcile};
    if (typeof module !== 'undefined' && module.exports) module.exports = api;
    if (root) root.EvaliSenseOCRReview = api;
})(typeof window !== 'undefined' ? window : null);
