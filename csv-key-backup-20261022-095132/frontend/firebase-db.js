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
const LOCAL_DATA_KEY = 'evalisense_local_data_v2';
let _localStore = {};
try { _localStore = JSON.parse(localStorage.getItem(LOCAL_DATA_KEY) || '{}'); } catch (_) {}
function persistLocalStore() {
    localStorage.setItem(LOCAL_DATA_KEY, JSON.stringify(_localStore));
}

function _getLocalCollection(name) {
    return _localStore[name] || [];
}

function _setLocalDoc(collection, id, data) {
    if (!_localStore[collection]) _localStore[collection] = [];
    const idx = _localStore[collection].findIndex(d => d.id === id);
    const doc = { ...(idx >= 0 ? _localStore[collection][idx] : {}), ...data, id };
    if (idx >= 0) _localStore[collection][idx] = doc;
    else _localStore[collection].push(doc);
    persistLocalStore();
    return doc;
}

function _deleteLocalDoc(collection, id) {
    if (!_localStore[collection]) return;
    _localStore[collection] = _localStore[collection].filter(d => d.id !== id);
    persistLocalStore();
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

        // Questions are created from uploaded papers or manual entry, never seeded.

        // Answer keys are uploaded files, never seeded metadata.

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

// Real answer keys have stored original files and a reviewed numbered-answer map.
function actualAnswerKeys(keys) {
    return keys.filter(k => k.source === 'uploaded_answer_key' && k.file_id && Array.isArray(k.answers))
        .sort((a, b) => (b.version || 0) - (a.version || 0) || String(b.uploaded_at || '').localeCompare(String(a.uploaded_at || '')));
}
function activeStoredAnswerKey(keys, examId) {
    const real = actualAnswerKeys(keys).filter(k => k.exam_id === examId);
    return real.find(k => k.is_active) || null;
}
function normalizeKeySection(value) {
    return String(value || '').replace(/^(?:section|part)\s*/i, '').trim().toUpperCase();
}
function resolveKeyReference(question, key) {
    if (!key || key.exam_id !== question.exam_id) return {status: 'missing_key'};
    const number = Number(question.source_question_number || question.question_number);
    const section = normalizeKeySection(question.section);
    let entries = key.answers.filter(a => Number(a.question_number) === number);
    if (section) {
        const exact = entries.filter(a => normalizeKeySection(a.section) === section);
        entries = exact.length ? exact : entries.filter(a => !normalizeKeySection(a.section));
    }
    if (!entries.length) return {status: 'unmatched'};
    if (entries.length !== 1) return {status: 'ambiguous'};
    const entry = entries[0];
    const answer = String(entry.answer_text || '').trim();
    let reference = answer;
    let optionLabel = String(entry.correct_option || '').trim().toUpperCase();
    if (question.question_type === 'MCQ') {
        const options = question.options || [];
        if (!optionLabel) {
            const normalized = answer.toLowerCase().replace(/\s+/g, ' ');
            const matches = options.filter(o => String(o.text).trim().toLowerCase().replace(/\s+/g, ' ') === normalized);
            if (matches.length !== 1) return {status: 'option_needs_review'};
            optionLabel = matches[0].label;
        }
        const matches = options.filter(o => String(o.label).toUpperCase() === optionLabel);
        if (matches.length !== 1) return {status: 'option_needs_review'};
        reference = `${optionLabel}. ${matches[0].text}`;
        if (answer && answer.toLowerCase() !== String(matches[0].text).trim().toLowerCase()) reference += `\n${answer}`;
    } else if (optionLabel) {
        reference = entry.raw_answer || `${optionLabel}${answer ? '. ' + answer : ''}`;
    }
    if (!reference.trim()) return {status: 'unmatched'};
    return {status: 'matched', reference_answer: reference, correct_option: optionLabel};
}
function attachAnswerKeyReference(question, key) {
    const q = {...question};
    // A teacher-edited answer is never replaced by a later key upload.
    if (q.reference_answer?.trim() && q.reference_source !== 'answer_key') return q;
    const result = resolveKeyReference(q, key);
    q.reference_match_status = result.status;
    q.reference_answer = result.reference_answer || '';
    q.correct_option = result.correct_option || '';
    q.reference_source = 'answer_key';
    q.reference_key_id = key?.id || '';
    q.reference_key_version = key?.version || null;
    q.rubric_json = JSON.stringify({question: q.question_text, max_marks: q.max_marks,
        reference_answer: q.reference_answer, criteria: q.criteria || []});
    return q;
}
async function readExamDocuments(collection, examId) {
    if (!fbDb || _useLocalFallback) return _getLocalCollection(collection).filter(d => d.exam_id === examId);
    // Unlike the generic fallback helpers, errors must not look like empty data.
    const snapshot = await fbDb.collection(collection).where('exam_id', '==', examId).get();
    return snapshot.docs.map(d => ({...d.data(), id: d.id}));
}
async function commitDocumentChanges(changes) {
    if (changes.length > 450) throw new Error('Too many records for one safe save (maximum 450 changes).');
    const local = !fbDb || _useLocalFallback;
    if (!local) {
        const batch = fbDb.batch();
        for (const change of changes) {
            const {id, ...data} = change.data;
            batch.set(fbDb.collection(change.collection).doc(id), data);
        }
        await batch.commit();
    }
    const snapshot = JSON.stringify(_localStore);
    try {
        // Persist once, so an offline save is all-or-nothing even on quota failure.
        for (const change of changes) {
            const {collection, data} = change;
            if (!_localStore[collection]) _localStore[collection] = [];
            _localStore[collection] = [..._localStore[collection].filter(d => d.id !== data.id), data];
        }
        persistLocalStore();
    } catch (err) {
        _localStore = JSON.parse(snapshot);
        if (local) throw new Error('Browser storage is full. The previous key is unchanged; free space and retry.');
        console.warn('Saved to cloud; local cache could not be updated.', err);
    }
    return local;
}
async function saveExamAnswerKey(examId, document) {
    if (!examId || document.exam_id !== examId || !/^[a-f0-9]{32}$/.test(document.file_id || '')) throw new Error('The answer key belongs to a different examination.');
    if (!document.answers?.length) throw new Error('Review the numbered answers before saving.');
    const seen = new Set();
    const answers = document.answers.map(a => {
        const number = Number(a.question_number);
        const section = normalizeKeySection(a.section);
        const identity = `${section}:${number}`;
        const correct_option = String(a.correct_option || '').trim().toUpperCase();
        const answer_text = String(a.answer_text || '').trim();
        if (!Number.isInteger(number) || number < 1 || seen.has(identity) ||
            (correct_option && !/^[A-H]$/.test(correct_option)) || (!answer_text && !correct_option)) {
            throw new Error('Each answer needs a unique section/number and either answer text or a valid option letter A–H.');
        }
        seen.add(identity);
        return {question_number: number, section, correct_option, answer_text,
            raw_answer: correct_option ? `${correct_option}${answer_text ? '. ' + answer_text : ''}` : answer_text};
    });
    const [keys, questions] = await Promise.all([readExamDocuments('answer_keys', examId), readExamDocuments('questions', examId)]);
    const real = actualAnswerKeys(keys);
    const id = `ak_${document.file_id}`;
    const previous = real.find(k => k.id === id);
    const key = {...document, answers, id, exam_id: examId, source: 'uploaded_answer_key',
        version: previous?.version || Math.max(0, ...real.map(k => Number(k.version) || 0)) + 1,
        uploaded_at: previous?.uploaded_at || new Date().toISOString(),
        is_active: true, is_approved: false, status: 'UPLOADED'};
    // Leave headroom under Firestore's per-document size limit, including Unicode.
    const bytes = encodeURIComponent(JSON.stringify(key)).replace(/%[A-F\d]{2}/g, 'x').length;
    if (bytes > 850000) throw new Error('This key is too large to save safely. Upload a smaller exam-specific key.');
    const changes = keys.filter(k => k.id !== id && k.is_active).map(k => ({collection: 'answer_keys', data: {...k, is_active: false, status: 'SUPERSEDED'}}));
    changes.push({collection: 'answer_keys', data: key});
    let matched = 0, unresolved = 0, preserved = 0;
    for (const question of questions.filter(q => q.source === 'question_paper' || q.id === `q_${examId}_${q.question_number}`)) {
        if (question.reference_answer?.trim() && question.reference_source !== 'answer_key') { preserved++; continue; }
        const next = attachAnswerKeyReference(question, key);
        if (next.reference_match_status === 'matched') matched++; else unresolved++;
        changes.push({collection: 'questions', data: next});
    }
    changes.push({collection: 'audit_logs', data: {id: `answer_key_upload_${key.file_id}`,
        user_name: key.uploader_name || key.uploaded_by || 'Teacher', user_role: 'TEACHER',
        action: 'UPLOAD_ANSWER_KEY', entity_type: 'answer_key', entity_id: key.id,
        details: `Stored answer key v${key.version} for exam ${examId}; matched ${matched} references.`,
        timestamp: new Date().toISOString()}});
    const local = await commitDocumentChanges(changes);
    return {key, matched, unresolved, preserved, local};
}

// Strict, atomic import: cloud failures never report a successful import.
async function importExamQuestions(examId, questions, mode = 'replace', filename = '') {
    if (!examId || !['merge', 'replace'].includes(mode) || !questions.length) throw new Error('Invalid import.');
    const numbers = new Set();
    for (const q of questions) {
        if (!Number.isInteger(q.question_number) || q.question_number < 1 || numbers.has(q.question_number) ||
            !q.question_text?.trim() || !Number.isFinite(q.max_marks) || q.max_marks <= 0 ||
            !['MCQ', 'WRITTEN'].includes(q.question_type) ||
            (q.question_type === 'MCQ' && (!Array.isArray(q.options) || q.options.length < 2 ||
                q.options.some(o => !/^[A-H]$/.test(o.label) || !o.text?.trim()) || new Set(q.options.map(o => o.label)).size !== q.options.length))) {
            throw new Error('Review the preview: question numbers must be unique positive integers, marks positive, and each question must have a type with valid MCQ choices.');
        }
        numbers.add(q.question_number);
    }
    const local = !fbDb || _useLocalFallback;
    const existing = local ? _getLocalCollection('questions').filter(q => q.exam_id === examId) :
        (await fbDb.collection('questions').where('exam_id', '==', examId).get()).docs.map(d => ({...d.data(), id: d.id}));
    const key = activeStoredAnswerKey(await readExamDocuments('answer_keys', examId), examId);
    const keptNumbers = new Set(existing.map(q => Number(q.question_number)));
    const incoming = questions.filter(q => mode === 'replace' || !keptNumbers.has(q.question_number)).map(q => attachAnswerKeyReference({
        ...q, id: `q_${examId}_${q.question_number}`, exam_id: examId,
        source_filename: filename, source: 'question_paper',
        rubric_json: JSON.stringify({question: q.question_text, max_marks: q.max_marks,
            reference_answer: q.reference_answer || '', criteria: q.criteria || []})
    }, key));
    const removed = mode === 'replace' ? existing : [];
    if (removed.length + incoming.length > 450) throw new Error('Import exceeds the safe batch limit (450 changes).');
    if (!local) {
        const batch = fbDb.batch();
        for (const q of removed.filter(q => !incoming.some(n => n.id === q.id))) batch.delete(fbDb.collection('questions').doc(q.id));
        for (const q of incoming) { const {id, ...data} = q; batch.set(fbDb.collection('questions').doc(id), data); }
        await batch.commit();
    }
    const snapshot = JSON.stringify(_localStore);
    try {
        _localStore.questions = [..._getLocalCollection('questions').filter(q =>
            !removed.some(r => r.id === q.id) && !incoming.some(r => r.id === q.id)), ...incoming];
        persistLocalStore();
    } catch (err) {
        _localStore = JSON.parse(snapshot);
        if (local) throw err;
        console.warn('Cloud import saved; browser cache unavailable.', err);
    }
    return {added: incoming.length, kept: mode === 'merge' ? existing.length : 0, local,
        matched: incoming.filter(q => q.reference_match_status === 'matched').length,
        unresolved: incoming.filter(q => q.reference_match_status !== 'matched').length};
}

// Global Export
window.firebaseConfig = firebaseConfig;
window.EvaliSenseDB = {
    actualAnswerKeys, activeStoredAnswerKey, resolveKeyReference, attachAnswerKeyReference, saveExamAnswerKey,
    importExamQuestions,
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
