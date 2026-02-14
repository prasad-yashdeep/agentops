// ─── AgentOps Frontend — Auth + Role-Based Dashboard ────────────────
let ws = null;
let currentUser = null;  // { id, name, email, role, role_display, avatar_color, permissions, is_highest_authority }
let currentIncident = null;
let timelineSteps = [];
let notifications = [];

const AVATAR_COLORS = ['#a855f7','#22c55e','#ef4444','#3b82f6','#eab308','#ec4899','#06b6d4','#f97316'];
function avatarColor(name) { if (currentUser?.avatar_color) return currentUser.avatar_color; let h=0; for(let c of name) h=c.charCodeAt(0)+((h<<5)-h); return AVATAR_COLORS[Math.abs(h)%AVATAR_COLORS.length]; }
function timeAgo(ts) { if(!ts)return''; const s=Math.floor((Date.now()-new Date(ts))/1000); if(s<5)return'now'; if(s<60)return s+'s'; if(s<3600)return Math.floor(s/60)+'m'; return Math.floor(s/3600)+'h'; }

// ─── Auth ───────────────────────────────────────────────────────────
async function doLogin() {
    const email = document.getElementById('login-email').value.trim();
    const password = document.getElementById('login-password').value.trim();
    if (!email || !password) return;

    try {
        const res = await fetch('/api/auth/login', {
            method: 'POST', headers: {'Content-Type':'application/json'},
            body: JSON.stringify({ email, password }),
        });
        if (!res.ok) {
            const err = await res.json();
            document.getElementById('login-error').textContent = err.detail || 'Login failed';
            document.getElementById('login-error').classList.remove('hidden');
            return;
        }
        const data = await res.json();
        localStorage.setItem('agentops_token', data.token);
        currentUser = data.user;
        enterApp();
    } catch(e) {
        document.getElementById('login-error').textContent = 'Connection error';
        document.getElementById('login-error').classList.remove('hidden');
    }
}

function quickLogin(email) {
    document.getElementById('login-email').value = email;
    document.getElementById('login-password').value = '1234';
    doLogin();
}

function doLogout() {
    localStorage.removeItem('agentops_token');
    currentUser = null;
    if (ws) ws.close();
    document.getElementById('app-page').classList.add('hidden');
    document.getElementById('login-page').classList.remove('hidden');
}

async function tryAutoLogin() {
    const token = localStorage.getItem('agentops_token');
    if (!token) return;
    try {
        const res = await fetch(`/api/auth/me?token=${token}`);
        if (res.ok) {
            const user = await res.json();
            currentUser = user;
            enterApp();
        } else {
            localStorage.removeItem('agentops_token');
        }
    } catch(e) {}
}

function enterApp() {
    document.getElementById('login-page').classList.add('hidden');
    document.getElementById('app-page').classList.remove('hidden');

    // Set user profile in header
    document.getElementById('user-avatar').style.background = currentUser.avatar_color;
    document.getElementById('user-avatar').textContent = currentUser.name[0].toUpperCase();
    document.getElementById('user-name').textContent = currentUser.name;
    document.getElementById('user-role').textContent = currentUser.role_display || currentUser.role;

    // Role-based UI
    const injectBtn = document.getElementById('inject-btn');
    if (injectBtn && !currentUser.permissions?.can_inject_faults) {
        injectBtn.classList.add('opacity-50');
        injectBtn.title = 'Senior Developer+ required';
    }

    // Hide reports tab for non-team-leads
    const reportsTab = document.getElementById('tab-reports');
    if (reportsTab && !currentUser.permissions?.can_view_reports) {
        reportsTab.classList.add('opacity-30');
    }

    connectWS();
    loadInitialData();
    loadNotifications();
}

// ─── WebSocket ──────────────────────────────────────────────────────
function connectWS() {
    if (!currentUser) return;
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    ws = new WebSocket(`${proto}://${location.host}/ws/${currentUser.name}`);
    ws.onmessage = (e) => handleMsg(JSON.parse(e.data));
    ws.onclose = () => setTimeout(connectWS, 2000);
}

function handleMsg(msg) {
    const d = msg.data;
    switch(msg.type) {
        case 'health_update': updateHealth(d); break;
        case 'incident_new': onNewIncident(d); break;
        case 'incident_update': onIncidentUpdate(d); break;
        case 'activity': addActivity(d); break;
        case 'new_comment': onNewComment(d); break;
        case 'presence': updatePresence(d); break;
        case 'voice_alert': playVoice(d); break;
        case 'notification': onNotification(d); break;
        case 'clearance_report': onClearanceReport(d); break;
        case 'fault_injected':
            addActivity({ actor:'system', action:'fault_injected', detail:`💥 ${d.fault}: ${d.detail}`, created_at:new Date().toISOString() });
            break;
    }
    refreshStats();
}

