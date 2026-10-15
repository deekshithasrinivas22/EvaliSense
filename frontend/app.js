/**
 * EvaliSense — Frontend Application Logic
 *
 * Implements:
 * 1. Role-Based Access Control (HOD, Teacher, Scanner, Guest)
 * 2. Session and JWT token lifecycle
 * 3. HOD administration (Users, Roles, Academics, Exams, Rubrics)
 * 4. Scanner workflows (Intake upload, blur validation, scan issue resolution)
 * 5. Teacher review workspace (Image, OCR, Rubric, AI mark, Risk factors, Final marks)
 * 6. Authoritative student results aggregation
 * 7. Preserved interactive AI evaluation pipeline demo
 */

const API_BASE = window.location.origin;

// State
let authToken = localStorage.getItem('evalisense_token') || null;
let currentUser = null;
let currentSessionId = null;
let currentReviewAssignmentId = null;

// ──────────────────────────────────────────────────────────────────────
// Network Helpers (with automatic JWT authentication)
// ──────────────────────────────────────────────────────────────────────

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
        headers: authHeaders(false),
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
        headers: authHeaders(isJson),
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

async function apiPut(url, body) {
    const resp = await fetch(`${API_BASE}${url}`, {
        method: 'PUT',
        headers: authHeaders(true),
        body: JSON.stringify(body),
    });
    if (!resp.ok) {
        const err = await resp.json().catch(() => ({ detail: resp.statusText }));
        throw new Error(err.detail || resp.statusText);
    }
    return resp.json();
}

async function apiDelete(url) {
    const resp = await fetch(`${API_BASE}${url}`, {
        method: 'DELETE',
        headers: authHeaders(false),
    });
    if (!resp.ok) {
        const err = await resp.json().catch(() => ({ detail: resp.statusText }));
        throw new Error(err.detail || resp.statusText);
    }
    return resp.json();
}

// ──────────────────────────────────────────────────────────────────────
// Authentication & User Session Lifecycle
// ──────────────────────────────────────────────────────────────────────

async function checkAuth() {
    if (!authToken) {
        setGuestState();
        return;
    }
    try {
        const user = await apiGet('/api/auth/me');
        setCurrentUser(user);
    } catch {
        setGuestState();
    }
}

function setCurrentUser(user) {
    currentUser = user;
    const greeting = document.getElementById('topbar-user-greeting');
    const badge = document.getElementById('topbar-role-badge');
    const btnLogin = document.getElementById('btn-login-open');
    const btnLogout = document.getElementById('btn-logout');

    greeting.textContent = `Hello, ${user.full_name}`;
    badge.textContent = user.role_name;
    badge.className = `topbar-role-badge role-badge-${user.role_name.toLowerCase()}`;
    document.getElementById('display-active-role').textContent = user.role_name;

    btnLogin.style.display = 'none';
    btnLogout.style.display = 'inline-block';

    updateSidebarNavigation();
    checkNotifications();

    // Route to appropriate home page for the role
    if (user.role_name === 'HOD') showPage('hod-overview');
    else if (user.role_name === 'TEACHER') showPage('teacher-dashboard');
    else if (user.role_name === 'SCANNER') showPage('scanner-dashboard');
    else showPage('dashboard');
}

function setGuestState() {
    currentUser = null;
    authToken = null;
    localStorage.removeItem('evalisense_token');

    document.getElementById('topbar-user-greeting').textContent = 'Welcome to EvaliSense';
    const badge = document.getElementById('topbar-role-badge');
    badge.textContent = 'Guest';
    badge.className = 'topbar-role-badge role-badge-guest';
    document.getElementById('display-active-role').textContent = 'Guest';

    document.getElementById('btn-login-open').style.display = 'inline-block';
    document.getElementById('btn-logout').style.display = 'none';

    updateSidebarNavigation();
    showPage('dashboard');
}

async function login(username, password) {
    showLoading('Authenticating...');
    try {
        const data = await apiPost('/api/auth/login', { username, password });
        authToken = data.access_token;
        localStorage.setItem('evalisense_token', authToken);
        closeModal('modal-login');
        await checkAuth();
    } catch (err) {
        alert(`Sign in failed: ${err.message}`);
    } finally {
        hideLoading();
    }
}

function logout() {
    apiPost('/api/auth/logout').catch(() => {});
    setGuestState();
}

async function quickLogin(username, password) {
    await login(username, password);
}

// ──────────────────────────────────────────────────────────────────────
// Dynamic Navigation Based on Role
// ──────────────────────────────────────────────────────────────────────

function updateSidebarNavigation() {
    const role = currentUser ? currentUser.role_name : 'GUEST';
    const nav = document.getElementById('nav-links');
    nav.innerHTML = '';

    const items = [];

    if (role === 'GUEST') {
        items.push({ page: 'dashboard', icon: '📊', label: 'Overview' });
        items.push({ page: 'evaluate', icon: '📝', label: 'Pipeline Demo' });
        items.push({ page: 'model', icon: '🤖', label: 'Model Info' });
    } else if (role === 'HOD') {
        items.push({ page: 'hod-overview', icon: '📊', label: 'Overview' });
        items.push({ page: 'hod-users', icon: '👥', label: 'Users & Roles' });
        items.push({ page: 'hod-academics', icon: '🏛️', label: 'Academics' });
        items.push({ page: 'hod-exams', icon: '📋', label: 'Examinations' });
        items.push({ page: 'scripts-monitoring', icon: '📑', label: 'Answer Scripts' });
        items.push({ page: 'results', icon: '📈', label: 'Exam Results' });
        items.push({ page: 'profile', icon: '👤', label: 'My Profile' });
        items.push({ page: 'notifications', icon: '🔔', label: 'Notifications' });
        items.push({ page: 'evaluate', icon: '🧪', label: 'Interactive Demo' });
        items.push({ page: 'model', icon: '🤖', label: 'Model Info' });
    } else if (role === 'TEACHER') {
        items.push({ page: 'teacher-dashboard', icon: '📊', label: 'Teacher Portal' });
        items.push({ page: 'teacher-exams', icon: '📚', label: 'My Examinations' });
        items.push({ page: 'teacher-answer-keys', icon: '🔑', label: 'Answer Keys & Rubrics' });
        items.push({ page: 'teacher-reviews', icon: '⚠️', label: 'Pending Reviews' });
        items.push({ page: 'teacher-completed-reviews', icon: '✅', label: 'Completed Reviews' });
        items.push({ page: 'results', icon: '📈', label: 'Class Results' });
        items.push({ page: 'profile', icon: '👤', label: 'My Profile' });
        items.push({ page: 'notifications', icon: '🔔', label: 'Notifications' });
        items.push({ page: 'evaluate', icon: '🧪', label: 'Interactive Demo' });
        items.push({ page: 'model', icon: '🤖', label: 'Model Info' });
    } else if (role === 'SCANNER') {
        items.push({ page: 'scanner-dashboard', icon: '📠', label: 'Scanner Portal' });
        items.push({ page: 'scripts-monitoring', icon: '📑', label: 'My Uploads' });
        items.push({ page: 'profile', icon: '👤', label: 'My Profile' });
        items.push({ page: 'notifications', icon: '🔔', label: 'Notifications' });
        items.push({ page: 'evaluate', icon: '🧪', label: 'Interactive Demo' });
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

    // Page-specific data loading
    if (pageId === 'hod-overview') loadHodOverview();
    else if (pageId === 'hod-users') { loadHodUsers(); loadHodRoles(); }
    else if (pageId === 'hod-academics') loadHodAcademics();
    else if (pageId === 'hod-exams') loadHodExams();
    else if (pageId === 'scripts-monitoring') loadScriptsMonitoring();
    else if (pageId === 'teacher-dashboard') loadTeacherDashboard();
    else if (pageId === 'teacher-exams') loadTeacherExams();
    else if (pageId === 'teacher-answer-keys') loadTeacherAnswerKeys();
    else if (pageId === 'teacher-reviews') loadTeacherReviews();
    else if (pageId === 'teacher-completed-reviews') loadTeacherCompletedReviews();
    else if (pageId === 'scanner-dashboard') loadScannerDashboard();
    else if (pageId === 'results') loadResultsPage();
    else if (pageId === 'profile') loadProfile();
    else if (pageId === 'notifications') loadNotificationsPage();
    else if (pageId === 'model') refreshModelInfo();
}

// ──────────────────────────────────────────────────────────────────────
// HOD Dashboard Functions
// ──────────────────────────────────────────────────────────────────────

async function loadHodOverview() {
    try {
        const metrics = await apiGet('/api/analytics/overview');
        document.getElementById('m-students').textContent = metrics.total_students;
        document.getElementById('m-teachers').textContent = metrics.total_teachers;
        document.getElementById('m-subjects').textContent = metrics.active_subjects;
        document.getElementById('m-exams').textContent = metrics.active_examinations;
        document.getElementById('m-uploaded').textContent = metrics.scripts_uploaded;
        document.getElementById('m-risky').textContent = metrics.high_risk_answers;
        document.getElementById('m-pending').textContent = metrics.pending_teacher_reviews;
        document.getElementById('m-completed').textContent = metrics.completed_reviews;

        // Render teacher workloads
        const tbody = document.querySelector('#table-teacher-workload tbody');
        if (metrics.teacher_workloads && metrics.teacher_workloads.length) {
            tbody.innerHTML = metrics.teacher_workloads.map(t => `
                <tr>
                    <td><strong>${escapeHtml(t.teacher_name)}</strong></td>
                    <td><code>${escapeHtml(t.username)}</code></td>
                    <td><span class="status-pill status-high_risk">${t.pending_count} pending</span></td>
                    <td><span class="status-pill status-completed">${t.completed_count} completed</span></td>
                    <td>${t.pending_count > 3 ? '⚠️ High Load' : '✓ Normal'}</td>
                </tr>
            `).join('');
        } else {
            tbody.innerHTML = '<tr><td colspan="5" class="empty-state">No teachers registered yet.</td></tr>';
        }
    } catch (err) {
        console.error('Failed to load HOD overview:', err);
    }
}

async function loadHodUsers() {
    try {
        const users = await apiGet('/api/users');
        const tbody = document.querySelector('#table-users tbody');
        tbody.innerHTML = users.map(u => `
            <tr>
                <td>${u.id}</td>
                <td><strong>${escapeHtml(u.full_name)}</strong></td>
                <td><code>${escapeHtml(u.username)}</code></td>
                <td><span class="topbar-role-badge role-badge-${(u.role_name || '').toLowerCase()}">${u.role_name}</span></td>
                <td>${escapeHtml(u.email)}</td>
                <td>${escapeHtml(u.employee_id || '—')}</td>
                <td>${u.is_active ? '✓ Active' : '✗ Inactive'}</td>
                <td>
                    ${u.is_active ? `<button class="btn btn-secondary" style="padding: 2px 8px; font-size: 0.75rem;" onclick="deactivateUser(${u.id})">Deactivate</button>` : '—'}
                </td>
            </tr>
        `).join('');
    } catch (err) {
        console.error('Failed to load users:', err);
    }
}

async function loadHodRoles() {
    try {
        const roles = await apiGet('/api/roles');
        const tbody = document.querySelector('#table-roles tbody');
        tbody.innerHTML = roles.map(r => `
            <tr>
                <td><strong>${escapeHtml(r.name)}</strong></td>
                <td>${escapeHtml(r.description || '—')}</td>
                <td>${r.is_system_role ? '<span class="status-pill status-ocr_completed">System</span>' : '<span class="status-pill status-uploaded">Custom</span>'}</td>
                <td>${r.is_active ? 'Yes' : 'No'}</td>
                <td>
                    ${!r.is_system_role ? `<button class="btn btn-secondary" style="padding: 2px 8px; font-size: 0.75rem;" onclick="deleteRole(${r.id})">Delete</button>` : '<span style="color: var(--color-text-muted);">Protected</span>'}
                </td>
            </tr>
        `).join('');

        // Populate user modal role dropdown
        const roleSelect = document.getElementById('user-role-select');
        if (roleSelect) {
            roleSelect.innerHTML = roles.map(r => `<option value="${r.id}">${r.name}</option>`).join('');
        }
    } catch (err) {
        console.error('Failed to load roles:', err);
    }
}

async function deactivateUser(userId) {
    if (!confirm('Are you sure you want to deactivate this user?')) return;
    try {
        await apiDelete(`/api/users/${userId}`);
        loadHodUsers();
    } catch (err) {
        alert(err.message);
    }
}

async function deleteRole(roleId) {
    if (!confirm('Are you sure you want to delete this custom role?')) return;
    try {
        await apiDelete(`/api/roles/${roleId}`);
        loadHodRoles();
    } catch (err) {
        alert(err.message);
    }
}

// ─── Academics Management ───

function switchTab(tabId) {
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));

    const tabBtn = Array.from(document.querySelectorAll('.tab-btn')).find(b => b.getAttribute('onclick')?.includes(tabId));
    if (tabBtn) tabBtn.classList.add('active');

    const content = document.getElementById(tabId);
    if (content) content.classList.add('active');
}

async function loadHodAcademics() {
    try {
        const [depts, sections, students, subjects, mappings, users] = await Promise.all([
            apiGet('/api/departments'),
            apiGet('/api/sections'),
            apiGet('/api/students'),
            apiGet('/api/subjects'),
            apiGet('/api/teacher-subjects'),
            apiGet('/api/users'),
        ]);

        // Departments
        document.querySelector('#table-departments tbody').innerHTML = depts.map(d => `
            <tr>
                <td><code>${escapeHtml(d.code)}</code></td>
                <td><strong>${escapeHtml(d.name)}</strong></td>
                <td>${d.is_active ? 'Active' : 'Inactive'}</td>
            </tr>
        `).join('');

        // Sections
        document.querySelector('#table-sections tbody').innerHTML = sections.map(s => `
            <tr>
                <td><strong>${escapeHtml(s.name)}</strong></td>
                <td>${escapeHtml(s.department_code || '')}</td>
                <td>Sem ${s.semester}</td>
                <td>${escapeHtml(s.academic_year)}</td>
            </tr>
        `).join('');

        // Students
        document.querySelector('#table-students tbody').innerHTML = students.map(st => `
            <tr>
                <td><code>${escapeHtml(st.usn)}</code></td>
                <td><strong>${escapeHtml(st.name)}</strong></td>
                <td>${escapeHtml(st.section_name || '—')}</td>
                <td>${escapeHtml(st.roll_number || '—')}</td>
                <td>${escapeHtml(st.email || '—')}</td>
            </tr>
        `).join('');

        // Subjects
        document.querySelector('#table-subjects tbody').innerHTML = subjects.map(sub => `
            <tr>
                <td><code>${escapeHtml(sub.code)}</code></td>
                <td><strong>${escapeHtml(sub.name)}</strong></td>
                <td>Sem ${sub.semester}</td>
                <td>${sub.max_marks}</td>
            </tr>
        `).join('');

        // Teacher Subjects
        document.querySelector('#table-teacher-subjects tbody').innerHTML = mappings.map(m => `
            <tr>
                <td><strong>${escapeHtml(m.teacher_name || '')}</strong></td>
                <td>${escapeHtml(m.subject_code || '')} - ${escapeHtml(m.subject_name || '')}</td>
                <td>${escapeHtml(m.section_name || 'All')}</td>
                <td>${escapeHtml(m.academic_year || '—')}</td>
                <td><button class="btn btn-secondary" style="padding: 2px 8px; font-size: 0.75rem;" onclick="removeTeacherMapping(${m.id})">Remove</button></td>
            </tr>
        `).join('');

        // Populate dropdowns in modals
        const deptSelects = ['sec-dept-select', 'sub-dept-select'];
        deptSelects.forEach(id => {
            const el = document.getElementById(id);
            if (el) el.innerHTML = depts.map(d => `<option value="${d.id}">${d.code} - ${d.name}</option>`).join('');
        });

        const studSecSelect = document.getElementById('stud-sec-select');
        const mapSecSelect = document.getElementById('map-section-select');
        if (studSecSelect) studSecSelect.innerHTML = sections.map(s => `<option value="${s.id}">${s.name} (${s.academic_year})</option>`).join('');
        if (mapSecSelect) mapSecSelect.innerHTML = '<option value="">All Sections</option>' + sections.map(s => `<option value="${s.id}">${s.name}</option>`).join('');

        const mapSubSelect = document.getElementById('map-subject-select');
        const examSubSelect = document.getElementById('exam-subject-select');
        if (mapSubSelect) mapSubSelect.innerHTML = subjects.map(s => `<option value="${s.id}">${s.code} - ${s.name}</option>`).join('');
        if (examSubSelect) examSubSelect.innerHTML = subjects.map(s => `<option value="${s.id}">${s.code} - ${s.name}</option>`).join('');

        const mapTeacherSelect = document.getElementById('map-teacher-select');
        if (mapTeacherSelect) {
            const teachers = users.filter(u => u.role_name === 'TEACHER');
            mapTeacherSelect.innerHTML = teachers.map(t => `<option value="${t.id}">${t.full_name} (${t.username})</option>`).join('');
        }
    } catch (err) {
        console.error('Failed to load academics:', err);
    }
}

