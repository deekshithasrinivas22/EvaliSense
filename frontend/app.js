/**
 * EvaliSense — Frontend Application Logic
 *
 * Handles the evaluation workflow:
 * Upload → Preprocess → HTR → Evaluate → Risk Predict → Examiner Review
 */

const API_BASE = window.location.origin;
let currentSessionId = null;

// ──────────────────────────────────────────────────────────────────────
// Navigation
// ──────────────────────────────────────────────────────────────────────

document.querySelectorAll('.nav-link').forEach(link => {
    link.addEventListener('click', (e) => {
        e.preventDefault();
        const page = link.dataset.page;
        showPage(page);
    });
});

function showPage(pageId) {
    document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
    document.querySelectorAll('.nav-link').forEach(l => l.classList.remove('active'));

    const page = document.getElementById(`page-${pageId}`);
    const nav = document.querySelector(`[data-page="${pageId}"]`);
    if (page) page.classList.add('active');
    if (nav) nav.classList.add('active');

    if (pageId === 'dashboard') refreshDashboard();
    if (pageId === 'model') refreshModelInfo();
    if (pageId === 'review') refreshReviewQueue();
}

// ──────────────────────────────────────────────────────────────────────
// Dashboard
// ──────────────────────────────────────────────────────────────────────

async function refreshDashboard() {
    try {
        const health = await apiGet('/api/health');
        document.querySelector('#stat-api-status .stat-value').textContent = '✓ Online';
    } catch {
        document.querySelector('#stat-api-status .stat-value').textContent = '✗ Offline';
    }

    try {
        const sessions = await apiGet('/api/sessions');
        document.querySelector('#stat-sessions .stat-value').textContent = sessions.count || 0;
    } catch { /* ignore */ }

    try {
        const modelInfo = await apiGet('/api/model-info');
        const val = modelInfo.status === 'loaded' ? modelInfo.model_name : 'Not loaded';
        document.querySelector('#stat-model-status .stat-value').textContent = val;
    } catch { /* ignore */ }
}

// ──────────────────────────────────────────────────────────────────────
// File Upload
// ──────────────────────────────────────────────────────────────────────

const uploadArea = document.getElementById('upload-area');
const fileInput = document.getElementById('file-input');

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

async function handleFileUpload(file) {
    showLoading('Uploading image...');

    const formData = new FormData();
    formData.append('file', file);

    try {
        const result = await apiPost('/api/upload', formData, false);
        currentSessionId = result.session_id;

        // Show preview
        const reader = new FileReader();
        reader.onload = (e) => {
            document.getElementById('preview-image').src = e.target.result;
            document.getElementById('preview-filename').textContent = file.name;
            document.getElementById('upload-preview').style.display = 'block';
        };
        reader.readAsDataURL(file);

        // Show next steps
        document.getElementById('preprocess-section').style.display = 'block';
        document.getElementById('htr-section').style.display = 'block';

        hideLoading();
    } catch (err) {
        hideLoading();
        alert('Upload failed: ' + err.message);
    }
}

// ──────────────────────────────────────────────────────────────────────
// Preprocessing
// ──────────────────────────────────────────────────────────────────────

document.getElementById('btn-preprocess').addEventListener('click', async () => {
    if (!currentSessionId) return;
    showLoading('Preprocessing image...');

    try {
        const result = await apiPost(`/api/preprocess/${currentSessionId}`);
        const box = document.getElementById('preprocess-result');
        box.style.display = 'block';
        box.innerHTML = `
            <h3>✓ Preprocessing Complete</h3>
            <p>Input shape: ${result.details?.input_shape?.join(' × ') || 'N/A'}</p>
            <p>Output shape: ${result.details?.output_shape?.join(' × ') || 'N/A'}</p>
        `;
        hideLoading();
    } catch (err) {
        hideLoading();
        alert('Preprocessing failed: ' + err.message);
    }
});

