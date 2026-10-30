const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const code = fs.readFileSync(path.join(__dirname, '../frontend/firebase-db.js'), 'utf8');
function browser(storage = new Map()) {
    const localStorage = {getItem: k => storage.get(k) || null, setItem: (k,v) => storage.set(k,v), removeItem: k => storage.delete(k)};
    const context = vm.createContext({window: {}, localStorage, console, setTimeout, clearTimeout});
    vm.runInContext(code, context);
    return {db: context.window.EvaliSenseDB, storage, localStorage};
}
const question = (number = 1) => ({question_number: number, question_text: 'Choose a colour', question_type: 'MCQ',
    options: [{label:'A',text:'Red'},{label:'B',text:'Blue'}],max_marks:2,criteria:[]});
const key = (exam, id='a'.repeat(32), option='B') => ({exam_id:exam,file_id:id,original_filename:'key.txt',
    answers:[{question_number:1,answer_type:'MCQ',correct_option:option,answer_text:''}]});

test('paper and key remain scoped to their examination and survive reload', async () => {
    const {db,storage} = browser();
    await db.importExamQuestions('exam1',[question()]);
    await db.importExamQuestions('exam2',[question()]);
    await db.saveExamAnswerKey('exam1',key('exam1'));
    const first = (await db.fsGetWhere('questions','exam_id','==','exam1'))[0];
    const second = (await db.fsGetWhere('questions','exam_id','==','exam2'))[0];
    assert.equal(first.correct_option,'B');
    assert.equal(second.reference_answer,'');
    assert.equal((await browser(storage).db.fsGetDoc('questions',first.id)).correct_option,'B');
});

test('new key versions preserve teacher edits and retire the previous key', async () => {
    const {db} = browser();
    await db.importExamQuestions('exam1',[question()]);
    await db.saveExamAnswerKey('exam1',key('exam1'));
    const q = (await db.fsGetWhere('questions','exam_id','==','exam1'))[0];
    await db.fsUpdateDoc('questions',q.id,{reference_answer:'Teacher correction',reference_source:'manual'});
    await db.saveExamAnswerKey('exam1',key('exam1','b'.repeat(32),'A'));
    assert.equal((await db.fsGetDoc('questions',q.id)).reference_answer,'Teacher correction');
    const versions = await db.fsGetWhere('answer_keys','exam_id','==','exam1');
    assert.equal(versions.filter(k=>k.is_active).length,1);
    assert.equal(versions.find(k=>k.is_active).version,2);
});

test('duplicate question numbers and cross-examination keys are rejected', async () => {
    const {db} = browser();
    await assert.rejects(db.importExamQuestions('exam1',[question(),question()]));
    await assert.rejects(db.saveExamAnswerKey('exam2',key('exam1')));
    assert.equal((await db.fsGetAll('questions')).length,0);
});

test('browser quota failure preserves the previous imported paper', async () => {
    const {db,localStorage} = browser();
    await db.importExamQuestions('exam1',[question()]);
    localStorage.setItem = () => {throw new Error('Quota exceeded');};
    await assert.rejects(db.importExamQuestions('exam1',[question(2)]));
    assert.equal((await db.fsGetWhere('questions','exam_id','==','exam1'))[0].question_number,1);
});

test('rubric edits persist and invalid criterion totals leave the saved rubric unchanged', async () => {
    const {db,storage} = browser();
    const q = {exam_id:'exam1',question_number:1,question_text:'Explain data',question_type:'WRITTEN',
        max_marks:5,reference_answer:'Data represents observations.',
        criteria:[{id:'c1',description:'Explains observations',marks:5,keywords:['observations']}]};
    const saved=await db.saveExamQuestion('exam1',q);
    await assert.rejects(db.saveExamQuestion('exam1',{...q,criteria:[{id:'c1',description:'Wrong total',marks:8}]},saved.id));
    const restored=await browser(storage).db.fsGetDoc('questions',saved.id);
    assert.equal(JSON.parse(restored.rubric_json).criteria[0].marks,5);
    await assert.rejects(db.saveExamQuestion('exam1',q));
});

test('answer-key approval is atomic and requires complete examination references', async () => {
    const {db,localStorage}=browser();
    await db.importExamQuestions('exam1',[question()]);
    const uploaded=await db.saveExamAnswerKey('exam1',key('exam1'));
    const write=localStorage.setItem;
    localStorage.setItem=()=>{throw new Error('Quota exceeded');};
    await assert.rejects(db.approveExamAnswerKey('exam1',uploaded.key.id));
    assert.equal((await db.fsGetDoc('answer_keys',uploaded.key.id)).is_approved,false);
    await assert.rejects(db.approveExamAnswerKey('exam2',uploaded.key.id));
    localStorage.setItem=write;
    await db.approveExamAnswerKey('exam1',uploaded.key.id,'Examiner');
    assert.equal((await db.fsGetDoc('answer_keys',uploaded.key.id)).is_approved,true);
    assert.equal((await db.fsGetAll('audit_logs')).filter(a=>a.action==='APPROVE_ANSWER_KEY').length,1);
});
