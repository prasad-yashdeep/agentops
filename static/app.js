// ─── AgentOps Frontend ──────────────────────────────────────────────
let ws = null;
let currentUser = null;
let selectedIncidentId = null;
let incidents = {};
let activities = [];

const SEVERITY_COLORS = {
    critical: { bg: 'bg-crit/20', text: 'text-crit', border: 'severity-critical', dot: 'bg-crit' },
    high: { bg: 'bg-danger/20', text: 'text-danger', border: 'severity-high', dot: 'bg-danger' },
    medium: { bg: 'bg-warn/20', text: 'text-warn', border: 'severity-medium', dot: 'bg-warn' },
    low: { bg: 'bg-ok/20', text: 'text-ok', border: 'severity-low', dot: 'bg-ok' },
};

const STATUS_LABELS = {
    detected: '🔍 Detected',
    diagnosing: '🧠 Diagnosing',
    fix_proposed: '🔧 Fix Ready',
    awaiting_approval: '⏳ Needs Approval',
    approved: '✅ Approved',
    deploying: '🚀 Deploying',
    resolved: '✅ Resolved',
    rejected: '❌ Rejected',
};

const AVATAR_COLORS = [
    '#6c5ce7', '#00b894', '#e17055', '#0984e3', '#fdcb6e',
    '#e84393', '#00cec9', '#d63031', '#74b9ff', '#55efc4',
];

function getAvatarColor(name) {
    let hash = 0;
    for (let c of name) hash = c.charCodeAt(0) + ((hash << 5) - hash);
    return AVATAR_COLORS[Math.abs(hash) % AVATAR_COLORS.length];
}

// ─── WebSocket ──────────────────────────────────────────────────────

function connectWS() {
    if (!currentUser) return;
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    ws = new WebSocket(`${proto}://${location.host}/ws/${currentUser}`);

    ws.onmessage = (e) => {
        const msg = JSON.parse(e.data);
        handleWSMessage(msg);
    };

    ws.onclose = () => {
        setTimeout(connectWS, 2000);
    };
}

function handleWSMessage(msg) {
    switch (msg.type) {
        case 'incident_new':
            addIncident(msg.data);
            break;
        case 'incident_update':
            updateIncident(msg.data);
            break;
        case 'activity':
            addActivity(msg.data);
            break;
        case 'new_comment':
            addCommentToFeed(msg.data);
            break;
        case 'presence':
            updatePresence(msg.data);
            break;
        case 'agent_status':
            updateAgentStatus(msg.data);
            break;
        case 'voice_alert':
            playVoiceAlert(msg.data);
            break;
        case 'health_update':
            updateAppHealth(msg.data);
            break;
        case 'fault_injected':
            addActivity({
                actor: 'system', action: 'fault_injected',
                detail: `💥 ${msg.data.fault} fault injected — ${msg.data.detail || ''}`,
                created_at: new Date().toISOString(),
            });
            break;
        case 'user_typing':
            showTypingIndicator(msg.data);
            break;
    }
    refreshStats();
}

// ─── Session ────────────────────────────────────────────────────────

function joinSession() {
    const input = document.getElementById('username-input');
    const name = input.value.trim();
    if (!name) return;
    currentUser = name;
    input.style.display = 'none';
    document.querySelector('#user-section button').style.display = 'none';
    document.getElementById('user-section').innerHTML = `
        <div class="flex items-center gap-2">
            <div class="w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold text-white"
                 style="background: ${getAvatarColor(name)}">${name[0].toUpperCase()}</div>
            <span class="text-sm">${name}</span>
        </div>
    `;
    document.getElementById('comment-section').classList.remove('hidden');
    connectWS();
    loadInitialData();
}

// ─── Data Loading ───────────────────────────────────────────────────

async function loadInitialData() {
    try {
        const [incidentsRes, activityRes, statsRes] = await Promise.all([
            fetch('/api/incidents'),
            fetch('/api/activity?limit=100'),
            fetch('/api/agent/status'),
        ]);
        const incidentsList = await incidentsRes.json();
        const activityList = await activityRes.json();
        const stats = await statsRes.json();

        incidentsList.forEach(inc => {
            incidents[inc.id] = inc;
        });
        activities = activityList;

        renderIncidentList();
        renderActivityFeed();
        updateStatsDisplay(stats);
    } catch (e) {
        console.error('Failed to load initial data:', e);
    }
}

async function refreshStats() {
    try {
        const res = await fetch('/api/agent/status');
        const stats = await res.json();
        updateStatsDisplay(stats);
    } catch (e) {}
}