// ─── Data Load ──────────────────────────────────────────────────────
async function loadInitialData() {
    try {
        const [inc, act, stats, target] = await Promise.all([
            fetch('/api/incidents').then(r=>r.json()),
            fetch('/api/activity?limit=50').then(r=>r.json()),
            fetch('/api/agent/status').then(r=>r.json()),
            fetch('/api/target-app').then(r=>r.json()),
        ]);
        const active = inc.find(i => !['resolved','rejected'].includes(i.status));
        if (active) showIncident(active);
        act.reverse().forEach(a => addActivity(a, true));
        updateStatsDisplay(stats);

        const ti = document.getElementById('target-info');
        const me = document.getElementById('modal-env');
        if (target.mode === 'blaxel') {
            ti.innerHTML = `🎯 <span class="text-purple-400">Blaxel Sandbox: ${target.sandbox}</span> (port ${target.port})`;
            if (me) me.textContent = `Blaxel sandbox "${target.sandbox}"`;
        } else {
            ti.textContent = `🎯 Target: localhost:${target.port}`;
            if (me) me.textContent = 'local environment';
        }
    } catch(e) { console.error(e); }
}

// ─── Health ─────────────────────────────────────────────────────────
function updateHealth(d) {
    const dot = document.getElementById('health-dot');
    const ring = document.getElementById('health-ring');
    const text = document.getElementById('health-text');
    if (d.healthy) {
        dot.className = 'w-2.5 h-2.5 rounded-full bg-green-500';
        ring.className = 'absolute inset-0 w-2.5 h-2.5 rounded-full bg-green-500 pulse-ring';
        text.textContent = `Healthy (${Math.round(d.response_time_ms || 0)}ms)`;
        text.className = 'text-zinc-400';
    } else {
        dot.className = 'w-2.5 h-2.5 rounded-full bg-red-500';
        ring.className = 'absolute inset-0 w-2.5 h-2.5 rounded-full bg-red-500 pulse-ring';
        text.textContent = d.error_type || d.error || 'Error';
        text.className = 'text-red-400';
    }
}

// ─── Incidents ──────────────────────────────────────────────────────
function onNewIncident(d) {
    currentIncident = d;
    timelineSteps = [];
    showIncident(d);
    addStep('🚨', 'Detected', d.title || d.description || 'Anomaly detected', 'red');
}

function onIncidentUpdate(d) {
    if (!currentIncident) { currentIncident = d; showIncident(d); return; }
    currentIncident = { ...currentIncident, ...d };

    if (d.status === 'diagnosing' && d.root_cause) {
        addStep('🔍', 'Root Cause Found', d.root_cause, 'amber');
        if (d.explanation) {
            addExplanation(d.explanation);
        }
        if (d.reasoning) {
            addStepDetail('Agent reasoning', typeof d.reasoning === 'string' ? d.reasoning : JSON.stringify(d.reasoning, null, 2));
        }
    } else if (d.status === 'diagnosing') {
        addStep('🧠', 'Diagnosing...', 'Analyzing error logs and source code', 'purple', true);
    }

    if (d.line_hint) currentIncident.line_hint = d.line_hint;
    if (d.file_at_fault) currentIncident.file_at_fault = d.file_at_fault;

    if (d.proposed_fix) {
        addStep('🔧', 'Fix Generated', d.proposed_fix, 'blue');
        if (d.fix_diff) addStepCode(d.fix_diff, d.file_at_fault);
    }

    if (d.safety) {
        const s = d.safety;
        const providerLabel = s.provider || 'White Circle AI';
        const modeLabel = s.provider_mode === 'api' ? '(API)' : '(Local Engine)';
        addStep(s.passed ? '🛡️' : '⚠️',
            `Safety Check: ${s.passed ? 'PASSED' : 'FAILED'}`,
            `Score: ${(s.score*100).toFixed(0)}% · ${providerLabel} ${modeLabel}` +
            (s.warnings?.length ? ` · ⚠️ ${s.warnings.length} warning(s)` : ''),
            s.passed ? 'green' : 'red');
        if (s.reasoning) {
            addStepDetail('White Circle AI — Safety Analysis', typeof s.reasoning === 'string' ? s.reasoning : JSON.stringify(s.reasoning, null, 2));
        }
        if (s.checks_detail?.length) {
            addStepDetail('Safety Checks Detail', s.checks_detail.join('\n'));
        }
    }

    if (d.confidence !== undefined) updateConfidence(d.confidence);

    if (d.status === 'deploying') {
        addStep('🚀', d.auto ? 'Auto-Deploying Fix' : `Deploying Fix (approved by ${d.approved_by || d.overridden_by || 'team'})`,
            d.auto ? `Confidence ${(d.confidence*100).toFixed(0)}% exceeded threshold` : 'Applying fix to production...',
            'purple', true);
    }

    if (d.status === 'resolved') {
        addStep('✅', 'Resolved!', d.auto_resolved ? 'Auto-fixed by agent' : 'Fixed with team approval', 'green');
        showResolved();
    }

    if (d.status === 'rejected') {
        addStep('❌', 'Rejected', `Rejected by ${d.rejected_by || 'team'}`, 'red');
        hideActions();
    }

    if (d.status === 'fix_proposed') showActions();
}