// ──────────────────────────────────────────────────────────────────────
// HTR
// ──────────────────────────────────────────────────────────────────────

document.getElementById('btn-recognize').addEventListener('click', async () => {
    if (!currentSessionId) return;
    showLoading('Running Handwritten Text Recognition...\nThis may take a moment on CPU.');

    try {
        const result = await apiPost(`/api/recognize/${currentSessionId}`);
        const box = document.getElementById('htr-result');
        box.style.display = 'block';

        let linesHtml = result.lines.map(l => {
            const conf = l.confidence !== null ? ` (conf: ${l.confidence.toFixed(3)})` : '';
            return `<div>Line ${l.line_number}: "${l.text}"${conf}</div>`;
        }).join('');

        const avgConf = result.average_confidence !== null
            ? result.average_confidence.toFixed(3) : 'N/A';

        box.innerHTML = `
            <h3>✓ HTR Complete — ${result.lines.length} lines detected</h3>
            <div style="margin: 0.75rem 0;">
                <strong>Average Confidence:</strong> ${avgConf}
                ${renderConfidenceBar(result.average_confidence)}
            </div>
            <div style="margin: 0.75rem 0;">
                <strong>Recognised Text:</strong>
                <pre>${escapeHtml(result.text)}</pre>
            </div>
            <details>
                <summary style="cursor:pointer; font-size:0.85rem; color: var(--color-text-secondary);">Line details</summary>
                <div style="margin-top: 0.5rem; font-size: 0.85rem;">${linesHtml}</div>
            </details>
        `;

        document.getElementById('evaluate-section').style.display = 'block';
        hideLoading();
    } catch (err) {
        hideLoading();
        alert('HTR failed: ' + err.message);
    }
});

// ──────────────────────────────────────────────────────────────────────
// Evaluation
// ──────────────────────────────────────────────────────────────────────

document.getElementById('btn-load-sample-rubric').addEventListener('click', async () => {
    try {
        const resp = await fetch('/static/sample_rubric.json');
        if (!resp.ok) {
            // Fall back to the data/samples path
            const rubric = await apiGet('/api/health'); // just test connectivity
            // Embed a default sample
            document.getElementById('rubric-textarea').value = JSON.stringify(SAMPLE_RUBRIC, null, 2);
            return;
        }
        const rubric = await resp.json();
        document.getElementById('rubric-textarea').value = JSON.stringify(rubric, null, 2);
    } catch {
        document.getElementById('rubric-textarea').value = JSON.stringify(SAMPLE_RUBRIC, null, 2);
    }
});

document.getElementById('btn-evaluate').addEventListener('click', async () => {
    if (!currentSessionId) return;
    const rubricText = document.getElementById('rubric-textarea').value.trim();
    if (!rubricText) {
        alert('Please enter or load a rubric JSON.');
        return;
    }

    showLoading('Evaluating answer against rubric...');

    try {
        const formData = new FormData();
        formData.append('rubric_json', rubricText);

        const result = await apiPost(`/api/evaluate/${currentSessionId}`, formData, false);
        const evalResult = result.result;
        const box = document.getElementById('eval-result');
        box.style.display = 'block';

        let criteriaHtml = (evalResult.criterion_scores || []).map(cs => `
            <div class="criterion-row">
                <div class="criterion-status ${cs.awarded_marks > 0 ? 'pass' : 'fail'}">
                    ${cs.awarded_marks > 0 ? '✓' : '✗'}
                </div>
                <div class="criterion-info">
                    <div class="criterion-desc">[${cs.criterion_id}] ${cs.criterion_description}</div>
                    <div class="criterion-evidence">${cs.evidence}</div>
                </div>
                <div class="criterion-marks">${cs.awarded_marks.toFixed(1)} / ${cs.max_marks.toFixed(1)}</div>
            </div>
        `).join('');

        box.innerHTML = `
            <h3>✓ Evaluation Complete</h3>
            <div class="mark-display">
                ${evalResult.total_score.toFixed(1)} <span class="max">/ ${evalResult.max_score.toFixed(1)}</span>
            </div>
            <div style="margin-bottom: 0.75rem;">
                <strong>Overall Similarity:</strong> ${evalResult.overall_similarity.toFixed(3)} |
                <strong>Confidence:</strong> ${evalResult.confidence.toFixed(3)}
                ${renderConfidenceBar(evalResult.confidence)}
            </div>
            <h3 style="margin-top: 1rem;">Criterion Scores</h3>
            ${criteriaHtml}
        `;

        document.getElementById('risk-section').style.display = 'block';
        hideLoading();
    } catch (err) {
        hideLoading();
        alert('Evaluation failed: ' + err.message);
    }
});