function updateStatsDisplay(stats) {
    document.getElementById('stat-total').textContent = stats.incidents_total || 0;
    document.getElementById('stat-resolved').textContent = stats.incidents_resolved || 0;
    document.getElementById('stat-auto').textContent = stats.auto_resolved || 0;
    document.getElementById('stat-learning').textContent = stats.learning_records || 0;
    const avg = stats.confidence_avg;
    document.getElementById('stat-confidence').textContent = avg > 0 ? `${(avg * 100).toFixed(0)}%` : '—';
    const safety = stats.safety_stats || {};
    document.getElementById('stat-safety').textContent = `${safety.checks_passed || 0}/${safety.checks_run || 0}`;
}

// ─── Incident List ──────────────────────────────────────────────────

function addIncident(data) {
    incidents[data.id] = { ...incidents[data.id], ...data };
    renderIncidentList();
    // Flash effect
    setTimeout(() => {
        const el = document.getElementById(`inc-${data.id}`);
        if (el) el.classList.add('slide-in');
    }, 10);
}

function updateIncident(data) {
    if (incidents[data.id]) {
        incidents[data.id] = { ...incidents[data.id], ...data };
    } else {
        incidents[data.id] = data;
    }
    renderIncidentList();
    if (selectedIncidentId === data.id) {
        renderIncidentDetail(data.id);
    }
}

function renderIncidentList() {
    const list = document.getElementById('incident-list');
    const sorted = Object.values(incidents).sort((a, b) => {
        const aTime = new Date(a.detected_at || 0).getTime();
        const bTime = new Date(b.detected_at || 0).getTime();
        return bTime - aTime;
    });

    if (sorted.length === 0) {
        list.innerHTML = '<div class="text-center text-gray-600 text-sm py-8">No incidents yet</div>';
        return;
    }

    list.innerHTML = sorted.map(inc => {
        const sev = SEVERITY_COLORS[inc.severity] || SEVERITY_COLORS.medium;
        const status = STATUS_LABELS[inc.status] || inc.status;
        const selected = selectedIncidentId === inc.id ? 'bg-surface-300' : 'hover:bg-surface-200';
        const timeAgo = getTimeAgo(inc.detected_at);

        return `
            <div id="inc-${inc.id}" onclick="selectIncident('${inc.id}')"
                 class="${sev.border} ${selected} rounded-lg p-3 cursor-pointer transition">
                <div class="flex items-start justify-between">
                    <div class="flex-1 min-w-0">
                        <div class="text-xs ${sev.text} font-semibold uppercase">${inc.severity}</div>
                        <div class="text-sm font-medium text-white truncate mt-0.5">${inc.service_name || inc.service || 'unknown'}</div>
                        <div class="text-xs text-gray-500 mt-1">${status}</div>
                    </div>
                    <div class="text-xs text-gray-600 ml-2">${timeAgo}</div>
                </div>
                ${inc.confidence_score ? `
                    <div class="mt-2 flex items-center gap-2">
                        <div class="flex-1 h-1 bg-surface-300 rounded-full overflow-hidden">
                            <div class="h-full rounded-full ${inc.confidence_score > 0.8 ? 'bg-ok' : inc.confidence_score > 0.5 ? 'bg-warn' : 'bg-danger'}"
                                 style="width: ${inc.confidence_score * 100}%"></div>
                        </div>
                        <span class="text-xs text-gray-500">${(inc.confidence_score * 100).toFixed(0)}%</span>
                    </div>
                ` : ''}
            </div>
        `;
    }).join('');
}

// ─── Incident Detail ────────────────────────────────────────────────

async function selectIncident(id) {
    selectedIncidentId = id;
    renderIncidentList();

    // Tell server we're viewing this incident
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'viewing', incident_id: id }));
    }

    // Load full incident data
    try {
        const [incRes, commentsRes, approvalsRes] = await Promise.all([
            fetch(`/api/incidents/${id}`),
            fetch(`/api/incidents/${id}/comments`),
            fetch(`/api/incidents/${id}/approvals`),
        ]);
        const inc = await incRes.json();
        const comments = await commentsRes.json();
        const approvals = await approvalsRes.json();

        incidents[id] = inc;
        renderIncidentDetail(id, comments, approvals);

        // Load incident-specific activity
        const actRes = await fetch(`/api/activity?incident_id=${id}`);
        const incActivities = await actRes.json();
        renderActivityFeed(incActivities);
    } catch (e) {
        console.error('Failed to load incident:', e);
    }
}

