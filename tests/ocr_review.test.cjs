const test=require('node:test');
const assert=require('node:assert/strict');
const {reconcile}=require('../frontend/ocr-review.js');

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
