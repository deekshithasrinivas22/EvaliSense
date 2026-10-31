const test=require('node:test');
const assert=require('node:assert/strict');
const {reconcile}=require('../frontend/ocr-review.js');
const {cleanRecognition}=require('../frontend/ocr-review.js');

test('fresh OCR replaces an unedited automatic reading and retains a restore copy',()=>{
    const result=reconcile('1. B','1. B','1. C');
    assert.equal(result.text,'1. C');assert.equal(result.previous,'1. B');assert.equal(result.keptCorrections,false);
});
test('fresh OCR never overwrites examiner corrections',()=>{
    const result=reconcile('15. B — corrected from the scan','16. B','16. D');
    assert.equal(result.text,'15. B — corrected from the scan');
    assert.equal(result.candidate,'16. D');assert.equal(result.keptCorrections,true);
});
test('corrections typed while a retry is running are also retained',()=>{
    const result=reconcile('Current edited words','Earlier automatic text','New automatic words');
    assert.equal(result.text,'Current edited words');assert.equal(result.previous,'Current edited words');
});

test('blank review labels disappear without removing real candidate words or changing diagnostics',()=>{
    const original={text:'[Unclear page 2 line 16 — review scan]\n\n21. Real written words [Unclear page 2 line 17 — review scan]',
        lines:[{text:'[Unclear line 1 — review scan]'},{text:'21. Real written words [Unclear line 2 — review scan]'}],metadata:{needs_review:true}};
    const clean=cleanRecognition(original);
    assert.equal(clean.text,'21. Real written words');assert.equal(clean.lines.length,1);
    assert.equal(clean.lines[0].text,'21. Real written words');
    assert.equal(clean.metadata.needs_review,true);assert.match(original.text,/Unclear/);
});