// ──────────────────────────────────────────────────────────────────────
// Risk Prediction
// ──────────────────────────────────────────────────────────────────────

document.getElementById('btn-predict-risk').addEventListener('click', async () => {
    if (!currentSessionId) return;
    showLoading('Predicting grading error risk...');

    try {
        const result = await apiPost(`/api/predict-risk/${currentSessionId}`);
        const pred = result.prediction;
        const box = document.getElementById('risk-result');
        box.style.display = 'block';

        const badgeClass = pred.risk_label === 'HIGH' ? 'high' : 'low';
        let factorsHtml = (pred.contributing_factors || []).map(f =>
            `<li>${escapeHtml(f)}</li>`
        ).join('');

        box.innerHTML = `
            <h3>Grading Error Risk Prediction</h3>
            <div style="display: flex; align-items: center; gap: 1rem; margin: 0.75rem 0;">
                <span class="risk-badge ${badgeClass}">${pred.risk_label} RISK</span>
                <span style="font-size: 1.1rem; font-weight: 600;">
                    ${(pred.risk_probability * 100).toFixed(1)}%
                </span>
            </div>
            ${result.note ? `<p style="color: var(--color-warning); font-size: 0.85rem; margin-bottom: 0.5rem;">⚠️ ${result.note}</p>` : ''}
            <h3 style="margin-top: 1rem;">Contributing Factors</h3>
            <ul class="factor-list">${factorsHtml}</ul>
        `;

        // Show examiner review
        setupExaminerReview(result);
        document.getElementById('review-section-inline').style.display = 'block';
        hideLoading();
    } catch (err) {
        hideLoading();
        alert('Risk prediction failed: ' + err.message);
    }
});

// ──────────────────────────────────────────────────────────────────────
// Examiner Review
// ──────────────────────────────────────────────────────────────────────

function setupExaminerReview(riskResult) {
    // Get session data
    apiGet(`/api/session/${currentSessionId}`).then(session => {
        const evalResult = session.eval_result || {};
        const aiMark = evalResult.total_score || 0;
        const maxMark = evalResult.max_score || 0;
        const riskLabel = (session.risk_prediction || {}).risk_label || 'UNKNOWN';

        document.getElementById('review-summary').innerHTML = `
            <p><strong>AI Preliminary Mark:</strong> ${aiMark.toFixed(1)} / ${maxMark.toFixed(1)}</p>
            <p><strong>Risk Level:</strong> <span class="risk-badge ${riskLabel === 'HIGH' ? 'high' : 'low'}">${riskLabel}</span></p>
            <p style="margin-top: 0.5rem; font-size: 0.85rem; color: var(--color-text-secondary);">
                The examiner is the final authority. Review the AI evaluation and enter your final mark below.
            </p>
        `;

        document.getElementById('examiner-mark-input').max = maxMark;
        document.getElementById('examiner-mark-input').value = aiMark;
        document.getElementById('max-mark-display').textContent = ` / ${maxMark}`;

        // Approve button pre-fills the AI mark
        document.getElementById('btn-approve').onclick = () => {
            document.getElementById('examiner-mark-input').value = aiMark;
            submitReview();
        };
    });
}