function showIncident(inc) {
    currentIncident = inc;
    lastSeenIncidentId = inc.id;
    document.getElementById('empty-state').classList.add('hidden');
    document.getElementById('incident-view').classList.remove('hidden');
    document.getElementById('comments-section').classList.remove('hidden');

    const sevColors = { critical:'red', high:'orange', medium:'amber', low:'green', blocker:'red' };
    const c = sevColors[inc.severity] || 'zinc';
    const bugSev = inc.bug_severity || 'medium';
    const bugSevColors = { blocker:'red', medium:'amber', low:'green' };
    const bc = bugSevColors[bugSev] || 'zinc';

    document.getElementById('inc-header').innerHTML = `
        <div class="flex items-center gap-3 mb-2 flex-wrap">
            <span class="text-xs font-bold uppercase px-2 py-1 rounded-md bg-${c}-500/10 text-${c}-400 border border-${c}-500/20">${inc.severity || 'detected'}</span>
            <span class="text-xs font-bold uppercase px-2 py-1 rounded-md bg-${bc}-500/10 text-${bc}-400 border border-${bc}-500/20">Bug: ${bugSev}</span>
            <span class="text-xs text-zinc-600 mono">#${inc.id}</span>
            <span class="text-xs text-zinc-600">${timeAgo(inc.detected_at)} ago</span>
        </div>
        <h2 class="text-xl font-bold">${inc.title || inc.description || 'Incident Detected'}</h2>
        ${inc.description ? `<p class="text-sm text-zinc-400 mt-1">${inc.description}</p>` : ''}
        ${inc.impact_analysis ? `<details class="mt-2"><summary class="text-xs text-zinc-500 cursor-pointer hover:text-zinc-300">📊 Impact Analysis ▸</summary><pre class="mt-2 text-xs text-zinc-400 bg-zinc-900 border border-zinc-800 rounded-lg p-3 whitespace-pre-wrap">${esc(inc.impact_analysis)}</pre></details>` : ''}
        <div class="flex items-center gap-4 mt-3 text-xs text-zinc-500">
            ${inc.reported_by ? `<span>👤 Reported: ${inc.reported_by}</span>` : ''}
            ${inc.assigned_to ? `<span>🔧 Assigned: ${inc.assigned_to}</span>` : ''}
            ${inc.cleared_by ? `<span>✅ Cleared: ${inc.cleared_by}</span>` : ''}
        </div>
        <div id="confidence-bar" class="hidden mt-3"></div>
    `;

    // Parse agent_reasoning for explanation, file_at_fault, line_hint
    let diagData = {};
    if (inc.agent_reasoning) {
        try { diagData = JSON.parse(inc.agent_reasoning); } catch(e) {}
    }
    if (diagData.line_hint) inc.line_hint = diagData.line_hint;
    if (diagData.file_at_fault) inc.file_at_fault = diagData.file_at_fault;

    if (inc.root_cause) {
        addStep('🚨', 'Detected', inc.title || 'Anomaly detected', 'red');
        addStep('🔍', 'Root Cause Found', inc.root_cause, 'amber');
        if (diagData.explanation) addExplanation(diagData.explanation);
    }
    if (inc.proposed_fix) {
        addStep('🔧', 'Fix Generated', inc.proposed_fix, 'blue');
        let fileGuess = inc.file_at_fault || diagData.file_at_fault;
        if (!fileGuess && inc.fix_diff) {
            if (inc.fix_diff.includes('handler.py')) fileGuess = 'handler.py';
            else if (inc.fix_diff.includes('config.json')) fileGuess = 'config.json';
        }
        if (inc.fix_diff) addStepCode(inc.fix_diff, fileGuess);
    }
    if (inc.confidence_score) updateConfidence(inc.confidence_score);
    if (inc.safety_check_result) {
        try {
            const s = JSON.parse(inc.safety_check_result);
            addStep(s.passed ? '🛡️' : '⚠️', `Safety: ${s.passed?'PASSED':'FAILED'}`, `Score: ${(s.score*100).toFixed(0)}%`, s.passed?'green':'red');
        } catch(e){}
    }
    if (inc.status === 'resolved') {
        addStep('✅', 'Resolved', inc.auto_resolved ? 'Auto-fixed' : 'Fixed by team', 'green');
        showResolved();
    } else if (['fix_proposed','awaiting_approval'].includes(inc.status)) {
        showActions();
    }
}

