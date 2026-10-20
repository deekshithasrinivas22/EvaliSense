/**
 * EvaliSense — Firebase Authentication & Firestore Database Integration
 *
 * Provides:
 * 1. Firebase client initialization with user-supplied credentials
 * 2. Firebase Auth with 3 built-in login types (HOD, Teacher, Scanner)
 * 3. Firestore as complete database with automatic seeding for all entities
 * 4. CRUD operations for academic structure, exams, answer keys, rubrics, reviews, and results
 */

const firebaseConfig = {
  apiKey: "AIzaSyDaVHoDUXmXxt4g_iPbIvg8rYnMzXMI_3k",
  authDomain: "evalisense.firebaseapp.com",
  projectId: "evalisense",
  storageBucket: "evalisense.firebasestorage.app",
  messagingSenderId: "47270956687",
  appId: "1:47270956687:web:760364fa48509a5de0aafa"
};

// Initialize Firebase
if (typeof firebase !== 'undefined' && !firebase.apps.length) {
    try {
        firebase.initializeApp(firebaseConfig);
        console.log('✓ Firebase initialized successfully with project:', firebaseConfig.projectId);
    } catch (err) {
        console.error('Firebase initialization error:', err);
    }
}

const fbAuth = typeof firebase !== 'undefined' ? firebase.auth() : null;
const fbDb = typeof firebase !== 'undefined' ? firebase.firestore() : null;

// Built-in Demo Credentials for the 3 available login types
const DEMO_LOGINS = {
    HOD: {
        email: "hod@evalisense.edu",
        password: "Admin@123",
        username: "admin",
        full_name: "Prof. Eleanor Vance",
        role: "HOD",
        role_label: "HOD / Administrator",
        dept: "Computer Science & Engineering",
        employee_id: "EMP-HOD-01"
    },
    TEACHER: {
        email: "teacher@evalisense.edu",
        password: "Teacher@123",
        username: "teacher1",
        full_name: "Dr. Marcus Thorne",
        role: "TEACHER",
        role_label: "Teacher / Examiner",
        dept: "Computer Science & Engineering",
        employee_id: "EMP-TCH-08"
    },
    SCANNER: {
        email: "scanner@evalisense.edu",
        password: "Scanner@123",
        username: "scanner1",
        full_name: "Alex Rivera",
        role: "SCANNER",
        role_label: "Scanner Operator",
        dept: "Examination Section Intake",
        employee_id: "EMP-SCN-03"
    }
};

// Map usernames and emails to standard login definitions
function resolveLoginInfo(emailOrUsername) {
    const val = (emailOrUsername || '').trim().toLowerCase();
    if (val === 'admin' || val === 'hod@evalisense.edu') return DEMO_LOGINS.HOD;
    if (val === 'teacher1' || val === 'teacher' || val === 'teacher@evalisense.edu') return DEMO_LOGINS.TEACHER;
    if (val === 'scanner1' || val === 'scanner' || val === 'scanner@evalisense.edu') return DEMO_LOGINS.SCANNER;
    return null;
}

// ─────────────────────────────────────────────────────────────────────────────
// In-Memory Fallback Data (used when Firestore is unreachable)
// ─────────────────────────────────────────────────────────────────────────────

let _useLocalFallback = false;
const _localStore = {};

function _getLocalCollection(name) {
    return _localStore[name] || [];
}

function _setLocalDoc(collection, id, data) {
    if (!_localStore[collection]) _localStore[collection] = [];
    const idx = _localStore[collection].findIndex(d => d.id === id);
    const doc = { id, ...data };
    if (idx >= 0) _localStore[collection][idx] = doc;
    else _localStore[collection].push(doc);
    return doc;
}

function _deleteLocalDoc(collection, id) {
    if (!_localStore[collection]) return;
    _localStore[collection] = _localStore[collection].filter(d => d.id !== id);
}

// ─────────────────────────────────────────────────────────────────────────────
// Firestore Generic Helpers (with automatic local fallback)
// ─────────────────────────────────────────────────────────────────────────────