async function removeTeacherMapping(id) {
    if (!confirm('Remove this teacher assignment mapping?')) return;
    try {
        await apiDelete(`/api/teacher-subjects/${id}`);
        loadHodAcademics();
    } catch (err) {
        alert(err.message);
    }
}

// ─── Examinations Management ───

async function loadHodExams() {
    try {
        const exams = await apiGet('/api/exams');
        const tbody = document.querySelector('#table-exams tbody');
        tbody.innerHTML = exams.map(e => `
            <tr>
                <td><strong>${escapeHtml(e.name)}</strong></td>
                <td>${escapeHtml(e.subject_code || '')}</td>
                <td>${escapeHtml(e.exam_date || 'TBD')}</td>
                <td>${e.total_marks}</td>
                <td>${e.question_count}</td>
                <td><span class="status-pill status-${e.status.toLowerCase()}">${e.status}</span></td>
                <td>
                    <button class="btn btn-secondary" style="padding: 2px 8px; font-size: 0.75rem;" onclick="viewExamQuestions(${e.id}, '${escapeHtml(e.name)}')">Questions & Rubric</button>
                </td>
            </tr>
        `).join('');
    } catch (err) {
        console.error('Failed to load exams:', err);
    }
}

async function viewExamQuestions(examId, examName) {
    const panel = document.getElementById('exam-questions-panel');
    const title = document.getElementById('exam-questions-title');
    const btnAdd = document.getElementById('btn-add-question-to-exam');
    title.textContent = `Questions & Rubrics for: ${examName}`;
    panel.style.display = 'block';

    btnAdd.onclick = () => {
        document.getElementById('q-exam-id').value = examId;
        openModal('modal-add-question');
    };

    try {
        const questions = await apiGet(`/api/exams/${examId}/questions`);
        const tbody = document.querySelector('#table-questions tbody');
        if (questions && questions.length) {
            tbody.innerHTML = questions.map(q => {
                let rubricCount = 0;
                try {
                    const r = JSON.parse(q.rubric_json);
                    rubricCount = r.criteria ? r.criteria.length : 0;
                } catch { /* ignore */ }
                return `
                    <tr>
                        <td><strong>Q${q.question_number}</strong></td>
                        <td>${escapeHtml(q.question_text)}</td>
                        <td><strong>${q.max_marks}</strong></td>
                        <td><small>${escapeHtml(q.reference_answer || '—')}</small></td>
                        <td><span class="status-pill status-completed">${rubricCount} criteria</span></td>
                    </tr>
                `;
            }).join('');
        } else {
            tbody.innerHTML = '<tr><td colspan="5" class="empty-state">No questions configured yet for this examination.</td></tr>';
        }
    } catch (err) {
        console.error('Failed to load questions:', err);
    }
}

// ─── Scripts Monitoring ───

async function loadScriptsMonitoring() {
    try {
        const scripts = await apiGet('/api/scripts');
        const tbody = document.querySelector('#table-all-scripts tbody');
        if (scripts && scripts.length) {
            tbody.innerHTML = scripts.map(s => `
                <tr>
                    <td>#${s.id}</td>
                    <td><strong>${escapeHtml(s.exam_name || 'Exam #' + s.exam_id)}</strong></td>
                    <td><code>${escapeHtml(s.student_usn || 'Unassigned')}</code></td>
                    <td>${escapeHtml(s.original_filename)}</td>
                    <td><span class="status-pill status-${s.scan_quality.toLowerCase()}">${s.scan_quality}</span></td>
                    <td><span class="status-pill status-${s.status.toLowerCase()}">${s.status}</span></td>
                    <td>${escapeHtml(s.uploader_name || 'Scanner')}</td>
                    <td>
                        ${s.status === 'UPLOADED' || s.status === 'PROCESSING' ? `
                            <button class="btn btn-primary" style="padding: 2px 8px; font-size: 0.75rem;" onclick="runScriptEvaluation(${s.id})">▶ Evaluate</button>
                        ` : ''}
                        ${s.status === 'REUPLOAD_REQUIRED' ? (
                            currentUser && currentUser.role_name === 'SCANNER' ?
                            `<button class="btn btn-secondary" style="padding: 2px 8px; font-size: 0.75rem; background: #fee2e2; color: #b91c1c;" onclick="openRescanModal(${s.id})">🔄 Rescan</button>` :
                            `<span class="status-pill status-high_risk" style="font-size: 0.75rem;">Rescan Required</span>`
                        ) : ''}
                    </td>
                </tr>
            `).join('');
        } else {
            tbody.innerHTML = '<tr><td colspan="8" class="empty-state">No answer scripts uploaded yet.</td></tr>';
        }
    } catch (err) {
        console.error('Failed to load scripts:', err);
    }
}

async function runScriptEvaluation(scriptId) {
    showLoading('Running Preprocessing, TrOCR HTR & Rubric Evaluation...');
    try {
        const res = await apiPost(`/api/scripts/${scriptId}/evaluate`);
        alert(`Evaluation completed! Status: ${res.script_status}`);
        loadScriptsMonitoring();
        if (currentUser && currentUser.role_name === 'HOD') loadHodOverview();
    } catch (err) {
        alert(`Evaluation failed: ${err.message}`);
    } finally {
        hideLoading();
    }
}

// ──────────────────────────────────────────────────────────────────────
// Teacher Review Workflow
// ──────────────────────────────────────────────────────────────────────

async function loadTeacherDashboard() {
    try {
        const [assignments, subjects] = await Promise.all([
            apiGet('/api/teacher/assignments'),
            apiGet('/api/teacher/subjects'),
        ]);

        const pending = assignments.filter(a => a.assignment_status === 'ASSIGNED' || a.assignment_status === 'IN_REVIEW');
        const completed = assignments.filter(a => a.assignment_status === 'COMPLETED');

        document.getElementById('t-stat-pending').textContent = pending.length;
        document.getElementById('t-stat-completed').textContent = completed.length;
        document.getElementById('t-stat-subjects').textContent = subjects.length;

        const tbody = document.querySelector('#table-teacher-my-subjects tbody');
        if (subjects && subjects.length) {
            tbody.innerHTML = subjects.map(s => `
                <tr>
                    <td><code>${escapeHtml(s.subject_code)}</code></td>
                    <td><strong>${escapeHtml(s.subject_name)}</strong></td>
                    <td>${escapeHtml(s.section_name || 'All Sections')}</td>
                    <td>${escapeHtml(s.academic_year || '—')}</td>
                </tr>
            `).join('');
        } else {
            tbody.innerHTML = '<tr><td colspan="4" class="empty-state">No subjects assigned yet.</td></tr>';
        }
    } catch (err) {
        console.error('Failed to load teacher dashboard:', err);
    }
}

async function loadTeacherReviews() {
    try {
        const assignments = await apiGet('/api/teacher/assignments');
        const pending = assignments.filter(a => a.assignment_status !== 'COMPLETED');
        const tbody = document.querySelector('#table-teacher-assignments tbody');

        if (pending && pending.length) {
            tbody.innerHTML = pending.map(a => `
                <tr>
                    <td>#${a.assignment_id}</td>
                    <td><strong>Q${a.question_number || 1}</strong></td>
                    <td>${a.max_marks}</td>
                    <td><strong>${a.ai_mark !== null ? a.ai_mark : '—'}</strong></td>
                    <td><span class="status-pill status-high_risk">${a.risk_label || 'HIGH'}</span></td>
                    <td>${Math.round((a.risk_probability || 0) * 100)}%</td>
                    <td><span class="status-pill status-${a.assignment_status.toLowerCase()}">${a.assignment_status}</span></td>
                    <td>
                        <button class="btn btn-primary" style="padding: 4px 10px; font-size: 0.8rem;" onclick="openTeacherWorkspace(${a.assignment_id})">Review Answer →</button>
                    </td>
                </tr>
            `).join('');
        } else {
            tbody.innerHTML = '<tr><td colspan="8" class="empty-state">🎉 All assigned reviews are completed! No pending risky answers.</td></tr>';
        }
    } catch (err) {
        console.error('Failed to load teacher reviews:', err);
    }
}

async function openTeacherWorkspace(assignmentId) {
    showLoading('Loading answer review workspace...');
    try {
        const data = await apiGet(`/api/teacher/assignments/${assignmentId}`);
        currentReviewAssignmentId = assignmentId;

        document.getElementById('workspace-subtitle').textContent = `Assignment #${assignmentId} (Answer #${data.answer_id})`;
        document.getElementById('workspace-img').src = `${API_BASE}${data.image_url}`;
        document.getElementById('workspace-ocr-text').textContent = data.extracted_text || '(No text recognised)';
        document.getElementById('workspace-ocr-conf').textContent = `OCR Average Confidence: ${data.ocr_confidence ? (data.ocr_confidence * 100).toFixed(1) + '%' : 'N/A'}`;

        const q = data.question || {};
        document.getElementById('workspace-q-num').textContent = q.number || 1;
        document.getElementById('workspace-q-max').textContent = q.max_marks || 0;
        document.getElementById('workspace-max-mark-hint').textContent = q.max_marks || 0;
        document.getElementById('workspace-q-text').textContent = q.text || '';
        document.getElementById('workspace-ref-answer').textContent = q.reference_answer || '(None provided)';

        const ai = data.ai_evaluation || {};
        document.getElementById('workspace-ai-mark').textContent = ai.ai_mark !== null ? ai.ai_mark : '—';
        document.getElementById('workspace-sim').textContent = ai.semantic_similarity !== null ? `${Math.round(ai.semantic_similarity * 100)}%` : '—';
        document.getElementById('workspace-cov').textContent = ai.rubric_coverage !== null ? `${Math.round(ai.rubric_coverage * 100)}%` : '—';

        // Risk indicators
        document.getElementById('workspace-risk-label').textContent = ai.risk_label || 'HIGH';
        document.getElementById('workspace-risk-prob').textContent = `${Math.round((ai.risk_probability || 0) * 100)}% Error Risk`;

        const factorsList = document.getElementById('workspace-risk-factors');
        if (ai.risk_factors && ai.risk_factors.length) {
            factorsList.innerHTML = ai.risk_factors.map(f => `<li>${escapeHtml(f)}</li>`).join('');
        } else {
            factorsList.innerHTML = '<li>Automated scoring inconsistency flagged.</li>';
        }

        // Form default
        const inputMark = document.getElementById('workspace-final-mark-input');
        inputMark.value = ai.ai_mark !== null ? ai.ai_mark : '';
        inputMark.max = q.max_marks || 100;

        document.getElementById('btn-workspace-approve-ai').onclick = () => {
            inputMark.value = ai.ai_mark;
            submitTeacherDecision('APPROVED');
        };

        document.getElementById('btn-workspace-submit').onclick = () => {
            submitTeacherDecision('MODIFIED');
        };

        showPage('teacher-eval-workspace');
    } catch (err) {
        alert(`Failed to load review: ${err.message}`);
    } finally {
        hideLoading();
    }
}

async function submitTeacherDecision(decision) {
    if (!currentReviewAssignmentId) return;

    const markVal = parseFloat(document.getElementById('workspace-final-mark-input').value);
    const notesVal = document.getElementById('workspace-notes-input').value.trim();

    if (isNaN(markVal) || markVal < 0) {
        alert('Please enter a valid final mark.');
        return;
    }

    showLoading('Submitting finalized mark...');
    try {
        await apiPost(`/api/teacher/assignments/${currentReviewAssignmentId}/review`, {
            final_mark: markVal,
            teacher_notes: notesVal,
            decision: decision,
        });

        alert('Evaluation successfully approved and saved!');
        showPage('teacher-reviews');
    } catch (err) {
        alert(`Error submitting mark: ${err.message}`);
    } finally {
        hideLoading();
    }
}

// ──────────────────────────────────────────────────────────────────────
// Teacher Assigned Examinations & Answer Key Workflows
// ──────────────────────────────────────────────────────────────────────

let currentSelectedExamId = null;