document.getElementById('btn-submit-review').addEventListener('click', submitReview);

async function submitReview() {
    if (!currentSessionId) return;
    const mark = parseFloat(document.getElementById('examiner-mark-input').value);
    const notes = document.getElementById('examiner-notes-input').value;

    if (isNaN(mark) || mark < 0) {
        alert('Please enter a valid mark.');
        return;
    }

    showLoading('Submitting examiner review...');

    try {
        const formData = new FormData();
        formData.append('examiner_mark', mark);
        formData.append('examiner_notes', notes);

        const result = await apiPost(`/api/submit-review/${currentSessionId}`, formData, false);
        const box = document.getElementById('review-result');
        box.style.display = 'block';

        const review = result.review;
        box.innerHTML = `
            <h3>✓ Review Submitted</h3>
            <p><strong>AI Mark:</strong> ${review.ai_mark.toFixed(1)}</p>
            <p><strong>Examiner Mark:</strong> ${review.examiner_mark.toFixed(1)}</p>
            <p><strong>Disagreement:</strong> ${review.disagreement.toFixed(1)} marks</p>
            <p><strong>Action:</strong> ${review.action === 'approved' ? '✓ Approved' : '✎ Modified'}</p>
            <p style="margin-top: 0.5rem; color: var(--color-success); font-weight: 600;">
                This evaluation has been recorded as ground-truth data for future model improvement.
            </p>
        `;

        hideLoading();
    } catch (err) {
        hideLoading();
        alert('Review submission failed: ' + err.message);
    }
}

// ──────────────────────────────────────────────────────────────────────
// Model Info
// ──────────────────────────────────────────────────────────────────────

async function refreshModelInfo() {
    try {
        const info = await apiGet('/api/model-info');
        const container = document.getElementById('model-info-content');

        if (info.status !== 'loaded') {
            container.innerHTML = `
                <div class="empty-state">
                    <p>No trained risk model is currently loaded.</p>
                    <p style="margin-top: 0.5rem; font-size: 0.85rem;">
                        Train a model with:<br>
                        <code>python generate_synthetic_dataset.py</code><br>
                        <code>python train_risk_model.py --dataset data/samples/synthetic_dataset.jsonl --compare</code>
                    </p>
                </div>
            `;
            return;
        }

        const metrics = info.metrics || {};
        let importanceHtml = '';
        if (metrics.feature_importances) {
            const sorted = Object.entries(metrics.feature_importances)
                .sort((a, b) => b[1] - a[1]);
            importanceHtml = `
                <h3 style="margin-top: 1.25rem;">Feature Importance</h3>
                <p style="font-size: 0.8rem; color: var(--color-text-secondary); margin-bottom: 0.5rem;">
                    Model-level feature importance — does not imply causation.
                </p>
                ${sorted.map(([name, val]) => `
                    <div style="display: flex; align-items: center; gap: 8px; margin: 4px 0;">
                        <span style="width: 220px; font-size: 0.82rem; font-weight: 500;">${name}</span>
                        <div style="flex:1; height:12px; background: var(--color-border-light); border-radius:6px; overflow:hidden;">
                            <div style="width:${(val / sorted[0][1] * 100).toFixed(0)}%; height:100%; background: var(--color-primary-500); border-radius:6px;"></div>
                        </div>
                        <span style="font-size: 0.8rem; color: var(--color-text-secondary); width: 50px; text-align:right;">${val.toFixed(4)}</span>
                    </div>
                `).join('')}
            `;
        }

        container.innerHTML = `
            <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 1rem; margin-bottom: 1.25rem;">
                <div class="stat-card"><div class="stat-value">${metrics.accuracy?.toFixed(3) || 'N/A'}</div><div class="stat-label">Accuracy</div></div>
                <div class="stat-card"><div class="stat-value">${metrics.precision?.toFixed(3) || 'N/A'}</div><div class="stat-label">Precision</div></div>
                <div class="stat-card"><div class="stat-value">${metrics.recall?.toFixed(3) || 'N/A'}</div><div class="stat-label">Recall</div></div>
                <div class="stat-card"><div class="stat-value">${metrics.f1_score?.toFixed(3) || 'N/A'}</div><div class="stat-label">F1 Score</div></div>
                <div class="stat-card"><div class="stat-value">${metrics.roc_auc?.toFixed(3) || 'N/A'}</div><div class="stat-label">ROC-AUC</div></div>
            </div>
            <p><strong>Model:</strong> ${info.model_name}</p>
            <p><strong>Features:</strong> ${info.feature_names?.length || 0} features</p>
            ${metrics.confusion_matrix ? `
                <h3 style="margin-top: 1rem;">Confusion Matrix</h3>
                <pre>${JSON.stringify(metrics.confusion_matrix, null, 2)}</pre>
            ` : ''}
            ${importanceHtml}
        `;
    } catch (err) {
        document.getElementById('model-info-content').innerHTML =
            `<p class="empty-state">Could not load model info: ${err.message}</p>`;
    }
}