async function fsGetAll(collectionName) {
    if (!fbDb || _useLocalFallback) return _getLocalCollection(collectionName);
    try {
        const snap = await fbDb.collection(collectionName).get();
        return snap.docs.map(doc => ({ id: doc.id, ...doc.data() }));
    } catch (err) {
        if (err.code === 'permission-denied' || (err.message && err.message.includes('permission'))) {
            _useLocalFallback = true;
            return _getLocalCollection(collectionName);
        }
        console.warn(`Firestore read failed for ${collectionName}:`, err.message);
        return [];
    }
}

async function fsGetWhere(collectionName, field, op, value) {
    if (!fbDb || _useLocalFallback) {
        const all = _getLocalCollection(collectionName);
        return all.filter(doc => {
            const v = doc[field];
            if (op === '==') return v === value;
            if (op === '!=') return v !== value;
            if (op === '<') return v < value;
            if (op === '>') return v > value;
            return v === value;
        });
    }
    try {
        const snap = await fbDb.collection(collectionName).where(field, op, value).get();
        return snap.docs.map(doc => ({ id: doc.id, ...doc.data() }));
    } catch (err) {
        if (err.code === 'permission-denied' || (err.message && err.message.includes('permission'))) {
            _useLocalFallback = true;
            const all = _getLocalCollection(collectionName);
            return all.filter(doc => doc[field] === value);
        }
        console.warn(`Firestore query failed for ${collectionName}:`, err.message);
        return [];
    }
}

async function fsGetDoc(collectionName, docId) {
    if (!fbDb || !docId || _useLocalFallback) {
        const all = _getLocalCollection(collectionName);
        return all.find(d => d.id === docId) || null;
    }
    try {
        const doc = await fbDb.collection(collectionName).doc(String(docId)).get();
        if (doc.exists) return { id: doc.id, ...doc.data() };
        return null;
    } catch (err) {
        if (err.code === 'permission-denied' || (err.message && err.message.includes('permission'))) {
            _useLocalFallback = true;
            const all = _getLocalCollection(collectionName);
            return all.find(d => d.id === docId) || null;
        }
        return null;
    }
}

async function fsSetDoc(collectionName, docId, data, merge = true) {
    _setLocalDoc(collectionName, docId, data);
    if (!fbDb || !docId || _useLocalFallback) return { id: docId, ...data };
    try {
        await fbDb.collection(collectionName).doc(String(docId)).set(data, { merge });
        return { id: docId, ...data };
    } catch (err) {
        if (err.code === 'permission-denied' || (err.message && err.message.includes('permission'))) {
            _useLocalFallback = true;
        }
        return { id: docId, ...data };
    }
}

async function fsAddDoc(collectionName, data) {
    const localId = 'local_' + Date.now() + '_' + Math.random().toString(36).substr(2, 6);
    _setLocalDoc(collectionName, localId, data);
    if (!fbDb || _useLocalFallback) return { id: localId, ...data };
    try {
        const ref = await fbDb.collection(collectionName).add({
            ...data,
            created_at: firebase.firestore.FieldValue.serverTimestamp()
        });
        return { id: ref.id, ...data };
    } catch (err) {
        if (err.code === 'permission-denied' || (err.message && err.message.includes('permission'))) {
            _useLocalFallback = true;
        }
        return { id: localId, ...data };
    }
}

async function fsUpdateDoc(collectionName, docId, data) {
    _setLocalDoc(collectionName, docId, data);
    if (!fbDb || !docId || _useLocalFallback) return { id: docId, ...data };
    try {
        await fbDb.collection(collectionName).doc(String(docId)).update({
            ...data,
            updated_at: firebase.firestore.FieldValue.serverTimestamp()
        });
        return { id: docId, ...data };
    } catch (err) {
        if (err.code === 'permission-denied' || (err.message && err.message.includes('permission'))) {
            _useLocalFallback = true;
        }
        return { id: docId, ...data };
    }
}