async function loadTeacherExams() {
    try {
        const exams = await apiGet('/api/teacher/exams');
        const tbody = document.querySelector('#table-teacher-my-exams tbody');
        if (exams && exams.length) {
            tbody.innerHTML = exams.map(e => `
                <tr>
                    <td><strong>${escapeHtml(e.name)}</strong></td>
                    <td>${escapeHtml(e.subject_code ? `${e.subject_code} - ${e.subject_name}` : `Subject #${e.subject_id}`)}</td>
                    <td>${escapeHtml(e.exam_date || '—')}</td>
                    <td><strong>${e.total_marks}</strong></td>
                    <td>${e.active_answer_key_version ? `<span class="status-pill status-completed">v${e.active_answer_key_version} Active</span>` : `<span class="status-pill status-high_risk">No Key</span>`}</td>
                    <td><span class="status-pill status-completed">Active</span></td>
                    <td>
                        <button class="btn btn-primary" style="padding: 3px 10px; font-size: 0.78rem;" onclick="openAnswerKeyForExam(${e.id}, ${e.subject_id})">Key & Rubric →</button>
                    </td>
                </tr>
            `).join('');
        } else {
            tbody.innerHTML = '<tr><td colspan="7" class="empty-state">No examinations scheduled for your assigned subjects yet.</td></tr>';
        }
    } catch (err) {
        console.error('Failed to load teacher exams:', err);
    }
}

async function openAnswerKeyForExam(examId, subjectId) {
    showPage('teacher-answer-keys');
    await loadTeacherAnswerKeys();
    const subSelect = document.getElementById('ak-subject-select');
    if (subjectId && subSelect) {
        subSelect.value = subjectId;
        subSelect.dispatchEvent(new Event('change'));
    }
    const examSelect = document.getElementById('ak-exam-select');
    if (examSelect) {
        examSelect.value = examId;
        examSelect.dispatchEvent(new Event('change'));
    }
}

async function loadTeacherAnswerKeys() {
    try {
        const [subjects, exams] = await Promise.all([
            apiGet('/api/teacher/subjects'),
            apiGet('/api/teacher/exams'),
        ]);

        const subSelect = document.getElementById('ak-subject-select');
        const examSelect = document.getElementById('ak-exam-select');

        subSelect.innerHTML = '<option value="">-- All Assigned Subjects --</option>' +
            subjects.map(s => `<option value="${s.id}">${escapeHtml(s.code)} - ${escapeHtml(s.name)}</option>`).join('');

        function populateExams(filteredSubjectId = null) {
            let filtered = exams;
            if (filteredSubjectId) {
                filtered = exams.filter(e => String(e.subject_id) === String(filteredSubjectId));
            }
            examSelect.innerHTML = '<option value="">-- Select Examination --</option>' +
                filtered.map(e => `<option value="${e.id}">${escapeHtml(e.name)} (${escapeHtml(e.subject_code || '')})</option>`).join('');
        }

        populateExams();

        subSelect.onchange = () => {
            populateExams(subSelect.value);
            document.getElementById('ak-summary-card').style.display = 'none';
            document.getElementById('ak-questions-card').style.display = 'none';
            currentSelectedExamId = null;
        };

        examSelect.onchange = async () => {
            const examId = examSelect.value;
            if (!examId) {
                document.getElementById('ak-summary-card').style.display = 'none';
                document.getElementById('ak-questions-card').style.display = 'none';
                currentSelectedExamId = null;
                return;
            }
            currentSelectedExamId = examId;
            await loadAnswerKeyDetails(examId);
        };
    } catch (err) {
        console.error('Failed to load teacher answer keys workspace:', err);
    }
}

async function loadAnswerKeyDetails(examId) {
    showLoading('Loading answer key, question paper & rubrics...');
    try {
        const [keyData, questions, qpData] = await Promise.all([
            apiGet(`/api/teacher/exams/${examId}/answer-key`).catch(() => ({ has_active_key: false, versions: [] })),
            apiGet(`/api/exams/${examId}/questions`).catch(() => []),
            apiGet(`/api/teacher/exams/${examId}/question-papers`).catch(() => ({ has_active_question_paper: false, versions: [] })),
        ]);

        // Render Question Paper Summary Card
        renderQuestionPaperCard(examId, qpData);

        // Render Answer Key Summary Card
        const summaryCard = document.getElementById('ak-summary-card');
        const questionsCard = document.getElementById('ak-questions-card');
        summaryCard.style.display = 'block';
        questionsCard.style.display = 'block';

        const activeBadge = document.getElementById('ak-active-version-badge');
        const activeMeta = document.getElementById('ak-active-meta');
        const btnDownload = document.getElementById('btn-ak-download-file');
        const btnUpload = document.getElementById('btn-ak-open-upload');
        const btnArchiveActive = document.getElementById('btn-ak-archive-active');
        const versionsCount = document.getElementById('ak-versions-count');
        const versionsList = document.getElementById('ak-versions-list');

        const active = keyData.active_key;
        if (active) {
            activeBadge.textContent = `v${active.version} Active`;
            activeBadge.className = 'status-pill status-completed';
            const fileName = active.file_name || active.original_filename || 'Answer Key';
            const dateStr = active.created_at || active.uploaded_at;
            let dateDisplay = 'Not available';
            if (dateStr) {
                const d = new Date(dateStr);
                if (!isNaN(d.getTime())) dateDisplay = d.toLocaleString();
            }
            activeMeta.textContent = `File: ${fileName} • Uploaded by ${escapeHtml(active.uploader_name || 'Teacher')} on ${dateDisplay}`;
            btnDownload.style.display = 'inline-block';
            btnDownload.onclick = () => downloadAnswerKeyFile(active.id, fileName);

            if (btnArchiveActive) {
                btnArchiveActive.style.display = 'inline-block';
                btnArchiveActive.onclick = () => archiveAnswerKey(examId, active.id, active.version);
            }
        } else {
            activeBadge.textContent = 'No Active Key';
            activeBadge.className = 'status-pill status-high_risk';
            activeMeta.textContent = 'No official answer key file uploaded yet for this examination.';
            btnDownload.style.display = 'none';
            if (btnArchiveActive) btnArchiveActive.style.display = 'none';
        }

        btnUpload.onclick = () => {
            document.getElementById('ak-modal-exam-id').value = examId;
            openModal('modal-upload-answer-key');
        };

        const versions = keyData.versions || [];
        versionsCount.textContent = `${versions.length} version${versions.length === 1 ? '' : 's'}`;
        if (versions.length) {
            versionsList.innerHTML = versions.map(v => {
                const vFileName = v.file_name || v.original_filename || 'Answer Key';
                const vDateStr = v.created_at || v.uploaded_at;
                let vDateDisplay = 'Not available';
                if (vDateStr) {
                    const vd = new Date(vDateStr);
                    if (!isNaN(vd.getTime())) vDateDisplay = vd.toLocaleDateString();
                }
                const isArchived = v.status === 'ARCHIVED' || !v.is_active;

                return `
                <div style="display: flex; justify-content: space-between; align-items: center; background: #fff; padding: 0.5rem 0.75rem; border: 1px solid var(--color-border); border-radius: var(--radius-sm); font-size: 0.85rem; flex-wrap: wrap; gap: 0.5rem;">
                    <div>
                        <strong>v${v.version}</strong> — <code>${escapeHtml(vFileName)}</code>
                        <span class="status-pill status-${v.is_active ? 'completed' : 'low_risk'}" style="margin-left: 0.5rem; font-size: 0.72rem;">${v.is_active ? 'Active' : (v.status || 'Archived')}</span>
                        <span style="color: var(--color-text-secondary); margin-left: 0.5rem; font-size: 0.75rem;">${escapeHtml(v.uploader_name || 'Teacher')} • ${vDateDisplay}</span>
                    </div>
                    <div style="display: flex; gap: 0.35rem; align-items: center;">
                        <button class="btn btn-secondary" style="padding: 2px 8px; font-size: 0.75rem;" onclick="downloadAnswerKeyFile(${v.id}, '${escapeHtml(vFileName)}')">📥 Download</button>
                        ${v.is_active
                            ? `<button class="btn btn-secondary" style="padding: 2px 8px; font-size: 0.75rem;" onclick="archiveAnswerKey(${examId}, ${v.id}, ${v.version})">📦 Archive</button>`
                            : `<button class="btn btn-secondary" style="padding: 2px 8px; font-size: 0.75rem;" onclick="activateAnswerKey(${examId}, ${v.id}, ${v.version})">⚡ Activate</button>`
                        }
                        <button class="btn btn-secondary" style="padding: 2px 8px; font-size: 0.75rem; color: #b91c1c; border-color: #fca5a5;" onclick="deleteAnswerKey(${examId}, ${v.id}, ${v.version})">🗑️ Delete</button>
                    </div>
                </div>
            `;
            }).join('');
        } else {
            versionsList.innerHTML = '<p class="empty-state" style="margin: 0; font-size: 0.85rem;">No historical versions archived.</p>';
        }

        // Render questions & rubric scheme
        const tbody = document.querySelector('#table-ak-questions tbody');
        if (questions && questions.length) {
            tbody.innerHTML = questions.map(q => {
                let rubricCount = 0;
                try {
                    const r = typeof q.rubric_json === 'string' ? JSON.parse(q.rubric_json) : q.rubric_json;
                    if (r && r.criteria) rubricCount = r.criteria.length;
                } catch { /* ignore */ }
                return `
                    <tr>
                        <td><strong>Q${q.question_number}</strong></td>
                        <td>${escapeHtml(q.question_text)}</td>
                        <td><strong>${q.max_marks}</strong></td>
                        <td><small>${escapeHtml(q.reference_answer || '—')}</small></td>
                        <td><span class="status-pill status-completed">${rubricCount} criteria</span></td>
                        <td>
                            <button class="btn btn-secondary" style="padding: 2px 8px; font-size: 0.75rem;" onclick="editQuestionRubric(${examId}, ${q.id})">Edit</button>
                        </td>
                    </tr>
                `;
            }).join('');
        } else {
            tbody.innerHTML = '<tr><td colspan="6" class="empty-state">No questions configured yet for this examination.</td></tr>';
        }

        document.getElementById('btn-ak-add-question').onclick = () => {
            const form = document.getElementById('form-add-question');
            delete form.dataset.editQuestionId;
            document.getElementById('q-exam-id').value = examId;
            document.getElementById('q-number').value = questions.length + 1;
            document.getElementById('q-text').value = '';
            document.getElementById('q-marks').value = '5.0';
            document.getElementById('q-ref').value = '';
            document.getElementById('q-rubric').value = '';
            openModal('modal-add-question');
        };

        const btnUploadQp = document.getElementById('btn-ak-upload-qp');
        if (btnUploadQp) {
            btnUploadQp.onclick = () => {
                document.getElementById('qp-exam-id').value = examId;
                const errDiv = document.getElementById('qp-upload-error');
                if (errDiv) errDiv.style.display = 'none';
                const previewDiv = document.getElementById('qp-file-preview');
                if (previewDiv) previewDiv.style.display = 'none';
                const fileInput = document.getElementById('qp-file-input');
                if (fileInput) fileInput.value = '';
                currentSelectedQpFile = null;
                openModal('modal-upload-question-paper');
            };
        }

    } catch (err) {
        alert(`Failed to load answer key details: ${err.message}`);
    } finally {
        hideLoading();
    }
}

async function editQuestionRubric(examId, questionId) {
    try {
        const q = await apiGet(`/api/questions/${questionId}`);
        const form = document.getElementById('form-add-question');
        form.dataset.editQuestionId = questionId;
        document.getElementById('q-exam-id').value = examId;
        document.getElementById('q-number').value = q.question_number;
        document.getElementById('q-text').value = q.question_text;
        document.getElementById('q-marks').value = q.max_marks;
        document.getElementById('q-ref').value = q.reference_answer || '';
        document.getElementById('q-rubric').value = typeof q.rubric_json === 'object' ? JSON.stringify(q.rubric_json, null, 2) : (q.rubric_json || '');
        openModal('modal-add-question');
    } catch (err) {
        alert(`Failed to load question for editing: ${err.message}`);
    }
}

async function downloadAnswerKeyFile(keyId, fileName = 'answer_key') {
    showLoading('Downloading answer key file...');
    try {
        const resp = await fetch(`${API_BASE}/api/teacher/answer-keys/${keyId}/file`, {
            headers: authHeaders(false),
        });
        if (!resp.ok) {
            const err = await resp.json().catch(() => ({ detail: resp.statusText }));
            throw new Error(err.detail || 'Download failed');
        }
        const blob = await resp.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = fileName;
        document.body.appendChild(a);
        a.click();
        a.remove();
        window.URL.revokeObjectURL(url);
    } catch (err) {
        alert(`Download failed: ${err.message}`);
    } finally {
        hideLoading();
    }
}

function confirmActionModal({ title, message, details, confirmText = 'Confirm', onConfirm }) {
    const titleEl = document.getElementById('modal-confirm-title');
    const msgEl = document.getElementById('modal-confirm-message');
    const detailsEl = document.getElementById('modal-confirm-details');
    const btnSubmit = document.getElementById('btn-confirm-action-submit');

    if (titleEl) titleEl.textContent = title || '⚠️ Confirm Action';
    if (msgEl) msgEl.textContent = message || 'Are you sure you want to proceed?';
    if (detailsEl) detailsEl.textContent = details || 'This action cannot be undone.';
    if (btnSubmit) {
        btnSubmit.textContent = confirmText;
        btnSubmit.onclick = async () => {
            closeModal('modal-confirm-action');
            if (onConfirm) await onConfirm();
        };
    }
    openModal('modal-confirm-action');
}

function renderQuestionPaperCard(examId, qpData) {
    const qpSummaryCard = document.getElementById('qp-summary-card');
    if (!qpSummaryCard) return;
    qpSummaryCard.style.display = 'block';

    const activeBadge = document.getElementById('qp-active-version-badge');
    const activeMeta = document.getElementById('qp-active-meta');
    const btnDownload = document.getElementById('btn-qp-download-file');
    const btnPreview = document.getElementById('btn-qp-preview-file');
    const btnUpload = document.getElementById('btn-qp-open-upload');
    const btnArchive = document.getElementById('btn-qp-archive-active');
    const versionsCount = document.getElementById('qp-versions-count');
    const versionsList = document.getElementById('qp-versions-list');

    const active = qpData.active_question_paper;
    if (active) {
        activeBadge.textContent = `v${active.version} Active`;
        activeBadge.className = 'status-pill status-completed';

        const fileName = active.original_filename || active.file_name || 'Question Paper';
        const dateStr = active.uploaded_at || active.created_at;
        let dateDisplay = 'Not available';
        if (dateStr) {
            const d = new Date(dateStr);
            if (!isNaN(d.getTime())) dateDisplay = d.toLocaleString();
        }
        const sizeStr = active.file_size ? ` • ${(active.file_size / 1024).toFixed(1)} KB` : '';
        activeMeta.textContent = `File: ${fileName}${sizeStr} • ${active.question_count || 0} questions • Uploaded by ${escapeHtml(active.uploader_name || 'Teacher')} on ${dateDisplay}`;

        btnDownload.style.display = 'inline-block';
        btnDownload.onclick = () => downloadQuestionPaperFile(active.id, fileName);

        btnPreview.style.display = 'inline-block';
        btnPreview.onclick = () => {
            const previewUrl = `/api/teacher/exams/${examId}/question-paper/preview`;
            window.open(previewUrl, '_blank');
        };

        btnArchive.style.display = 'inline-block';
        btnArchive.onclick = () => archiveQuestionPaper(examId, active.id, active.version);
    } else {
        activeBadge.textContent = 'No Active Paper';
        activeBadge.className = 'status-pill status-high_risk';
        activeMeta.textContent = 'No official question paper uploaded yet for this examination.';
        btnDownload.style.display = 'none';
        btnPreview.style.display = 'none';
        btnArchive.style.display = 'none';
    }

    btnUpload.onclick = () => {
        document.getElementById('qp-exam-id').value = examId;
        const errDiv = document.getElementById('qp-upload-error');
        if (errDiv) errDiv.style.display = 'none';
        const previewDiv = document.getElementById('qp-file-preview');
        if (previewDiv) previewDiv.style.display = 'none';
        const progDiv = document.getElementById('qp-upload-progress');
        if (progDiv) progDiv.style.display = 'none';
        const fileInput = document.getElementById('qp-file-input');
        if (fileInput) fileInput.value = '';
        currentSelectedQpFile = null;
        openModal('modal-upload-question-paper');
    };

    const versions = qpData.versions || [];
    versionsCount.textContent = `${versions.length} version${versions.length === 1 ? '' : 's'}`;
    if (versions.length) {
        versionsList.innerHTML = versions.map(v => {
            const vFileName = v.original_filename || v.file_name || 'Question Paper';
            const vDateStr = v.uploaded_at || v.created_at;
            let vDateDisplay = 'Not available';
            if (vDateStr) {
                const vd = new Date(vDateStr);
                if (!isNaN(vd.getTime())) vDateDisplay = vd.toLocaleDateString();
            }

            return `
                <div style="display: flex; justify-content: space-between; align-items: center; background: #fff; padding: 0.5rem 0.75rem; border: 1px solid var(--color-border); border-radius: var(--radius-sm); font-size: 0.85rem; flex-wrap: wrap; gap: 0.5rem;">
                    <div>
                        <strong>v${v.version}</strong> — <code>${escapeHtml(vFileName)}</code>
                        <span class="status-pill status-${v.is_active ? 'completed' : 'low_risk'}" style="margin-left: 0.5rem; font-size: 0.72rem;">${v.is_active ? 'Active' : (v.status || 'Archived')}</span>
                        <span style="color: var(--color-text-secondary); margin-left: 0.5rem; font-size: 0.75rem;">${v.question_count || 0} Qs • ${escapeHtml(v.uploader_name || 'Teacher')} • ${vDateDisplay}</span>
                    </div>
                    <div style="display: flex; gap: 0.35rem; align-items: center;">
                        <button class="btn btn-secondary" style="padding: 2px 8px; font-size: 0.75rem;" onclick="downloadQuestionPaperFile(${v.id}, '${escapeHtml(vFileName)}')">📥 Download</button>
                        ${v.is_active
                            ? `<button class="btn btn-secondary" style="padding: 2px 8px; font-size: 0.75rem;" onclick="archiveQuestionPaper(${examId}, ${v.id}, ${v.version})">📦 Archive</button>`
                            : `<button class="btn btn-secondary" style="padding: 2px 8px; font-size: 0.75rem;" onclick="activateQuestionPaper(${examId}, ${v.id}, ${v.version})">⚡ Activate</button>`
                        }
                        <button class="btn btn-secondary" style="padding: 2px 8px; font-size: 0.75rem; color: #b91c1c; border-color: #fca5a5;" onclick="deleteQuestionPaper(${examId}, ${v.id}, ${v.version})">🗑️ Delete</button>
                    </div>
                </div>
            `;
        }).join('');
    } else {
        versionsList.innerHTML = '<p class="empty-state" style="margin: 0; font-size: 0.85rem;">No question paper versions recorded.</p>';
    }
}

async function downloadQuestionPaperFile(qpId, fileName = 'question_paper') {
    showLoading('Downloading question paper...');
    try {
        const resp = await fetch(`${API_BASE}/api/teacher/question-papers/${qpId}/file`, {
            headers: authHeaders(false),
        });
        if (!resp.ok) {
            const err = await resp.json().catch(() => ({ detail: resp.statusText }));
            throw new Error(err.detail || 'Download failed');
        }
        const blob = await resp.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = fileName;
        document.body.appendChild(a);
        a.click();
        a.remove();
        window.URL.revokeObjectURL(url);
    } catch (err) {
        alert(`Download failed: ${err.message}`);
    } finally {
        hideLoading();
    }
}

async function activateQuestionPaper(examId, qpId, version) {
    showLoading(`Activating question paper v${version}...`);
    try {
        await apiPost(`/api/teacher/exams/${examId}/question-papers/${qpId}/activate`);
        alert(`✓ Question paper v${version} is now active.`);
        await loadAnswerKeyDetails(examId);
    } catch (err) {
        alert(`Failed to activate: ${err.message}`);
    } finally {
        hideLoading();
    }
}

async function archiveQuestionPaper(examId, qpId, version) {
    confirmActionModal({
        title: `Archive Question Paper v${version}`,
        message: `Are you sure you want to archive Question Paper v${version}?`,
        details: 'Archiving marks this version as inactive while preserving all previous evaluation records and question links. It will not be used for new evaluations unless restored.',
        confirmText: 'Archive Version',
        onConfirm: async () => {
            showLoading(`Archiving question paper v${version}...`);
            try {
                await apiPost(`/api/teacher/exams/${examId}/question-papers/${qpId}/archive`);
                alert(`✓ Question paper v${version} has been archived.`);
                await loadAnswerKeyDetails(examId);
            } catch (err) {
                alert(`Failed to archive: ${err.message}`);
            } finally {
                hideLoading();
            }
        },
    });
}

async function deleteQuestionPaper(examId, qpId, version) {
    confirmActionModal({
        title: `Delete Question Paper v${version}`,
        message: `Permanently delete Question Paper v${version}?`,
        details: 'Deletion is only permitted if no student evaluations depend on this question paper. Evaluated student answer sheets and audit records will never be deleted.',
        confirmText: 'Delete Permanently',
        onConfirm: async () => {
            showLoading(`Deleting question paper v${version}...`);
            try {
                await apiDelete(`/api/teacher/exams/${examId}/question-papers/${qpId}`);
                alert(`✓ Question paper v${version} deleted.`);
                await loadAnswerKeyDetails(examId);
            } catch (err) {
                alert(`Cannot delete question paper: ${err.message}`);
            } finally {
                hideLoading();
            }
        },
    });
}

async function activateAnswerKey(examId, keyId, version) {
    showLoading(`Activating answer key v${version}...`);
    try {
        await apiPost(`/api/teacher/exams/${examId}/answer-keys/${keyId}/activate`);
        alert(`✓ Answer key v${version} is now active.`);
        await loadAnswerKeyDetails(examId);
    } catch (err) {
        alert(`Failed to activate: ${err.message}`);
    } finally {
        hideLoading();
    }
}

async function archiveAnswerKey(examId, keyId, version) {
    confirmActionModal({
        title: `Archive Answer Key v${version}`,
        message: `Are you sure you want to archive Answer Key v${version}?`,
        details: 'Archiving preserves historical evaluation reference data while marking this version inactive for future grading.',
        confirmText: 'Archive Key',
        onConfirm: async () => {
            showLoading(`Archiving answer key v${version}...`);
            try {
                await apiPost(`/api/teacher/exams/${examId}/answer-keys/${keyId}/archive`);
                alert(`✓ Answer key v${version} archived.`);
                await loadAnswerKeyDetails(examId);
            } catch (err) {
                alert(`Failed to archive: ${err.message}`);
            } finally {
                hideLoading();
            }
        },
    });
}

async function deleteAnswerKey(examId, keyId, version) {
    confirmActionModal({
        title: `Delete Answer Key v${version}`,
        message: `Permanently delete Answer Key v${version}?`,
        details: 'Answer keys used in completed student evaluations cannot be deleted to maintain auditability. Archiving is recommended.',
        confirmText: 'Delete Key',
        onConfirm: async () => {
            showLoading(`Deleting answer key v${version}...`);
            try {
                await apiDelete(`/api/teacher/exams/${examId}/answer-keys/${keyId}`);
                alert(`✓ Answer key v${version} removed.`);
                await loadAnswerKeyDetails(examId);
            } catch (err) {
                alert(`Cannot delete answer key: ${err.message}`);
            } finally {
                hideLoading();
            }
        },
    });
}

async function loadTeacherCompletedReviews() {
    try {
        const assignments = await apiGet('/api/teacher/assignments');
        const completed = assignments.filter(a => a.assignment_status === 'COMPLETED');
        const tbody = document.querySelector('#table-teacher-completed-reviews tbody');

        if (completed && completed.length) {
            tbody.innerHTML = completed.map(a => `
                <tr>
                    <td>#${a.assignment_id}</td>
                    <td><strong>Q${a.question_number || 1}</strong></td>
                    <td>${a.ai_mark !== null ? a.ai_mark : '—'}</td>
                    <td><strong>${a.final_mark !== null ? a.final_mark : '—'}</strong> / ${a.max_marks}</td>
                    <td><span class="status-pill status-completed">${a.decision || 'MODIFIED'}</span></td>
                    <td>${escapeHtml(a.teacher_notes || '—')}</td>
                    <td>${a.reviewed_at ? new Date(a.reviewed_at).toLocaleString() : '—'}</td>
                </tr>
            `).join('');
        } else {
            tbody.innerHTML = '<tr><td colspan="7" class="empty-state">No completed reviews recorded yet.</td></tr>';
        }
    } catch (err) {
        console.error('Failed to load completed reviews:', err);
    }
}

async function loadProfile() {
    if (!currentUser) return;
    try {
        const user = await apiGet('/api/auth/me');
        currentUser = user;
        document.getElementById('prof-name').textContent = user.full_name;
        document.getElementById('prof-avatar').textContent = (user.full_name || 'U').charAt(0).toUpperCase();
        const badge = document.getElementById('prof-role-badge');
        badge.textContent = user.role_name;
        badge.className = `status-pill status-completed role-badge-${user.role_name.toLowerCase()}`;
        document.getElementById('prof-username').textContent = user.username;
        document.getElementById('prof-empid').textContent = user.employee_id || 'Not assigned';
        document.getElementById('prof-email').textContent = user.email || '—';
        document.getElementById('prof-phone').textContent = user.phone || '—';
    } catch (err) {
        console.error('Failed to load profile:', err);
    }
}

// ──────────────────────────────────────────────────────────────────────
// Scanner Operations
// ──────────────────────────────────────────────────────────────────────

async function loadScannerDashboard() {
    try {
        const [scripts, issues, exams] = await Promise.all([
            apiGet('/api/scanner/scripts'),
            apiGet('/api/scanner/issues'),
            apiGet('/api/exams'),
        ]);

        document.getElementById('scn-stat-uploaded').textContent = scripts.length;
        document.getElementById('scn-stat-issues').textContent = issues.filter(i => i.status === 'OPEN').length;
        document.getElementById('scn-stat-processed').textContent = scripts.filter(s => s.status === 'COMPLETED' || s.status === 'RISK_REVIEW').length;

        // Populate exam select
        const examSelect = document.getElementById('upload-exam-select');
        examSelect.innerHTML = exams.map(e => `<option value="${e.id}">${e.name} (${e.subject_code || ''})</option>`).join('');

        // Issues table
        const tbody = document.querySelector('#table-scanner-issues tbody');
        const openIssues = issues.filter(i => i.status === 'OPEN');
        if (openIssues.length) {
            tbody.innerHTML = openIssues.map(i => `
                <tr>
                    <td>#${i.script_id}</td>
                    <td><strong>${escapeHtml(i.script_filename || 'Script #' + i.script_id)}</strong></td>
                    <td><span class="status-pill status-reupload_required">${i.issue_type}</span></td>
                    <td>${escapeHtml(i.description)}</td>
                    <td>${i.severity}</td>
                    <td>${i.status}</td>
                    <td>
                        <button class="btn btn-primary" style="padding: 2px 8px; font-size: 0.75rem;" onclick="openRescanModal(${i.script_id})">Re-upload Scan</button>
                    </td>
                </tr>
            `).join('');
        } else {
            tbody.innerHTML = '<tr><td colspan="7" class="empty-state">✓ No open scan issues. All uploaded scripts meet quality standards.</td></tr>';
        }
    } catch (err) {
        console.error('Failed to load scanner dashboard:', err);
    }
}

function openRescanModal(scriptId) {
    document.getElementById('rescan-script-id').textContent = scriptId;
    document.getElementById('rescan-id').value = scriptId;
    openModal('modal-rescan');
}

// ──────────────────────────────────────────────────────────────────────
// Results Page
// ──────────────────────────────────────────────────────────────────────

async function loadResultsPage() {
    try {
        const exams = await apiGet('/api/exams');
        const select = document.getElementById('results-exam-select');
        select.innerHTML = '<option value="">-- Choose Examination --</option>' + exams.map(e => `<option value="${e.id}">${e.name} (${e.subject_code || ''})</option>`).join('');

        select.onchange = async () => {
            const examId = select.value;
            if (!examId) return;
            showLoading('Aggregating examination results...');
            try {
                const data = await apiGet(`/api/exams/${examId}/results`);
                document.getElementById('r-stat-avg').textContent = `${data.class_average} / ${data.total_marks}`;
                document.getElementById('r-stat-high').textContent = `${data.highest_score} / ${data.total_marks}`;
                document.getElementById('r-stat-pass').textContent = `${data.pass_percentage}%`;

                const tbody = document.querySelector('#table-exam-results tbody');
                if (data.students && data.students.length) {
                    tbody.innerHTML = data.students.map((st, idx) => `
                        <tr>
                            <td>#${idx + 1}</td>
                            <td><strong>${escapeHtml(st.student_name)}</strong></td>
                            <td><code>${escapeHtml(st.student_usn)}</code></td>
                            <td><strong>${st.total_obtained}</strong> / ${st.total_max}</td>
                            <td>${st.percentage}%</td>
                            <td><span class="status-pill status-${st.percentage >= 40 ? 'low_risk' : 'high_risk'}">${st.percentage >= 40 ? 'PASS' : 'FAIL'}</span></td>
                        </tr>
                    `).join('');
                } else {
                    tbody.innerHTML = '<tr><td colspan="6" class="empty-state">No finalized evaluations for this examination yet.</td></tr>';
                }
            } catch (err) {
                alert(`Error loading results: ${err.message}`);
            } finally {
                hideLoading();
            }
        };
    } catch (err) {
        console.error('Failed to load exams for results:', err);
    }
}

// ──────────────────────────────────────────────────────────────────────
// Notifications
// ──────────────────────────────────────────────────────────────────────

async function checkNotifications() {
    if (!currentUser) return;
    try {
        const notifs = await apiGet('/api/notifications?unread_only=true');
        const badge = document.getElementById('notif-count-badge');
        if (notifs.length > 0) {
            badge.textContent = notifs.length;
            badge.style.display = 'inline-block';
        } else {
            badge.style.display = 'none';
        }
    } catch { /* ignore */ }
}

async function loadNotificationsPage() {
    try {
        const notifs = await apiGet('/api/notifications');
        const list = document.getElementById('notifications-list');
        if (notifs && notifs.length) {
            list.innerHTML = notifs.map(n => `
                <li style="padding: 1rem; border-bottom: 1px solid var(--color-border); display: flex; justify-content: space-between; align-items: center; background: ${n.is_read ? 'transparent' : '#f0fdf4'};">
                    <div>
                        <strong>${escapeHtml(n.title)}</strong>
                        <p style="font-size: 0.88rem; color: var(--color-text-secondary); margin: 0.25rem 0 0 0;">${escapeHtml(n.message)}</p>
                        <small style="color: var(--color-text-muted); font-size: 0.75rem;">${n.created_at ? new Date(n.created_at).toLocaleString() : ''}</small>
                    </div>
                    ${!n.is_read ? `<button class="btn btn-secondary" style="padding: 2px 8px; font-size: 0.75rem;" onclick="markNotificationRead(${n.id})">Mark Read</button>` : '<span style="color: var(--color-text-muted); font-size: 0.8rem;">Read</span>'}
                </li>
            `).join('');
        } else {
            list.innerHTML = '<li class="empty-state">No notifications yet.</li>';
        }
    } catch (err) {
        console.error('Failed to load notifications:', err);
    }
}

async function markNotificationRead(id) {
    try {
        await apiPost(`/api/notifications/${id}/read`);
        loadNotificationsPage();
        checkNotifications();
    } catch (err) {
        alert(err.message);
    }
}

// ──────────────────────────────────────────────────────────────────────
// Modal Helpers & Form Handlers
// ──────────────────────────────────────────────────────────────────────

function openModal(id) {
    const m = document.getElementById(id);
    if (m) m.style.display = 'flex';
}

function closeModal(id) {
    const m = document.getElementById(id);
    if (m) m.style.display = 'none';
}

// ──────────────────────────────────────────────────────────────────────
// PRESERVED: Step-by-Step AI Evaluation Pipeline Demo
// ──────────────────────────────────────────────────────────────────────

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

async function handleFileUpload(file) {
    showLoading('Uploading image...');
    const formData = new FormData();
    formData.append('file', file);

    try {
        const result = await apiPost('/api/upload', formData, false);
        currentSessionId = result.session_id;

        const reader = new FileReader();
        reader.onload = (e) => {
            document.getElementById('preview-image').src = e.target.result;
            document.getElementById('preview-filename').textContent = file.name;
            document.getElementById('upload-preview').style.display = 'block';
        };
        reader.readAsDataURL(file);

        document.getElementById('preprocess-section').style.display = 'block';
        document.getElementById('preprocess-section').scrollIntoView({ behavior: 'smooth' });
    } catch (err) {
        alert(`Upload failed: ${err.message}`);
    } finally {
        hideLoading();
    }
}

document.getElementById('btn-preprocess')?.addEventListener('click', async () => {
    if (!currentSessionId) return;
    showLoading('Running image preprocessing...');
    try {
        const data = await apiPost(`/api/preprocess/${currentSessionId}`);
        const box = document.getElementById('preprocess-result');
        box.style.display = 'block';
        box.innerHTML = `<p><strong>✓ Preprocessing Complete:</strong> Image deskewed and cleaned up.</p>`;
        document.getElementById('htr-section').style.display = 'block';
        document.getElementById('htr-section').scrollIntoView({ behavior: 'smooth' });
    } catch (err) {
        alert(`Preprocessing failed: ${err.message}`);
    } finally {
        hideLoading();
    }
});

document.getElementById('btn-recognize')?.addEventListener('click', async () => {
    if (!currentSessionId) return;
    showLoading('Running TrOCR Handwriting Recognition (CPU)...');
    try {
        const data = await apiPost(`/api/recognize/${currentSessionId}`);
        const box = document.getElementById('htr-result');
        box.style.display = 'block';
        box.innerHTML = `
            <p><strong>Recognised Text (${data.lines ? data.lines.length : 0} lines, Conf: ${data.average_confidence ? (data.average_confidence * 100).toFixed(1) + '%' : 'N/A'}):</strong></p>
            <pre style="background: var(--color-surface-2); padding: 0.75rem; margin-top: 0.5rem; border-radius: var(--radius-sm); font-family: monospace;">${escapeHtml(data.text)}</pre>
        `;
        document.getElementById('evaluate-section').style.display = 'block';
        document.getElementById('evaluate-section').scrollIntoView({ behavior: 'smooth' });
    } catch (err) {
        alert(`HTR failed: ${err.message}`);
    } finally {
        hideLoading();
    }
});

document.getElementById('btn-load-sample-rubric')?.addEventListener('click', () => {
    document.getElementById('rubric-textarea').value = JSON.stringify(SAMPLE_RUBRIC, null, 2);
});

document.getElementById('btn-evaluate')?.addEventListener('click', async () => {
    if (!currentSessionId) return;
    const rubricJson = document.getElementById('rubric-textarea').value.trim();
    if (!rubricJson) {
        alert('Please paste or load a rubric JSON.');
        return;
    }

    showLoading('Evaluating text with Sentence-BERT...');
    const formData = new FormData();
    formData.append('rubric_json', rubricJson);

    try {
        const data = await apiPost(`/api/evaluate/${currentSessionId}`, formData, false);
        const res = data.result;
        const box = document.getElementById('eval-result');
        box.style.display = 'block';
        box.innerHTML = `
            <p><strong>AI Preliminary Score:</strong> <span style="font-size: 1.25rem; font-weight: 700; color: var(--color-primary-600);">${res.total_score} / ${res.max_score}</span></p>
            <p>Overall Semantic Similarity: ${(res.overall_similarity * 100).toFixed(1)}%</p>
        `;
        document.getElementById('risk-section').style.display = 'block';
        document.getElementById('risk-section').scrollIntoView({ behavior: 'smooth' });
    } catch (err) {
        alert(`Evaluation failed: ${err.message}`);
    } finally {
        hideLoading();
    }
});

document.getElementById('btn-predict-risk')?.addEventListener('click', async () => {
    if (!currentSessionId) return;
    showLoading('Running ML Grading Error Risk Model...');
    try {
        const data = await apiPost(`/api/predict-risk/${currentSessionId}`);
        const pred = data.prediction;
        const box = document.getElementById('risk-result');
        box.style.display = 'block';
        box.innerHTML = `
            <div class="risk-alert-box ${pred.risk_label === 'LOW' ? 'low' : ''}">
                <p><strong>Risk Label:</strong> <span class="status-pill status-${pred.risk_label === 'HIGH' ? 'high_risk' : 'low_risk'}">${pred.risk_label}</span> (${(pred.risk_probability * 100).toFixed(1)}% risk probability)</p>
                <p style="margin-top: 0.5rem;"><strong>Contributing Indicators:</strong></p>
                <ul>${(pred.contributing_factors || []).map(f => `<li>${escapeHtml(f)}</li>`).join('')}</ul>
            </div>
        `;
        document.getElementById('review-section-inline').style.display = 'block';
        document.getElementById('review-section-inline').scrollIntoView({ behavior: 'smooth' });
    } catch (err) {
        alert(`Risk prediction failed: ${err.message}`);
    } finally {
        hideLoading();
    }
});

document.getElementById('btn-approve')?.addEventListener('click', () => {
    const aiMarkEl = document.querySelector('#eval-result span');
    if (aiMarkEl) {
        const val = parseFloat(aiMarkEl.textContent);
        document.getElementById('examiner-mark-input').value = val;
    }
    submitInlineReview('approved');
});

document.getElementById('btn-submit-review')?.addEventListener('click', () => {
    submitInlineReview('modified');
});

async function submitInlineReview(action) {
    if (!currentSessionId) return;
    const mark = parseFloat(document.getElementById('examiner-mark-input').value);
    const notes = document.getElementById('examiner-notes-input').value;

    if (isNaN(mark)) {
        alert('Please enter a valid final mark.');
        return;
    }

    showLoading('Submitting review...');
    const formData = new FormData();
    formData.append('examiner_mark', mark);
    formData.append('examiner_notes', notes);

    try {
        await apiPost(`/api/submit-review/${currentSessionId}`, formData, false);
        const box = document.getElementById('review-result');
        box.style.display = 'block';
        box.innerHTML = `<p style="color: var(--color-success); font-weight: 600;">✓ Examiner review submitted successfully. Final mark: ${mark}</p>`;
    } catch (err) {
        alert(err.message);
    } finally {
        hideLoading();
    }
}

// ──────────────────────────────────────────────────────────────────────
// PRESERVED: Model Info Page
// ──────────────────────────────────────────────────────────────────────

async function refreshModelInfo() {
    const content = document.getElementById('model-info-content');
    try {
        const info = await apiGet('/api/model-info');
        if (info.status === 'loaded') {
            content.innerHTML = `
                <p><strong>Model:</strong> ${escapeHtml(info.model_name)}</p>
                <p style="margin-top: 0.5rem;"><strong>Target:</strong> Predicts whether AI evaluation absolute error &gt;= 2.0 marks.</p>
                <p style="margin-top: 0.5rem;"><strong>Features (${info.feature_names ? info.feature_names.length : 0}):</strong></p>
                <div style="display: flex; flex-wrap: wrap; gap: 6px; margin-top: 0.5rem;">
                    ${(info.feature_names || []).map(f => `<span class="status-pill status-uploaded"><code>${escapeHtml(f)}</code></span>`).join('')}
                </div>
            `;
        } else {
            content.innerHTML = `<p class="empty-state">${escapeHtml(info.message || 'No trained model available.')}</p>`;
        }
    } catch {
        content.innerHTML = '<p class="empty-state">Could not connect to model service.</p>';
    }
}

// ──────────────────────────────────────────────────────────────────────
// Helper Functions
// ──────────────────────────────────────────────────────────────────────

function showLoading(text = 'Processing...') {
    document.getElementById('loading-text').textContent = text;
    document.getElementById('loading-overlay').style.display = 'flex';
}

function hideLoading() {
    document.getElementById('loading-overlay').style.display = 'none';
}

function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str || '';
    return div.innerHTML;
}

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

// ──────────────────────────────────────────────────────────────────────
// Event Listeners Initialization
// ──────────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
    // Check initial authentication
    checkAuth();

    // Topbar events
    document.getElementById('btn-login-open')?.addEventListener('click', () => openModal('modal-login'));
    document.getElementById('btn-logout')?.addEventListener('click', () => logout());
    document.getElementById('btn-toggle-notifs')?.addEventListener('click', () => showPage('notifications'));
    document.getElementById('btn-mark-all-read')?.addEventListener('click', async () => {
        await apiPost('/api/notifications/read-all');
        loadNotificationsPage();
        checkNotifications();
    });

    // Auto-assign risky answers (HOD)
    document.getElementById('btn-hod-auto-assign')?.addEventListener('click', async () => {
        showLoading('Balancing pending high-risk workload across teachers...');
        try {
            const res = await apiPost('/api/evaluations/auto-assign');
            alert(res.message);
            loadHodOverview();
        } catch (err) {
            alert(err.message);
        } finally {
            hideLoading();
        }
    });

    // Login Form Submit
    document.getElementById('form-login')?.addEventListener('submit', (e) => {
        e.preventDefault();
        const u = document.getElementById('login-username').value.trim();
        const p = document.getElementById('login-password').value;
        login(u, p);
    });

    // Add User Form
    document.getElementById('form-add-user')?.addEventListener('submit', async (e) => {
        e.preventDefault();
        showLoading('Registering user...');
        try {
            await apiPost('/api/users', {
                role_id: parseInt(document.getElementById('user-role-select').value),
                full_name: document.getElementById('user-fullname').value,
                username: document.getElementById('user-username').value,
                email: document.getElementById('user-email').value,
                employee_id: document.getElementById('user-empid').value || null,
                password: document.getElementById('user-password').value,
            });
            closeModal('modal-add-user');
            loadHodUsers();
        } catch (err) {
            alert(err.message);
        } finally {
            hideLoading();
        }
    });

    // Add Role Form
    document.getElementById('form-add-role')?.addEventListener('submit', async (e) => {
        e.preventDefault();
        showLoading('Creating role...');
        try {
            await apiPost('/api/roles', {
                name: document.getElementById('role-name').value,
                description: document.getElementById('role-desc').value,
            });
            closeModal('modal-add-role');
            loadHodRoles();
        } catch (err) {
            alert(err.message);
        } finally {
            hideLoading();
        }
    });

    // Add Department Form
    document.getElementById('form-add-dept')?.addEventListener('submit', async (e) => {
        e.preventDefault();
        try {
            await apiPost('/api/departments', {
                code: document.getElementById('dept-code').value,
                name: document.getElementById('dept-name').value,
            });
            closeModal('modal-add-dept');
            loadHodAcademics();
        } catch (err) {
            alert(err.message);
        }
    });

    // Add Section Form
    document.getElementById('form-add-section')?.addEventListener('submit', async (e) => {
        e.preventDefault();
        try {
            await apiPost('/api/sections', {
                department_id: parseInt(document.getElementById('sec-dept-select').value),
                name: document.getElementById('sec-name').value,
                semester: parseInt(document.getElementById('sec-sem').value),
                academic_year: document.getElementById('sec-year').value,
            });
            closeModal('modal-add-section');
            loadHodAcademics();
        } catch (err) {
            alert(err.message);
        }
    });

    // Add Student Form
    document.getElementById('form-add-student')?.addEventListener('submit', async (e) => {
        e.preventDefault();
        try {
            await apiPost('/api/students', {
                usn: document.getElementById('stud-usn').value,
                name: document.getElementById('stud-name').value,
                section_id: parseInt(document.getElementById('stud-sec-select').value),
                roll_number: document.getElementById('stud-roll').value || null,
                email: document.getElementById('stud-email').value || null,
            });
            closeModal('modal-add-student');
            loadHodAcademics();
        } catch (err) {
            alert(err.message);
        }
    });

    // Add Subject Form
    document.getElementById('form-add-subject')?.addEventListener('submit', async (e) => {
        e.preventDefault();
        try {
            await apiPost('/api/subjects', {
                code: document.getElementById('sub-code').value,
                name: document.getElementById('sub-name').value,
                department_id: parseInt(document.getElementById('sub-dept-select').value),
                semester: parseInt(document.getElementById('sub-sem').value),
                max_marks: parseFloat(document.getElementById('sub-marks').value),
            });
            closeModal('modal-add-subject');
            loadHodAcademics();
        } catch (err) {
            alert(err.message);
        }
    });

    // Add Mapping Form
    document.getElementById('form-add-mapping')?.addEventListener('submit', async (e) => {
        e.preventDefault();
        try {
            await apiPost('/api/teacher-subjects', {
                teacher_id: parseInt(document.getElementById('map-teacher-select').value),
                subject_id: parseInt(document.getElementById('map-subject-select').value),
                section_id: document.getElementById('map-section-select').value ? parseInt(document.getElementById('map-section-select').value) : null,
                academic_year: document.getElementById('map-year').value || null,
            });
            closeModal('modal-add-mapping');
            loadHodAcademics();
        } catch (err) {
            alert(err.message);
        }
    });

    // Add Exam Form
    document.getElementById('form-add-exam')?.addEventListener('submit', async (e) => {
        e.preventDefault();
        try {
            await apiPost('/api/exams', {
                subject_id: parseInt(document.getElementById('exam-subject-select').value),
                name: document.getElementById('exam-name').value,
                exam_type: document.getElementById('exam-type').value,
                total_marks: parseFloat(document.getElementById('exam-marks').value),
                exam_date: document.getElementById('exam-date').value || null,
                academic_year: document.getElementById('exam-year').value,
            });
            closeModal('modal-add-exam');
            loadHodExams();
        } catch (err) {
            alert(err.message);
        }
    });

    // Add / Edit Question Form
    document.getElementById('form-add-question')?.addEventListener('submit', async (e) => {
        e.preventDefault();
        const form = document.getElementById('form-add-question');
        const examId = document.getElementById('q-exam-id').value;
        const editQuestionId = form.dataset.editQuestionId;

        const payload = {
            question_number: parseInt(document.getElementById('q-number').value),
            question_text: document.getElementById('q-text').value,
            max_marks: parseFloat(document.getElementById('q-marks').value),
            reference_answer: document.getElementById('q-ref').value || null,
            rubric_json: document.getElementById('q-rubric').value || null,
        };

        try {
            if (editQuestionId) {
                await apiPut(`/api/questions/${editQuestionId}`, payload);
                delete form.dataset.editQuestionId;
                alert('✓ Question and rubric updated successfully.');
            } else {
                await apiPost(`/api/exams/${examId}/questions`, payload);
                alert('✓ Question and rubric added successfully.');
            }
            closeModal('modal-add-question');
            if (document.getElementById('exam-questions-panel')?.style.display !== 'none') {
                viewExamQuestions(examId, 'Exam');
            }
            if (currentSelectedExamId && String(currentSelectedExamId) === String(examId)) {
                loadAnswerKeyDetails(examId);
            }
        } catch (err) {
            alert(err.message);
        }
    });

    // Answer Key Upload Form
    document.getElementById('form-upload-answer-key')?.addEventListener('submit', async (e) => {
        e.preventDefault();
        const examId = document.getElementById('ak-modal-exam-id').value;
        const fileInput = document.getElementById('ak-modal-file');
        const file = fileInput.files[0];
        const questionsJson = document.getElementById('ak-modal-questions-json').value.trim();

        if (!file) {
            alert('Please select an official answer key file.');
            return;
        }

        showLoading('Uploading answer key and creating new active version...');
        const formData = new FormData();
        formData.append('file', file);
        if (questionsJson) {
            formData.append('questions_json', questionsJson);
        }

        try {
            const res = await apiPost(`/api/teacher/exams/${examId}/answer-key`, formData, false);
            closeModal('modal-upload-answer-key');
            alert(`✓ Answer key version ${res.version} activated successfully!`);
            fileInput.value = '';
            document.getElementById('ak-modal-questions-json').value = '';
            if (currentSelectedExamId) {
                loadAnswerKeyDetails(currentSelectedExamId);
            }
            loadTeacherExams();
        } catch (err) {
            alert(`Answer key upload failed: ${err.message}`);
        } finally {
            hideLoading();
        }
    });

    // Scanner Upload Area & File Validation
    const scnUploadArea = document.getElementById('scanner-upload-area');
    const scnFileInput = document.getElementById('scanner-file-input');
    const scnFeedback = document.getElementById('scanner-upload-feedback');
    const ALLOWED_UPLOAD_EXTS = ['.png', '.jpg', '.jpeg', '.pdf'];
    const MAX_UPLOAD_BYTES = 25 * 1024 * 1024; // 25 MB
    let currentScannerFile = null;

    function handleScannerFileSelection(file) {
        if (!file) return false;

        // Reset feedback
        if (scnFeedback) {
            scnFeedback.style.display = 'none';
            scnFeedback.textContent = '';
        }

        const ext = '.' + file.name.split('.').pop().toLowerCase();
        if (!ALLOWED_UPLOAD_EXTS.includes(ext)) {
            const err = `Unsupported file type "${ext}". Allowed formats: PNG, JPG, JPEG, PDF.`;
            if (scnFeedback) {
                scnFeedback.style.display = 'block';
                scnFeedback.style.background = '#fee2e2';
                scnFeedback.style.color = '#b91c1c';
                scnFeedback.style.border = '1px solid #fca5a5';
                scnFeedback.textContent = `❌ ${err}`;
            }
            alert(err);
            document.getElementById('scanner-file-preview').style.display = 'none';
            currentScannerFile = null;
            if (scnFileInput) scnFileInput.value = '';
            return false;
        }

        if (file.size > MAX_UPLOAD_BYTES) {
            const sizeMb = (file.size / (1024 * 1024)).toFixed(1);
            const err = `File size (${sizeMb} MB) exceeds maximum upload limit of 25 MB.`;
            if (scnFeedback) {
                scnFeedback.style.display = 'block';
                scnFeedback.style.background = '#fee2e2';
                scnFeedback.style.color = '#b91c1c';
                scnFeedback.style.border = '1px solid #fca5a5';
                scnFeedback.textContent = `❌ ${err}`;
            }
            alert(err);
            document.getElementById('scanner-file-preview').style.display = 'none';
            currentScannerFile = null;
            if (scnFileInput) scnFileInput.value = '';
            return false;
        }

        currentScannerFile = file;
        const sizeFormatted = file.size < 1024 * 1024
            ? `${(file.size / 1024).toFixed(1)} KB`
            : `${(file.size / (1024 * 1024)).toFixed(2)} MB`;
        const typeFormatted = ext === '.pdf' ? 'PDF Document' : (file.type || `${ext.replace('.', '').toUpperCase()} Image`);

        document.getElementById('scanner-selected-filename').textContent = file.name;
        const fileTypeEl = document.getElementById('scanner-selected-filetype');
        if (fileTypeEl) fileTypeEl.textContent = typeFormatted;
        const fileSizeEl = document.getElementById('scanner-selected-filesize');
        if (fileSizeEl) fileSizeEl.textContent = sizeFormatted;
        document.getElementById('scanner-file-preview').style.display = 'block';
        return true;
    }

    if (scnUploadArea && scnFileInput) {
        scnUploadArea.addEventListener('click', () => scnFileInput.click());
        scnFileInput.addEventListener('change', () => {
            if (scnFileInput.files.length) {
                handleScannerFileSelection(scnFileInput.files[0]);
            }
        });

        // Drag & Drop handlers
        ['dragenter', 'dragover'].forEach(eventName => {
            scnUploadArea.addEventListener(eventName, (e) => {
                e.preventDefault();
                e.stopPropagation();
                scnUploadArea.classList.add('dragover');
            });
        });

        ['dragleave', 'dragend'].forEach(eventName => {
            scnUploadArea.addEventListener(eventName, (e) => {
                e.preventDefault();
                e.stopPropagation();
                scnUploadArea.classList.remove('dragover');
            });
        });

        scnUploadArea.addEventListener('drop', (e) => {
            e.preventDefault();
            e.stopPropagation();
            scnUploadArea.classList.remove('dragover');
            if (e.dataTransfer && e.dataTransfer.files.length) {
                const droppedFile = e.dataTransfer.files[0];
                const valid = handleScannerFileSelection(droppedFile);
                if (valid && scnFileInput) {
                    try {
                        const dt = new DataTransfer();
                        dt.items.add(droppedFile);
                        scnFileInput.files = dt.files;
                    } catch (_) {
                        // fallback
                    }
                }
            }
        });
    }

    // Scanner Upload Form Submit
    document.getElementById('form-scanner-upload')?.addEventListener('submit', async (e) => {
        e.preventDefault();
        const examId = document.getElementById('upload-exam-select').value;
        const studentUsn = document.getElementById('upload-student-usn').value.trim();
        const file = currentScannerFile || (scnFileInput ? scnFileInput.files[0] : null);

        if (!file) {
            alert('Please select or drop an answer sheet file (PNG, JPG, JPEG, PDF).');
            return;
        }

        const btnSubmit = document.getElementById('btn-submit-upload');
        if (btnSubmit) {
            btnSubmit.disabled = true;
            btnSubmit.textContent = 'Processing upload...';
        }

        const isPdf = file.name.toLowerCase().endsWith('.pdf');
        showLoading(isPdf
            ? 'Uploading and processing PDF answer script (rendering pages at high resolution)...'
            : 'Uploading script and running blur validation...'
        );

        const formData = new FormData();
        formData.append('exam_id', examId);
        if (studentUsn) formData.append('student_usn', studentUsn);
        formData.append('file', file);

        try {
            const res = await apiPost('/api/scripts/upload', formData, false);
            if (scnFeedback) {
                scnFeedback.style.display = 'block';
                if (res.status === 'REUPLOAD_REQUIRED') {
                    scnFeedback.style.background = '#fef3c7';
                    scnFeedback.style.color = '#d97706';
                    scnFeedback.style.border = '1px solid #fcd34d';
                    scnFeedback.textContent = `⚠️ Scan Quality Issue: Script #${res.id} flagged as ${res.scan_quality}. Rescan required.`;
                    alert(`⚠️ Scan Quality Issue Detected: Script was flagged as ${res.scan_quality}. A scan issue has been logged and rescan is required.`);
                } else {
                    scnFeedback.style.background = '#dcfce7';
                    scnFeedback.style.color = '#16a34a';
                    scnFeedback.style.border = '1px solid #86efac';
                    scnFeedback.textContent = `✓ Script #${res.id} (${res.original_filename}) uploaded successfully with ${res.scan_quality} quality.`;
                    alert(`✓ Script #${res.id} uploaded successfully with ${res.scan_quality} quality.`);
                }
            } else {
                if (res.status === 'REUPLOAD_REQUIRED') {
                    alert(`⚠️ Scan Quality Issue Detected: Script was flagged as ${res.scan_quality}. Rescan required.`);
                } else {
                    alert(`✓ Script #${res.id} uploaded successfully with ${res.scan_quality} quality.`);
                }
            }

            // Reset selection state
            currentScannerFile = null;
            if (scnFileInput) scnFileInput.value = '';
            document.getElementById('scanner-file-preview').style.display = 'none';
            document.getElementById('upload-student-usn').value = '';

            loadScannerDashboard();
        } catch (err) {
            if (scnFeedback) {
                scnFeedback.style.display = 'block';
                scnFeedback.style.background = '#fee2e2';
                scnFeedback.style.color = '#b91c1c';
                scnFeedback.style.border = '1px solid #fca5a5';
                scnFeedback.textContent = `❌ Upload failed: ${err.message}`;
            }
            alert(`Upload error: ${err.message}`);
        } finally {
            if (btnSubmit) {
                btnSubmit.disabled = false;
                btnSubmit.textContent = 'Upload & Validate Scan';
            }
            hideLoading();
        }
    });

    // Rescan Form Submit
    document.getElementById('form-rescan')?.addEventListener('submit', async (e) => {
        e.preventDefault();
        const scriptId = document.getElementById('rescan-id').value;
        const file = document.getElementById('rescan-file').files[0];

        if (!file) {
            alert('Please select a replacement image.');
            return;
        }

        showLoading('Uploading replacement scan...');
        const formData = new FormData();
        formData.append('file', file);

        try {
            await apiPost(`/api/scripts/${scriptId}/rescan`, formData, false);
            closeModal('modal-rescan');
            alert('✓ Replacement scan accepted and issue marked as resolved.');
            loadScannerDashboard();
        } catch (err) {
            alert(err.message);
        } finally {
            hideLoading();
        }
    });

    // ─── Initialize Question Paper Upload & Review ───
    initQuestionPaperUpload();
    document.getElementById('btn-qp-add-empty-q')?.addEventListener('click', addBlankReviewQuestion);
    document.getElementById('btn-qp-save-only')?.addEventListener('click', () => saveConfirmedQuestions(true));
    document.getElementById('btn-qp-save-and-continue')?.addEventListener('click', () => saveConfirmedQuestions(false));
});