// ─── Timeline Steps ─────────────────────────────────────────────────
function addStep(icon, title, detail, color='zinc', loading=false) {
    const timeline = document.getElementById('timeline');
    const div = document.createElement('div');
    div.className = 'step-enter opacity-0';
    div.innerHTML = `
        <div class="flex gap-3 items-start">
            <div class="w-8 h-8 rounded-lg bg-${color}-500/10 flex items-center justify-center text-sm shrink-0 mt-0.5">${icon}</div>
            <div class="flex-1 min-w-0">
                <div class="flex items-center gap-2">
                    <span class="text-sm font-semibold">${title}</span>
                    ${loading ? '<div class="w-3 h-3 border-2 border-purple-500 border-t-transparent rounded-full animate-spin"></div>' : ''}
                </div>
                <p class="text-sm text-zinc-400 mt-0.5">${detail}</p>
            </div>
            <span class="text-xs text-zinc-700 shrink-0">${new Date().toLocaleTimeString()}</span>
        </div>`;
    timeline.appendChild(div);
    requestAnimationFrame(() => div.classList.remove('opacity-0'));
    div.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

function addStepDetail(title, content) {
    const timeline = document.getElementById('timeline');
    const div = document.createElement('div');
    div.className = 'step-enter opacity-0 ml-11';
    div.innerHTML = `
        <details class="group" open>
            <summary class="text-xs text-zinc-500 cursor-pointer hover:text-zinc-300 transition">${title} ▸</summary>
            <pre class="mt-2 text-xs text-zinc-500 mono bg-zinc-900 border border-zinc-800 rounded-lg p-3 whitespace-pre-wrap overflow-x-auto max-h-48">${content}</pre>
        </details>`;
    timeline.appendChild(div);
    requestAnimationFrame(() => div.classList.remove('opacity-0'));
}

function addExplanation(text) {
    const timeline = document.getElementById('timeline');
    const div = document.createElement('div');
    div.className = 'step-enter opacity-0 ml-11';
    div.innerHTML = `
        <div class="mt-2 p-4 rounded-xl border border-amber-500/20 bg-amber-500/5">
            <div class="flex items-center gap-2 mb-2">
                <span class="text-sm">📖</span>
                <span class="text-xs font-semibold text-amber-400 uppercase tracking-wide">What happened (in plain English)</span>
            </div>
            <p class="text-sm text-zinc-300 leading-relaxed">${text}</p>
        </div>`;
    timeline.appendChild(div);
    requestAnimationFrame(() => div.classList.remove('opacity-0'));
}

function addStepCode(code, fileAtFault) {
    const timeline = document.getElementById('timeline');
    const div = document.createElement('div');
    div.className = 'step-enter opacity-0 ml-11';

    const ghBase = 'https://github.com/prasad-yashdeep/agentops';
    const filePath = fileAtFault ? `target_app/${fileAtFault}` : null;
    const lineNum = currentIncident?.line_hint;
    let lineAnchor = '';
    let lineLabel = '';
    if (lineNum) {
        const rangeMatch = String(lineNum).match(/^(\d+)-(\d+)$/);
        if (rangeMatch) {
            lineAnchor = `#L${rangeMatch[1]}-L${rangeMatch[2]}`;
            lineLabel = `lines ${rangeMatch[1]}-${rangeMatch[2]}`;
        } else if (/^\d+$/.test(String(lineNum))) {
            lineAnchor = `#L${lineNum}`;
            lineLabel = `line ${lineNum}`;
        }
    }
    const ghLink = filePath ? `${ghBase}/blob/main/${filePath}${lineAnchor}` : ghBase;
    const ghLabel = filePath ? `${filePath}${lineLabel ? ` (${lineLabel})` : ''}` : 'Repository';

    div.innerHTML = `
        <div class="flex items-center justify-between mb-1">
            <span class="text-xs text-zinc-600 mono">${fileAtFault ? `📄 ${fileAtFault}` : ''}</span>
            <a href="${ghLink}" target="_blank" class="flex items-center gap-1 text-xs text-purple-400 hover:text-purple-300 transition bg-purple-500/5 border border-purple-500/20 px-2.5 py-1 rounded-lg">
                <svg class="w-3.5 h-3.5" viewBox="0 0 16 16" fill="currentColor"><path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"/></svg>
                ${ghLabel !== 'Repository' ? `View ${ghLabel}` : 'View on GitHub'}
            </a>
        </div>
        <pre class="text-xs mono bg-zinc-900 border border-zinc-800 rounded-lg p-3 whitespace-pre-wrap overflow-x-auto max-h-56 leading-relaxed">${highlightDiff(code)}</pre>`;
    timeline.appendChild(div);
    requestAnimationFrame(() => div.classList.remove('opacity-0'));
}

function highlightDiff(text) {
    return text.split('\n').map(line => {
        if (line.startsWith('+') && !line.startsWith('+++')) return `<span class="text-green-400">${esc(line)}</span>`;
        if (line.startsWith('-') && !line.startsWith('---')) return `<span class="text-red-400">${esc(line)}</span>`;
        if (line.startsWith('@@')) return `<span class="text-purple-400">${esc(line)}</span>`;
        return `<span class="text-zinc-500">${esc(line)}</span>`;
    }).join('\n');
}
function esc(s) { return (s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }

function updateConfidence(val) {
    const bar = document.getElementById('confidence-bar');
    if (!bar) return;
    bar.classList.remove('hidden');
    const pct = (val*100).toFixed(0);
    const color = val > 0.85 ? 'green' : val > 0.5 ? 'amber' : 'red';
    bar.innerHTML = `
        <div class="flex items-center justify-between text-xs mb-1">
            <span class="text-zinc-500">Agent Confidence</span>
            <span class="font-mono font-bold text-${color}-400">${pct}%</span>
        </div>
        <div class="h-1.5 bg-zinc-800 rounded-full overflow-hidden">
            <div class="h-full bg-${color}-500 rounded-full transition-all duration-700" style="width:${pct}%"></div>
        </div>
        <div class="flex justify-between text-[10px] text-zinc-700 mt-1">
            <span>← Escalate (50%)</span>
            <span>Auto-fix (85%) →</span>
        </div>`;
}

// ─── Actions (Role-Based) ───────────────────────────────────────────
function showActions() {
    if (!currentUser) return;
    const el = document.getElementById('action-buttons');
    el.classList.remove('hidden');

    const bugSev = currentIncident?.bug_severity || 'medium';
    const canApprove = currentUser.permissions?.[`can_approve_${bugSev}`] ??
                       currentUser.permissions?.can_approve_medium ?? true;

    const approveDisabled = !canApprove;
    const approveTitle = approveDisabled
        ? `🚫 ${bugSev.toUpperCase()} bugs require ${bugSev === 'blocker' ? 'Team Lead' : 'Senior Developer+'} approval`
        : 'Approve and deploy the fix';

    el.innerHTML = `
        <div class="flex gap-3 flex-wrap step-enter">
            <button onclick="doApprove('approve')" ${approveDisabled ? 'disabled' : ''}
                class="bg-green-500/10 text-green-400 hover:bg-green-500/20 border border-green-500/20 px-6 py-3 rounded-xl font-semibold text-sm transition flex items-center gap-2 ${approveDisabled ? 'opacity-40 cursor-not-allowed' : ''}"
                title="${approveTitle}">
                ✅ Approve & Deploy
                ${approveDisabled ? `<span class="text-[10px] bg-red-500/10 text-red-400 border border-red-500/20 px-1.5 py-0.5 rounded-full ml-1">${bugSev === 'blocker' ? 'TEAM LEAD ONLY' : 'SENIOR+'}</span>` : ''}
            </button>
            <button onclick="doApprove('reject')" class="bg-red-500/10 text-red-400 hover:bg-red-500/20 border border-red-500/20 px-6 py-3 rounded-xl font-semibold text-sm transition flex items-center gap-2">
                ❌ Reject
            </button>
            <button onclick="doOverride()" class="bg-amber-500/10 text-amber-400 hover:bg-amber-500/20 border border-amber-500/20 px-6 py-3 rounded-xl font-semibold text-sm transition flex items-center gap-2">
                ✏️ Override Fix
            </button>
            <button onclick="doRequestChanges()" class="bg-zinc-800 text-zinc-400 hover:bg-zinc-700 border border-zinc-700 px-6 py-3 rounded-xl font-semibold text-sm transition flex items-center gap-2">
                💬 Request Changes
            </button>
        </div>
        ${approveDisabled ? `<p class="text-xs text-red-400/70 mt-2">⚠️ Your role (${currentUser.role_display}) cannot approve ${bugSev.toUpperCase()} severity bugs.</p>` : ''}
    `;
}

function hideActions() { document.getElementById('action-buttons').classList.add('hidden'); }

function showResolved() {
    hideActions();
    document.querySelectorAll('#timeline .animate-spin').forEach(el => el.remove());
    setTimeout(() => {
        document.getElementById('health-dot').className = 'w-2.5 h-2.5 rounded-full bg-green-500';
        document.getElementById('health-ring').className = 'absolute inset-0 w-2.5 h-2.5 rounded-full bg-green-500 pulse-ring';
        document.getElementById('health-text').textContent = 'Healthy';
        document.getElementById('health-text').className = 'text-zinc-400';
    }, 1000);
}

async function doApprove(action) {
    if (!currentIncident || !currentUser) return;
    const comment = action === 'reject' ? (prompt('Reason?') || '') : '';
    hideActions();
    addStep('⏳', action === 'approve' ? 'Deploying...' : 'Processing...', `${currentUser.name} (${currentUser.role_display}) ${action === 'approve' ? 'approved' : 'rejected'} the fix`, 'purple', true);
    try {
        const res = await fetch(`/api/incidents/${currentIncident.id}/approve`, {
            method: 'POST', headers: {'Content-Type':'application/json'},
            body: JSON.stringify({ user_name: currentUser.name, action, comment }),
        });
        const data = await res.json();
        if (!res.ok) {
            addStep('🚫', 'Permission Denied', data.detail || 'Insufficient role', 'red');
            showActions();
        }
    } catch(e) {
        addStep('❌', 'Error', `Failed: ${e.message}`, 'red');
    }
}

function doOverride() {
    const fix = prompt('Enter your override fix:');
    if (!fix || !currentIncident) return;
    hideActions();
    fetch(`/api/incidents/${currentIncident.id}/approve`, {
        method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({ user_name: currentUser.name, action:'override', comment: fix }),
    });
}

function doRequestChanges() {
    const feedback = prompt('What changes should the agent make?');
    if (!feedback || !currentIncident) return;
    fetch(`/api/incidents/${currentIncident.id}/approve`, {
        method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({ user_name: currentUser.name, action:'request_changes', comment: feedback }),
    });
}

// ─── Comments ───────────────────────────────────────────────────────
function onNewComment(d) {
    const list = document.getElementById('comments-list');
    const roleColors = { team_lead:'purple', senior_dev:'blue', junior_dev:'green' };
    const rc = roleColors[d.user_role] || 'zinc';
    list.innerHTML += `
        <div class="flex gap-2 step-enter">
            <div class="w-5 h-5 rounded-full flex items-center justify-center text-xs font-bold shrink-0" style="background:${avatarColor(d.user_name)}">${d.user_name[0].toUpperCase()}</div>
            <div>
                <span class="text-xs font-medium">${d.user_name}</span>
                ${d.user_role ? `<span class="text-[10px] text-${rc}-400 ml-1">${d.user_role.replace('_',' ')}</span>` : ''}
                <span class="text-xs text-zinc-600 ml-1">${timeAgo(d.created_at)}</span>
                <p class="text-sm text-zinc-300">${d.content}</p>
            </div>
        </div>`;
    list.scrollTop = list.scrollHeight;
}

async function sendComment() {
    if (!currentUser || !currentIncident) return;
    const input = document.getElementById('comment-input');
    const content = input.value.trim();
    if (!content) return;
    input.value = '';
    await fetch(`/api/incidents/${currentIncident.id}/comments`, {
        method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({ user_name: currentUser.name, content }),
    });
}

// ─── Activity Feed ──────────────────────────────────────────────────
function addActivity(d, silent=false) {
    const feed = document.getElementById('activity-feed');
    if (feed.querySelector('.text-zinc-700')) feed.innerHTML = '';
    const icons = {
        incident_detected:'🚨', diagnosed:'🔍', fix_proposed:'🔧', auto_deploying:'🚀',
        escalated:'⚠️', resolved:'✅', approved:'👍', rejected:'👎', overridden:'✏️',
        changes_requested:'💬', sandbox_test:'🧪', safety_check:'🛡️', fix_refined:'🔄',
        learning_recorded:'📚', started:'▶️', stopped:'⏹️', fault_injected:'💥', commented:'💬',
        assigned:'👤',
    };
    const icon = icons[d.action] || '•';
    const isAgent = d.actor === 'agent' || d.actor === 'system';
    const el = document.createElement('div');
    el.className = `flex items-start gap-2 py-1 text-xs ${silent ? '' : 'step-enter'}`;
    el.innerHTML = `
        <span class="shrink-0">${icon}</span>
        <span class="${isAgent ? 'text-purple-400' : 'text-zinc-400'}">${d.actor}${d.actor_role ? ` (${d.actor_role.replace('_',' ')})` : ''}</span>
        <span class="text-zinc-600 flex-1 truncate">${d.detail || d.action.replace(/_/g,' ')}</span>
        <span class="text-zinc-700 shrink-0">${timeAgo(d.created_at)}</span>`;
    feed.prepend(el);
    while (feed.children.length > 50) feed.lastChild.remove();
}

// ─── Presence ───────────────────────────────────────────────────────
function updatePresence(d) {
    const c = document.getElementById('online-users');
    c.innerHTML = (d.online||[]).map(u => `
        <div class="w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold -ml-1 first:ml-0 border-2 border-zinc-900" style="background:${avatarColor(u)}" title="${u}">${u[0].toUpperCase()}</div>
    `).join('');
}

// ─── Stats ──────────────────────────────────────────────────────────
async function refreshStats() {
    try {
        const s = await fetch('/api/agent/status').then(r=>r.json());
        updateStatsDisplay(s);
    } catch(e){}
}
function updateStatsDisplay(s) {
    document.getElementById('stat-total').textContent = s.incidents_total||0;
    document.getElementById('stat-resolved').textContent = s.incidents_resolved||0;
    document.getElementById('stat-auto').textContent = s.auto_resolved||0;
    document.getElementById('stat-learning').textContent = s.learning_records||0;
}

// ─── Notifications ──────────────────────────────────────────────────
async function loadNotifications() {
    if (!currentUser) return;
    try {
        const data = await fetch(`/api/notifications?user_name=${currentUser.name}`).then(r=>r.json());
        notifications = data;
        updateNotifBadge();
    } catch(e) {}
}

function onNotification(d) {
    notifications.unshift(d);
    updateNotifBadge();
    renderNotifications();
}

function onClearanceReport(d) {
    // Show a toast-like notification
    addActivity({
        actor: 'system', action: 'clearance_report',
        detail: `📋 Bug #${d.incident_id} cleared by ${d.cleared_by} (${d.cleared_by_role}) — report sent to ${d.authority}`,
        created_at: new Date().toISOString(),
    });
    loadNotifications();
}

function updateNotifBadge() {
    const badge = document.getElementById('notif-count');
    const unread = notifications.filter(n => !n.read).length;
    if (unread > 0) {
        badge.textContent = unread;
        badge.classList.remove('hidden');
    } else {
        badge.classList.add('hidden');
    }
}

function toggleNotifications() {
    const panel = document.getElementById('notif-panel');
    panel.classList.toggle('hidden');
    if (!panel.classList.contains('hidden')) renderNotifications();
}

function renderNotifications() {
    const list = document.getElementById('notif-list');
    if (notifications.length === 0) {
        list.innerHTML = '<div class="text-xs text-zinc-600 text-center py-4">No notifications</div>';
        return;
    }
    list.innerHTML = notifications.map(n => `
        <div class="p-3 rounded-xl border ${n.read ? 'border-zinc-800 bg-zinc-900/50' : 'border-purple-500/20 bg-purple-500/5'} cursor-pointer transition hover:bg-zinc-800"
             onclick="markNotifRead('${n.id}')">
            <div class="flex items-center gap-2 mb-1">
                <span class="text-xs">${n.type === 'clearance_report' ? '📋' : n.type === 'critical' ? '🚨' : '🔔'}</span>
                <span class="text-xs font-semibold ${n.read ? 'text-zinc-400' : 'text-white'}">${n.title}</span>
                <span class="text-[10px] text-zinc-600 ml-auto">${timeAgo(n.created_at)}</span>
            </div>
            <pre class="text-[11px] text-zinc-500 whitespace-pre-wrap max-h-40 overflow-y-auto">${esc(n.message?.slice(0, 500) || '')}</pre>
        </div>
    `).join('');
}

async function markNotifRead(id) {
    await fetch(`/api/notifications/${id}/read`, { method: 'POST' });
    const n = notifications.find(n => n.id === id);
    if (n) n.read = true;
    updateNotifBadge();
    renderNotifications();
}

// ─── Tabs ───────────────────────────────────────────────────────────
function showTab(name) {
    ['incidents','analytics','team','reports'].forEach(t => {
        document.getElementById(`page-${t}`).classList.toggle('hidden', t !== name);
        const btn = document.getElementById(`tab-${t}`);
        if (btn) {
            btn.classList.toggle('border-purple-500', t === name);
            btn.classList.toggle('text-white', t === name);
            btn.classList.toggle('border-transparent', t !== name);
            btn.classList.toggle('text-zinc-500', t !== name);
        }
    });
    if (name === 'analytics') loadAnalytics();
    if (name === 'team') loadTeam();
    if (name === 'reports') loadReports();
}

async function loadAnalytics() {
    try {
        const data = await fetch('/api/analytics/dashboard').then(r=>r.json());
        const s = data.summary;

        document.getElementById('analytics-summary').innerHTML = `
            <div class="bg-zinc-900 border border-zinc-800 rounded-xl p-4 text-center">
                <div class="text-3xl font-bold mono">${s.total}</div>
                <div class="text-xs text-zinc-500 mt-1">Total Bugs</div>
            </div>
            <div class="bg-zinc-900 border border-zinc-800 rounded-xl p-4 text-center">
                <div class="text-3xl font-bold text-green-400 mono">${s.resolution_rate}%</div>
                <div class="text-xs text-zinc-500 mt-1">Resolution Rate</div>
            </div>
            <div class="bg-zinc-900 border border-zinc-800 rounded-xl p-4 text-center">
                <div class="text-3xl font-bold text-purple-400 mono">${s.auto_fix_rate}%</div>
                <div class="text-xs text-zinc-500 mt-1">Auto-Fix Rate</div>
            </div>
            <div class="bg-zinc-900 border border-zinc-800 rounded-xl p-4 text-center">
                <div class="text-3xl font-bold text-amber-400 mono">${data.avg_resolution_seconds > 0 ? Math.round(data.avg_resolution_seconds) + 's' : '—'}</div>
                <div class="text-xs text-zinc-500 mt-1">Avg Resolution</div>
            </div>
        `;

        // Severity chart
        const sevColors = { blocker:'red', medium:'amber', low:'green' };
        const maxSev = Math.max(...Object.values(data.severity_breakdown || {blocker:0}), 1);
        document.getElementById('severity-chart').innerHTML = Object.entries(data.severity_breakdown || {}).map(([sev, count]) => {
            const c = sevColors[sev] || 'zinc';
            return `
                <div class="flex items-center gap-3">
                    <span class="text-xs w-16 text-${c}-400 font-semibold uppercase">${sev}</span>
                    <div class="flex-1 h-6 bg-zinc-800 rounded-full overflow-hidden">
                        <div class="h-full bg-${c}-500/30 rounded-full transition-all" style="width:${(count/maxSev*100).toFixed(0)}%"></div>
                    </div>
                    <span class="text-sm font-bold mono w-8 text-right">${count}</span>
                </div>`;
        }).join('') || '<div class="text-xs text-zinc-600">No data yet</div>';

        // Team chart
        document.getElementById('team-chart').innerHTML = Object.entries(data.team_performance || {}).map(([name, stats]) => `
            <div class="flex items-center gap-3 bg-zinc-900 rounded-lg px-4 py-3">
                <div class="w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold" style="background:${avatarColor(name)}">${name[0]}</div>
                <div class="flex-1">
                    <div class="text-sm font-medium">${name}</div>
                    <div class="text-xs text-zinc-500">${stats.role?.replace('_',' ') || ''}</div>
                </div>
                <div class="text-right">
                    <span class="text-green-400 text-sm font-bold">${stats.approvals}</span>
                    <span class="text-zinc-600 text-xs">approved</span>
                    <span class="text-red-400 text-sm font-bold ml-2">${stats.rejections}</span>
                    <span class="text-zinc-600 text-xs">rejected</span>
                </div>
            </div>
        `).join('') || '<div class="text-xs text-zinc-600">No team activity yet</div>';

        // Recent clearances
        document.getElementById('recent-clearances').innerHTML = data.recent_clearances?.map(c => `
            <div class="flex items-center gap-3 bg-zinc-900 rounded-lg px-4 py-3">
                <span class="text-xs mono text-zinc-600">#${c.id}</span>
                <div class="flex-1">
                    <div class="text-sm">${c.title}</div>
                    <div class="text-xs text-zinc-500">${c.resolution_method || 'Auto-fix'}</div>
                </div>
                <div class="text-right">
                    <div class="text-xs text-green-400">✅ ${c.cleared_by}</div>
                    <div class="text-[10px] text-zinc-600">${timeAgo(c.cleared_at)}</div>
                </div>
            </div>
        `).join('') || '<div class="text-xs text-zinc-600">No clearances yet</div>';

    } catch(e) { console.error(e); }
}

async function loadTeam() {
    try {
        const team = await fetch('/api/team').then(r=>r.json());
        document.getElementById('team-list').innerHTML = team.map(u => {
            const roleIcons = { team_lead:'👑', senior_dev:'⚡', junior_dev:'🌱' };
            return `
                <div class="border border-zinc-800 rounded-2xl p-5 flex items-center gap-4 ${u.is_highest_authority ? 'border-purple-500/30 bg-purple-500/5' : ''}">
                    <div class="w-14 h-14 rounded-full flex items-center justify-center text-xl font-bold" style="background:${u.avatar_color}">${u.name[0]}</div>
                    <div class="flex-1">
                        <div class="flex items-center gap-2">
                            <span class="font-semibold text-lg">${u.name}</span>
                            ${u.is_highest_authority ? '<span class="text-xs bg-purple-500/10 text-purple-400 border border-purple-500/20 px-2 py-0.5 rounded-full">⭐ Highest Authority</span>' : ''}
                        </div>
                        <div class="text-sm text-zinc-400">${roleIcons[u.role] || ''} ${u.role_display || u.role.replace('_',' ')}</div>
                        <div class="text-xs text-zinc-600 mono mt-1">${u.email}</div>
                    </div>
                    <div class="text-right text-xs text-zinc-500">
                        <div>Joined ${timeAgo(u.created_at)} ago</div>
                    </div>
                </div>`;
        }).join('');
    } catch(e) { console.error(e); }
}

async function loadReports() {
    try {
        const data = await fetch(`/api/notifications?user_name=${currentUser.name}&limit=50`).then(r=>r.json());
        const reports = data.filter(n => n.type === 'clearance_report');
        document.getElementById('reports-list').innerHTML = reports.length > 0
            ? reports.map(r => `
                <div class="border border-zinc-800 rounded-2xl p-5">
                    <div class="flex items-center gap-2 mb-3">
                        <span>📋</span>
                        <span class="font-semibold">${r.title}</span>
                        <span class="text-xs text-zinc-600 ml-auto">${timeAgo(r.created_at)}</span>
                    </div>
                    <pre class="text-xs mono text-zinc-400 bg-zinc-900 border border-zinc-800 rounded-lg p-4 whitespace-pre-wrap max-h-96 overflow-y-auto">${esc(r.message)}</pre>
                </div>
            `).join('')
            : '<div class="text-center py-12 text-zinc-600"><span class="text-4xl block mb-3">📋</span>No clearance reports yet. Reports are generated automatically when bugs are resolved.</div>';
    } catch(e) { console.error(e); }
}

// ─── Inject ─────────────────────────────────────────────────────────
function showInjectModal() {
    if (!currentUser?.permissions?.can_inject_faults) {
        alert('🚫 Only Senior Developers and Team Leads can inject faults.');
        return;
    }
    const m = document.getElementById('inject-modal');
    m.classList.remove('hidden');
    m.classList.add('flex');
}
function hideInjectModal() { const m=document.getElementById('inject-modal'); m.classList.add('hidden'); m.classList.remove('flex'); }

async function injectFault(type) {
    hideInjectModal();
    currentIncident = null;
    timelineSteps = [];
    document.getElementById('timeline').innerHTML = '';
    document.getElementById('action-buttons').classList.add('hidden');
    document.getElementById('comments-list').innerHTML = '';
    document.getElementById('empty-state').classList.add('hidden');
    document.getElementById('incident-view').classList.remove('hidden');
    document.getElementById('inc-header').innerHTML = `
        <div class="flex items-center gap-2">
            <div class="w-3 h-3 border-2 border-purple-500 border-t-transparent rounded-full animate-spin"></div>
            <span class="text-sm text-zinc-400">Injecting fault and waiting for agent detection...</span>
        </div>`;

    try {
        const res = await fetch('/api/inject', {
            method:'POST', headers:{'Content-Type':'application/json'},
            body: JSON.stringify({fault_type:type, reported_by: currentUser?.name }),
        });
        const d = await res.json();
        addActivity({ actor: currentUser?.name || 'you', action:'fault_injected', detail:`💥 ${type}: ${d.detail||''}`, created_at:new Date().toISOString() });
    } catch(e) { console.error(e); }
}

// ─── Voice ──────────────────────────────────────────────────────────
function playVoice(d) {
    if (d.audio_b64) {
        const p = document.getElementById('voice-player');
        p.src = `data:audio/mpeg;base64,${d.audio_b64}`;
        p.play().catch(()=>{});
    }
    addActivity({ actor:'agent', action:'voice_alert', detail:`🔊 ${d.script||'Voice alert'}`, created_at:new Date().toISOString() });
}

async function fetchVoiceSummary() {
    try {
        const d = await fetch('/api/voice/summary').then(r=>r.json());
        if (d.audio_b64) {
            document.getElementById('voice-player').src = `data:audio/mpeg;base64,${d.audio_b64}`;
            document.getElementById('voice-player').play();
        }
        addActivity({ actor:'agent', action:'voice_summary', detail:`🔊 ${d.script}`, created_at:new Date().toISOString() });
    } catch(e) { console.error(e); }
}

// ─── Auto-refresh ───────────────────────────────────────────────────
setInterval(refreshStats, 10000);
setInterval(() => loadNotifications(), 15000);

let lastSeenIncidentId = null;
setInterval(async () => {
    if (!currentUser) return;
    try {
        const incs = await fetch('/api/incidents').then(r=>r.json());
        const active = incs.find(i => !['resolved','rejected'].includes(i.status));
        if (active && active.id !== lastSeenIncidentId && !currentIncident) {
            lastSeenIncidentId = active.id;
            showIncident(active);
        }
    } catch(e) {}
}, 5000);

// ─── Init ───────────────────────────────────────────────────────────
tryAutoLogin();
