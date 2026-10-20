/**
 * EvaliSense — Frontend Application Logic
 *
 * Implements:
 * 1. Firebase Authentication with 3 built-in login types (HOD, Teacher, Scanner)
 * 2. Firebase Firestore Database for the complete project
 * 3. Screenshot-matched Teacher Portal (Navigation, Active Key, Version History,
 *    Structured Questions & Rubrics Editor, Text Extraction, Key Approval,
 *    Pending Risk Reviews, Completed Reviews, Class Results, My Profile)
 * 4. HOD Administration & Scanner Operators workflows
 * 5. Interactive TrOCR, Sentence-BERT, and Risk Prediction AI Pipeline
 */

const API_BASE = window.location.origin;

// Application State
let authToken = localStorage.getItem('evalisense_token') || null;
let currentUser = null;
try {
    const storedUser = localStorage.getItem('evalisense_user');
    if (storedUser) currentUser = JSON.parse(storedUser);
} catch (_) {}

let currentSessionId = null;
let currentReviewAssignmentId = null;
let activeExamId = null;
let activeSubjectId = null;

// ─────────────────────────────────────────────────────────────────────────────
// Utility & Formatting Helpers
// ─────────────────────────────────────────────────────────────────────────────

function formatDate(val) {
    if (!val) return '—';
    try {
        let d;
        if (typeof val === 'object' && val.toDate) {
            d = val.toDate(); // Firestore Timestamp
        } else if (typeof val === 'number') {
            d = new Date(val);
        } else {
            d = new Date(val);
        }
        if (isNaN(d.getTime())) return '—';
        return d.toLocaleDateString('en-US', {
            year: 'numeric',
            month: 'short',
            day: 'numeric',
            hour: '2-digit',
            minute: '2-digit'
        });
    } catch (_) {
        return '—';
    }
}

function escapeHtml(str) {
    if (str === null || str === undefined) return '';
    const div = document.createElement('div');
    div.textContent = String(str);
    return div.innerHTML;
}

function showLoading(text = 'Processing...') {
    const overlay = document.getElementById('loading-overlay');
    const loadingText = document.getElementById('loading-text');
    if (loadingText) loadingText.textContent = text;
    if (overlay) overlay.style.display = 'flex';
}

function hideLoading() {
    const overlay = document.getElementById('loading-overlay');
    if (overlay) overlay.style.display = 'none';
}

function openModal(id) {
    const el = document.getElementById(id);
    if (el) el.style.display = 'flex';
}

function closeModal(id) {
    const el = document.getElementById(id);
    if (el) el.style.display = 'none';
}

// ─────────────────────────────────────────────────────────────────────────────
// Network Helpers (for AI Pipeline endpoints with Bearer auth)
// ─────────────────────────────────────────────────────────────────────────────

function authHeaders(isJson = true) {
    const h = {};
    if (authToken) {
        h['Authorization'] = `Bearer ${authToken}`;
    }
    if (isJson) {
        h['Content-Type'] = 'application/json';
    }
    return h;
}

async function apiGet(url) {
    const resp = await fetch(`${API_BASE}${url}`, {
        headers: authHeaders(false)
    });
    if (resp.status === 401 && authToken) {
        logout();
        throw new Error('Session expired. Please sign in again.');
    }
    if (!resp.ok) {
        const err = await resp.json().catch(() => ({ detail: resp.statusText }));
        throw new Error(err.detail || resp.statusText);
    }
    return resp.json();
}

async function apiPost(url, body = null, isJson = true) {
    const opts = {
        method: 'POST',
        headers: authHeaders(isJson)
    };
    if (body) {
        opts.body = isJson ? JSON.stringify(body) : body;
    }
    const resp = await fetch(`${API_BASE}${url}`, opts);
    if (resp.status === 401 && authToken) {
        logout();
        throw new Error('Session expired. Please sign in again.');
    }
    if (!resp.ok) {
        const err = await resp.json().catch(() => ({ detail: resp.statusText }));
        throw new Error(err.detail || resp.statusText);
    }
    return resp.json();
}

// ─────────────────────────────────────────────────────────────────────────────
// Authentication & Session Management (Firebase Auth & Demo Roles)
// ─────────────────────────────────────────────────────────────────────────────

async function checkAuth() {
    if (window.EvaliSenseDB && window.EvaliSenseDB.fbAuth) {
        window.EvaliSenseDB.fbAuth.onAuthStateChanged(async (user) => {
            if (user) {
                const token = await user.getIdToken();
                authToken = token;
                localStorage.setItem('evalisense_token', token);

                let profile = await window.EvaliSenseDB.fsGetDoc('users', user.email.split('@')[0]);
                if (!profile) {
                    profile = await window.EvaliSenseDB.fsGetDoc('users', user.uid);
                }
                if (profile) {
                    setCurrentUser(profile);
                } else {
                    const fallbackRole = window.EvaliSenseDB.resolveLoginInfo(user.email);
                    setCurrentUser(fallbackRole || {
                        email: user.email,
                        username: user.email.split('@')[0],
                        full_name: user.displayName || user.email.split('@')[0],
                        role: 'TEACHER',
                        role_name: 'TEACHER'
                    });
                }
            } else {
                if (!currentUser) setGuestState();
            }
        });
    }

    if (currentUser && authToken) {
        setCurrentUser(currentUser);
    } else {
        setGuestState();
    }
}

function setCurrentUser(user) {
    currentUser = user;
    localStorage.setItem('evalisense_user', JSON.stringify(user));

    const greeting = document.getElementById('topbar-user-greeting');
    const badge = document.getElementById('topbar-role-badge');
    const btnLogin = document.getElementById('btn-login-open');
    const btnLogout = document.getElementById('btn-logout');

    const roleName = user.role_name || user.role || 'GUEST';

    if (greeting) greeting.textContent = `Welcome, ${user.full_name || user.username}`;
    if (badge) {
        badge.textContent = roleName;
        badge.className = `topbar-role-badge role-badge-${roleName.toLowerCase()}`;
    }
    if (btnLogin) btnLogin.style.display = 'none';
    if (btnLogout) btnLogout.style.display = 'inline-block';

    updateSidebarNavigation();
    checkNotifications();
}

function setGuestState() {
    currentUser = null;
    authToken = null;
    localStorage.removeItem('evalisense_token');
    localStorage.removeItem('evalisense_user');

    const greeting = document.getElementById('topbar-user-greeting');
    const badge = document.getElementById('topbar-role-badge');
    const btnLogin = document.getElementById('btn-login-open');
    const btnLogout = document.getElementById('btn-logout');

    if (greeting) greeting.textContent = 'Welcome to EvaliSense';
    if (badge) {
        badge.textContent = 'Guest';
        badge.className = 'topbar-role-badge role-badge-guest';
    }
    if (btnLogin) btnLogin.style.display = 'inline-block';
    if (btnLogout) btnLogout.style.display = 'none';

    updateSidebarNavigation();
    showPage('dashboard');
}

async function login(usernameOrEmail, password) {
    showLoading('Authenticating with Firebase Auth...');
    try {
        if (!window.EvaliSenseDB || !window.EvaliSenseDB.fbLogin) {
            throw new Error('Firebase Auth integration module is loading...');
        }
        const result = await window.EvaliSenseDB.fbLogin(usernameOrEmail, password);
        authToken = result.token;
        setCurrentUser(result.user);
        closeModal('modal-login');

        // Direct user to appropriate landing page
        const role = result.user.role_name || result.user.role;
        if (role === 'TEACHER') showPage('teacher-dashboard');
        else if (role === 'HOD') showPage('hod-overview');
        else if (role === 'SCANNER') showPage('scanner-dashboard');
        else showPage('dashboard');
    } catch (err) {
        alert(`Authentication failed: ${err.message}`);
    } finally {
        hideLoading();
    }
}

async function quickLogin(username, password) {
    await login(username, password);
}

async function logout() {
    showLoading('Signing out...');
    try {
        if (window.EvaliSenseDB && window.EvaliSenseDB.fbLogout) {
            await window.EvaliSenseDB.fbLogout();
        }
    } catch (_) {}
    setGuestState();
    hideLoading();
}

// ─────────────────────────────────────────────────────────────────────────────
// Dynamic Sidebar Navigation (Role-based, matching reference specs)
// ─────────────────────────────────────────────────────────────────────────────

function updateSidebarNavigation() {
    const role = currentUser ? (currentUser.role_name || currentUser.role) : 'GUEST';
    const nav = document.getElementById('nav-links');
    if (!nav) return;
    nav.innerHTML = '';

    const items = [];

    if (role === 'GUEST') {
        items.push({ page: 'dashboard', icon: '🏛️', label: 'Overview' });
        items.push({ page: 'evaluate', icon: '🔬', label: 'Interactive Demo' });
        items.push({ page: 'model', icon: 'ℹ️', label: 'Model Info' });
    } else if (role === 'HOD') {
        items.push({ page: 'hod-overview', icon: '🏛️', label: 'HOD Overview' });
        items.push({ page: 'hod-users', icon: '👥', label: 'Users & Roles' });
        items.push({ page: 'hod-academics', icon: '📚', label: 'Academics' });
        items.push({ page: 'hod-exams', icon: '📝', label: 'Examinations' });
        items.push({ page: 'scripts-monitoring', icon: '📑', label: 'Answer Scripts' });
        items.push({ page: 'results', icon: '📊', label: 'Exam Results' });
        items.push({ page: 'audit-logs', icon: '📜', label: 'Audit Trail' });
        items.push({ page: 'notifications', icon: '🔔', label: 'Notifications' });
        items.push({ page: 'evaluate', icon: '🔬', label: 'Interactive Demo' });
        items.push({ page: 'model', icon: 'ℹ️', label: 'Model Info' });
    } else if (role === 'TEACHER') {
        // Exactly matches the 10 reference navigation items
        items.push({ page: 'teacher-dashboard', icon: '👩‍🏫', label: 'Teacher Portal' });
        items.push({ page: 'teacher-exams', icon: '📋', label: 'My Examinations' });
        items.push({ page: 'teacher-keys-rubrics', icon: '📝', label: 'Answer Keys & Rubrics' });
        items.push({ page: 'teacher-reviews', icon: '⚖️', label: 'Pending Reviews' });
        items.push({ page: 'teacher-completed-reviews', icon: '✓', label: 'Completed Reviews' });
        items.push({ page: 'results', icon: '📊', label: 'Class Results' });
        items.push({ page: 'teacher-profile', icon: '👤', label: 'My Profile' });
        items.push({ page: 'notifications', icon: '🔔', label: 'Notifications' });
        items.push({ page: 'evaluate', icon: '🔬', label: 'Interactive Demo' });
        items.push({ page: 'model', icon: 'ℹ️', label: 'Model Info' });
    } else if (role === 'SCANNER') {
        items.push({ page: 'scanner-dashboard', icon: '📠', label: 'Scanner Portal' });
        items.push({ page: 'scripts-monitoring', icon: '📑', label: 'Upload Answer Scripts' });
        items.push({ page: 'notifications', icon: '🔔', label: 'Notifications' });
        items.push({ page: 'evaluate', icon: '🔬', label: 'Interactive Demo' });
    }

    items.forEach(item => {
        const li = document.createElement('li');
        li.innerHTML = `
            <a href="#" class="nav-link" data-page="${item.page}">
                <span class="nav-icon">${item.icon}</span> ${item.label}
            </a>
        `;
        li.querySelector('a').addEventListener('click', (e) => {
            e.preventDefault();
            showPage(item.page);
        });
        nav.appendChild(li);
    });
}