// ══════════════════════════════════════════════════════════════
// Question Paper Upload & Interactive Review Workspace
// ══════════════════════════════════════════════════════════════
let currentSelectedQpFile = null;
let currentReviewQuestions = [];
let currentQpMetadata = null;
let currentQpExamId = null;
let currentQpPreviewPage = 1;

function initQuestionPaperUpload() {
    const qpUploadArea = document.getElementById('qp-upload-area');
    const qpFileInput = document.getElementById('qp-file-input');
    const qpFilePreview = document.getElementById('qp-file-preview');
    const qpSelectedFilename = document.getElementById('qp-selected-filename');
    const qpSelectedFiletype = document.getElementById('qp-selected-filetype');
    const qpSelectedFilesize = document.getElementById('qp-selected-filesize');
    const qpUploadError = document.getElementById('qp-upload-error');
    const formUploadQp = document.getElementById('form-upload-question-paper');

    if (!qpUploadArea || !qpFileInput) return;

    function handleQpFileSelect(file) {
        if (!file) return false;
        const ext = '.' + file.name.split('.').pop().toLowerCase();
        const allowedExts = ['.pdf', '.png', '.jpg', '.jpeg', '.txt'];
        if (!allowedExts.includes(ext)) {
            if (qpUploadError) {
                qpUploadError.style.display = 'block';
                qpUploadError.textContent = `Unsupported format "${ext}". Allowed: PDF, PNG, JPG, JPEG, TXT.`;
            }
            return false;
        }

        const maxBytes = 25 * 1024 * 1024;
        if (file.size > maxBytes) {
            if (qpUploadError) {
                qpUploadError.style.display = 'block';
                qpUploadError.textContent = `File size (${(file.size / (1024 * 1024)).toFixed(1)} MB) exceeds maximum limit of 25 MB.`;
            }
            return false;
        }

        if (qpUploadError) qpUploadError.style.display = 'none';
        currentSelectedQpFile = file;

        if (qpFilePreview && qpSelectedFilename) {
            qpSelectedFilename.textContent = file.name;
            if (qpSelectedFiletype) qpSelectedFiletype.textContent = file.type || ext.toUpperCase();
            if (qpSelectedFilesize) qpSelectedFilesize.textContent = `${(file.size / 1024).toFixed(1)} KB`;
            qpFilePreview.style.display = 'block';
        }
        return true;
    }

    qpUploadArea.addEventListener('click', () => qpFileInput.click());

    qpFileInput.addEventListener('change', () => {
        if (qpFileInput.files && qpFileInput.files.length) {
            handleQpFileSelect(qpFileInput.files[0]);
        }
    });

    ['dragenter', 'dragover'].forEach(evt => {
        qpUploadArea.addEventListener(evt, (e) => {
            e.preventDefault();
            e.stopPropagation();
            qpUploadArea.style.borderColor = 'var(--color-primary)';
            qpUploadArea.style.background = 'var(--color-surface-2)';
        });
    });

    ['dragleave', 'dragend', 'drop'].forEach(evt => {
        qpUploadArea.addEventListener(evt, (e) => {
            e.preventDefault();
            e.stopPropagation();
            qpUploadArea.style.borderColor = 'var(--color-border)';
            qpUploadArea.style.background = 'transparent';
        });
    });

    qpUploadArea.addEventListener('drop', (e) => {
        if (e.dataTransfer && e.dataTransfer.files.length) {
            const dropped = e.dataTransfer.files[0];
            const ok = handleQpFileSelect(dropped);
            if (ok) {
                try {
                    const dt = new DataTransfer();
                    dt.items.add(dropped);
                    qpFileInput.files = dt.files;
                } catch (_) {}
            }
        }
    });

    formUploadQp?.addEventListener('submit', async (e) => {
        e.preventDefault();
        const examId = document.getElementById('qp-exam-id')?.value;
        const file = currentSelectedQpFile || (qpFileInput ? qpFileInput.files[0] : null);

        if (!examId) {
            alert('Please select an examination first.');
            return;
        }
        if (!file) {
            alert('Please choose or drop a question paper file.');
            return;
        }

        const btnSubmit = document.getElementById('btn-submit-qp-upload');
        if (btnSubmit) {
            btnSubmit.disabled = true;
            btnSubmit.textContent = 'Processing Question Paper...';
        }

        const progressDiv = document.getElementById('qp-upload-progress');
        const progressStep = document.getElementById('qp-progress-step');
        if (progressDiv) progressDiv.style.display = 'block';
        if (progressStep) progressStep.textContent = 'Stage 1/4: Uploading question paper file...';

        const timer1 = setTimeout(() => {
            if (progressStep) progressStep.textContent = 'Stage 2/4: Extracting text & analyzing document layout...';
        }, 500);
        const timer2 = setTimeout(() => {
            if (progressStep) progressStep.textContent = 'Stage 3/4: Detecting section marking rules & subquestions...';
        }, 1200);
        const timer3 = setTimeout(() => {
            if (progressStep) progressStep.textContent = 'Stage 4/4: Segmenting questions & assigning marks...';
        }, 2000);

        const formData = new FormData();
        formData.append('file', file);

        try {
            const res = await apiPost(`/api/teacher/exams/${examId}/upload-question-paper`, formData, false);
            clearTimeout(timer1);
            clearTimeout(timer2);
            clearTimeout(timer3);
            if (progressStep) progressStep.textContent = '✓ Complete! Opening review workspace...';
            closeModal('modal-upload-question-paper');
            openQuestionExtractionReview(res, examId);
        } catch (err) {
            clearTimeout(timer1);
            clearTimeout(timer2);
            clearTimeout(timer3);
            if (qpUploadError) {
                qpUploadError.style.display = 'block';
                qpUploadError.textContent = `Extraction failed: ${err.message}`;
            } else {
                alert(`Upload failed: ${err.message}`);
            }
        } finally {
            if (progressDiv) progressDiv.style.display = 'none';
            if (btnSubmit) {
                btnSubmit.disabled = false;
                btnSubmit.textContent = 'Extract Questions Automatically';
            }
        }
    });
}