function renderIncidentDetail(id, comments = [], approvals = []) {
    const inc = incidents[id];
    if (!inc) return;

    const sev = SEVERITY_COLORS[inc.severity] || SEVERITY_COLORS.medium;
    const status = STATUS_LABELS[inc.status] || inc.status;
    const detail = document.getElementById('incident-detail');

    let safetyHtml = '';
    if (inc.safety_check_result) {
        try {
            const safety = typeof inc.safety_check_result === 'string' ? JSON.parse(inc.safety_check_result) : inc.safety_check_result;
            const checks = safety.checks || {};
            safetyHtml = `
                <div class="bg-surface-100 rounded-lg p-4 border border-surface-300">
                    <h3 class="text-sm font-semibold text-gray-400 mb-3 flex items-center gap-2">
                        🛡️ Safety Check 
                        <span class="text-xs px-2 py-0.5 rounded ${safety.passed ? 'bg-ok/20 text-ok' : 'bg-danger/20 text-danger'}">
                            ${safety.passed ? 'PASSED' : 'FAILED'}
                        </span>
                        <span class="text-xs text-gray-600">via ${safety.provider || 'unknown'}</span>
                    </h3>
                    <div class="grid grid-cols-2 gap-2">
                        ${Object.entries(checks).map(([k, v]) => `
                            <div class="flex items-center gap-2 text-xs">
                                <span>${v ? '✅' : '❌'}</span>
                                <span class="text-gray-400">${k.replace(/_/g, ' ')}</span>
                            </div>
                        `).join('')}
                    </div>
                    ${safety.warnings?.length ? `
                        <div class="mt-2 space-y-1">
                            ${safety.warnings.map(w => `<div class="text-xs text-warn">⚠️ ${w}</div>`).join('')}
                        </div>
                    ` : ''}
                </div>
            `;
        } catch (e) {}
    }

    detail.innerHTML = `
        <div class="max-w-3xl mx-auto space-y-4">
            <!-- Header -->
            <div class="flex items-start justify-between">
                <div>
                    <div class="flex items-center gap-2 mb-1">
                        <span class="text-xs font-bold uppercase px-2 py-0.5 rounded ${sev.bg} ${sev.text}">${inc.severity}</span>
                        <span class="text-xs text-gray-500 mono">#${inc.id}</span>
                    </div>
                    <h2 class="text-xl font-bold text-white">${inc.title || `${inc.service_name} incident`}</h2>
                    <p class="text-sm text-gray-400 mt-1">${inc.description || ''}</p>
                </div>
                <div class="text-right">
                    <div class="text-sm font-medium">${status}</div>
                    <div class="text-xs text-gray-500 mt-1">${formatTime(inc.detected_at)}</div>
                </div>
            </div>

            <!-- Confidence Bar -->
            ${inc.confidence_score ? `
                <div class="bg-surface-100 rounded-lg p-4 border border-surface-300">
                    <div class="flex items-center justify-between mb-2">
                        <span class="text-sm text-gray-400">Agent Confidence</span>
                        <span class="text-lg font-bold ${inc.confidence_score > 0.8 ? 'text-ok' : inc.confidence_score > 0.5 ? 'text-warn' : 'text-danger'}">
                            ${(inc.confidence_score * 100).toFixed(0)}%
                        </span>
                    </div>
                    <div class="h-2 bg-surface-300 rounded-full overflow-hidden">
                        <div class="h-full rounded-full transition-all duration-500 ${inc.confidence_score > 0.8 ? 'bg-ok' : inc.confidence_score > 0.5 ? 'bg-warn' : 'bg-danger'}"
                             style="width: ${inc.confidence_score * 100}%"></div>
                    </div>
                    <div class="flex justify-between mt-1 text-xs text-gray-600">
                        <span>Escalate (${(0.5 * 100).toFixed(0)}%)</span>
                        <span>Auto-fix (${(0.85 * 100).toFixed(0)}%)</span>
                    </div>
                </div>
            ` : ''}

            <!-- Root Cause -->
            ${inc.root_cause ? `
                <div class="bg-surface-100 rounded-lg p-4 border border-surface-300">
                    <h3 class="text-sm font-semibold text-gray-400 mb-2">🔍 Root Cause</h3>
                    <p class="text-sm text-white">${inc.root_cause}</p>
                    ${inc.agent_reasoning ? `
                        <details class="mt-2">
                            <summary class="text-xs text-gray-500 cursor-pointer hover:text-gray-400">Agent Reasoning</summary>
                            <pre class="text-xs text-gray-400 mt-2 whitespace-pre-wrap mono bg-surface-200 p-3 rounded">${
                                typeof inc.agent_reasoning === 'string' ? inc.agent_reasoning : JSON.stringify(inc.agent_reasoning, null, 2)
                            }</pre>
                        </details>
                    ` : ''}
                </div>
            ` : ''}

            <!-- Proposed Fix -->
            ${inc.proposed_fix ? `
                <div class="bg-surface-100 rounded-lg p-4 border border-surface-300">
                    <h3 class="text-sm font-semibold text-gray-400 mb-2">🔧 Proposed Fix</h3>
                    <p class="text-sm text-white">${inc.proposed_fix}</p>
                    ${inc.fix_diff ? `
                        <pre class="text-xs mt-3 p-3 bg-surface-200 rounded mono text-green-400 whitespace-pre-wrap overflow-x-auto">${inc.fix_diff}</pre>
                    ` : ''}
                </div>
            ` : ''}

            <!-- Safety Check -->
            ${safetyHtml}

            <!-- Error Logs -->
            ${inc.error_logs ? `
                <details class="bg-surface-100 rounded-lg border border-surface-300">
                    <summary class="p-4 text-sm font-semibold text-gray-400 cursor-pointer hover:text-gray-300">📋 Error Logs</summary>
                    <pre class="px-4 pb-4 text-xs text-red-400 mono whitespace-pre-wrap overflow-x-auto max-h-64">${
                        typeof inc.error_logs === 'string' ? inc.error_logs : JSON.stringify(inc.error_logs, null, 2)
                    }</pre>
                </details>
            ` : ''}

            <!-- Action Buttons -->
            ${['fix_proposed', 'awaiting_approval'].includes(inc.status) && currentUser ? `
                <div class="bg-surface-100 rounded-lg p-4 border border-surface-300">
                    <h3 class="text-sm font-semibold text-gray-400 mb-3">👥 Your Decision</h3>
                    <div class="flex gap-2 flex-wrap">
                        <button onclick="approveIncident('${inc.id}', 'approve')"
                                class="bg-ok/20 text-ok hover:bg-ok/30 px-4 py-2 rounded font-medium text-sm transition">
                            ✅ Approve & Deploy
                        </button>
                        <button onclick="approveIncident('${inc.id}', 'reject')"
                                class="bg-danger/20 text-danger hover:bg-danger/30 px-4 py-2 rounded font-medium text-sm transition">
                            ❌ Reject
                        </button>
                        <button onclick="showOverrideModal('${inc.id}')"
                                class="bg-warn/20 text-warn hover:bg-warn/30 px-4 py-2 rounded font-medium text-sm transition">
                            ✏️ Override Fix
                        </button>
                        <button onclick="requestChanges('${inc.id}')"
                                class="bg-accent/20 text-accent-light hover:bg-accent/30 px-4 py-2 rounded font-medium text-sm transition">
                            💬 Request Changes
                        </button>
                    </div>
                </div>
            ` : ''}

            <!-- Approvals History -->
            ${approvals.length ? `
                <div class="bg-surface-100 rounded-lg p-4 border border-surface-300">
                    <h3 class="text-sm font-semibold text-gray-400 mb-3">📝 Approvals</h3>
                    <div class="space-y-2">
                        ${approvals.map(a => `
                            <div class="flex items-center gap-2 text-sm">
                                <div class="w-5 h-5 rounded-full flex items-center justify-center text-xs font-bold text-white"
                                     style="background: ${getAvatarColor(a.user_name)}">${a.user_name[0].toUpperCase()}</div>
                                <span class="font-medium">${a.user_name}</span>
                                <span class="text-gray-500">${a.action}</span>
                                ${a.comment ? `<span class="text-gray-400">— "${a.comment}"</span>` : ''}
                                <span class="text-xs text-gray-600 ml-auto">${getTimeAgo(a.created_at)}</span>
                            </div>
                        `).join('')}
                    </div>
                </div>
            ` : ''}

            <!-- Comments -->
            ${comments.length ? `
                <div class="bg-surface-100 rounded-lg p-4 border border-surface-300">
                    <h3 class="text-sm font-semibold text-gray-400 mb-3">💬 Discussion</h3>
                    <div class="space-y-3">
                        ${comments.map(c => `
                            <div class="flex gap-2">
                                <div class="w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold text-white shrink-0"
                                     style="background: ${getAvatarColor(c.user_name)}">${c.user_name[0].toUpperCase()}</div>
                                <div>
                                    <div class="flex items-center gap-2">
                                        <span class="text-sm font-medium">${c.user_name}</span>
                                        <span class="text-xs text-gray-600">${getTimeAgo(c.created_at)}</span>
                                    </div>
                                    <p class="text-sm text-gray-300">${c.content}</p>
                                </div>
                            </div>
                        `).join('')}
                    </div>
                </div>
            ` : ''}
        </div>
    `;
}