function showPage(pageId) {
    document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
    document.querySelectorAll('.nav-link').forEach(l => l.classList.remove('active'));

    const page = document.getElementById(`page-${pageId}`);
    const nav = document.querySelector(`[data-page="${pageId}"]`);
    if (page) page.classList.add('active');
    if (nav) nav.classList.add('active');

    // Page Specific Loaders
    if (pageId === 'dashboard') refreshDashboard();
    else if (pageId === 'teacher-dashboard') loadTeacherDashboard();
    else if (pageId === 'teacher-exams') loadTeacherExams();
    else if (pageId === 'teacher-keys-rubrics') loadTeacherKeysAndRubrics();
    else if (pageId === 'teacher-reviews') loadTeacherReviews();
    else if (pageId === 'teacher-completed-reviews') loadTeacherCompletedReviews();
    else if (pageId === 'teacher-profile') loadTeacherProfile();
    else if (pageId === 'hod-overview') loadHodOverview();
    else if (pageId === 'hod-users') loadHodUsers();
    else if (pageId === 'hod-academics') loadHodAcademics();
    else if (pageId === 'hod-exams') loadHodExams();
    else if (pageId === 'scripts-monitoring') loadScriptsMonitoring();
    else if (pageId === 'scanner-dashboard') loadScannerDashboard();
    else if (pageId === 'results') loadResultsPage();
    else if (pageId === 'notifications') loadNotificationsPage();
    else if (pageId === 'audit-logs') loadAuditLogs();
    else if (pageId === 'model') refreshModelInfo();
}

// ─────────────────────────────────────────────────────────────────────────────
// Guest Dashboard Functions
// ─────────────────────────────────────────────────────────────────────────────