// ─────────────────────────────────────────────────────────────────────────────
// Question Extraction Review & Bulk Management Workspace
// ─────────────────────────────────────────────────────────────────────────────

let currentReviewSections = [];
let selectedQuestionIndices = new Set();
let deletedQuestionsHistory = [];
let currentReviewViewMode = 'table'; // 'table' or 'cards'
let hasUnsavedReviewChanges = false;

function handleCloseReviewModal() {
    if (hasUnsavedReviewChanges) {
        confirmActionModal({
            title: 'Unsaved Changes',
            message: 'You have uncommitted modifications to questions or marks.',
            details: 'Closing the review workspace will discard these adjustments. Are you sure you want to close?',
            confirmText: 'Discard Changes',
            onConfirm: () => {
                hasUnsavedReviewChanges = false;
                closeModal('modal-review-questions');
            },
        });
    } else {
        closeModal('modal-review-questions');
    }
}

function openQuestionExtractionReview(data, examId) {
    currentQpExamId = examId;
    currentQpMetadata = data;
    currentQpPreviewPage = 1;
    deletedQuestionsHistory = [];
    selectedQuestionIndices.clear();
    currentReviewViewMode = 'table';
    hasUnsavedReviewChanges = false;

    // Deep copy questions with normalized fields
    currentReviewQuestions = (data.questions || []).map((q, idx) => ({
        question_number: q.question_number || (idx + 1),
        section: q.section || null,
        question_text: q.question_text || '',
        max_marks: q.max_marks !== null && q.max_marks !== undefined ? parseFloat(q.max_marks) : null,
        confidence: q.confidence || (q.max_marks ? 'HIGH' : 'LOW'),
        marks_source: q.marks_source || (q.max_marks ? 'Detected from document' : 'Unresolved: Teacher input required'),
        subquestions: Array.isArray(q.subquestions) ? q.subquestions : [],
        reference_answer: q.reference_answer || '',
        warnings: Array.isArray(q.warnings) ? q.warnings : [],
        criteria: [],
    }));

    // Collect distinct sections
    const secSet = new Set();
    currentReviewQuestions.forEach(q => {
        if (q.section) secSet.add(q.section);
    });
    currentReviewSections = Array.from(secSet);

    // Populate bulk section select dropdown
    const bulkSecSelect = document.getElementById('qp-bulk-section-select');
    if (bulkSecSelect) {
        bulkSecSelect.innerHTML = '<option value="">Choose Section...</option>' +
            currentReviewSections.map(s => `<option value="${escapeHtml(s)}">${escapeHtml(s)}</option>`).join('');
    }

    // Header badge
    const badge = document.getElementById('qp-review-doc-badge');
    if (badge) {
        badge.textContent = `${data.filename} (${data.page_count} page${data.page_count === 1 ? '' : 's'} • ${currentReviewQuestions.length} questions)`;
    }

    // Warnings banner
    const warningsContainer = document.getElementById('qp-review-warnings-container');
    const warningsList = document.getElementById('qp-review-warnings-list');
    const allWarnings = data.warnings || [];
    if (allWarnings.length && warningsContainer && warningsList) {
        warningsList.innerHTML = allWarnings.map(w => `<div>&bull; ${escapeHtml(w)}</div>`).join('');
        warningsContainer.style.display = 'block';
    } else if (warningsContainer) {
        warningsContainer.style.display = 'none';
    }

    // Left pane: Extracted raw text
    const rawTextEl = document.getElementById('qp-raw-extracted-text');
    if (rawTextEl) {
        rawTextEl.textContent = data.raw_text || '(No text extracted)';
    }

    // Left pane: Document visual preview
    setupQpPreviewPane(data);

    // Setup bulk tools & view toggles
    setupReviewToolsAndFilters();

    // Render questions in selected view
    renderQuestionReview();

    openModal('modal-review-questions');
}