// ──────────────────────────────────────────────────────────────────────
// Review Queue
// ──────────────────────────────────────────────────────────────────────

async function refreshReviewQueue() {
    try {
        const data = await apiGet('/api/sessions');
        const container = document.getElementById('review-queue');

        if (!data.sessions || data.sessions.length === 0) {
            container.innerHTML = '<p class="empty-state">No sessions available.</p>';
            return;
        }

        container.innerHTML = data.sessions.map(s => `
            <div class="card" style="margin-bottom: 0.75rem; padding: 1rem;">
                <div style="display: flex; justify-content: space-between; align-items: center;">
                    <div>
                        <strong>${s.filename || 'Unknown'}</strong>
                        <span style="font-size: 0.82rem; color: var(--color-text-secondary); margin-left: 0.5rem;">
                            ${s.session_id}
                        </span>
                    </div>
                    <span class="risk-badge ${s.status === 'reviewed' ? 'low' : 'high'}">
                        ${s.status}
                    </span>
                </div>
            </div>
        `).join('');
    } catch {
        document.getElementById('review-queue').innerHTML =
            '<p class="empty-state">Could not load sessions.</p>';
    }
}

// ──────────────────────────────────────────────────────────────────────
// Helpers
// ──────────────────────────────────────────────────────────────────────

async function apiGet(url) {
    const resp = await fetch(`${API_BASE}${url}`);
    if (!resp.ok) {
        const err = await resp.json().catch(() => ({ detail: resp.statusText }));
        throw new Error(err.detail || resp.statusText);
    }
    return resp.json();
}

async function apiPost(url, body = null, isJson = true) {
    const opts = { method: 'POST' };
    if (body) {
        if (isJson) {
            opts.headers = { 'Content-Type': 'application/json' };
            opts.body = JSON.stringify(body);
        } else {
            opts.body = body;
        }
    }
    const resp = await fetch(`${API_BASE}${url}`, opts);
    if (!resp.ok) {
        const err = await resp.json().catch(() => ({ detail: resp.statusText }));
        throw new Error(err.detail || resp.statusText);
    }
    return resp.json();
}

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

function renderConfidenceBar(value) {
    if (value === null || value === undefined) return '';
    const pct = Math.round(value * 100);
    let color = 'var(--color-success)';
    if (value < 0.4) color = 'var(--color-danger)';
    else if (value < 0.65) color = 'var(--color-warning)';

    return `
        <div class="confidence-bar">
            <div class="confidence-bar-fill" style="width: ${pct}%; background: ${color};"></div>
        </div>
    `;
}

// Default sample rubric (fallback when fetch fails)
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
// Init
// ──────────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
    refreshDashboard();
});