// ─── Actions ────────────────────────────────────────────────────────

async function approveIncident(id, action) {
    if (!currentUser) return alert('Please join first');
    const comment = action === 'reject' ? prompt('Reason for rejection (optional):') || '' : '';

    try {
        await fetch(`/api/incidents/${id}/approve`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ user_name: currentUser, action, comment }),
        });
    } catch (e) {
        console.error('Action failed:', e);
    }
}

function showOverrideModal(id) {
    const fix = prompt('Enter your override fix:');
    if (fix) {
        fetch(`/api/incidents/${id}/approve`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ user_name: currentUser, action: 'override', comment: fix }),
        });
    }
}

function requestChanges(id) {
    const feedback = prompt('What changes do you want the agent to make?');
    if (feedback) {
        fetch(`/api/incidents/${id}/approve`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ user_name: currentUser, action: 'request_changes', comment: feedback }),
        });
    }
}

async function sendComment() {
    if (!currentUser || !selectedIncidentId) return;
    const input = document.getElementById('comment-input');
    const content = input.value.trim();
    if (!content) return;

    input.value = '';
    try {
        await fetch(`/api/incidents/${selectedIncidentId}/comments`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ user_name: currentUser, content }),
        });
    } catch (e) {
        console.error('Comment failed:', e);
    }
}