function setupReviewToolsAndFilters() {
    // View Switch buttons
    const btnViewTable = document.getElementById('btn-qp-view-table');
    const btnViewCards = document.getElementById('btn-qp-view-cards');
    const tableContainer = document.getElementById('qp-review-table-container');
    const cardsContainer = document.getElementById('qp-review-cards-list');

    if (btnViewTable && btnViewCards) {
        btnViewTable.onclick = () => {
            currentReviewViewMode = 'table';
            btnViewTable.className = 'btn btn-sm btn-primary';
            btnViewCards.className = 'btn btn-sm btn-secondary';
            if (tableContainer) tableContainer.style.display = 'block';
            if (cardsContainer) cardsContainer.style.display = 'none';
            renderQuestionReview();
        };

        btnViewCards.onclick = () => {
            currentReviewViewMode = 'cards';
            btnViewCards.className = 'btn btn-sm btn-primary';
            btnViewTable.className = 'btn btn-sm btn-secondary';
            if (tableContainer) tableContainer.style.display = 'none';
            if (cardsContainer) cardsContainer.style.display = 'flex';
            renderQuestionReview();
        };
    }

    // Search input & Status filter
    const searchInput = document.getElementById('qp-search-filter');
    const statusFilter = document.getElementById('qp-status-filter');
    if (searchInput) searchInput.oninput = () => renderQuestionReview();
    if (statusFilter) statusFilter.onchange = () => renderQuestionReview();

    // Add empty question button
    const btnAddEmpty = document.getElementById('btn-qp-add-empty-q');
    if (btnAddEmpty) btnAddEmpty.onclick = () => addBlankReviewQuestion();

    // Bulk Confirm Confident Marks
    const btnBulkConfirm = document.getElementById('btn-qp-bulk-confirm');
    if (btnBulkConfirm) {
        btnBulkConfirm.onclick = () => {
            let count = 0;
            currentReviewQuestions.forEach(q => {
                if (q.max_marks !== null && q.max_marks > 0) {
                    q.confidence = 'HIGH';
                    q.marks_source = 'Verified & confirmed by teacher';
                    q.warnings = q.warnings.filter(w => !w.includes('MARKS REQUIRED'));
                    count++;
                }
            });
            hasUnsavedReviewChanges = true;
            renderQuestionReview();
            alert(`✓ Confirmed marks for ${count} questions.`);
        };
    }

    // Bulk Apply to Section
    const btnApplySec = document.getElementById('btn-qp-apply-section-marks');
    if (btnApplySec) {
        btnApplySec.onclick = () => {
            const sec = document.getElementById('qp-bulk-section-select')?.value;
            const marksVal = parseFloat(document.getElementById('qp-bulk-section-marks')?.value);
            if (!sec) {
                alert('Please select a section to apply marks to.');
                return;
            }
            if (isNaN(marksVal) || marksVal <= 0) {
                alert('Please enter a valid positive marks value.');
                return;
            }
            let updated = 0;
            currentReviewQuestions.forEach(q => {
                if (q.section === sec) {
                    q.max_marks = marksVal;
                    q.confidence = 'HIGH';
                    q.marks_source = `Bulk applied to ${sec} (${marksVal} Marks)`;
                    q.warnings = q.warnings.filter(w => !w.includes('MARKS REQUIRED'));
                    updated++;
                }
            });
            hasUnsavedReviewChanges = true;
            renderQuestionReview();
            alert(`✓ Applied ${marksVal} marks to ${updated} questions in ${sec}.`);
        };
    }

    // Bulk Apply to Range
    const btnApplyRange = document.getElementById('btn-qp-apply-range-marks');
    if (btnApplyRange) {
        btnApplyRange.onclick = () => {
            const fromQ = parseInt(document.getElementById('qp-bulk-range-from')?.value, 10);
            const toQ = parseInt(document.getElementById('qp-bulk-range-to')?.value, 10);
            const marksVal = parseFloat(document.getElementById('qp-bulk-range-marks')?.value);

            if (isNaN(fromQ) || isNaN(toQ) || fromQ > toQ) {
                alert('Please specify a valid question range (From Q# <= To Q#).');
                return;
            }
            if (isNaN(marksVal) || marksVal <= 0) {
                alert('Please enter a valid positive marks value.');
                return;
            }
            let updated = 0;
            currentReviewQuestions.forEach(q => {
                if (q.question_number >= fromQ && q.question_number <= toQ) {
                    q.max_marks = marksVal;
                    q.confidence = 'HIGH';
                    q.marks_source = `Bulk range Q${fromQ}–Q${toQ} (${marksVal} Marks)`;
                    q.warnings = q.warnings.filter(w => !w.includes('MARKS REQUIRED'));
                    updated++;
                }
            });
            hasUnsavedReviewChanges = true;
            renderQuestionReview();
            alert(`✓ Applied ${marksVal} marks to questions Q${fromQ} through Q${toQ} (${updated} questions).`);
        };
    }

    // Bulk Apply to Unresolved
    const btnApplyUnresolved = document.getElementById('btn-qp-apply-unresolved-marks');
    if (btnApplyUnresolved) {
        btnApplyUnresolved.onclick = () => {
            const marksVal = parseFloat(document.getElementById('qp-bulk-unresolved-marks')?.value);
            if (isNaN(marksVal) || marksVal <= 0) {
                alert('Please enter a valid positive marks value.');
                return;
            }
            let updated = 0;
            currentReviewQuestions.forEach(q => {
                if (q.max_marks === null || q.max_marks <= 0) {
                    q.max_marks = marksVal;
                    q.confidence = 'MEDIUM';
                    q.marks_source = `Assigned to unresolved questions (${marksVal} Marks)`;
                    q.warnings = q.warnings.filter(w => !w.includes('MARKS REQUIRED'));
                    updated++;
                }
            });
            hasUnsavedReviewChanges = true;
            renderQuestionReview();
            alert(`✓ Applied ${marksVal} marks to ${updated} previously unresolved questions.`);
        };
    }

    // Bulk Selection Actions
    const selectAllCheckbox = document.getElementById('qp-select-all-qs');
    if (selectAllCheckbox) {
        selectAllCheckbox.onchange = (e) => {
            const checked = e.target.checked;
            selectedQuestionIndices.clear();
            if (checked) {
                currentReviewQuestions.forEach((_, idx) => selectedQuestionIndices.add(idx));
            }
            updateBulkSelectionBar();
            renderQuestionReviewTableRows();
        };
    }

    const btnSetSelectedMarks = document.getElementById('btn-qp-set-selected-marks');
    if (btnSetSelectedMarks) {
        btnSetSelectedMarks.onclick = () => {
            const val = parseFloat(document.getElementById('qp-selected-marks-input')?.value);
            if (isNaN(val) || val <= 0) {
                alert('Please enter a valid positive marks value.');
                return;
            }
            selectedQuestionIndices.forEach(idx => {
                if (currentReviewQuestions[idx]) {
                    currentReviewQuestions[idx].max_marks = val;
                    currentReviewQuestions[idx].confidence = 'HIGH';
                    currentReviewQuestions[idx].marks_source = `Teacher bulk selection (${val} Marks)`;
                    currentReviewQuestions[idx].warnings = currentReviewQuestions[idx].warnings.filter(w => !w.includes('MARKS REQUIRED'));
                }
            });
            hasUnsavedReviewChanges = true;
            selectedQuestionIndices.clear();
            updateBulkSelectionBar();
            renderQuestionReview();
        };
    }

    const btnDeleteSelected = document.getElementById('btn-qp-delete-selected');
    if (btnDeleteSelected) {
        btnDeleteSelected.onclick = () => {
            if (!selectedQuestionIndices.size) return;
            const toDelete = Array.from(selectedQuestionIndices).sort((a, b) => b - a);
            const deletedItems = [];
            toDelete.forEach(idx => {
                deletedItems.push({ index: idx, item: currentReviewQuestions[idx] });
                currentReviewQuestions.splice(idx, 1);
            });
            deletedQuestionsHistory.push(deletedItems);
            selectedQuestionIndices.clear();
            hasUnsavedReviewChanges = true;

            const undoBtn = document.getElementById('btn-qp-undo-delete');
            if (undoBtn) undoBtn.style.display = 'inline-block';

            updateBulkSelectionBar();
            renderQuestionReview();
        };
    }

    const btnUndoDelete = document.getElementById('btn-qp-undo-delete');
    if (btnUndoDelete) {
        btnUndoDelete.onclick = () => {
            if (!deletedQuestionsHistory.length) return;
            const lastBatch = deletedQuestionsHistory.pop();
            // Restore in ascending order
            lastBatch.sort((a, b) => a.index - b.index).forEach(({ index, item }) => {
                currentReviewQuestions.splice(Math.min(index, currentReviewQuestions.length), 0, item);
            });
            hasUnsavedReviewChanges = true;
            if (!deletedQuestionsHistory.length) btnUndoDelete.style.display = 'none';
            renderQuestionReview();
        };
    }

    // Modal Footer Save buttons
    const btnSaveOnly = document.getElementById('btn-qp-save-only');
    const btnSaveAndContinue = document.getElementById('btn-qp-save-and-continue');
    if (btnSaveOnly) btnSaveOnly.onclick = () => saveConfirmedQuestions(true);
    if (btnSaveAndContinue) btnSaveAndContinue.onclick = () => saveConfirmedQuestions(false);
}