async function fsDeleteDoc(collectionName, docId) {
    _deleteLocalDoc(collectionName, docId);
    if (!fbDb || !docId || _useLocalFallback) return true;
    try {
        await fbDb.collection(collectionName).doc(String(docId)).delete();
        return true;
    } catch (err) {
        if (err.code === 'permission-denied' || (err.message && err.message.includes('permission'))) {
            _useLocalFallback = true;
        }
        return true;
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// Automatic Firestore / Local Seeding (Initial setup of complete project data)
// ─────────────────────────────────────────────────────────────────────────────

let _seedingDone = false;

async function seedFirestoreIfEmpty() {
    if (_seedingDone) return;
    _seedingDone = true;

    // Try Firestore first, fall back to local store
    let alreadyPopulated = false;
    if (fbDb) {
        try {
            const usersSnap = await fbDb.collection('users').limit(1).get();
            if (!usersSnap.empty) {
                console.log('✓ Firestore already populated with project data.');
                alreadyPopulated = true;
            }
        } catch (permErr) {
            console.warn('Firestore read check failed (likely permissions). Seeding to local fallback.', permErr.message);
            _useLocalFallback = true;
        }
    } else {
        _useLocalFallback = true;
    }

    if (alreadyPopulated) return;

    try {
        console.log('⚡ Initializing data store with complete academic and evaluation dataset...');

        // 1. Roles
        const roles = [
            { id: 'HOD', name: 'HOD', description: 'Head of Department / Academic Administrator', is_system: true },
            { id: 'TEACHER', name: 'TEACHER', description: 'Course Faculty & Answer Key / Risk Reviewer', is_system: true },
            { id: 'SCANNER', name: 'SCANNER', description: 'Intake Scanner Operator for physical student answer scripts', is_system: true }
        ];
        for (const r of roles) { await fsSetDoc('roles', r.id, r); }

        // 2. Default Users for the 3 login types
        for (const u of Object.values(DEMO_LOGINS)) {
            await fsSetDoc('users', u.username, {
                username: u.username,
                email: u.email,
                full_name: u.full_name,
                role: u.role,
                role_name: u.role,
                department: u.dept,
                employee_id: u.employee_id,
                is_active: true,
                created_at: new Date().toISOString()
            });
        }

        // 3. Departments
        const departments = [
            { id: 'dept_cse', code: 'CSE', name: 'Computer Science & Engineering', status: 'Active' },
            { id: 'dept_ece', code: 'ECE', name: 'Electronics & Communication Engineering', status: 'Active' },
            { id: 'dept_me', code: 'ME', name: 'Mechanical Engineering', status: 'Active' }
        ];
        for (const d of departments) { await fsSetDoc('departments', d.id, d); }

        // 4. Sections
        const sections = [
            { id: 'sec_cse_a', name: 'CSE-A', department_id: 'dept_cse', department_code: 'CSE', semester: 5, academic_year: '2026-2027' },
            { id: 'sec_cse_b', name: 'CSE-B', department_id: 'dept_cse', department_code: 'CSE', semester: 5, academic_year: '2026-2027' }
        ];
        for (const s of sections) { await fsSetDoc('sections', s.id, s); }

        // 5. Students
        const students = [
            { id: '1MS22CS001', usn: '1MS22CS001', name: 'Aarav Sharma', section_id: 'sec_cse_a', section_name: 'CSE-A', roll_number: '01', email: 'aarav.sharma@evalisense.edu' },
            { id: '1MS22CS002', usn: '1MS22CS002', name: 'Ananya Rao', section_id: 'sec_cse_a', section_name: 'CSE-A', roll_number: '02', email: 'ananya.rao@evalisense.edu' },
            { id: '1MS22CS003', usn: '1MS22CS003', name: 'Rohan Patel', section_id: 'sec_cse_a', section_name: 'CSE-A', roll_number: '03', email: 'rohan.patel@evalisense.edu' },
            { id: '1MS22CS004', usn: '1MS22CS004', name: 'Priya Nair', section_id: 'sec_cse_b', section_name: 'CSE-B', roll_number: '04', email: 'priya.nair@evalisense.edu' },
            { id: '1MS22CS005', usn: '1MS22CS005', name: 'Karthik S', section_id: 'sec_cse_b', section_name: 'CSE-B', roll_number: '05', email: 'karthik.s@evalisense.edu' }
        ];
        for (const st of students) { await fsSetDoc('students', st.id, st); }

        // 6. Subjects
        const subjects = [
            { id: 'sub_cs501', code: 'CS501', name: 'Database Management Systems', department_code: 'CSE', semester: 5, max_marks: 100 },
            { id: 'sub_cs502', code: 'CS502', name: 'Operating Systems', department_code: 'CSE', semester: 5, max_marks: 100 },
            { id: 'sub_cs503', code: 'CS503', name: 'Theory of Computation', department_code: 'CSE', semester: 5, max_marks: 100 }
        ];
        for (const sub of subjects) { await fsSetDoc('subjects', sub.id, sub); }

        // 7. Teacher Assignments (Dr. Marcus Thorne assigned to CS501 and CS502)
        const assignments = [
            { id: 'assign_1', teacher_id: 'teacher1', teacher_name: 'Dr. Marcus Thorne', subject_id: 'sub_cs501', subject_code: 'CS501', subject_name: 'Database Management Systems', section_name: 'CSE-A', academic_year: '2026-2027', is_active: true },
            { id: 'assign_2', teacher_id: 'teacher1', teacher_name: 'Dr. Marcus Thorne', subject_id: 'sub_cs502', subject_code: 'CS502', subject_name: 'Operating Systems', section_name: 'CSE-A', academic_year: '2026-2027', is_active: true }
        ];
        for (const a of assignments) { await fsSetDoc('teacher_subjects', a.id, a); }

        // 8. Examinations
        const exams = [
            {
                id: 'exam_1',
                subject_id: 'sub_cs501',
                subject_code: 'CS501',
                subject_name: 'Database Management Systems',
                name: 'Midterm Assessment 1 — CS501 DBMS',
                exam_name: 'Midterm Assessment 1 — CS501 DBMS',
                exam_type: 'INTERNAL',
                total_marks: 25.0,
                exam_date: '2026-10-15',
                academic_year: '2026-2027',
                status: 'EVALUATED'
            },
            {
                id: 'exam_2',
                subject_id: 'sub_cs502',
                subject_code: 'CS502',
                subject_name: 'Operating Systems',
                name: 'Semester Examination — CS502 OS',
                exam_name: 'Semester Examination — CS502 OS',
                exam_type: 'SEMESTER',
                total_marks: 50.0,
                exam_date: '2026-10-25',
                academic_year: '2026-2027',
                status: 'SCHEDULED'
            }
        ];
        for (const e of exams) { await fsSetDoc('exams', e.id, e); }

        // 9. Structured Questions & Rubrics for Exam 1
        const questions = [
            {
                id: 'q_1_1',
                exam_id: 'exam_1',
                question_number: 1,
                question_text: "State and explain the ACID properties of database transactions with their significance.",
                max_marks: 5.0,
                reference_answer: "Atomicity: All actions of a transaction execute completely or none do (all-or-nothing). Consistency: Execution of a transaction takes the database from one valid state to another, preserving integrity constraints. Isolation: Concurrent transactions execute without interfering with one another; intermediate states remain invisible. Durability: Once a transaction commits, its effects persist permanently even in the event of system failure.",
                criteria: [
                    { id: "c1", description: "Defines Atomicity (all-or-nothing execution)", marks: 1.5, keywords: ["atomicity", "all or nothing", "abort", "rollback"] },
                    { id: "c2", description: "Explains Consistency and constraint preservation", marks: 1.0, keywords: ["consistency", "integrity constraints", "valid state"] },
                    { id: "c3", description: "Explains Isolation in concurrent execution", marks: 1.5, keywords: ["isolation", "concurrency", "invisible", "serializable"] },
                    { id: "c4", description: "Defines Durability upon transaction commit", marks: 1.0, keywords: ["durability", "permanent", "crash", "persist"] }
                ]
            },
            {
                id: 'q_1_2',
                exam_id: 'exam_1',
                question_number: 2,
                question_text: "Differentiate between B-Tree and B+ Tree index structures. Why are B+ trees preferred for relational database storage?",
                max_marks: 5.0,
                reference_answer: "In a B-Tree, both keys and records/pointers are stored in internal and leaf nodes. In a B+ Tree, internal nodes store only search keys to guide indexing, while all record pointers and actual data values reside exclusively in leaf nodes. Furthermore, leaf nodes in a B+ Tree are linked together via a doubly-linked list, enabling efficient sequential range scans. B+ trees provide higher fan-out, shallower tree height, and superior disk I/O performance.",
                criteria: [
                    { id: "c1", description: "Key vs record storage location difference", marks: 2.0, keywords: ["internal nodes", "leaf nodes", "data pointers", "keys only"] },
                    { id: "c2", description: "Doubly linked list in B+ tree leaf nodes for range scans", marks: 1.5, keywords: ["linked list", "sequential", "range scan", "leaves"] },
                    { id: "c3", description: "Disk I/O efficiency, shallower tree height, higher fan-out", marks: 1.5, keywords: ["fan-out", "disk I/O", "cache", "shallow", "height"] }
                ]
            },
            {
                id: 'q_1_3',
                exam_id: 'exam_1',
                question_number: 3,
                question_text: "Define Third Normal Form (3NF). Provide an example relation exhibiting transitive dependency and demonstrate its decomposition.",
                max_marks: 15.0,
                reference_answer: "A relation is in 3NF if it is in 2NF and no non-prime attribute is transitively dependent on the primary key. Formally, for every non-trivial functional dependency X -> A, either X is a superkey or A is a prime attribute. Example: Employee(EmpID, DeptID, DeptName). Here, EmpID -> DeptID and DeptID -> DeptName, creating a transitive dependency EmpID -> DeptName. Decomposition into 3NF yields: Emp_Dept(EmpID, DeptID) and Department(DeptID, DeptName).",
                criteria: [
                    { id: "c1", description: "2NF prerequisite and formal 3NF definition (superkey or prime attribute)", marks: 4.0, keywords: ["2NF", "transitive dependency", "superkey", "prime attribute"] },
                    { id: "c2", description: "Clear relation example with functional dependencies showing transitive chain", marks: 5.0, keywords: ["functional dependency", "EmpID", "DeptID", "DeptName", "X -> Y -> Z"] },
                    { id: "c3", description: "Correct lossless-join decomposition into normalized tables", marks: 6.0, keywords: ["decomposition", "lossless", "dependency preserving", "tables"] }
                ]
            }
        ];
        for (const q of questions) {
            await fsSetDoc('questions', q.id, {
                ...q,
                rubric_json: JSON.stringify({
                    question: q.question_text,
                    max_marks: q.max_marks,
                    reference_answer: q.reference_answer,
                    criteria: q.criteria
                })
            });
        }

        // 10. Answer Keys (Exam 1)
        const answerKeys = [
            {
                id: 'ak_1_v2',
                exam_id: 'exam_1',
                version: 2,
                original_filename: 'DBMS_Model_Answer_Scheme_v2.pdf',
                filename: 'DBMS_Model_Answer_Scheme_v2.pdf',
                uploaded_by: 'teacher1',
                uploader_name: 'Dr. Marcus Thorne',
                file_size: 2457600,
                mime_type: 'application/pdf',
                status: 'APPROVED',
                is_approved: true,
                is_active: true,
                uploaded_at: '2026-10-14T11:30:00Z',
                approved_at: '2026-10-15T09:00:00Z',
                extracted_text: "OFFICIAL MARKING SCHEME: CS501 DATABASE MANAGEMENT SYSTEMS...\nQ1: ACID properties definition with all 4 components...\nQ2: B-Tree vs B+ Tree internal storage and linked list...",
                notes: 'Official semester midterm verified marking scheme approved by Departmental Faculty.'
            },
            {
                id: 'ak_1_v1',
                exam_id: 'exam_1',
                version: 1,
                original_filename: 'DBMS_Answer_Key_Draft.pdf',
                filename: 'DBMS_Answer_Key_Draft.pdf',
                uploaded_by: 'teacher1',
                uploader_name: 'Dr. Marcus Thorne',
                file_size: 2120000,
                mime_type: 'application/pdf',
                status: 'SUPERSEDED',
                is_approved: false,
                is_active: false,
                uploaded_at: '2026-10-11T14:15:00Z',
                extracted_text: "Draft marking scheme v1...",
                notes: 'Superseded by version 2.'
            }
        ];
        for (const ak of answerKeys) { await fsSetDoc('answer_keys', ak.id, ak); }

        // 11. Answer Scripts & Evaluations
        const scripts = [
            {
                id: 'script_101',
                exam_id: 'exam_1',
                student_id: '1MS22CS001',
                student_usn: '1MS22CS001',
                student_name: 'Aarav Sharma',
                status: 'EVALUATED',
                total_obtained: 22.5,
                total_max: 25.0,
                quality_status: 'CLEAN',
                ocr_confidence: 0.94,
                uploaded_at: '2026-10-15T10:00:00Z'
            },
            {
                id: 'script_102',
                exam_id: 'exam_1',
                student_id: '1MS22CS002',
                student_usn: '1MS22CS002',
                student_name: 'Ananya Rao',
                status: 'PENDING_REVIEW',
                total_obtained: null,
                total_max: 25.0,
                quality_status: 'FLAGGED_HIGH_RISK',
                ocr_confidence: 0.58,
                uploaded_at: '2026-10-15T10:05:00Z'
            },
            {
                id: 'script_103',
                exam_id: 'exam_1',
                student_id: '1MS22CS003',
                student_usn: '1MS22CS003',
                student_name: 'Rohan Patel',
                status: 'COMPLETED_REVIEW',
                total_obtained: 21.0,
                total_max: 25.0,
                quality_status: 'REVIEWED',
                ocr_confidence: 0.88,
                uploaded_at: '2026-10-15T10:10:00Z'
            }
        ];
        for (const sc of scripts) { await fsSetDoc('scripts', sc.id, sc); }

        // 12. Review Assignments & Evaluations
        const evaluations = [
            {
                id: 'eval_102_q1',
                script_id: 'script_102',
                exam_id: 'exam_1',
                exam_name: 'Midterm Assessment 1 — CS501 DBMS',
                student_usn: '1MS22CS002',
                student_name: 'Ananya Rao',
                question_number: 1,
                question_text: "State and explain the ACID properties of database transactions with their significance.",
                max_marks: 5.0,
                ai_preliminary_mark: 2.0,
                semantic_similarity: 0.62,
                rubric_coverage: 0.50,
                risk_level: 'HIGH',
                risk_probability: 0.86,
                risk_factors: [
                    "Low OCR word recognition confidence (58%)",
                    "Discrepancy detected in Durability rubric criteria",
                    "Extracted handwriting length is significantly shorter than model answer"
                ],
                extracted_text: "Atomicity means all or nothing. Consistency keeps DB valid. Isolation runs without interference. Durability means data survives power cut.",
                reference_answer: "Atomicity ensures all actions within a transaction execute completely or none at all. Consistency preserves database integrity constraints. Isolation ensures concurrent transactions do not interfere with each other. Durability guarantees committed transactions survive system failures.",
                status: 'PENDING',
                assigned_teacher_id: 'teacher1',
                assigned_teacher_name: 'Dr. Marcus Thorne',
                final_mark: null,
                teacher_notes: null,
                reviewed_at: null
            },
            {
                id: 'eval_103_q1',
                script_id: 'script_103',
                exam_id: 'exam_1',
                exam_name: 'Midterm Assessment 1 — CS501 DBMS',
                student_usn: '1MS22CS003',
                student_name: 'Rohan Patel',
                question_number: 1,
                question_text: "State and explain the ACID properties of database transactions with their significance.",
                max_marks: 5.0,
                ai_preliminary_mark: 3.5,
                semantic_similarity: 0.82,
                rubric_coverage: 0.75,
                risk_level: 'MEDIUM',
                risk_probability: 0.45,
                status: 'COMPLETED',
                assigned_teacher_id: 'teacher1',
                assigned_teacher_name: 'Dr. Marcus Thorne',
                final_mark: 4.5,
                teacher_notes: "Awarded additional credit: student clearly articulated transaction rollback mechanisms for Atomicity and serialization for Isolation.",
                reviewed_at: '2026-10-16T14:40:00Z'
            }
        ];
        for (const ev of evaluations) { await fsSetDoc('evaluations', ev.id, ev); }

        // 13. Notifications
        const notifications = [
            {
                id: 'notif_1',
                user_id: 'teacher1',
                recipient_role: 'TEACHER',
                title: 'High-Risk Review Assignment',
                message: 'Answer script for 1MS22CS002 in CS501 Midterm has been flagged for human verification.',
                is_read: false,
                created_at: new Date(Date.now() - 3600000).toISOString()
            },
            {
                id: 'notif_2',
                user_id: 'teacher1',
                recipient_role: 'TEACHER',
                title: 'Answer Key v2 Approved',
                message: 'Official Answer Key Version 2 for CS501 DBMS is verified and active.',
                is_read: true,
                created_at: new Date(Date.now() - 86400000).toISOString()
            }
        ];
        for (const n of notifications) { await fsSetDoc('notifications', n.id, n); }

        // 14. Audit Logs
        const auditLogs = [
            {
                id: 'audit_1',
                user_name: 'Dr. Marcus Thorne',
                user_role: 'TEACHER',
                action: 'UPLOAD_ANSWER_KEY',
                entity_type: 'answer_key',
                entity_id: 'ak_1_v2',
                details: 'Uploaded version 2 of official marking key for CS501 DBMS.',
                timestamp: '2026-10-14T11:30:00Z'
            },
            {
                id: 'audit_2',
                user_name: 'Prof. Eleanor Vance',
                user_role: 'HOD',
                action: 'APPROVE_ANSWER_KEY',
                entity_type: 'answer_key',
                entity_id: 'ak_1_v2',
                details: 'Verified and approved answer key v2 as official grading benchmark.',
                timestamp: '2026-10-15T09:00:00Z'
            }
        ];
        for (const al of auditLogs) { await fsSetDoc('audit_logs', al.id, al); }

        console.log('✓ Data store successfully populated with all project collections.' + (_useLocalFallback ? ' (local fallback mode)' : ''));
    } catch (err) {
        console.error('Error during data seeding:', err);
        // Even if some writes failed, local store has the data
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// Firebase Auth Handlers (One login for each of the 3 available login types)
// ─────────────────────────────────────────────────────────────────────────────

async function fbLogin(emailOrUsername, password) {
    if (!fbAuth) {
        throw new Error('Firebase Auth is not initialized.');
    }

    let email = emailOrUsername.trim();
    let profileData = resolveLoginInfo(emailOrUsername);

    if (profileData) {
        email = profileData.email;
    }

    let userCred = null;

    try {
        // Attempt sign in with email and password
        userCred = await fbAuth.signInWithEmailAndPassword(email, password);
        console.log('✓ Firebase Auth signIn success:', userCred.user.email);
    } catch (authErr) {
        // If user does not exist in Firebase Auth yet, auto-provision user
        if (
            authErr.code === 'auth/user-not-found' ||
            authErr.code === 'auth/invalid-credential' ||
            authErr.code === 'auth/invalid-login-credentials'
        ) {
            console.log(`Auto-provisioning user account for ${email} in Firebase Auth...`);
            try {
                userCred = await fbAuth.createUserWithEmailAndPassword(email, password);
                console.log('✓ Firebase Auth user created successfully:', userCred.user.email);
            } catch (createErr) {
                // If create fails because email exists, rethrow original error
                if (createErr.code === 'auth/email-already-in-use') {
                    throw authErr;
                }
                throw createErr;
            }
        } else {
            throw authErr;
        }
    }

    const firebaseUser = userCred.user;
    const idToken = await firebaseUser.getIdToken();

    // Determine role and user profile
    if (!profileData) {
        // Lookup from Firestore
        let doc = await fsGetDoc('users', firebaseUser.uid);
        if (!doc) {
            const list = await fsGetWhere('users', 'email', '==', email);
            if (list.length) doc = list[0];
        }
        if (doc) {
            profileData = {
                uid: firebaseUser.uid,
                email: firebaseUser.email,
                username: doc.username || email.split('@')[0],
                full_name: doc.full_name || email,
                role: doc.role || 'TEACHER',
                role_name: doc.role || 'TEACHER',
                role_label: doc.role_label || doc.role,
                department: doc.department || 'Academic Department',
                employee_id: doc.employee_id || 'EMP-000'
            };
        } else {
            // Default profile for new user
            profileData = {
                uid: firebaseUser.uid,
                email: firebaseUser.email,
                username: email.split('@')[0],
                full_name: firebaseUser.displayName || email.split('@')[0],
                role: 'TEACHER',
                role_name: 'TEACHER',
                role_label: 'Teacher / Examiner',
                department: 'Computer Science & Engineering',
                employee_id: 'EMP-TCH'
            };
        }
    } else {
        profileData.uid = firebaseUser.uid;
        profileData.role_name = profileData.role;
    }

    // Save profile into Firestore if missing
    try {
        await fsSetDoc('users', profileData.username, {
            uid: firebaseUser.uid,
            email: profileData.email,
            username: profileData.username,
            full_name: profileData.full_name,
            role: profileData.role,
            role_name: profileData.role,
            department: profileData.dept || profileData.department,
            employee_id: profileData.employee_id,
            is_active: true,
            last_login: new Date().toISOString()
        }, true);
    } catch (saveErr) {
        console.warn('Could not update user doc in Firestore:', saveErr);
    }

    // Store in localStorage for application state
    localStorage.setItem('evalisense_token', idToken);
    localStorage.setItem('evalisense_user', JSON.stringify(profileData));

    // Audit log login event
    try {
        await fsAddDoc('audit_logs', {
            user_name: profileData.full_name,
            user_role: profileData.role,
            action: 'LOGIN',
            entity_type: 'user',
            entity_id: profileData.username,
            details: `Signed in via Firebase Auth (${profileData.role})`,
            timestamp: new Date().toISOString()
        });
    } catch (_) {}

    return { token: idToken, user: profileData };
}

async function fbLogout() {
    if (fbAuth) {
        try {
            await fbAuth.signOut();
        } catch (err) {
            console.warn('Firebase signOut error:', err);
        }
    }
    localStorage.removeItem('evalisense_token');
    localStorage.removeItem('evalisense_user');
}

// Global Export
window.firebaseConfig = firebaseConfig;
window.EvaliSenseDB = {
    fbAuth,
    fbDb,
    DEMO_LOGINS,
    resolveLoginInfo,
    fsGetAll,
    fsGetWhere,
    fsGetDoc,
    fsSetDoc,
    fsAddDoc,
    fsUpdateDoc,
    fsDeleteDoc,
    seedFirestoreIfEmpty,
    fbLogin,
    fbLogout,
    isLocalFallback: () => _useLocalFallback
};

// Seed on page load — uses local fallback if Firestore permissions are denied
if (typeof document !== 'undefined') {
    document.addEventListener('DOMContentLoaded', () => {
        // Seed data immediately (will fall back to local store if permissions denied)
        seedFirestoreIfEmpty().catch(e => console.warn('Seed fallback:', e));
    });
}
