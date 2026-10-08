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
        items.push({ page: 'notifications', icon: '🔔', label: 'Notifications' });
        items.push({ page: 'evaluate', icon: '🧪', label: 'Interactive Demo' });
        items.push({ page: 'model', icon: '🤖', label: 'Model Info' });
    } else if (role === 'TEACHER') {
        items.push({ page: 'teacher-dashboard', icon: '📊', label: 'Teacher Portal' });
        items.push({ page: 'teacher-reviews', icon: '⚠️', label: 'Risk Reviews' });
        items.push({ page: 'results', icon: '📈', label: 'Class Results' });
        items.push({ page: 'notifications', icon: '🔔', label: 'Notifications' });
        items.push({ page: 'evaluate', icon: '🧪', label: 'Interactive Demo' });
        items.push({ page: 'model', icon: '🤖', label: 'Model Info' });
    } else if (role === 'SCANNER') {
        items.push({ page: 'scanner-dashboard', icon: '📠', label: 'Scanner Portal' });
        items.push({ page: 'scripts-monitoring', icon: '📑', label: 'My Uploads' });
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
    else if (pageId === 'teacher-reviews') loadTeacherReviews();
    else if (pageId === 'scanner-dashboard') loadScannerDashboard();
    else if (pageId === 'results') loadResultsPage();
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
                        ${s.status === 'REUPLOAD_REQUIRED' ? `
                            <button class="btn btn-secondary" style="padding: 2px 8px; font-size: 0.75rem; background: #fee2e2; color: #b91c1c;" onclick="openRescanModal(${s.id})">🔄 Rescan</button>
                        ` : ''}
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

    // Add Question Form
    document.getElementById('form-add-question')?.addEventListener('submit', async (e) => {
        e.preventDefault();
        const examId = document.getElementById('q-exam-id').value;
        try {
            await apiPost(`/api/exams/${examId}/questions`, {
                question_number: parseInt(document.getElementById('q-number').value),
                question_text: document.getElementById('q-text').value,
                max_marks: parseFloat(document.getElementById('q-marks').value),
                reference_answer: document.getElementById('q-ref').value || null,
                rubric_json: document.getElementById('q-rubric').value || null,
            });
            closeModal('modal-add-question');
            viewExamQuestions(examId, 'Exam');
        } catch (err) {
            alert(err.message);
        }
    });

    // Scanner Upload Area
    const scnUploadArea = document.getElementById('scanner-upload-area');
    const scnFileInput = document.getElementById('scanner-file-input');
    if (scnUploadArea && scnFileInput) {
        scnUploadArea.addEventListener('click', () => scnFileInput.click());
        scnFileInput.addEventListener('change', () => {
            if (scnFileInput.files.length) {
                document.getElementById('scanner-selected-filename').textContent = scnFileInput.files[0].name;
                document.getElementById('scanner-file-preview').style.display = 'block';
            }
        });
    }

    // Scanner Upload Form Submit
    document.getElementById('form-scanner-upload')?.addEventListener('submit', async (e) => {
        e.preventDefault();
        const examId = document.getElementById('upload-exam-select').value;
        const studentUsn = document.getElementById('upload-student-usn').value.trim();
        const file = scnFileInput.files[0];

        if (!file) {
            alert('Please select a file to upload.');
            return;
        }

        showLoading('Uploading script and running blur validation...');
        const formData = new FormData();
        formData.append('exam_id', examId);
        if (studentUsn) formData.append('student_usn', studentUsn);
        formData.append('file', file);

        try {
            const res = await apiPost('/api/scripts/upload', formData, false);
            if (res.status === 'REUPLOAD_REQUIRED') {
                alert(`⚠️ Scan Quality Issue Detected: Script was flagged as ${res.scan_quality}. A scan issue has been logged and rescan is required.`);
            } else {
                alert(`✓ Script #${res.id} uploaded successfully with ${res.scan_quality} quality.`);
            }
            loadScannerDashboard();
        } catch (err) {
            alert(`Upload error: ${err.message}`);
        } finally {
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
});