function updateBulkSelectionBar() {
    const bar = document.getElementById('qp-bulk-selection-bar');
    const countEl = document.getElementById('qp-selected-count');
    const selectAllCb = document.getElementById('qp-select-all-qs');

    if (!bar) return;
    if (selectedQuestionIndices.size > 0) {
        bar.style.display = 'flex';
        if (countEl) countEl.textContent = selectedQuestionIndices.size;
    } else {
        bar.style.display = 'none';
        if (selectAllCb) selectAllCb.checked = false;
    }
}

function getFilteredQuestionIndices() {
    const searchText = (document.getElementById('qp-search-filter')?.value || '').toLowerCase().trim();
    const statusVal = document.getElementById('qp-status-filter')?.value || 'all';

    const indices = [];
    currentReviewQuestions.forEach((q, idx) => {
        // Status filter
        if (statusVal === 'missing' && (q.max_marks !== null && q.max_marks > 0)) return;
        if (statusVal === 'confident' && (q.max_marks === null || q.max_marks <= 0 || q.confidence === 'LOW')) return;

        // Search text
        if (searchText) {
            const matchesNum = String(q.question_number).includes(searchText);
            const matchesText = (q.question_text || '').toLowerCase().includes(searchText);
            const matchesSec = (q.section || '').toLowerCase().includes(searchText);
            if (!matchesNum && !matchesText && !matchesSec) return;
        }

        indices.push(idx);
    });
    return indices;
}

function renderQuestionReview() {
    const detectedCountEl = document.getElementById('qp-detected-count');
    if (detectedCountEl) {
        detectedCountEl.textContent = `${currentReviewQuestions.length} Questions Extracted`;
    }

    if (currentReviewViewMode === 'table') {
        renderQuestionReviewTableRows();
    } else {
        renderQuestionReviewCards();
    }

    updateQpReviewFooter();
}

function renderQuestionReviewTableRows() {
    const tbody = document.getElementById('qp-review-table-body');
    if (!tbody) return;

    const filteredIndices = getFilteredQuestionIndices();

    if (!filteredIndices.length) {
        tbody.innerHTML = '<tr><td colspan="7" class="empty-state" style="padding: 2rem; text-align: center; color: var(--color-text-secondary);">No questions match current filters.</td></tr>';
        return;
    }

    tbody.innerHTML = filteredIndices.map(idx => {
        const q = currentReviewQuestions[idx];
        const isSelected = selectedQuestionIndices.has(idx);
        const hasMissingMarks = q.max_marks === null || q.max_marks === undefined || isNaN(q.max_marks) || q.max_marks <= 0;
        const marksVal = hasMissingMarks ? '' : q.max_marks;

        let badgeHtml = '';
        if (hasMissingMarks) {
            badgeHtml = `<span class="status-pill status-high_risk" title="${escapeHtml(q.marks_source || 'Marks required')}" style="font-size: 0.72rem;">⚠️ Required</span>`;
        } else if (q.confidence === 'HIGH') {
            badgeHtml = `<span class="status-pill status-completed" title="${escapeHtml(q.marks_source)}" style="font-size: 0.72rem;">✓ High</span>`;
        } else {
            badgeHtml = `<span class="status-pill status-low_risk" title="${escapeHtml(q.marks_source)}" style="font-size: 0.72rem;">~ ${escapeHtml(q.confidence || 'Medium')}</span>`;
        }

        return `
            <tr style="${isSelected ? 'background: #eff6ff;' : ''}">
                <td style="text-align: center;">
                    <input type="checkbox" class="qp-row-cb" data-idx="${idx}" ${isSelected ? 'checked' : ''}>
                </td>
                <td>
                    <input type="number" min="1" class="compact-q-num" data-idx="${idx}" value="${q.question_number}" style="width: 44px; padding: 2px 4px; font-size: 0.82rem; font-weight: 700; border: 1px solid var(--color-border); border-radius: var(--radius-sm);">
                </td>
                <td>
                    <span class="status-pill status-low_risk" style="font-size: 0.72rem;">${escapeHtml(q.section || 'General')}</span>
                </td>
                <td>
                    <textarea class="compact-q-text" data-idx="${idx}" rows="1" style="width: 100%; font-size: 0.82rem; padding: 3px 5px; border: 1px solid var(--color-border); border-radius: var(--radius-sm); resize: vertical; line-height: 1.3;">${escapeHtml(q.question_text)}</textarea>
                </td>
                <td>
                    <input type="number" step="0.5" min="0.5" class="compact-q-marks ${hasMissingMarks ? 'qp-missing-marks' : ''}" data-idx="${idx}" value="${marksVal}" placeholder="Marks" style="width: 58px; font-weight: 700; padding: 2px 4px; font-size: 0.82rem; border: 1px solid ${hasMissingMarks ? '#ef4444' : '#10b981'}; background: ${hasMissingMarks ? '#fef2f2' : '#f0fdf4'}; border-radius: var(--radius-sm);">
                </td>
                <td>
                    ${badgeHtml}
                    <div style="font-size: 0.7rem; color: var(--color-text-secondary); margin-top: 2px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 140px;" title="${escapeHtml(q.marks_source || '')}">
                        ${escapeHtml(q.marks_source || '')}
                    </div>
                </td>
                <td style="text-align: center;">
                    <button type="button" class="btn btn-secondary btn-sm" onclick="removeReviewQuestion(${idx})" title="Remove Question" style="padding: 1px 6px; font-size: 0.72rem; color: #b91c1c; border-color: #fca5a5;">✕</button>
                </td>
            </tr>
        `;
    }).join('');

    // Attach row listeners
    tbody.querySelectorAll('.qp-row-cb').forEach(cb => {
        cb.onchange = (e) => {
            const idx = parseInt(e.target.dataset.idx, 10);
            if (e.target.checked) selectedQuestionIndices.add(idx);
            else selectedQuestionIndices.delete(idx);
            updateBulkSelectionBar();
            renderQuestionReviewTableRows();
        };
    });

    tbody.querySelectorAll('.compact-q-num').forEach(el => {
        el.onchange = (e) => {
            const idx = parseInt(e.target.dataset.idx, 10);
            currentReviewQuestions[idx].question_number = parseInt(e.target.value, 10) || (idx + 1);
            hasUnsavedReviewChanges = true;
        };
    });

    tbody.querySelectorAll('.compact-q-marks').forEach(el => {
        el.oninput = (e) => {
            const idx = parseInt(e.target.dataset.idx, 10);
            const val = parseFloat(e.target.value);
            currentReviewQuestions[idx].max_marks = isNaN(val) ? null : val;
            currentReviewQuestions[idx].confidence = 'HIGH';
            currentReviewQuestions[idx].marks_source = 'Manually adjusted by teacher';
            hasUnsavedReviewChanges = true;
            updateQpReviewFooter();
        };
    });

    tbody.querySelectorAll('.compact-q-text').forEach(el => {
        el.oninput = (e) => {
            const idx = parseInt(e.target.dataset.idx, 10);
            currentReviewQuestions[idx].question_text = e.target.value;
            hasUnsavedReviewChanges = true;
        };
    });
}

function setupQpPreviewPane(data) {
    const tabDoc = document.getElementById('btn-qp-tab-doc');
    const tabText = document.getElementById('btn-qp-tab-text');
    const contentDoc = document.getElementById('qp-tab-content-doc');
    const contentText = document.getElementById('qp-tab-content-text');
    const imgEl = document.getElementById('qp-doc-img-preview');
    const emptyEl = document.getElementById('qp-doc-empty-preview');
    const pagerEl = document.getElementById('qp-preview-pager');
    const pageIndicator = document.getElementById('qp-page-indicator');
    const btnPrev = document.getElementById('btn-qp-prev-page');
    const btnNext = document.getElementById('btn-qp-next-page');

    function showDocTab() {
        if (contentDoc) contentDoc.style.display = 'block';
        if (contentText) contentText.style.display = 'none';
        if (tabDoc) tabDoc.className = 'btn btn-primary btn-sm';
        if (tabText) tabText.className = 'btn btn-secondary btn-sm';
    }

    function showTextTab() {
        if (contentDoc) contentDoc.style.display = 'none';
        if (contentText) contentText.style.display = 'block';
        if (tabDoc) tabDoc.className = 'btn btn-secondary btn-sm';
        if (tabText) tabText.className = 'btn btn-primary btn-sm';
    }

    if (tabDoc) tabDoc.onclick = showDocTab;
    if (tabText) tabText.onclick = showTextTab;

    const ext = (data.file_type || '').toLowerCase();
    const isImageOrPdf = ['.pdf', '.png', '.jpg', '.jpeg'].includes(ext);

    if (isImageOrPdf && data.preview_url) {
        showDocTab();
        function updatePreviewImage() {
            if (imgEl) {
                imgEl.src = `${data.preview_url}?page=${currentQpPreviewPage}&t=${Date.now()}`;
                imgEl.style.display = 'inline-block';
            }
            if (emptyEl) emptyEl.style.display = 'none';
            if (pageIndicator) pageIndicator.textContent = `Page ${currentQpPreviewPage} / ${data.page_count || 1}`;
        }
        updatePreviewImage();

        if (data.page_count && data.page_count > 1 && pagerEl) {
            pagerEl.style.display = 'flex';
            if (btnPrev) {
                btnPrev.onclick = () => {
                    if (currentQpPreviewPage > 1) {
                        currentQpPreviewPage--;
                        updatePreviewImage();
                    }
                };
            }
            if (btnNext) {
                btnNext.onclick = () => {
                    if (currentQpPreviewPage < data.page_count) {
                        currentQpPreviewPage++;
                        updatePreviewImage();
                    }
                };
            }
        } else if (pagerEl) {
            pagerEl.style.display = 'none';
        }
    } else {
        showTextTab();
        if (imgEl) imgEl.style.display = 'none';
        if (emptyEl) emptyEl.style.display = 'block';
        if (pagerEl) pagerEl.style.display = 'none';
    }
}