// ─── Activity Feed ──────────────────────────────────────────────────

function renderActivityFeed(items = null) {
    const feed = document.getElementById('activity-feed');
    const list = items || activities;

    if (!list.length) {
        feed.innerHTML = '<div class="text-center text-gray-600 text-sm py-4">No activity yet</div>';
        return;
    }

    feed.innerHTML = list.slice(0, 50).map(a => {
        const isAgent = a.actor === 'agent' || a.actor === 'system';
        const color = isAgent ? '#6c5ce7' : getAvatarColor(a.actor);
        const icon = getActivityIcon(a.action);

        return `
            <div class="flex gap-2 p-2 rounded hover:bg-surface-200 transition slide-in">
                <div class="w-5 h-5 rounded-full flex items-center justify-center text-xs shrink-0"
                     style="background: ${color}20; color: ${color}">
                    ${isAgent ? '🤖' : a.actor[0].toUpperCase()}
                </div>
                <div class="flex-1 min-w-0">
                    <div class="text-xs">
                        <span class="font-medium text-gray-300">${a.actor}</span>
                        <span class="text-gray-500 ml-1">${icon} ${a.action.replace(/_/g, ' ')}</span>
                    </div>
                    <div class="text-xs text-gray-600 truncate">${a.detail || ''}</div>
                </div>
                <div class="text-xs text-gray-700 shrink-0">${getTimeAgo(a.created_at)}</div>
            </div>
        `;
    }).join('');

    feed.scrollTop = 0;
}

function addActivity(data) {
    activities.unshift(data);
    if (!selectedIncidentId || data.incident_id === selectedIncidentId) {
        renderActivityFeed();
    }
}

function addCommentToFeed(data) {
    addActivity({
        actor: data.user_name,
        action: 'commented',
        detail: data.content,
        created_at: data.created_at,
        incident_id: data.incident_id,
    });
    // Refresh detail if viewing this incident
    if (selectedIncidentId === data.incident_id) {
        selectIncident(data.incident_id);
    }
}

function getActivityIcon(action) {
    const icons = {
        incident_detected: '🚨', diagnosed: '🔍', fix_proposed: '🔧',
        auto_deploying: '🚀', escalated: '⚠️', resolved: '✅',
        approved: '👍', rejected: '👎', overridden: '✏️',
        changes_requested: '💬', sandbox_test: '🧪', safety_check: '🛡️',
        fix_refined: '🔄', learning_recorded: '📚', started: '▶️',
        stopped: '⏹️', deploy_failed: '💥', fault_injected: '💥',
        commented: '💬', error: '❌',
    };
    return icons[action] || '•';
}