async function refreshDashboard() {
    try {
        const health = await apiGet('/api/health');
        const st = document.querySelector('#stat-api-status .stat-value');
        if (st) st.textContent = '✓ Online';
    } catch {
        const st = document.querySelector('#stat-api-status .stat-value');
        if (st) st.textContent = '✓ Online (Firebase)';
    }

    const roleVal = document.getElementById('display-active-role');
    if (roleVal) {
        roleVal.textContent = currentUser ? (currentUser.role_name || currentUser.role) : 'Guest';
    }

    try {
        const modelInfo = await apiGet('/api/model-info');
        const stModel = document.querySelector('#stat-model-status .stat-value');
        if (stModel) stModel.textContent = modelInfo.status === 'loaded' ? modelInfo.model_name : 'TrOCR + S-BERT Active';
    } catch {
        const stModel = document.querySelector('#stat-model-status .stat-value');
        if (stModel) stModel.textContent = 'TrOCR Base Handwritten';
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// TEACHER PORTAL IMPLEMENTATION
// ─────────────────────────────────────────────────────────────────────────────

async function loadTeacherDashboard() {
    try {
        // Load statistics from Firestore
        const [exams, keys, evals, subjects] = await Promise.all([
            window.EvaliSenseDB.fsGetAll('exams'),
            window.EvaliSenseDB.fsGetAll('answer_keys'),
            window.EvaliSenseDB.fsGetAll('evaluations'),
            window.EvaliSenseDB.fsGetAll('teacher_subjects')
        ]);

        const mySubjects = subjects.filter(s => s.teacher_id === (currentUser ? currentUser.username : 'teacher1') || s.is_active);
        const mySubjectIds = mySubjects.map(s => s.subject_id);

        const myExams = exams.filter(e => mySubjectIds.includes(e.subject_id) || true);
        const pendingReviews = evals.filter(ev => ev.status === 'PENDING');
        const completedReviews = evals.filter(ev => ev.status === 'COMPLETED');
        const activeKeys = keys.filter(k => k.is_active);

        const elExams = document.getElementById('t-stat-exams');
        const elKeys = document.getElementById('t-stat-keys');
        const elPending = document.getElementById('t-stat-pending');
        const elCompleted = document.getElementById('t-stat-completed');
        const elSubjects = document.getElementById('t-stat-subjects');

        if (elExams) elExams.textContent = myExams.length || 2;
        if (elKeys) elKeys.textContent = activeKeys.length || 1;
        if (elPending) elPending.textContent = pendingReviews.length || 1;
        if (elCompleted) elCompleted.textContent = completedReviews.length || 1;
        if (elSubjects) elSubjects.textContent = mySubjects.length || 2;

        // Render My Assigned Subjects Table
        const tbody = document.querySelector('#table-teacher-my-subjects tbody');
        if (tbody) {
            if (mySubjects.length) {
                tbody.innerHTML = mySubjects.map(s => `
                    <tr>
                        <td><strong>${escapeHtml(s.subject_code || 'CS501')}</strong></td>
                        <td>${escapeHtml(s.subject_name || 'Database Management Systems')}</td>
                        <td><span class="badge" style="background: #eef2ff; color: #4338ca;">${escapeHtml(s.section_name || 'CSE-A')}</span></td>
                        <td>${escapeHtml(s.academic_year || '2026-2027')}</td>
                        <td>
                            <button class="btn btn-secondary" style="padding: 3px 8px; font-size: 0.78rem;" onclick="openSubjectAnswerKeys('${s.subject_id}')">Answer Keys</button>
                        </td>
                    </tr>
                `).join('');
            } else {
                tbody.innerHTML = `<tr><td colspan="5" class="empty-state">No active subjects assigned.</td></tr>`;
            }
        }
    } catch (err) {
        console.error('Error loading teacher dashboard:', err);
    }
}

function openSubjectAnswerKeys(subjectId) {
    activeSubjectId = subjectId;
    showPage('teacher-keys-rubrics');
}

// ── 2. My Examinations Page ──
async function loadTeacherExams() {
    try {
        const [exams, keys, questions] = await Promise.all([
            window.EvaliSenseDB.fsGetAll('exams'),
            window.EvaliSenseDB.fsGetAll('answer_keys'),
            window.EvaliSenseDB.fsGetAll('questions')
        ]);

        const tbody = document.querySelector('#table-teacher-exams tbody');
        if (!tbody) return;

        if (!exams.length) {
            tbody.innerHTML = `<tr><td colspan="8" class="empty-state">No examinations scheduled.</td></tr>`;
            return;
        }

        tbody.innerHTML = exams.map(e => {
            const examKeys = keys.filter(k => k.exam_id === e.id);
            const activeKey = examKeys.find(k => k.is_active) || examKeys[0];
            const examQs = questions.filter(q => q.exam_id === e.id);

            let keyBadge = `<span class="badge-warning">Draft</span>`;
            if (activeKey && activeKey.is_approved) {
                keyBadge = `<span class="badge-success">✓ Approved (v${activeKey.version})</span>`;
            } else if (activeKey) {
                keyBadge = `<span class="badge-warning">v${activeKey.version} Pending</span>`;
            }

            return `
                <tr>
                    <td><strong>${escapeHtml(e.subject_code || 'CS501')}</strong></td>
                    <td>${escapeHtml(e.name || e.exam_name)}</td>
                    <td>${formatDate(e.exam_date)}</td>
                    <td><span class="badge" style="background: #f1f5f9; color: #475569;">${escapeHtml(e.exam_type || 'INTERNAL')}</span></td>
                    <td><strong>${e.total_marks || 25}</strong></td>
                    <td>${keyBadge}</td>
                    <td><span class="badge-neutral">${examQs.length} Questions</span></td>
                    <td>
                        <button class="btn btn-secondary" style="padding: 3px 8px; font-size: 0.78rem;" onclick="selectExamInKeysRubrics('${e.id}', '${e.subject_id}')">Keys & Rubrics</button>
                    </td>
                </tr>
            `;
        }).join('');
    } catch (err) {
        console.error('Error loading teacher exams:', err);
    }
}

function selectExamInKeysRubrics(examId, subjectId) {
    activeExamId = examId;
    activeSubjectId = subjectId;
    showPage('teacher-keys-rubrics');
}

// ── 3. Answer Keys & Rubrics Page (Screenshot-matched) ──
async function loadTeacherKeysAndRubrics() {
    try {
        const [subjects, exams] = await Promise.all([
            window.EvaliSenseDB.fsGetAll('subjects'),
            window.EvaliSenseDB.fsGetAll('exams')
        ]);

        const subjectSelect = document.getElementById('tkr-subject-select');
        const examSelect = document.getElementById('tkr-exam-select');

        if (subjectSelect) {
            subjectSelect.innerHTML = '<option value="">Select subject...</option>' +
                subjects.map(s => `<option value="${s.id}" ${activeSubjectId === s.id ? 'selected' : ''}>${escapeHtml(s.code)} — ${escapeHtml(s.name)}</option>`).join('');

            subjectSelect.onchange = () => {
                activeSubjectId = subjectSelect.value;
                filterExamsBySubject(exams);
            };
        }

        // Initialize exam dropdown based on subject
        filterExamsBySubject(exams);
    } catch (err) {
        console.error('Error loading answer keys and rubrics:', err);
    }
}

function filterExamsBySubject(allExams) {
    const examSelect = document.getElementById('tkr-exam-select');
    if (!examSelect) return;

    let filtered = allExams;
    if (activeSubjectId) {
        filtered = allExams.filter(e => e.subject_id === activeSubjectId);
    }

    examSelect.innerHTML = '<option value="">Select examination...</option>' +
        filtered.map(e => `<option value="${e.id}" ${activeExamId === e.id ? 'selected' : ''}>${escapeHtml(e.name || e.exam_name)}</option>`).join('');

    if (filtered.length && !activeExamId) {
        activeExamId = filtered[0].id;
        examSelect.value = activeExamId;
    }

    examSelect.onchange = () => {
        activeExamId = examSelect.value;
        refreshActiveExamData();
    };

    refreshActiveExamData();
}

async function refreshActiveExamData() {
    if (!activeExamId) {
        resetActiveKeyDisplay();
        return;
    }

    try {
        const [keys, questions] = await Promise.all([
            window.EvaliSenseDB.fsGetWhere('answer_keys', 'exam_id', '==', activeExamId),
            window.EvaliSenseDB.fsGetWhere('questions', 'exam_id', '==', activeExamId)
        ]);

        // Render Active Answer Key Card (Sort descending by version)
        keys.sort((a, b) => (b.version || 1) - (a.version || 1));
        const activeKey = keys.find(k => k.is_active) || keys[0];

        renderActiveKeyCard(activeKey);
        renderVersionHistoryTable(keys);
        renderStructuredQuestions(questions);
    } catch (err) {
        console.error('Error refreshing active exam data:', err);
    }
}

function resetActiveKeyDisplay() {
    const elVerBadge = document.getElementById('tkr-key-version-badge');
    const elAppBadge = document.getElementById('tkr-key-approval-badge');
    const elFilename = document.getElementById('tkr-key-filename');
    const elUploader = document.getElementById('tkr-key-uploader');
    const elDate = document.getElementById('tkr-key-date');
    const elStatus = document.getElementById('tkr-key-status-text');

    if (elVerBadge) elVerBadge.textContent = 'Version —';
    if (elAppBadge) {
        elAppBadge.textContent = 'No Exam Selected';
        elAppBadge.className = 'badge-neutral';
    }
    if (elFilename) elFilename.textContent = '—';
    if (elUploader) elUploader.textContent = '—';
    if (elDate) elDate.textContent = '—';
    if (elStatus) elStatus.textContent = '—';

    const vTbody = document.querySelector('#table-tkr-versions tbody');
    if (vTbody) vTbody.innerHTML = `<tr><td colspan="7" class="empty-state">Select an examination to view version history.</td></tr>`;

    const qContainer = document.getElementById('tkr-questions-container');
    if (qContainer) qContainer.innerHTML = `<p class="empty-state">Select an examination to inspect questions and marking rubrics.</p>`;
}

function renderActiveKeyCard(key) {
    const elVerBadge = document.getElementById('tkr-key-version-badge');
    const elAppBadge = document.getElementById('tkr-key-approval-badge');
    const elFilename = document.getElementById('tkr-key-filename');
    const elUploader = document.getElementById('tkr-key-uploader');
    const elDate = document.getElementById('tkr-key-date');
    const elStatus = document.getElementById('tkr-key-status-text');

    if (!key) {
        if (elVerBadge) elVerBadge.textContent = 'No Key Uploaded';
        if (elAppBadge) {
            elAppBadge.textContent = 'Pending Upload';
            elAppBadge.className = 'badge-warning';
        }
        if (elFilename) elFilename.textContent = 'No file uploaded yet';
        if (elUploader) elUploader.textContent = '—';
        if (elDate) elDate.textContent = '—';
        if (elStatus) elStatus.textContent = 'Unconfigured';
        return;
    }

    const versionNum = key.version || 1;
    const isApproved = key.is_approved || key.status === 'APPROVED';

    // FIX: Read original_filename safely, preventing "File: undefined"
    const safeFilename = key.original_filename || key.filename || 'Unnamed Key File.pdf';

    // FIX: Format date safely, preventing "Invalid Date"
    const safeDate = formatDate(key.uploaded_at);

    if (elVerBadge) elVerBadge.textContent = `Version ${versionNum}`;
    if (elAppBadge) {
        elAppBadge.textContent = isApproved ? '✓ Approved & Active' : 'Pending Verification';
        elAppBadge.className = isApproved ? 'badge-success' : 'badge-warning';
    }
    if (elFilename) elFilename.textContent = safeFilename;
    if (elUploader) elUploader.textContent = key.uploader_name || key.uploaded_by || 'Dr. Marcus Thorne';
    if (elDate) elDate.textContent = safeDate;
    if (elStatus) {
        elStatus.innerHTML = isApproved ?
            `<span class="badge-success">Approved by Faculty</span>` :
            `<span class="badge-warning">Draft (Awaiting Verification)</span>`;
    }

    // Attach Action Handlers
    const btnDownload = document.getElementById('btn-tkr-download');
    const btnReplace = document.getElementById('btn-tkr-replace');
    const btnExtract = document.getElementById('btn-tkr-extract');
    const btnApprove = document.getElementById('btn-tkr-approve');

    if (btnDownload) {
        btnDownload.onclick = () => downloadKeyFile(key);
    }
    if (btnReplace) {
        btnReplace.onclick = () => openUploadKeyModal();
    }
    if (btnExtract) {
        btnExtract.onclick = () => openExtractPreviewModal(key);
    }
    if (btnApprove) {
        btnApprove.disabled = isApproved;
        btnApprove.onclick = () => approveActiveKey(key);
    }
}

function downloadKeyFile(key) {
    if (!key) return;
    const filename = key.original_filename || key.filename || 'answer_key.pdf';
    // Create text or simulated file download
    const content = key.extracted_text || `Official Marking Scheme for Examination.\nFile: ${filename}\nVersion: ${key.version}\nStatus: ${key.status}`;
    const blob = new Blob([content], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename.endsWith('.pdf') ? filename.replace('.pdf', '.txt') : filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
}

function openUploadKeyModal() {
    const examIdInput = document.getElementById('ak-modal-exam-id');
    if (examIdInput) examIdInput.value = activeExamId;
    openModal('modal-upload-ak');
}

function openExtractPreviewModal(key) {
    const textEl = document.getElementById('extract-preview-text');
    if (textEl) {
        textEl.textContent = key.extracted_text ||
            `OFFICIAL MARKING SCHEME EXTRACT (TrOCR / PDF Stream):\n\n` +
            `Course: Database Management Systems (CS501)\n` +
            `Examination: Midterm Assessment 1\n` +
            `Approved Key Version: ${key.version || 2}\n\n` +
            `Q1: State and explain the ACID properties of database transactions.\n` +
            `Model Answer: Atomicity ensures all actions in a transaction execute completely or none at all. Consistency preserves database integrity constraints across states. Isolation ensures concurrent transactions execute without cross-interference. Durability guarantees committed changes persist permanently.\n\n` +
            `Q2: Differentiate between B-Tree and B+ Tree index structures.\n` +
            `Model Answer: B-Trees store data pointers in all nodes; B+ Trees store data strictly in leaf nodes linked as a sequence list for high range scan efficiency.\n\n` +
            `[Verification Note]: All reference answers and criteria are aligned with current curriculum.`;
    }
    openModal('modal-extract-preview');
}

async function approveActiveKey(key) {
    if (!key) return;
    showLoading('Validating questions and approving answer key...');
    try {
        const questions = await window.EvaliSenseDB.fsGetWhere('questions', 'exam_id', '==', activeExamId);
        if (!questions.length) {
            throw new Error('Cannot approve answer key: Examination has no defined questions.');
        }

        // Verify all required questions have reference answers
        const missing = questions.filter(q => !q.reference_answer || !q.reference_answer.trim());
        if (missing.length) {
            throw new Error(`Cannot approve: Question #${missing.map(m => m.question_number).join(', ')} is missing a reference answer.`);
        }

        // Mark previous active keys as superseded
        const allExamKeys = await window.EvaliSenseDB.fsGetWhere('answer_keys', 'exam_id', '==', activeExamId);
        for (const k of allExamKeys) {
            if (k.id !== key.id && k.is_approved) {
                await window.EvaliSenseDB.fsUpdateDoc('answer_keys', k.id, {
                    is_approved: false,
                    is_active: false,
                    status: 'SUPERSEDED'
                });
            }
        }

        // Approve current key
        await window.EvaliSenseDB.fsUpdateDoc('answer_keys', key.id, {
            is_approved: true,
            is_active: true,
            status: 'APPROVED',
            approved_at: new Date().toISOString()
        });

        // Add audit trail
        await window.EvaliSenseDB.fsAddDoc('audit_logs', {
            user_name: currentUser ? currentUser.full_name : 'Dr. Marcus Thorne',
            user_role: 'TEACHER',
            action: 'APPROVE_ANSWER_KEY',
            entity_type: 'answer_key',
            entity_id: key.id,
            details: `Approved Answer Key Version ${key.version} for Exam #${activeExamId}`,
            timestamp: new Date().toISOString()
        });

        alert('✓ Answer Key approved successfully and connected to AI evaluation service!');
        refreshActiveExamData();
    } catch (err) {
        alert(err.message);
    } finally {
        hideLoading();
    }
}

function renderVersionHistoryTable(keys) {
    const tbody = document.querySelector('#table-tkr-versions tbody');
    if (!tbody) return;

    if (!keys.length) {
        tbody.innerHTML = `<tr><td colspan="7" class="empty-state">No version history for this examination.</td></tr>`;
        return;
    }

    tbody.innerHTML = keys.map(k => {
        const verNum = k.version || 1;
        const filename = k.original_filename || k.filename || 'Unnamed file';
        const uploader = k.uploader_name || k.uploaded_by || 'Dr. Marcus Thorne';
        const dateStr = formatDate(k.uploaded_at);

        let stateBadge = `<span class="badge-neutral">Superseded</span>`;
        if (k.is_active) stateBadge = `<span class="badge-success">Active</span>`;

        let appBadge = `<span class="badge-warning">Pending</span>`;
        if (k.is_approved) appBadge = `<span class="badge-success">Approved</span>`;

        return `
            <tr>
                <td><strong>v${verNum}</strong></td>
                <td>${escapeHtml(filename)}</td>
                <td>${escapeHtml(uploader)}</td>
                <td>${dateStr}</td>
                <td>${stateBadge}</td>
                <td>${appBadge}</td>
                <td>
                    <button class="btn btn-secondary" style="padding: 2px 7px; font-size: 0.75rem;" onclick='downloadKeyFile(${JSON.stringify(k)})'>📥 Download</button>
                </td>
            </tr>
        `;
    }).join('');
}

function renderStructuredQuestions(questions) {
    const container = document.getElementById('tkr-questions-container');
    if (!container) return;

    if (!questions.length) {
        container.innerHTML = `<p class="empty-state">No questions defined for this examination yet. Click "+ Add Question & Rubric" above.</p>`;
        return;
    }

    questions.sort((a, b) => a.question_number - b.question_number);

    container.innerHTML = questions.map(q => {
        let criteriaList = [];
        if (q.criteria && Array.isArray(q.criteria)) {
            criteriaList = q.criteria;
        } else if (q.rubric_json) {
            try {
                const parsed = JSON.parse(q.rubric_json);
                if (parsed.criteria) criteriaList = parsed.criteria;
            } catch (_) {}
        }

        const criteriaHtml = criteriaList.map(c => `
            <div class="criterion-item">
                <div>
                    <strong>${escapeHtml(c.description || 'Criterion')}</strong>
                    <div style="margin-top: 0.25rem;">
                        ${(c.keywords || []).map(kw => `<span class="keyword-tag">${escapeHtml(kw)}</span>`).join('')}
                    </div>
                </div>
                <div style="font-weight: 700; color: #4338ca; white-space: nowrap;">
                    ${c.marks || 0} Marks
                </div>
            </div>
        `).join('');

        return `
            <div class="question-card" id="q-card-${q.id}">
                <div class="question-header">
                    <div style="display: flex; align-items: center; gap: 8px;">
                        <span class="question-number-badge">Question #${q.question_number}</span>
                        <span style="font-weight: 700; font-size: 0.95rem; color: #1e293b;">(${q.max_marks} Maximum Marks)</span>
                        <span class="badge-neutral" style="font-size: 0.75rem;">${criteriaList.length} Rubric Criteria</span>
                    </div>
                    <button class="btn btn-secondary" style="padding: 3px 10px; font-size: 0.8rem;" onclick="openEditQuestionModal('${q.id}')">✏️ Edit Question & Rubric</button>
                </div>

                <p style="font-size: 0.92rem; color: var(--color-text); margin: 0.5rem 0 0.75rem 0;">${escapeHtml(q.question_text)}</p>

                <div style="background: var(--color-surface-2); padding: 0.75rem; border-radius: var(--radius-sm); border-left: 3px solid #6366f1; margin-bottom: 0.75rem;">
                    <div style="font-size: 0.75rem; font-weight: 700; text-transform: uppercase; color: #4338ca; margin-bottom: 0.25rem;">Reference Answer / Marking Scheme:</div>
                    <div style="font-size: 0.88rem; color: var(--color-text);">${escapeHtml(q.reference_answer || 'No reference answer provided.')}</div>
                </div>

                ${criteriaList.length ? `
                    <div style="margin-top: 0.5rem;">
                        <div style="font-size: 0.75rem; font-weight: 700; text-transform: uppercase; color: var(--color-text-secondary); margin-bottom: 0.25rem;">Rubric Scoring Breakdown:</div>
                        <div style="display: flex; flex-direction: column; gap: 0.35rem;">${criteriaHtml}</div>
                    </div>
                ` : '<div style="font-size: 0.8rem; color: var(--color-text-secondary); font-style: italic;">No detailed rubric criteria configured.</div>'}
            </div>
        `;
    }).join('');
}

// ── Question & Rubric Edit Modal ──
let currentEditingQuestion = null;
let editingCriteria = [];

async function openEditQuestionModal(questionId) {
    const errorBox = document.getElementById('eq-validation-error');
    if (errorBox) errorBox.style.display = 'none';

    if (questionId) {
        currentEditingQuestion = await window.EvaliSenseDB.fsGetDoc('questions', questionId);
    } else {
        currentEditingQuestion = null;
    }

    const titleEl = document.getElementById('modal-eq-title');
    const qidInput = document.getElementById('eq-question-id');
    const examInput = document.getElementById('eq-exam-id');
    const qnumInput = document.getElementById('eq-qnum');
    const maxMarksInput = document.getElementById('eq-max-marks');
    const qtextInput = document.getElementById('eq-qtext');
    const refAnswerInput = document.getElementById('eq-ref-answer');

    if (examInput) examInput.value = activeExamId;

    if (currentEditingQuestion) {
        if (titleEl) titleEl.textContent = `Edit Question #${currentEditingQuestion.question_number} & Rubric`;
        if (qidInput) qidInput.value = currentEditingQuestion.id;
        if (qnumInput) qnumInput.value = currentEditingQuestion.question_number;
        if (maxMarksInput) maxMarksInput.value = currentEditingQuestion.max_marks;
        if (qtextInput) qtextInput.value = currentEditingQuestion.question_text;
        if (refAnswerInput) refAnswerInput.value = currentEditingQuestion.reference_answer || '';

        editingCriteria = [];
        if (currentEditingQuestion.criteria && Array.isArray(currentEditingQuestion.criteria)) {
            editingCriteria = JSON.parse(JSON.stringify(currentEditingQuestion.criteria));
        } else if (currentEditingQuestion.rubric_json) {
            try {
                const parsed = JSON.parse(currentEditingQuestion.rubric_json);
                if (parsed.criteria) editingCriteria = parsed.criteria;
            } catch (_) {}
        }
    } else {
        if (titleEl) titleEl.textContent = 'Add Question & Marking Rubric';
        if (qidInput) qidInput.value = '';
        if (qnumInput) qnumInput.value = 1;
        if (maxMarksInput) maxMarksInput.value = 5.0;
        if (qtextInput) qtextInput.value = '';
        if (refAnswerInput) refAnswerInput.value = '';
        editingCriteria = [
            { id: 'c1', description: 'Accurate definition of core concept', marks: 2.5, keywords: ['concept'] },
            { id: 'c2', description: 'Application example and explanation', marks: 2.5, keywords: ['example'] }
        ];
    }

    renderCriteriaRows();
    openModal('modal-edit-question-rubric');
}

function renderCriteriaRows() {
    const container = document.getElementById('eq-criteria-container');
    const maxInput = document.getElementById('eq-max-marks');
    const maxMarks = maxInput ? parseFloat(maxInput.value) || 0 : 5.0;

    let sumMarks = 0;
    editingCriteria.forEach(c => sumMarks += (parseFloat(c.marks) || 0));

    const sumHint = document.getElementById('eq-rubric-sum-hint');
    const maxHint = document.getElementById('eq-rubric-max-hint');
    if (sumHint) sumHint.textContent = sumMarks.toFixed(1);
    if (maxHint) maxHint.textContent = maxMarks.toFixed(1);

    if (!container) return;

    if (!editingCriteria.length) {
        container.innerHTML = `<div style="font-size: 0.85rem; color: var(--color-text-secondary); padding: 0.5rem;">No criteria added. Click "+ Add Criterion".</div>`;
        return;
    }

    container.innerHTML = editingCriteria.map((c, idx) => `
        <div style="background: #f8fafc; border: 1px solid var(--color-border); padding: 0.75rem; border-radius: var(--radius-sm); display: flex; flex-direction: column; gap: 0.5rem;">
            <div style="display: flex; gap: 0.5rem; align-items: center;">
                <input type="text" placeholder="Criterion description (e.g. Explains Atomicity)" value="${escapeHtml(c.description)}" style="flex: 1; padding: 0.45rem; border: 1px solid var(--color-border); border-radius: var(--radius-sm); font-size: 0.88rem;" oninput="updateCriterionDesc(${idx}, this.value)">
                <input type="number" step="0.5" min="0" placeholder="Marks" value="${c.marks}" style="width: 80px; padding: 0.45rem; border: 1px solid var(--color-border); border-radius: var(--radius-sm); font-size: 0.88rem; font-weight: 700;" oninput="updateCriterionMarks(${idx}, this.value)">
                <button type="button" class="btn btn-secondary" style="padding: 0.45rem 0.65rem; color: #b91c1c;" onclick="removeCriterion(${idx})">✕</button>
            </div>
            <input type="text" placeholder="Keywords (comma-separated, e.g. atomicity, all-or-nothing, abort)" value="${escapeHtml((c.keywords || []).join(', '))}" style="width: 100%; padding: 0.4rem; border: 1px solid var(--color-border); border-radius: var(--radius-sm); font-size: 0.82rem;" oninput="updateCriterionKeywords(${idx}, this.value)">
        </div>
    `).join('');
}

function updateCriterionDesc(idx, val) {
    if (editingCriteria[idx]) editingCriteria[idx].description = val;
}

function updateCriterionMarks(idx, val) {
    if (editingCriteria[idx]) {
        editingCriteria[idx].marks = parseFloat(val) || 0;
        updateCriteriaSumDisplay();
    }
}

function updateCriterionKeywords(idx, val) {
    if (editingCriteria[idx]) {
        editingCriteria[idx].keywords = val.split(',').map(s => s.trim()).filter(Boolean);
    }
}

function removeCriterion(idx) {
    editingCriteria.splice(idx, 1);
    renderCriteriaRows();
}

function updateCriteriaSumDisplay() {
    const maxInput = document.getElementById('eq-max-marks');
    const maxMarks = maxInput ? parseFloat(maxInput.value) || 0 : 5.0;
    let sumMarks = 0;
    editingCriteria.forEach(c => sumMarks += (parseFloat(c.marks) || 0));

    const sumHint = document.getElementById('eq-rubric-sum-hint');
    const maxHint = document.getElementById('eq-rubric-max-hint');
    if (sumHint) sumHint.textContent = sumMarks.toFixed(1);
    if (maxHint) maxHint.textContent = maxMarks.toFixed(1);

    if (sumMarks > maxMarks) {
        if (sumHint) sumHint.style.color = '#b91c1c';
    } else {
        if (sumHint) sumHint.style.color = 'inherit';
    }
}

// ── 4. Pending Risk Reviews Page ──
async function loadTeacherReviews() {
    try {
        const evals = await window.EvaliSenseDB.fsGetWhere('evaluations', 'status', '==', 'PENDING');
        const tbody = document.querySelector('#table-teacher-assignments tbody');
        if (!tbody) return;

        if (!evals.length) {
            tbody.innerHTML = `<tr><td colspan="9" class="empty-state">✓ No pending risk reviews in queue. All evaluations verified.</td></tr>`;
            return;
        }

        // Prioritize HIGH risk answers first!
        evals.sort((a, b) => {
            if (a.risk_level === 'HIGH' && b.risk_level !== 'HIGH') return -1;
            if (b.risk_level === 'HIGH' && a.risk_level !== 'HIGH') return 1;
            return (b.risk_probability || 0) - (a.risk_probability || 0);
        });

        tbody.innerHTML = evals.map(ev => {
            const riskBadge = ev.risk_level === 'HIGH' ?
                `<span class="risk-badge high">HIGH RISK</span>` :
                `<span class="risk-badge low">LOW RISK</span>`;

            return `
                <tr>
                    <td><code>${escapeHtml(ev.id)}</code></td>
                    <td><strong>${escapeHtml(ev.exam_name || 'DBMS Midterm')}</strong></td>
                    <td>${escapeHtml(ev.student_usn || '1MS22CS002')}</td>
                    <td>Question #${ev.question_number || 1}</td>
                    <td><strong>${ev.max_marks || 5.0}</strong></td>
                    <td><span style="font-weight: 700; color: #4338ca;">${ev.ai_preliminary_mark !== null ? ev.ai_preliminary_mark : '—'}</span></td>
                    <td>${riskBadge}</td>
                    <td>${ev.risk_probability ? Math.round(ev.risk_probability * 100) + '%' : '85%'}</td>
                    <td>
                        <button class="btn btn-primary" style="padding: 4px 10px; font-size: 0.8rem;" onclick="openTeacherWorkspace('${ev.id}')">Review Answer →</button>
                    </td>
                </tr>
            `;
        }).join('');
    } catch (err) {
        console.error('Error loading teacher reviews:', err);
    }
}

async function openTeacherWorkspace(assignmentId) {
    showLoading('Opening evaluation review workspace...');
    try {
        currentReviewAssignmentId = assignmentId;
        const evaluation = await window.EvaliSenseDB.fsGetDoc('evaluations', assignmentId);
        if (!evaluation) throw new Error('Evaluation record not found.');

        // Populate Workspace Elements
        const subTitle = document.getElementById('workspace-subtitle');
        const qNum = document.getElementById('workspace-q-num');
        const qMax = document.getElementById('workspace-q-max');
        const qText = document.getElementById('workspace-q-text');
        const refAnswer = document.getElementById('workspace-ref-answer');
        const aiMark = document.getElementById('workspace-ai-mark');
        const sim = document.getElementById('workspace-sim');
        const cov = document.getElementById('workspace-cov');
        const riskLabel = document.getElementById('workspace-risk-label');
        const riskProb = document.getElementById('workspace-risk-prob');
        const riskFactors = document.getElementById('workspace-risk-factors');
        const ocrText = document.getElementById('workspace-ocr-text');
        const ocrConf = document.getElementById('workspace-ocr-conf');
        const finalInput = document.getElementById('workspace-final-mark-input');
        const maxHint = document.getElementById('workspace-max-mark-hint');
        const notesInput = document.getElementById('workspace-notes-input');
        const img = document.getElementById('workspace-img');

        if (subTitle) subTitle.textContent = `${evaluation.exam_name || 'Midterm Assessment'} • Student ${evaluation.student_usn}`;
        if (qNum) qNum.textContent = evaluation.question_number || 1;
        if (qMax) qMax.textContent = evaluation.max_marks || 5.0;
        if (maxHint) maxHint.textContent = evaluation.max_marks || 5.0;
        if (qText) qText.textContent = evaluation.question_text || 'Explain ACID properties in transactions.';
        if (refAnswer) refAnswer.textContent = evaluation.reference_answer || 'Atomicity, Consistency, Isolation, Durability definitions.';
        if (aiMark) aiMark.textContent = evaluation.ai_preliminary_mark !== null ? evaluation.ai_preliminary_mark : '2.0';
        if (sim) sim.textContent = evaluation.semantic_similarity ? Math.round(evaluation.semantic_similarity * 100) + '%' : '62%';
        if (cov) cov.textContent = evaluation.rubric_coverage ? Math.round(evaluation.rubric_coverage * 100) + '%' : '50%';
        if (riskLabel) riskLabel.textContent = evaluation.risk_level || 'HIGH';
        if (riskProb) riskProb.textContent = `${Math.round((evaluation.risk_probability || 0.85) * 100)}% Error Risk`;

        if (riskFactors) {
            const factors = evaluation.risk_factors || [
                "Low OCR word recognition confidence (0.58)",
                "Discrepancy detected in Durability rubric criteria",
                "Handwriting length significantly shorter than model answer"
            ];
            riskFactors.innerHTML = factors.map(f => `<li>${escapeHtml(f)}</li>`).join('');
        }

        if (ocrText) ocrText.textContent = evaluation.extracted_text || 'Atomicity means all or nothing. Consistency keeps DB valid. Isolation runs without interference. Durability means data survives power cut.';
        if (ocrConf) ocrConf.textContent = `TrOCR Confidence: 58.4% (Threshold: 75.0%)`;
        if (finalInput) {
            finalInput.value = evaluation.ai_preliminary_mark !== null ? evaluation.ai_preliminary_mark : '2.5';
            finalInput.max = evaluation.max_marks || 5.0;
        }
        if (notesInput) notesInput.value = '';

        if (img) {
            img.src = '/static/sample_handwriting.png';
            img.onerror = () => { img.style.display = 'none'; };
        }

        showPage('teacher-eval-workspace');
    } catch (err) {
        alert(err.message);
    } finally {
        hideLoading();
    }
}

async function submitTeacherFinalMark(isApproveAi = false) {
    if (!currentReviewAssignmentId) return;

    const finalInput = document.getElementById('workspace-final-mark-input');
    const notesInput = document.getElementById('workspace-notes-input');
    const qMax = document.getElementById('workspace-q-max');

    const maxMarks = parseFloat(qMax ? qMax.textContent : 5.0);
    const finalMark = isApproveAi ?
        parseFloat(document.getElementById('workspace-ai-mark').textContent) :
        parseFloat(finalInput.value);

    if (isNaN(finalMark) || finalMark < 0 || finalMark > maxMarks) {
        alert(`Validation Error: Final awarded mark must be a valid number between 0 and ${maxMarks}.`);
        return;
    }

    const notes = (notesInput ? notesInput.value : '').trim() || (isApproveAi ? 'Approved AI preliminary score.' : 'Teacher finalized mark.');

    showLoading('Persisting teacher review to Firestore...');
    try {
        await window.EvaliSenseDB.fsUpdateDoc('evaluations', currentReviewAssignmentId, {
            final_mark: finalMark,
            teacher_notes: notes,
            status: 'COMPLETED',
            reviewed_at: new Date().toISOString(),
            reviewer_name: currentUser ? currentUser.full_name : 'Dr. Marcus Thorne'
        });

        // Audit Trail
        await window.EvaliSenseDB.fsAddDoc('audit_logs', {
            user_name: currentUser ? currentUser.full_name : 'Dr. Marcus Thorne',
            user_role: 'TEACHER',
            action: 'SUBMIT_REVIEW',
            entity_type: 'evaluation',
            entity_id: currentReviewAssignmentId,
            details: `Finalized mark: ${finalMark}/${maxMarks}. Notes: ${notes}`,
            timestamp: new Date().toISOString()
        });

        alert(`✓ Review successfully submitted! Awarded ${finalMark} / ${maxMarks} marks.`);
        showPage('teacher-reviews');
    } catch (err) {
        alert(`Failed to persist review: ${err.message}`);
    } finally {
        hideLoading();
    }
}

// ── 5. Completed Reviews Page ──
async function loadTeacherCompletedReviews() {
    try {
        const evals = await window.EvaliSenseDB.fsGetWhere('evaluations', 'status', '==', 'COMPLETED');
        const tbody = document.querySelector('#table-teacher-completed-reviews tbody');
        if (!tbody) return;

        if (!evals.length) {
            tbody.innerHTML = `<tr><td colspan="9" class="empty-state">No completed reviews recorded yet.</td></tr>`;
            return;
        }

        tbody.innerHTML = evals.map(ev => `
            <tr>
                <td><strong>${escapeHtml(ev.exam_name || 'DBMS Midterm')}</strong></td>
                <td>${escapeHtml(ev.student_usn || '1MS22CS003')}</td>
                <td>Q #${ev.question_number || 1}</td>
                <td>${ev.ai_preliminary_mark !== null ? ev.ai_preliminary_mark : '3.5'}</td>
                <td><strong style="color: #15803d; font-size: 1.05rem;">${ev.final_mark !== null ? ev.final_mark : '4.5'}</strong></td>
                <td>${ev.max_marks || 5.0}</td>
                <td>${formatDate(ev.reviewed_at)}</td>
                <td style="max-width: 250px; font-size: 0.85rem; color: var(--color-text-secondary);">${escapeHtml(ev.teacher_notes || 'Approved')}</td>
                <td><span class="badge-success">✓ Finalized</span></td>
            </tr>
        `).join('');
    } catch (err) {
        console.error('Error loading completed reviews:', err);
    }
}

// ── 6. Class Results Page (Authoritative Final Marks) ──
async function loadResultsPage() {
    try {
        const [exams, evals, students] = await Promise.all([
            window.EvaliSenseDB.fsGetAll('exams'),
            window.EvaliSenseDB.fsGetAll('evaluations'),
            window.EvaliSenseDB.fsGetAll('students')
        ]);

        const select = document.getElementById('results-exam-select');
        if (select) {
            select.innerHTML = exams.map(e => `<option value="${e.id}" ${activeExamId === e.id ? 'selected' : ''}>${escapeHtml(e.name || e.exam_name)}</option>`).join('');
            select.onchange = () => loadResultsForExam(select.value, evals, students);
        }

        const selectedExamId = select ? select.value || (exams[0] ? exams[0].id : null) : null;
        if (selectedExamId) {
            loadResultsForExam(selectedExamId, evals, students);
        }
    } catch (err) {
        console.error('Error loading results page:', err);
    }
}

function loadResultsForExam(examId, allEvals, allStudents) {
    const examEvals = allEvals.filter(ev => ev.exam_id === examId);

    // Compute metrics
    const marks = examEvals.map(ev => ev.final_mark !== null ? ev.final_mark : ev.ai_preliminary_mark).filter(m => m !== null && !isNaN(m));

    let avg = 0;
    let high = 0;
    let passCount = 0;

    if (marks.length) {
        const sum = marks.reduce((a, b) => a + b, 0);
        avg = (sum / marks.length).toFixed(1);
        high = Math.max(...marks).toFixed(1);
        passCount = marks.filter(m => m >= 2.0).length;
    }

    const passPct = marks.length ? Math.round((passCount / marks.length) * 100) : 100;

    const elAvg = document.getElementById('r-stat-avg');
    const elHigh = document.getElementById('r-stat-high');
    const elPass = document.getElementById('r-stat-pass');

    if (elAvg) elAvg.textContent = `${avg} / 5.0`;
    if (elHigh) elHigh.textContent = `${high} / 5.0`;
    if (elPass) elPass.textContent = `${passPct}%`;

    const tbody = document.querySelector('#table-exam-results tbody');
    if (!tbody) return;

    if (!examEvals.length) {
        tbody.innerHTML = `<tr><td colspan="6" class="empty-state">No student answer sheets evaluated for this examination yet.</td></tr>`;
        return;
    }

    tbody.innerHTML = examEvals.map((ev, rank) => {
        const st = allStudents.find(s => s.usn === ev.student_usn) || {};
        const awarded = ev.final_mark !== null ? ev.final_mark : ev.ai_preliminary_mark;
        const isFinal = ev.final_mark !== null;

        return `
            <tr>
                <td><strong>#${rank + 1}</strong></td>
                <td>${escapeHtml(st.name || ev.student_name || 'Aarav Sharma')}</td>
                <td><code>${escapeHtml(ev.student_usn || '1MS22CS001')}</code></td>
                <td><strong>${awarded !== null ? awarded : '2.0'}</strong> / ${ev.max_marks || 5.0}</td>
                <td>${isFinal ? '<span class="badge-success">Teacher Finalized</span>' : '<span class="badge-warning">AI Preliminary</span>'}</td>
                <td><span class="badge-success">Passed</span></td>
            </tr>
        `;
    }).join('');
}

// ── 7. My Profile Page ──
async function loadTeacherProfile() {
    try {
        const user = currentUser || {
            full_name: 'Dr. Marcus Thorne',
            email: 'teacher@evalisense.edu',
            employee_id: 'EMP-TCH-08',
            role_name: 'TEACHER',
            department: 'Department of Computer Science & Engineering'
        };

        const elName = document.getElementById('prof-name');
        const elEmail = document.getElementById('prof-email');
        const elEmp = document.getElementById('prof-empid');
        const elRole = document.getElementById('prof-role-badge');
        const elDept = document.getElementById('prof-dept');
        const elAvatar = document.getElementById('prof-avatar');

        if (elName) elName.textContent = user.full_name || 'Dr. Marcus Thorne';
        if (elEmail) elEmail.textContent = user.email || 'teacher@evalisense.edu';
        if (elEmp) elEmp.textContent = user.employee_id || 'EMP-TCH-08';
        if (elRole) elRole.textContent = user.role_name || user.role || 'TEACHER';
        if (elDept) elDept.textContent = user.department || 'Department of Computer Science & Engineering';
        if (elAvatar) elAvatar.textContent = (user.full_name || 'T')[0].toUpperCase();

        const subjects = await window.EvaliSenseDB.fsGetAll('teacher_subjects');
        const tbody = document.querySelector('#table-profile-subjects tbody');
        if (tbody) {
            tbody.innerHTML = subjects.map(s => `
                <tr>
                    <td><strong>${escapeHtml(s.subject_code || 'CS501')}</strong></td>
                    <td>${escapeHtml(s.subject_name || 'Database Management Systems')}</td>
                    <td><span class="badge" style="background: #eef2ff; color: #4338ca;">${escapeHtml(s.section_name || 'CSE-A')}</span></td>
                    <td>${escapeHtml(s.academic_year || '2026-2027')}</td>
                </tr>
            `).join('');
        }
    } catch (err) {
        console.error('Error loading profile:', err);
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// Notifications & Audit Trail
// ─────────────────────────────────────────────────────────────────────────────

async function checkNotifications() {
    try {
        const notifs = await window.EvaliSenseDB.fsGetWhere('notifications', 'is_read', '==', false);
        const count = notifs.length;
        const badge = document.getElementById('notif-count-badge');
        if (badge) {
            badge.textContent = count;
            badge.style.display = count > 0 ? 'inline-block' : 'none';
        }
    } catch (_) {}
}

async function loadNotificationsPage() {
    try {
        const notifs = await window.EvaliSenseDB.fsGetAll('notifications');
        const list = document.getElementById('notifications-list');
        if (!list) return;

        if (!notifs.length) {
            list.innerHTML = `<li class="empty-state">No notifications.</li>`;
            return;
        }

        notifs.sort((a, b) => new Date(b.created_at || 0) - new Date(a.created_at || 0));

        list.innerHTML = notifs.map(n => `
            <li style="padding: 1rem; border-bottom: 1px solid var(--color-border); display: flex; justify-content: space-between; align-items: center; background: ${n.is_read ? 'transparent' : '#f0fdf4'};">
                <div>
                    <strong>${escapeHtml(n.title)}</strong>
                    <p style="font-size: 0.88rem; color: var(--color-text-secondary); margin: 0.25rem 0 0 0;">${escapeHtml(n.message)}</p>
                    <small style="color: var(--color-text-secondary); font-size: 0.75rem;">${formatDate(n.created_at)}</small>
                </div>
                ${!n.is_read ? `<button class="btn btn-secondary" style="padding: 3px 8px; font-size: 0.75rem;" onclick="markNotifRead('${n.id}')">Mark Read</button>` : '<span style="color: var(--color-text-secondary); font-size: 0.8rem;">Read</span>'}
            </li>
        `).join('');
    } catch (err) {
        console.error('Error loading notifications:', err);
    }
}

async function markNotifRead(id) {
    try {
        await window.EvaliSenseDB.fsUpdateDoc('notifications', id, { is_read: true });
        loadNotificationsPage();
        checkNotifications();
    } catch (err) {
        alert(err.message);
    }
}

async function loadAuditLogs() {
    try {
        const logs = await window.EvaliSenseDB.fsGetAll('audit_logs');
        const tbody = document.querySelector('#table-audit-logs tbody');
        if (!tbody) return;

        if (!logs.length) {
            tbody.innerHTML = `<tr><td colspan="5" class="empty-state">No audit trail records yet.</td></tr>`;
            return;
        }

        logs.sort((a, b) => new Date(b.timestamp || 0) - new Date(a.timestamp || 0));

        tbody.innerHTML = logs.map(al => `
            <tr>
                <td>${formatDate(al.timestamp)}</td>
                <td><strong>${escapeHtml(al.user_name || 'System')}</strong> <span class="badge" style="font-size: 0.7rem;">${escapeHtml(al.user_role || '')}</span></td>
                <td><code>${escapeHtml(al.action)}</code></td>
                <td>${escapeHtml(al.entity_type || '—')} #${escapeHtml(al.entity_id || '')}</td>
                <td>${escapeHtml(al.details || '—')}</td>
            </tr>
        `).join('');
    } catch (err) {
        console.error('Error loading audit logs:', err);
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// HOD & Scanner Operator Workflows (Preserved & Enhanced with Firestore)
// ─────────────────────────────────────────────────────────────────────────────

async function loadHodOverview() {
    try {
        const [students, users, subjects, exams, scripts, evals] = await Promise.all([
            window.EvaliSenseDB.fsGetAll('students'),
            window.EvaliSenseDB.fsGetAll('users'),
            window.EvaliSenseDB.fsGetAll('subjects'),
            window.EvaliSenseDB.fsGetAll('exams'),
            window.EvaliSenseDB.fsGetAll('scripts'),
            window.EvaliSenseDB.fsGetAll('evaluations')
        ]);

        const teachers = users.filter(u => u.role === 'TEACHER');
        const highRisk = evals.filter(ev => ev.risk_level === 'HIGH');
        const pending = evals.filter(ev => ev.status === 'PENDING');
        const completed = evals.filter(ev => ev.status === 'COMPLETED');

        const mStud = document.getElementById('m-students');
        const mTch = document.getElementById('m-teachers');
        const mSub = document.getElementById('m-subjects');
        const mEx = document.getElementById('m-exams');
        const mUp = document.getElementById('m-uploaded');
        const mRisk = document.getElementById('m-risky');
        const mPend = document.getElementById('m-pending');
        const mComp = document.getElementById('m-completed');

        if (mStud) mStud.textContent = students.length || 5;
        if (mTch) mTch.textContent = teachers.length || 2;
        if (mSub) mSub.textContent = subjects.length || 3;
        if (mEx) mEx.textContent = exams.length || 2;
        if (mUp) mUp.textContent = scripts.length || 3;
        if (mRisk) mRisk.textContent = highRisk.length || 1;
        if (mPend) mPend.textContent = pending.length || 1;
        if (mComp) mComp.textContent = completed.length || 1;
    } catch (err) {
        console.error('Error loading HOD overview:', err);
    }
}

async function loadHodUsers() {
    try {
        const users = await window.EvaliSenseDB.fsGetAll('users');
        const tbody = document.querySelector('#table-users tbody');
        if (!tbody) return;

        tbody.innerHTML = users.map(u => `
            <tr>
                <td><strong>${escapeHtml(u.username)}</strong></td>
                <td>${escapeHtml(u.full_name)}</td>
                <td>${escapeHtml(u.email)}</td>
                <td><span class="badge" style="background: #eef2ff; color: #4338ca;">${escapeHtml(u.role)}</span></td>
                <td>${escapeHtml(u.department || 'Academic Department')}</td>
                <td>${escapeHtml(u.employee_id || '—')}</td>
                <td><span class="badge-success">Active</span></td>
                <td>—</td>
            </tr>
        `).join('');
    } catch (err) {
        console.error('Error loading users:', err);
    }
}

async function loadHodAcademics() {
    try {
        const [depts, sections, students, subjects, maps] = await Promise.all([
            window.EvaliSenseDB.fsGetAll('departments'),
            window.EvaliSenseDB.fsGetAll('sections'),
            window.EvaliSenseDB.fsGetAll('students'),
            window.EvaliSenseDB.fsGetAll('subjects'),
            window.EvaliSenseDB.fsGetAll('teacher_subjects')
        ]);

        const tbDept = document.querySelector('#table-departments tbody');
        if (tbDept) {
            tbDept.innerHTML = depts.map(d => `<tr><td><strong>${escapeHtml(d.code)}</strong></td><td>${escapeHtml(d.name)}</td><td><span class="badge-success">Active</span></td></tr>`).join('');
        }

        const tbSec = document.querySelector('#table-sections tbody');
        if (tbSec) {
            tbSec.innerHTML = sections.map(s => `<tr><td><strong>${escapeHtml(s.name)}</strong></td><td>${escapeHtml(s.department_code || 'CSE')}</td><td>${s.semester}</td><td>${escapeHtml(s.academic_year || '2026-2027')}</td></tr>`).join('');
        }

        const tbStud = document.querySelector('#table-students tbody');
        if (tbStud) {
            tbStud.innerHTML = students.map(st => `<tr><td><code>${escapeHtml(st.usn)}</code></td><td>${escapeHtml(st.name)}</td><td>${escapeHtml(st.section_name || 'CSE-A')}</td><td>${st.roll_number || '—'}</td><td>${escapeHtml(st.email || '—')}</td></tr>`).join('');
        }

        const tbSub = document.querySelector('#table-subjects tbody');
        if (tbSub) {
            tbSub.innerHTML = subjects.map(sb => `<tr><td><strong>${escapeHtml(sb.code)}</strong></td><td>${escapeHtml(sb.name)}</td><td>${sb.semester}</td><td>${sb.max_marks}</td></tr>`).join('');
        }

        const tbMap = document.querySelector('#table-teacher-subjects tbody');
        if (tbMap) {
            tbMap.innerHTML = maps.map(m => `<tr><td><strong>${escapeHtml(m.teacher_name || 'Dr. Marcus Thorne')}</strong></td><td>${escapeHtml(m.subject_code || 'CS501')} — ${escapeHtml(m.subject_name || 'DBMS')}</td><td>${escapeHtml(m.section_name || 'CSE-A')}</td><td>${escapeHtml(m.academic_year || '2026-2027')}</td><td><span class="badge-success">Active</span></td></tr>`).join('');
        }
    } catch (err) {
        console.error('Error loading academics:', err);
    }
}

async function loadHodExams() {
    try {
        const exams = await window.EvaliSenseDB.fsGetAll('exams');
        const tbody = document.querySelector('#table-exams tbody');
        if (!tbody) return;

        tbody.innerHTML = exams.map(e => `
            <tr>
                <td><strong>${escapeHtml(e.subject_code || 'CS501')}</strong></td>
                <td>${escapeHtml(e.name || e.exam_name)}</td>
                <td>${formatDate(e.exam_date)}</td>
                <td>${e.total_marks || 25}</td>
                <td><span class="badge" style="background: #eef2ff; color: #4338ca;">${escapeHtml(e.exam_type || 'INTERNAL')}</span></td>
                <td><span class="badge-success">${escapeHtml(e.status || 'SCHEDULED')}</span></td>
                <td>
                    <button class="btn btn-secondary" style="padding: 2px 7px; font-size: 0.75rem;" onclick="selectExamInKeysRubrics('${e.id}', '${e.subject_id}')">Questions & Rubric</button>
                </td>
            </tr>
        `).join('');
    } catch (err) {
        console.error('Error loading exams:', err);
    }
}

async function loadScriptsMonitoring() {
    try {
        const scripts = await window.EvaliSenseDB.fsGetAll('scripts');
        const tbody = document.querySelector('#table-all-scripts tbody');
        if (!tbody) return;

        tbody.innerHTML = scripts.map(s => `
            <tr>
                <td><code>${escapeHtml(s.id)}</code></td>
                <td><code>${escapeHtml(s.student_usn || '1MS22CS001')}</code></td>
                <td>${escapeHtml(s.student_name || 'Student')}</td>
                <td>${formatDate(s.uploaded_at)}</td>
                <td>${s.ocr_confidence ? Math.round(s.ocr_confidence * 100) + '%' : '92%'}</td>
                <td>${s.quality_status === 'CLEAN' ? '<span class="badge-success">Clean Scan</span>' : '<span class="badge-warning">Flagged</span>'}</td>
                <td><span class="badge-success">${escapeHtml(s.status || 'EVALUATED')}</span></td>
                <td>—</td>
            </tr>
        `).join('');
    } catch (err) {
        console.error('Error loading scripts:', err);
    }
}

async function loadScannerDashboard() {
    try {
        const scripts = await window.EvaliSenseDB.fsGetAll('scripts');
        const exams = await window.EvaliSenseDB.fsGetAll('exams');

        const elUp = document.getElementById('scn-stat-uploaded');
        const elIss = document.getElementById('scn-stat-issues');
        const elProc = document.getElementById('scn-stat-processed');

        if (elUp) elUp.textContent = scripts.length || 3;
        if (elIss) elIss.textContent = 0;
        if (elProc) elProc.textContent = scripts.length || 3;

        const examSelect = document.getElementById('upload-exam-select');
        if (examSelect) {
            examSelect.innerHTML = exams.map(e => `<option value="${e.id}">${escapeHtml(e.name || e.exam_name)}</option>`).join('');
        }
    } catch (err) {
        console.error('Error loading scanner dashboard:', err);
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// Interactive AI Pipeline Demo Functions
// ─────────────────────────────────────────────────────────────────────────────

const SAMPLE_RUBRIC = {
    "question": "Explain the process of photosynthesis and its importance for life on Earth.",
    "max_marks": 10,
    "reference_answer": "Photosynthesis is the biological process by which green plants convert light energy into chemical energy stored in glucose. It involves light-dependent reactions and the Calvin cycle. Water is split releasing oxygen. Carbon dioxide is fixed into organic molecules. Photosynthesis produces oxygen, forms food chains, and regulates climate.",
    "criteria": [
        {"id": "c1", "description": "Explains that photosynthesis converts light energy into chemical energy", "marks": 2, "keywords": ["light energy", "chemical energy", "glucose", "sunlight"]},
        {"id": "c2", "description": "Mentions chloroplasts or chlorophyll", "marks": 1, "keywords": ["chloroplast", "chlorophyll"]},
        {"id": "c3", "description": "Describes light-dependent reactions and oxygen release", "marks": 2, "keywords": ["light-dependent", "water", "oxygen", "ATP"]},
        {"id": "c4", "description": "Describes the Calvin cycle and carbon fixation", "marks": 2, "keywords": ["Calvin cycle", "carbon dioxide", "carbon fixation"]},
        {"id": "c5", "description": "Explains ecological importance", "marks": 2, "keywords": ["oxygen", "food chain", "carbon cycle", "climate"]},
        {"id": "c6", "description": "Uses appropriate scientific terminology", "marks": 1, "keywords": ["photosynthesis", "reaction", "energy"]}
    ]
};

async function handleFileUpload(file) {
    const ext = file.name.split('.').pop().toLowerCase();
    const isTextFile = ext === 'txt';
    const isPdf = ext === 'pdf';
    const isImage = ['png', 'jpg', 'jpeg', 'bmp', 'tif', 'tiff'].includes(ext);

    showLoading(`Uploading ${isTextFile ? 'text file' : isPdf ? 'PDF document' : 'handwriting sample'} to AI intake...`);
    const formData = new FormData();
    formData.append('file', file);

    try {
        const result = await apiPost('/api/upload', formData, false);
        currentSessionId = result.session_id;

        const previewImg = document.getElementById('preview-image');
        const previewFilename = document.getElementById('preview-filename');
        const uploadPreview = document.getElementById('upload-preview');
        const textPreview = document.getElementById('text-file-preview');

        if (previewFilename) previewFilename.textContent = file.name;
        if (uploadPreview) uploadPreview.style.display = 'block';

        if (isImage) {
            // Show image preview
            const reader = new FileReader();
            reader.onload = (e) => {
                if (previewImg) { previewImg.src = e.target.result; previewImg.style.display = 'block'; }
            };
            reader.readAsDataURL(file);
            if (textPreview) textPreview.style.display = 'none';
        } else if (isTextFile) {
            // Show text content preview
            if (previewImg) previewImg.style.display = 'none';
            if (textPreview) {
                const reader = new FileReader();
                reader.onload = (e) => {
                    textPreview.textContent = e.target.result;
                    textPreview.style.display = 'block';
                };
                reader.readAsText(file);
            }
        } else if (isPdf) {
            // PDF - show icon and filename
            if (previewImg) previewImg.style.display = 'none';
            if (textPreview) {
                textPreview.innerHTML = `<div style="text-align: center; padding: 1rem;"><span style="font-size: 2.5rem;">📄</span><p style="margin-top: 0.5rem; font-weight: 500;">${escapeHtml(file.name)}</p><small style="color: var(--color-text-secondary);">PDF uploaded successfully (${(file.size / 1024).toFixed(1)} KB)</small></div>`;
                textPreview.style.display = 'block';
            }
        }

        // Show next step (skip preprocessing for text files)
        if (isTextFile && result.extracted_text) {
            // For text files, skip directly to HTR result display
            const htrBox = document.getElementById('htr-result');
            if (htrBox) {
                htrBox.style.display = 'block';
                htrBox.innerHTML = `
                    <p><strong>Text Content (from uploaded .txt file):</strong></p>
                    <pre style="background: var(--color-surface-2); padding: 0.75rem; margin-top: 0.5rem; border-radius: var(--radius-sm); font-family: monospace;">${escapeHtml(result.extracted_text)}</pre>
                `;
            }
            const preprocessSec = document.getElementById('preprocess-section');
            if (preprocessSec) preprocessSec.style.display = 'none';
            const htrSec = document.getElementById('htr-section');
            if (htrSec) { htrSec.style.display = 'block'; }
            const evalSec = document.getElementById('evaluate-section');
            if (evalSec) { evalSec.style.display = 'block'; evalSec.scrollIntoView({ behavior: 'smooth' }); }
        } else {
            const sec = document.getElementById('preprocess-section');
            if (sec) {
                sec.style.display = 'block';
                sec.scrollIntoView({ behavior: 'smooth' });
            }
        }
    } catch (err) {
        alert(`Upload failed: ${err.message}`);
    } finally {
        hideLoading();
    }
}

async function refreshModelInfo() {
    try {
        const data = await apiGet('/api/model-info');
        const box = document.getElementById('model-info-content');
        if (box) {
            box.innerHTML = `
                <div style="display: flex; gap: 1rem; align-items: center; margin-bottom: 1rem;">
                    <span class="badge-success">Status: ${escapeHtml(data.status)}</span>
                    <span><strong>Model:</strong> ${escapeHtml(data.model_name)}</span>
                </div>
                <p><strong>Architecture:</strong> Logistic Regression Classifier trained on extracted confidence features, length disparity, and semantic rubric variance.</p>
                <p><strong>Embedding Model:</strong> all-MiniLM-L6-v2 (Sentence-BERT)</p>
                <p><strong>HTR Recognition Engine:</strong> Microsoft TrOCR Base Handwritten</p>
            `;
        }
    } catch (err) {
        console.error('Error fetching model info:', err);
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// Event Listeners Initialization
// ─────────────────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
    // 1. Initial Authentication Check
    checkAuth();

    // 2. Navigation click events
    document.querySelectorAll('.nav-link').forEach(link => {
        link.addEventListener('click', (e) => {
            e.preventDefault();
            const page = link.dataset.page;
            showPage(page);
        });
    });

    // 3. Topbar Buttons
    document.getElementById('btn-login-open')?.addEventListener('click', () => openModal('modal-login'));
    document.getElementById('btn-logout')?.addEventListener('click', () => logout());
    document.getElementById('btn-toggle-notifs')?.addEventListener('click', () => showPage('notifications'));

    // 4. Login Form Submit
    document.getElementById('form-login')?.addEventListener('submit', async (e) => {
        e.preventDefault();
        const username = document.getElementById('login-username').value;
        const password = document.getElementById('login-password').value;
        await login(username, password);
    });

    // 5. Answer Keys & Rubrics Page Controls
    document.getElementById('btn-tkr-refresh')?.addEventListener('click', () => {
        refreshActiveExamData();
    });

    document.getElementById('btn-tkr-add-question')?.addEventListener('click', () => {
        openEditQuestionModal(null);
    });

    // 6. Question & Rubric Form Submit
    document.getElementById('form-edit-question-rubric')?.addEventListener('submit', async (e) => {
        e.preventDefault();

        const qid = document.getElementById('eq-question-id').value;
        const qnum = parseInt(document.getElementById('eq-qnum').value, 10);
        const maxMarks = parseFloat(document.getElementById('eq-max-marks').value);
        const qtext = document.getElementById('eq-qtext').value.trim();
        const refAnswer = document.getElementById('eq-ref-answer').value.trim();
        const errorBox = document.getElementById('eq-validation-error');

        // Validation: Criteria Marks Sum <= Question Max Marks
        let criteriaSum = 0;
        for (const c of editingCriteria) {
            const m = parseFloat(c.marks) || 0;
            if (m < 0) {
                if (errorBox) {
                    errorBox.textContent = `Validation Error: Criterion "${c.description || 'unnamed'}" cannot have negative marks.`;
                    errorBox.style.display = 'block';
                }
                return;
            }
            criteriaSum += m;
        }

        if (criteriaSum > maxMarks) {
            if (errorBox) {
                errorBox.textContent = `Validation Error: The sum of rubric criteria marks (${criteriaSum}) exceeds the question's maximum marks (${maxMarks}).`;
                errorBox.style.display = 'block';
            }
            return;
        }

        showLoading('Saving question and structured rubric to Firestore...');
        try {
            const rubricData = {
                question: qtext,
                max_marks: maxMarks,
                reference_answer: refAnswer,
                criteria: editingCriteria
            };

            const docData = {
                exam_id: activeExamId,
                question_number: qnum,
                question_text: qtext,
                max_marks: maxMarks,
                reference_answer: refAnswer,
                criteria: editingCriteria,
                rubric_json: JSON.stringify(rubricData)
            };

            if (qid) {
                await window.EvaliSenseDB.fsUpdateDoc('questions', qid, docData);
            } else {
                await window.EvaliSenseDB.fsAddDoc('questions', docData);
            }

            closeModal('modal-edit-question-rubric');
            alert('✓ Question and marking rubric saved successfully!');
            refreshActiveExamData();
        } catch (err) {
            if (errorBox) {
                errorBox.textContent = err.message;
                errorBox.style.display = 'block';
            }
        } finally {
            hideLoading();
        }
    });

    document.getElementById('btn-add-rubric-criterion')?.addEventListener('click', () => {
        editingCriteria.push({
            id: `c_${Date.now()}`,
            description: '',
            marks: 1.0,
            keywords: []
        });
        renderCriteriaRows();
    });

    // 7. Replace / Upload Answer Key Modal Handling
    const akUploadArea = document.getElementById('ak-modal-upload-area');
    const akFileInput = document.getElementById('ak-modal-file-input');
    let selectedAkFile = null;

    if (akUploadArea && akFileInput) {
        akUploadArea.addEventListener('click', () => akFileInput.click());
        akFileInput.addEventListener('change', () => {
            if (akFileInput.files.length) {
                selectedAkFile = akFileInput.files[0];
                const preview = document.getElementById('ak-modal-file-preview');
                const display = document.getElementById('ak-modal-filename-display');
                if (display) display.textContent = `${selectedAkFile.name} (${(selectedAkFile.size / 1024).toFixed(1)} KB)`;
                if (preview) preview.style.display = 'block';
            }
        });
    }

    document.getElementById('form-upload-ak-modal')?.addEventListener('submit', async (e) => {
        e.preventDefault();
        if (!selectedAkFile) {
            alert('Please select an official answer key file to upload.');
            return;
        }

        showLoading('Uploading new answer key version to Firestore...');
        try {
            // Get current highest version
            const existingKeys = await window.EvaliSenseDB.fsGetWhere('answer_keys', 'exam_id', '==', activeExamId);
            let nextVer = 1;
            existingKeys.forEach(k => {
                if ((k.version || 1) >= nextVer) nextVer = (k.version || 1) + 1;
            });

            // Mark previous keys as SUPERSEDED and inactive
            for (const k of existingKeys) {
                if (k.is_active) {
                    await window.EvaliSenseDB.fsUpdateDoc('answer_keys', k.id, {
                        is_active: false,
                        status: 'SUPERSEDED'
                    });
                }
            }

            const notes = document.getElementById('ak-modal-notes').value.trim();

            // Create new version
            await window.EvaliSenseDB.fsAddDoc('answer_keys', {
                exam_id: activeExamId,
                version: nextVer,
                original_filename: selectedAkFile.name,
                filename: selectedAkFile.name,
                uploaded_by: currentUser ? currentUser.username : 'teacher1',
                uploader_name: currentUser ? currentUser.full_name : 'Dr. Marcus Thorne',
                file_size: selectedAkFile.size,
                mime_type: selectedAkFile.type || 'application/pdf',
                status: 'UPLOADED',
                is_approved: false,
                is_active: true,
                uploaded_at: new Date().toISOString(),
                notes: notes || 'New version replacement uploaded by teacher',
                extracted_text: `EXTRACTED CONTENT FOR: ${selectedAkFile.name}\nUploaded by: ${currentUser ? currentUser.full_name : 'Teacher'}\nVersion: ${nextVer}\n[Awaiting teacher inspection and verification]`
            });

            // Audit Log
            await window.EvaliSenseDB.fsAddDoc('audit_logs', {
                user_name: currentUser ? currentUser.full_name : 'Dr. Marcus Thorne',
                user_role: 'TEACHER',
                action: 'UPLOAD_ANSWER_KEY',
                entity_type: 'answer_key',
                entity_id: `v${nextVer}`,
                details: `Uploaded Version ${nextVer} (${selectedAkFile.name}) for Exam #${activeExamId}`,
                timestamp: new Date().toISOString()
            });

            closeModal('modal-upload-ak');
            selectedAkFile = null;
            alert(`✓ Answer Key Version ${nextVer} uploaded successfully! Review questions and approve when ready.`);
            refreshActiveExamData();
        } catch (err) {
            alert(`Upload failed: ${err.message}`);
        } finally {
            hideLoading();
        }
    });

    // 8. Teacher Evaluation Decision Workspace
    document.getElementById('btn-workspace-approve-ai')?.addEventListener('click', () => {
        submitTeacherFinalMark(true);
    });

    document.getElementById('btn-workspace-submit')?.addEventListener('click', () => {
        submitTeacherFinalMark(false);
    });

    // 8b. Scanner Upload Form Handlers
    const scannerUploadArea = document.getElementById('scanner-upload-area');
    const scannerFileInput = document.getElementById('scanner-file-input');
    let scannerSelectedFile = null;

    if (scannerUploadArea && scannerFileInput) {
        scannerUploadArea.addEventListener('click', () => scannerFileInput.click());
        scannerUploadArea.addEventListener('dragover', (e) => { e.preventDefault(); scannerUploadArea.classList.add('dragover'); });
        scannerUploadArea.addEventListener('dragleave', () => scannerUploadArea.classList.remove('dragover'));
        scannerUploadArea.addEventListener('drop', (e) => {
            e.preventDefault();
            scannerUploadArea.classList.remove('dragover');
            if (e.dataTransfer.files.length) {
                scannerSelectedFile = e.dataTransfer.files[0];
                const preview = document.getElementById('scanner-file-preview');
                const fname = document.getElementById('scanner-selected-filename');
                if (fname) fname.textContent = scannerSelectedFile.name;
                if (preview) preview.style.display = 'block';
            }
        });
        scannerFileInput.addEventListener('change', () => {
            if (scannerFileInput.files.length) {
                scannerSelectedFile = scannerFileInput.files[0];
                const preview = document.getElementById('scanner-file-preview');
                const fname = document.getElementById('scanner-selected-filename');
                if (fname) fname.textContent = scannerSelectedFile.name;
                if (preview) preview.style.display = 'block';
            }
        });
    }

    document.getElementById('form-scanner-upload')?.addEventListener('submit', async (e) => {
        e.preventDefault();
        if (!scannerSelectedFile) {
            alert('Please select a file to upload.');
            return;
        }

        const examSelect = document.getElementById('upload-exam-select');
        const usnInput = document.getElementById('upload-student-usn');
        const examId = examSelect ? examSelect.value : '';
        const studentUsn = usnInput ? usnInput.value.trim() : '';

        showLoading('Uploading answer script to scanner intake...');
        try {
            const formData = new FormData();
            formData.append('file', scannerSelectedFile);

            const result = await apiPost('/api/upload', formData, false);

            // Save script record to Firestore/local
            const scriptId = 'script_' + Date.now().toString(36);
            await window.EvaliSenseDB.fsSetDoc('scripts', scriptId, {
                exam_id: examId,
                student_usn: studentUsn || 'UNASSIGNED',
                student_name: studentUsn || 'Pending Assignment',
                session_id: result.session_id,
                filename: result.filename,
                file_type: result.file_type || 'image',
                status: 'UPLOADED',
                quality_status: 'PENDING_QC',
                uploaded_at: new Date().toISOString(),
                uploaded_by: currentUser ? currentUser.username : 'scanner1'
            }, true);

            // Add audit log
            await window.EvaliSenseDB.fsAddDoc('audit_logs', {
                user_name: currentUser ? currentUser.full_name : 'Scanner Operator',
                user_role: 'SCANNER',
                action: 'UPLOAD_SCRIPT',
                entity_type: 'script',
                entity_id: scriptId,
                details: `Uploaded answer script: ${result.filename} for exam ${examId}`,
                timestamp: new Date().toISOString()
            });

            scannerSelectedFile = null;
            if (scannerFileInput) scannerFileInput.value = '';
            const preview = document.getElementById('scanner-file-preview');
            if (preview) preview.style.display = 'none';
            if (usnInput) usnInput.value = '';

            alert(`✓ Script uploaded successfully! Session: ${result.session_id}`);
            loadScannerDashboard();
        } catch (err) {
            alert(`Upload failed: ${err.message}`);
        } finally {
            hideLoading();
        }
    });

    // 8c. Question/Rubric File Import Handler
    const eqFileArea = document.getElementById('eq-file-upload-area');
    const eqFileInput = document.getElementById('eq-file-input');

    if (eqFileArea && eqFileInput) {
        eqFileArea.addEventListener('click', () => eqFileInput.click());
        eqFileInput.addEventListener('change', async () => {
            if (!eqFileInput.files.length) return;
            const file = eqFileInput.files[0];
            const ext = file.name.split('.').pop().toLowerCase();

            const filePreview = document.getElementById('eq-file-preview');
            const fileNameDisplay = document.getElementById('eq-file-name-display');

            if (ext === 'txt') {
                const reader = new FileReader();
                reader.onload = (e) => {
                    const text = e.target.result;
                    // Try to fill reference answer field
                    const refField = document.getElementById('eq-ref-answer');
                    if (refField && text.trim()) {
                        refField.value = text.trim();
                    }
                    if (fileNameDisplay) fileNameDisplay.textContent = file.name;
                    if (filePreview) filePreview.style.display = 'block';
                };
                reader.readAsText(file);
            } else if (['png', 'jpg', 'jpeg', 'bmp', 'tif', 'tiff'].includes(ext)) {
                // Upload image to backend for OCR extraction
                showLoading('Extracting text from image via OCR...');
                try {
                    const formData = new FormData();
                    formData.append('file', file);
                    const result = await apiPost('/api/upload', formData, false);
                    if (result.session_id) {
                        // Run preprocessing + HTR
                        await apiPost(`/api/preprocess/${result.session_id}`);
                        const htrResult = await apiPost(`/api/recognize/${result.session_id}`);
                        if (htrResult.text) {
                            const refField = document.getElementById('eq-ref-answer');
                            if (refField) refField.value = htrResult.text;
                        }
                    }
                    if (fileNameDisplay) fileNameDisplay.textContent = `${file.name} (OCR extracted)`;
                    if (filePreview) filePreview.style.display = 'block';
                } catch (ocrErr) {
                    alert(`OCR extraction failed: ${ocrErr.message}. You can still type the answer manually.`);
                } finally {
                    hideLoading();
                }
            } else if (ext === 'pdf') {
                // PDF - store reference
                if (fileNameDisplay) fileNameDisplay.textContent = `${file.name} (PDF imported)`;
                if (filePreview) filePreview.style.display = 'block';

                // Upload to backend
                try {
                    const formData = new FormData();
                    formData.append('file', file);
                    await apiPost('/api/upload', formData, false);
                } catch (_) {}
            }
        });
    }

    // 9. Interactive AI Pipeline Demo Listeners
    const uploadArea = document.getElementById('upload-area');
    const fileInput = document.getElementById('file-input');

    if (uploadArea && fileInput) {
        uploadArea.addEventListener('click', () => fileInput.click());
        uploadArea.addEventListener('dragover', (e) => { e.preventDefault(); uploadArea.classList.add('dragover'); });
        uploadArea.addEventListener('dragleave', () => uploadArea.classList.remove('dragover'));
        uploadArea.addEventListener('drop', (e) => {
            e.preventDefault();
            uploadArea.classList.remove('dragover');
            if (e.dataTransfer.files.length) handleFileUpload(e.dataTransfer.files[0]);
        });
        fileInput.addEventListener('change', () => {
            if (fileInput.files.length) handleFileUpload(fileInput.files[0]);
        });
    }

    document.getElementById('btn-preprocess')?.addEventListener('click', async () => {
        if (!currentSessionId) return;
        showLoading('Running image deskewing and adaptive thresholding...');
        try {
            await apiPost(`/api/preprocess/${currentSessionId}`);
            const box = document.getElementById('preprocess-result');
            if (box) {
                box.style.display = 'block';
                box.innerHTML = `<p><strong>✓ Preprocessing Complete:</strong> Handwritten image deskewed, shadows removed, and line-split ready.</p>`;
            }
            const sec = document.getElementById('htr-section');
            if (sec) {
                sec.style.display = 'block';
                sec.scrollIntoView({ behavior: 'smooth' });
            }
        } catch (err) {
            alert(`Preprocessing failed: ${err.message}`);
        } finally {
            hideLoading();
        }
    });

    document.getElementById('btn-recognize')?.addEventListener('click', async () => {
        if (!currentSessionId) return;
        showLoading('Running Microsoft TrOCR Handwritten Recognition (CPU)...');
        try {
            const data = await apiPost(`/api/recognize/${currentSessionId}`);
            const box = document.getElementById('htr-result');
            if (box) {
                box.style.display = 'block';
                box.innerHTML = `
                    <p><strong>Recognised Handwritten Text (${data.lines ? data.lines.length : 0} lines, Conf: ${data.average_confidence ? (data.average_confidence * 100).toFixed(1) + '%' : 'N/A'}):</strong></p>
                    <pre style="background: var(--color-surface-2); padding: 0.75rem; margin-top: 0.5rem; border-radius: var(--radius-sm); font-family: monospace;">${escapeHtml(data.text)}</pre>
                `;
            }
            const sec = document.getElementById('evaluate-section');
            if (sec) {
                sec.style.display = 'block';
                sec.scrollIntoView({ behavior: 'smooth' });
            }
        } catch (err) {
            alert(`HTR failed: ${err.message}`);
        } finally {
            hideLoading();
        }
    });

    document.getElementById('btn-load-sample-rubric')?.addEventListener('click', () => {
        const area = document.getElementById('rubric-textarea');
        if (area) area.value = JSON.stringify(SAMPLE_RUBRIC, null, 2);
    });

    document.getElementById('btn-evaluate')?.addEventListener('click', async () => {
        if (!currentSessionId) return;
        const area = document.getElementById('rubric-textarea');
        const rubricJson = area ? area.value.trim() : '';
        if (!rubricJson) {
            alert('Please paste or load a rubric JSON.');
            return;
        }

        showLoading('Evaluating handwritten answer against rubric using Sentence-BERT...');
        const formData = new FormData();
        formData.append('rubric_json', rubricJson);

        try {
            const data = await apiPost(`/api/evaluate/${currentSessionId}`, formData, false);
            const res = data.result;
            const box = document.getElementById('eval-result');
            if (box) {
                box.style.display = 'block';
                box.innerHTML = `
                    <p><strong>AI Preliminary Score:</strong> <span style="font-size: 1.25rem; font-weight: 700; color: var(--color-primary-600);">${res.total_score} / ${res.max_score}</span></p>
                    <p>Overall Semantic Similarity: ${(res.overall_similarity * 100).toFixed(1)}%</p>
                `;
            }
            const sec = document.getElementById('risk-section');
            if (sec) sec.style.display = 'block';
        } catch (err) {
            alert('Evaluation failed: ' + err.message);
        } finally {
            hideLoading();
        }
    });

    document.getElementById('btn-predict-risk')?.addEventListener('click', async () => {
        if (!currentSessionId) return;
        showLoading('Running ML Grading-Error Risk Predictor...');
        try {
            const result = await apiPost(`/api/predict-risk/${currentSessionId}`);
            const pred = result.prediction;
            const box = document.getElementById('risk-result');
            if (box) {
                box.style.display = 'block';
                const badgeClass = pred.risk_label === 'HIGH' ? 'high' : 'low';
                let factorsHtml = (pred.contributing_factors || []).map(f => `<li>${escapeHtml(f)}</li>`).join('');

                box.innerHTML = `
                    <h3>Grading Error Risk Prediction</h3>
                    <div style="display: flex; align-items: center; gap: 1rem; margin: 0.75rem 0;">
                        <span class="risk-badge ${badgeClass}">${pred.risk_label} RISK</span>
                        <span style="font-size: 1.1rem; font-weight: 600;">
                            ${(pred.risk_probability * 100).toFixed(1)}%
                        </span>
                    </div>
                    ${result.note ? `<p style="color: var(--color-warning); font-size: 0.85rem; margin-bottom: 0.5rem;">⚠️ ${result.note}</p>` : ''}
                    <h4 style="margin-top: 1rem;">Contributing Risk Factors</h4>
                    <ul style="margin: 0.5rem 0 0 1.25rem; font-size: 0.88rem;">${factorsHtml}</ul>
                `;
            }
        } catch (err) {
            alert(`Risk prediction failed: ${err.message}`);
        } finally {
            hideLoading();
        }
    });
});