function renderQuestionReviewCards() {
    const container = document.getElementById('qp-review-cards-list');
    if (!container) return;

    const filteredIndices = getFilteredQuestionIndices();

    if (!filteredIndices.length) {
        container.innerHTML = `
            <div style="text-align: center; padding: 3rem 1rem; color: var(--color-text-secondary);">
                <p>No questions match current filters.</p>
                <button type="button" class="btn btn-secondary btn-sm" onclick="addBlankReviewQuestion()">+ Add New Question</button>
            </div>
        `;
        return;
    }

    container.innerHTML = filteredIndices.map(idx => {
        const q = currentReviewQuestions[idx];
        const hasMissingMarks = q.max_marks === null || q.max_marks === undefined || isNaN(q.max_marks) || q.max_marks <= 0;
        const marksVal = hasMissingMarks ? '' : q.max_marks;
        const subqsHtml = (q.subquestions && q.subquestions.length)
            ? `<div style="margin-top: 0.5rem; padding: 0.5rem; background: var(--color-surface-2); border-radius: var(--radius-sm); font-size: 0.8rem;">
                <strong style="color: var(--color-text-secondary);">Detected Subparts:</strong>
                ${q.subquestions.map(s => {
                    const label = s.label || '';
                    const text = s.text || s;
                    const mark = s.marks ? ` [${s.marks} Marks]` : '';
                    return `<div style="margin-top: 0.2rem;">&bull; <strong>${escapeHtml(label)}</strong> ${escapeHtml(text)}${mark}</div>`;
                }).join('')}
               </div>`
            : '';

        const critCount = (q.criteria || []).length;

        return `
            <div class="card qp-review-card" data-idx="${idx}" style="border: 1px solid var(--color-border); padding: 1rem; background: var(--color-surface); box-shadow: 0 1px 3px rgba(0,0,0,0.03);">
                <!-- Card Header -->
                <div style="display: flex; justify-content: space-between; align-items: center; gap: 0.5rem; flex-wrap: wrap;">
                    <div style="display: flex; align-items: center; gap: 0.5rem;">
                        <span style="font-weight: 700; font-size: 0.95rem;">Q #</span>
                        <input type="number" min="1" class="qp-input-qnum" data-idx="${idx}" value="${q.question_number}" style="width: 60px; padding: 3px 6px; font-weight: 700; border: 1px solid var(--color-border); border-radius: var(--radius-sm);">
                        
                        ${q.section ? `<span class="status-pill status-low_risk" style="font-size: 0.72rem;">${escapeHtml(q.section)}</span>` : ''}

                        <span style="font-size: 0.88rem; color: var(--color-text-secondary); margin-left: 0.5rem;">Max Marks:</span>
                        <input type="number" step="0.5" min="0.5" class="qp-input-marks ${hasMissingMarks ? 'qp-missing-marks' : ''}" data-idx="${idx}" value="${marksVal}" placeholder="Marks *" style="width: 80px; padding: 3px 6px; font-weight: 600; border: 1px solid ${hasMissingMarks ? '#f59e0b' : 'var(--color-border)'}; background: ${hasMissingMarks ? '#fffbeb' : '#fff'}; border-radius: var(--radius-sm);">
                        
                        ${hasMissingMarks
                            ? '<span class="status-pill status-high_risk" style="font-size: 0.72rem; padding: 2px 6px;">Marks Required</span>'
                            : `<span class="status-pill status-completed" style="font-size: 0.72rem;" title="${escapeHtml(q.marks_source)}">✓ ${escapeHtml(q.confidence || 'HIGH')}</span>`
                        }
                    </div>

                    <button type="button" class="btn btn-secondary btn-sm" onclick="removeReviewQuestion(${idx})" title="Remove Question" style="padding: 2px 8px; color: #b91c1c; border-color: #fca5a5;">✕ Remove</button>
                </div>

                <!-- Provenance note -->
                ${q.marks_source ? `<div style="font-size: 0.72rem; color: var(--color-text-secondary); margin-top: 0.35rem;">Provenance: ${escapeHtml(q.marks_source)}</div>` : ''}

                <!-- Question Text -->
                <div style="margin-top: 0.75rem;">
                    <textarea class="form-control qp-input-text" data-idx="${idx}" rows="2" placeholder="Question statement..." style="width: 100%; font-size: 0.88rem; padding: 0.5rem; border: 1px solid var(--color-border); border-radius: var(--radius-sm); resize: vertical;">${escapeHtml(q.question_text)}</textarea>
                </div>

                ${subqsHtml}

                <!-- Collapsible Rubric & Reference Answer Accordion -->
                <details style="margin-top: 0.75rem; border-top: 1px dashed var(--color-border); padding-top: 0.5rem;">
                    <summary style="cursor: pointer; font-size: 0.82rem; font-weight: 600; color: var(--color-primary); user-select: none;">
                        Reference Answer & Grading Rubric (${critCount} criteria)
                    </summary>
                    <div style="margin-top: 0.75rem; display: flex; flex-direction: column; gap: 0.75rem;">
                        <div>
                            <label style="font-size: 0.78rem; font-weight: 600; color: var(--color-text-secondary); display: block; margin-bottom: 0.25rem;">Reference / Expected Answer:</label>
                            <textarea class="form-control qp-input-refans" data-idx="${idx}" rows="2" placeholder="Expected student answer solution / key..." style="width: 100%; font-size: 0.85rem; padding: 0.4rem; border: 1px solid var(--color-border); border-radius: var(--radius-sm);">${escapeHtml(q.reference_answer || '')}</textarea>
                        </div>

                        <!-- Criteria list -->
                        <div>
                            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.4rem;">
                                <label style="font-size: 0.78rem; font-weight: 600; color: var(--color-text-secondary);">Rubric Criteria Breakdown:</label>
                                <button type="button" class="btn btn-secondary btn-sm" onclick="addCriterionToQuestion(${idx})" style="font-size: 0.75rem; padding: 2px 6px;">+ Add Criterion</button>
                            </div>
                            <div class="qp-criteria-container" data-idx="${idx}" style="display: flex; flex-direction: column; gap: 0.4rem;">
                                ${renderCriteriaItemsHtml(q.criteria, idx, q.max_marks)}
                            </div>
                        </div>
                    </div>
                </details>
            </div>
        `;
    }).join('');

    // Attach listeners
    container.querySelectorAll('.qp-input-qnum').forEach(el => {
        el.onchange = (e) => {
            const idx = parseInt(e.target.dataset.idx, 10);
            currentReviewQuestions[idx].question_number = parseInt(e.target.value, 10) || (idx + 1);
            hasUnsavedReviewChanges = true;
        };
    });

    container.querySelectorAll('.qp-input-marks').forEach(el => {
        el.oninput = (e) => {
            const idx = parseInt(e.target.dataset.idx, 10);
            const val = parseFloat(e.target.value);
            currentReviewQuestions[idx].max_marks = isNaN(val) ? null : val;
            currentReviewQuestions[idx].confidence = 'HIGH';
            hasUnsavedReviewChanges = true;
            updateQpReviewFooter();
        };
    });

    container.querySelectorAll('.qp-input-text').forEach(el => {
        el.oninput = (e) => {
            const idx = parseInt(e.target.dataset.idx, 10);
            currentReviewQuestions[idx].question_text = e.target.value;
            hasUnsavedReviewChanges = true;
        };
    });

    container.querySelectorAll('.qp-input-refans').forEach(el => {
        el.oninput = (e) => {
            const idx = parseInt(e.target.dataset.idx, 10);
            currentReviewQuestions[idx].reference_answer = e.target.value;
            hasUnsavedReviewChanges = true;
        };
    });
}

function renderCriteriaItemsHtml(criteria, qIdx, maxMarks) {
    if (!criteria || !criteria.length) {
        return '<p style="font-size: 0.78rem; color: var(--color-text-secondary); margin: 0;">No criteria added yet. You can add grading rubrics now or configure them later.</p>';
    }

    const totalCrit = criteria.reduce((sum, c) => sum + (parseFloat(c.marks) || 0), 0);
    const maxVal = parseFloat(maxMarks) || 0;
    let badgeClass = 'status-completed';
    if (maxVal > 0 && totalCrit > maxVal) badgeClass = 'status-high_risk';
    else if (maxVal > 0 && totalCrit < maxVal) badgeClass = 'status-low_risk';

    const items = criteria.map((c, cIdx) => `
        <div style="display: grid; grid-template-columns: 2fr 80px 1.5fr 30px; gap: 0.4rem; align-items: center; background: var(--color-surface-2); padding: 0.35rem 0.5rem; border-radius: var(--radius-sm); border: 1px solid var(--color-border); font-size: 0.8rem;">
            <input type="text" placeholder="Description" value="${escapeHtml(c.description || '')}" onchange="updateCriterion(${qIdx}, ${cIdx}, 'description', this.value)" style="padding: 2px 6px; border: 1px solid var(--color-border); border-radius: var(--radius-sm);">
            <input type="number" step="0.5" min="0.5" placeholder="Marks" value="${c.marks || ''}" onchange="updateCriterion(${qIdx}, ${cIdx}, 'marks', this.value)" style="padding: 2px 6px; border: 1px solid var(--color-border); border-radius: var(--radius-sm);">
            <input type="text" placeholder="Keywords" value="${escapeHtml(c.keywords ? c.keywords.join(', ') : '')}" onchange="updateCriterion(${qIdx}, ${cIdx}, 'keywords', this.value)" style="padding: 2px 6px; border: 1px solid var(--color-border); border-radius: var(--radius-sm);">
            <button type="button" onclick="removeCriterion(${qIdx}, ${cIdx})" style="background: none; border: none; color: #b91c1c; cursor: pointer; font-weight: bold;">✕</button>
        </div>
    `).join('');

    return `
        ${items}
        <div style="margin-top: 0.25rem; font-size: 0.78rem; display: flex; justify-content: space-between; align-items: center;">
            <span class="status-pill ${badgeClass}">Rubric Total: ${totalCrit} / ${maxVal || '—'} Marks</span>
            ${(maxVal > 0 && totalCrit > maxVal) ? '<span style="color: #b91c1c;">⚠️ Exceeds question max marks</span>' : ''}
        </div>
    `;
}

function addCriterionToQuestion(qIdx) {
    if (!currentReviewQuestions[qIdx]) return;
    if (!currentReviewQuestions[qIdx].criteria) currentReviewQuestions[qIdx].criteria = [];
    currentReviewQuestions[qIdx].criteria.push({
        id: `c${currentReviewQuestions[qIdx].criteria.length + 1}`,
        description: 'Key point / criterion explanation',
        marks: 2.5,
        keywords: [],
    });
    hasUnsavedReviewChanges = true;
    renderQuestionReviewCards();
}

function updateCriterion(qIdx, cIdx, field, value) {
    if (!currentReviewQuestions[qIdx] || !currentReviewQuestions[qIdx].criteria[cIdx]) return;
    if (field === 'marks') {
        currentReviewQuestions[qIdx].criteria[cIdx].marks = parseFloat(value) || 0;
    } else if (field === 'keywords') {
        currentReviewQuestions[qIdx].criteria[cIdx].keywords = value.split(',').map(s => s.trim()).filter(Boolean);
    } else {
        currentReviewQuestions[qIdx].criteria[cIdx][field] = value;
    }
    hasUnsavedReviewChanges = true;
    renderQuestionReviewCards();
}

function removeCriterion(qIdx, cIdx) {
    if (!currentReviewQuestions[qIdx] || !currentReviewQuestions[qIdx].criteria) return;
    currentReviewQuestions[qIdx].criteria.splice(cIdx, 1);
    hasUnsavedReviewChanges = true;
    renderQuestionReviewCards();
}

function addBlankReviewQuestion() {
    const nextNum = currentReviewQuestions.length
        ? Math.max(...currentReviewQuestions.map(q => q.question_number || 0)) + 1
        : 1;
    currentReviewQuestions.push({
        question_number: nextNum,
        section: currentReviewSections[0] || null,
        question_text: 'New examination question',
        max_marks: 10.0,
        confidence: 'HIGH',
        marks_source: 'Created manually by teacher',
        subquestions: [],
        reference_answer: '',
        warnings: [],
        criteria: [],
    });
    hasUnsavedReviewChanges = true;
    renderQuestionReview();
}

function removeReviewQuestion(idx) {
    const q = currentReviewQuestions[idx];
    confirmActionModal({
        title: `Remove Question #${q.question_number}`,
        message: `Remove Question #${q.question_number} from the extracted set?`,
        details: 'You can undo this deletion using the "Undo Delete" button before saving.',
        confirmText: 'Remove Question',
        onConfirm: () => {
            deletedQuestionsHistory.push([{ index: idx, item: q }]);
            currentReviewQuestions.splice(idx, 1);
            selectedQuestionIndices.delete(idx);
            hasUnsavedReviewChanges = true;

            const undoBtn = document.getElementById('btn-qp-undo-delete');
            if (undoBtn) undoBtn.style.display = 'inline-block';

            renderQuestionReview();
        },
    });
}

function updateQpReviewFooter() {
    const totalQsEl = document.getElementById('qp-footer-total-qs');
    const totalMarksEl = document.getElementById('qp-footer-total-marks');
    if (totalQsEl) totalQsEl.textContent = currentReviewQuestions.length;

    let sumMarks = 0;
    for (const q of currentReviewQuestions) {
        if (q.max_marks !== null && !isNaN(q.max_marks)) {
            sumMarks += parseFloat(q.max_marks);
        }
    }
    if (totalMarksEl) totalMarksEl.textContent = sumMarks.toFixed(1);
}

async function saveConfirmedQuestions(completeRubricsLater = false) {
    if (!currentReviewQuestions.length) {
        alert('Please add at least one question before saving.');
        return;
    }

    // Validation pass
    for (let i = 0; i < currentReviewQuestions.length; i++) {
        const q = currentReviewQuestions[i];
        if (!q.question_text || !q.question_text.trim()) {
            alert(`Question #${q.question_number} statement cannot be empty.`);
            return;
        }
        if (q.max_marks === null || isNaN(q.max_marks) || q.max_marks <= 0) {
            alert(`Please specify a valid maximum mark (> 0) for Question #${q.question_number}.`);
            return;
        }

        // Validate criteria total if any
        if (q.criteria && q.criteria.length) {
            const sumCrit = q.criteria.reduce((s, c) => s + (parseFloat(c.marks) || 0), 0);
            if (sumCrit > q.max_marks) {
                alert(`Criteria marks total (${sumCrit}) exceeds max marks (${q.max_marks}) for Question #${q.question_number}. Please adjust criterion marks.`);
                return;
            }
        }
    }

    // Prepare payload
    const payloadQuestions = currentReviewQuestions.map(q => {
        let rubricJson = null;
        if (q.criteria && q.criteria.length) {
            rubricJson = JSON.stringify({
                question: q.question_text,
                max_marks: q.max_marks,
                reference_answer: q.reference_answer || '',
                criteria: q.criteria,
            });
        }
        return {
            question_number: parseInt(q.question_number, 10),
            question_text: q.question_text.trim(),
            max_marks: parseFloat(q.max_marks),
            reference_answer: q.reference_answer ? q.reference_answer.trim() : null,
            rubric_json: rubricJson,
        };
    });

    showLoading('Saving confirmed questions and rubrics...');
    try {
        await apiPost(`/api/teacher/exams/${currentQpExamId}/questions/confirm`, {
            questions: payloadQuestions,
            replace_existing: true,
        });

        hasUnsavedReviewChanges = false;
        closeModal('modal-review-questions');
        alert(`✓ Successfully saved ${payloadQuestions.length} questions for examination!`);
        await loadAnswerKeyDetails(currentQpExamId);
    } catch (err) {
        alert(`Failed to save questions: ${err.message}`);
    } finally {
        hideLoading();
    }
}