// ─── Presence ───────────────────────────────────────────────────────

function updatePresence(data) {
    const container = document.getElementById('online-users');
    const users = data.online || [];
    container.innerHTML = users.map(u => `
        <div class="w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold text-white border-2 border-surface-100 -ml-1 first:ml-0"
             style="background: ${getAvatarColor(u)}" title="${u}">${u[0].toUpperCase()}</div>
    `).join('');

    // Show viewers on current incident
    const viewers = document.getElementById('viewers');
    if (selectedIncidentId && data.viewing) {
        const viewingThis = Object.entries(data.viewing)
            .filter(([_, incId]) => incId === selectedIncidentId)
            .map(([user]) => user);
        viewers.innerHTML = viewingThis.length ? `👁️ ${viewingThis.join(', ')}` : '';
    }
}

function updateAgentStatus(data) {
    const dot = document.getElementById('agent-dot');
    const text = document.getElementById('agent-status-text');
    if (data.running) {
        dot.className = 'w-2 h-2 rounded-full bg-ok pulse-dot';
        text.textContent = 'Agent Active';
    } else {
        dot.className = 'w-2 h-2 rounded-full bg-gray-500';
        text.textContent = 'Agent Stopped';
    }
}

function showTypingIndicator(data) {
    // Could add typing bubble, keeping it simple for now
}

function updateAppHealth(data) {
    const dot = document.getElementById('app-dot');
    const text = document.getElementById('app-status-text');
    if (data.healthy) {
        dot.className = 'w-2 h-2 rounded-full bg-ok pulse-dot';
        text.textContent = `App Healthy${data.response_time_ms ? ` (${Math.round(data.response_time_ms)}ms)` : ''}`;
    } else {
        dot.className = 'w-2 h-2 rounded-full bg-crit pulse-dot';
        text.textContent = `App Down — ${data.error_type || data.error || 'Error'}`;
    }
}

// ─── Fault Injection ────────────────────────────────────────────────

function showInjectModal() {
    document.getElementById('inject-modal').classList.remove('hidden');
    document.getElementById('inject-modal').classList.add('flex');
}

function hideInjectModal() {
    document.getElementById('inject-modal').classList.add('hidden');
    document.getElementById('inject-modal').classList.remove('flex');
}

async function injectFault(faultType) {
    hideInjectModal();
    try {
        const res = await fetch('/api/inject', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ fault_type: faultType }),
        });
        const data = await res.json();
        addActivity({
            actor: 'you', action: 'fault_injected',
            detail: `💥 Injected "${faultType}" — ${data.detail || ''}`,
            created_at: new Date().toISOString(),
        });
    } catch (e) {
        console.error('Inject failed:', e);
    }
}

// ─── Voice ──────────────────────────────────────────────────────────

function playVoiceAlert(data) {
    if (data.audio_b64) {
        const player = document.getElementById('voice-player');
        player.src = `data:audio/mpeg;base64,${data.audio_b64}`;
        player.play().catch(() => {});
    }
    // Show the script as a notification
    addActivity({
        actor: 'agent',
        action: '🔊 voice_alert',
        detail: data.script,
        created_at: new Date().toISOString(),
        incident_id: data.incident_id,
    });
}

async function fetchVoiceSummary() {
    try {
        const res = await fetch('/api/voice/summary');
        const data = await res.json();
        if (data.audio_b64) {
            const player = document.getElementById('voice-player');
            player.src = `data:audio/mpeg;base64,${data.audio_b64}`;
            player.play();
        }
        addActivity({
            actor: 'agent',
            action: '🔊 voice_summary',
            detail: data.script,
            created_at: new Date().toISOString(),
        });
    } catch (e) {
        console.error('Voice summary failed:', e);
    }
}

// ─── Utilities ──────────────────────────────────────────────────────

function getTimeAgo(timestamp) {
    if (!timestamp) return '';
    const now = new Date();
    const then = new Date(timestamp);
    const diff = Math.floor((now - then) / 1000);
    if (diff < 5) return 'now';
    if (diff < 60) return `${diff}s`;
    if (diff < 3600) return `${Math.floor(diff / 60)}m`;
    if (diff < 86400) return `${Math.floor(diff / 3600)}h`;
    return `${Math.floor(diff / 86400)}d`;
}

function formatTime(timestamp) {
    if (!timestamp) return '';
    return new Date(timestamp).toLocaleTimeString();
}

// Auto-refresh stats every 10s
setInterval(refreshStats, 10000);
