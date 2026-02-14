// ─── AgentOps Frontend — Clean Demo UI ──────────────────────────────
let ws = null;
let currentUser = null;
let currentIncident = null;  // Single focused incident
let timelineSteps = [];

const AVATAR_COLORS = ['#a855f7','#22c55e','#ef4444','#3b82f6','#eab308','#ec4899','#06b6d4','#f97316'];
function avatarColor(name) { let h=0; for(let c of name) h=c.charCodeAt(0)+((h<<5)-h); return AVATAR_COLORS[Math.abs(h)%AVATAR_COLORS.length]; }
function timeAgo(ts) { if(!ts)return''; const s=Math.floor((Date.now()-new Date(ts))/1000); if(s<5)return'now'; if(s<60)return s+'s'; if(s<3600)return Math.floor(s/60)+'m'; return Math.floor(s/3600)+'h'; }

// ─── WebSocket ──────────────────────────────────────────────────────
function connectWS() {
    if (!currentUser) return;
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    ws = new WebSocket(`${proto}://${location.host}/ws/${currentUser}`);
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
        case 'fault_injected':
            addActivity({ actor:'system', action:'fault_injected', detail:`💥 ${d.fault}: ${d.detail}`, created_at:new Date().toISOString() });
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
    document.getElementById('join-section').innerHTML = `
        <div class="flex items-center gap-2 text-sm">
            <div class="w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold" style="background:${avatarColor(name)}">${name[0].toUpperCase()}</div>
            <span class="text-zinc-400">${name}</span>
        </div>`;
    connectWS();
    loadInitialData();
}

async function loadInitialData() {
    try {
        const [inc, act, stats, target] = await Promise.all([
            fetch('/api/incidents').then(r=>r.json()),
            fetch('/api/activity?limit=50').then(r=>r.json()),
            fetch('/api/agent/status').then(r=>r.json()),
            fetch('/api/target-app').then(r=>r.json()),
        ]);
        // Show the most recent unresolved incident
        const active = inc.find(i => !['resolved','rejected'].includes(i.status));
        if (active) showIncident(active);
        act.reverse().forEach(a => addActivity(a, true));
        updateStatsDisplay(stats);

        // Show environment info
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

// ─── Incident ───────────────────────────────────────────────────────
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
        if (d.reasoning) {
            addStepDetail('Agent reasoning', typeof d.reasoning === 'string' ? d.reasoning : JSON.stringify(d.reasoning, null, 2));
        }
    } else if (d.status === 'diagnosing') {
        addStep('🧠', 'Diagnosing...', 'Analyzing error logs and source code', 'purple', true);
    }

    if (d.proposed_fix) {
        addStep('🔧', 'Fix Generated', d.proposed_fix, 'blue');
        if (d.fix_diff) {
            addStepCode(d.fix_diff, d.file_at_fault);
        }
    }

    if (d.file_at_fault) {
        currentIncident.file_at_fault = d.file_at_fault;
    }

    if (d.safety) {
        const s = d.safety;
        const passed = s.passed;
        addStep(passed ? '🛡️' : '⚠️', `Safety Check: ${passed ? 'PASSED' : 'FAILED'}`,
            `Score: ${(s.score*100).toFixed(0)}% · Provider: ${s.provider || 'builtin'}` +
            (s.warnings?.length ? ` · ⚠️ ${s.warnings.length} warning(s)` : ''),
            passed ? 'green' : 'red');
    }

    if (d.confidence !== undefined) {
        const conf = d.confidence;
        const pct = (conf * 100).toFixed(0);
        updateConfidence(conf);
    }

    if (d.status === 'deploying') {
        addStep('🚀', d.auto ? 'Auto-Deploying Fix' : `Deploying Fix (approved by ${d.approved_by || d.overridden_by || 'team'})`,
            d.auto ? `Confidence ${(d.confidence*100).toFixed(0)}% exceeded threshold — deploying automatically` : 'Applying fix to production...',
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

    if (d.status === 'fix_proposed') {
        showActions();
    }
}

function showIncident(inc) {
    currentIncident = inc;
    lastSeenIncidentId = inc.id;
    document.getElementById('empty-state').classList.add('hidden');
    document.getElementById('incident-view').classList.remove('hidden');
    document.getElementById('comments-section').classList.remove('hidden');

    const sevColors = { critical:'red', high:'orange', medium:'amber', low:'green' };
    const c = sevColors[inc.severity] || 'zinc';

    document.getElementById('inc-header').innerHTML = `
        <div class="flex items-center gap-3 mb-2">
            <span class="text-xs font-bold uppercase px-2 py-1 rounded-md bg-${c}-500/10 text-${c}-400 border border-${c}-500/20">${inc.severity || 'detected'}</span>
            <span class="text-xs text-zinc-600 mono">#${inc.id}</span>
            <span class="text-xs text-zinc-600">${timeAgo(inc.detected_at)} ago</span>
        </div>
        <h2 class="text-xl font-bold">${inc.title || inc.description || 'Incident Detected'}</h2>
        ${inc.description ? `<p class="text-sm text-zinc-400 mt-1">${inc.description}</p>` : ''}
        <div id="confidence-bar" class="hidden mt-3"></div>
    `;

    // If incident has existing data, rebuild timeline
    if (inc.root_cause) {
        addStep('🚨', 'Detected', inc.title || 'Anomaly detected', 'red');
        addStep('🔍', 'Root Cause Found', inc.root_cause, 'amber');
    }
    if (inc.proposed_fix) {
        addStep('🔧', 'Fix Generated', inc.proposed_fix, 'blue');
        // Infer file from fix diff or root cause
        let fileGuess = inc.file_at_fault;
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
    const stepId = `step-${Date.now()}`;
    const div = document.createElement('div');
    div.id = stepId;
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
        </div>
    `;
    timeline.appendChild(div);
    // Trigger animation
    requestAnimationFrame(() => div.classList.remove('opacity-0'));
    div.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

function addStepDetail(title, content) {
    const timeline = document.getElementById('timeline');
    const div = document.createElement('div');
    div.className = 'step-enter opacity-0 ml-11';
    div.innerHTML = `
        <details class="group">
            <summary class="text-xs text-zinc-500 cursor-pointer hover:text-zinc-300 transition">${title} ▸</summary>
            <pre class="mt-2 text-xs text-zinc-500 mono bg-zinc-900 border border-zinc-800 rounded-lg p-3 whitespace-pre-wrap overflow-x-auto max-h-48">${content}</pre>
        </details>
    `;
    timeline.appendChild(div);
    requestAnimationFrame(() => div.classList.remove('opacity-0'));
}

function addStepCode(code, fileAtFault) {
    const timeline = document.getElementById('timeline');
    const div = document.createElement('div');
    div.className = 'step-enter opacity-0 ml-11';

    const ghBase = 'https://github.com/prasad-yashdeep/agentops';
    const filePath = fileAtFault ? `target_app/${fileAtFault}` : null;
    const ghLink = filePath ? `${ghBase}/blob/main/${filePath}` : ghBase;
    const ghLabel = filePath || 'Repository';

    div.innerHTML = `
        <div class="flex items-center justify-between mb-1">
            <span class="text-xs text-zinc-600 mono">${fileAtFault ? `📄 ${fileAtFault}` : ''}</span>
            <a href="${ghLink}" target="_blank" class="flex items-center gap-1 text-xs text-purple-400 hover:text-purple-300 transition bg-purple-500/5 border border-purple-500/20 px-2.5 py-1 rounded-lg">
                <svg class="w-3.5 h-3.5" viewBox="0 0 16 16" fill="currentColor"><path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"/></svg>
                View on GitHub
            </a>
        </div>
        <pre class="text-xs mono bg-zinc-900 border border-zinc-800 rounded-lg p-3 whitespace-pre-wrap overflow-x-auto max-h-56 leading-relaxed">${highlightDiff(code)}</pre>
    `;
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
function esc(s) { return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }

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
        </div>
    `;
}

// ─── Actions ────────────────────────────────────────────────────────
function showActions() {
    if (!currentUser) return;
    const el = document.getElementById('action-buttons');
    el.classList.remove('hidden');
    el.innerHTML = `
        <div class="flex gap-3 flex-wrap step-enter">
            <button onclick="doApprove('approve')" class="bg-green-500/10 text-green-400 hover:bg-green-500/20 border border-green-500/20 px-6 py-3 rounded-xl font-semibold text-sm transition flex items-center gap-2">
                ✅ Approve & Deploy
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
    `;
}

function hideActions() { document.getElementById('action-buttons').classList.add('hidden'); }

function showResolved() {
    hideActions();
    // Remove ALL spinners from the timeline
    document.querySelectorAll('#timeline .animate-spin').forEach(el => el.remove());
    // Switch health back visually
    setTimeout(() => {
        document.getElementById('health-dot').className = 'w-2.5 h-2.5 rounded-full bg-green-500';
        document.getElementById('health-ring').className = 'absolute inset-0 w-2.5 h-2.5 rounded-full bg-green-500 pulse-ring';
        document.getElementById('health-text').textContent = 'Healthy';
        document.getElementById('health-text').className = 'text-zinc-400';
    }, 1000);
}

async function doApprove(action) {
    console.log('doApprove called:', action, 'incident:', currentIncident?.id, 'user:', currentUser);
    if (!currentIncident || !currentUser) {
        console.error('Missing:', !currentIncident ? 'incident' : 'user');
        return;
    }
    const comment = action === 'reject' ? (prompt('Reason?') || '') : '';
    hideActions();
    addStep('⏳', action === 'approve' ? 'Deploying...' : 'Processing...', `${currentUser} ${action === 'approve' ? 'approved' : 'rejected'} the fix`, 'purple', true);
    try {
        const res = await fetch(`/api/incidents/${currentIncident.id}/approve`, {
            method: 'POST', headers: {'Content-Type':'application/json'},
            body: JSON.stringify({ user_name: currentUser, action, comment }),
        });
        const data = await res.json();
        console.log('Approve response:', data);
    } catch(e) {
        console.error('Approve failed:', e);
        addStep('❌', 'Error', `Failed to send approval: ${e.message}`, 'red');
    }
}

function doOverride() {
    const fix = prompt('Enter your override fix:');
    if (!fix || !currentIncident) return;
    hideActions();
    fetch(`/api/incidents/${currentIncident.id}/approve`, {
        method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({ user_name: currentUser, action:'override', comment: fix }),
    });
}

function doRequestChanges() {
    const feedback = prompt('What changes should the agent make?');
    if (!feedback || !currentIncident) return;
    fetch(`/api/incidents/${currentIncident.id}/approve`, {
        method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({ user_name: currentUser, action:'request_changes', comment: feedback }),
    });
}

// ─── Comments ───────────────────────────────────────────────────────
function onNewComment(d) {
    const list = document.getElementById('comments-list');
    list.innerHTML += `
        <div class="flex gap-2 step-enter">
            <div class="w-5 h-5 rounded-full flex items-center justify-center text-xs font-bold shrink-0" style="background:${avatarColor(d.user_name)}">${d.user_name[0].toUpperCase()}</div>
            <div>
                <span class="text-xs font-medium">${d.user_name}</span>
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
        body: JSON.stringify({ user_name: currentUser, content }),
    });
}

// ─── Activity Feed ──────────────────────────────────────────────────
function addActivity(d, silent=false) {
    const feed = document.getElementById('activity-feed');
    if (feed.querySelector('.text-zinc-700')) feed.innerHTML = ''; // Clear placeholder
    const icons = {
        incident_detected:'🚨', diagnosed:'🔍', fix_proposed:'🔧', auto_deploying:'🚀',
        escalated:'⚠️', resolved:'✅', approved:'👍', rejected:'👎', overridden:'✏️',
        changes_requested:'💬', sandbox_test:'🧪', safety_check:'🛡️', fix_refined:'🔄',
        learning_recorded:'📚', started:'▶️', stopped:'⏹️', fault_injected:'💥', commented:'💬',
    };
    const icon = icons[d.action] || '•';
    const isAgent = d.actor === 'agent' || d.actor === 'system';
    const el = document.createElement('div');
    el.className = `flex items-start gap-2 py-1 text-xs ${silent ? '' : 'step-enter'}`;
    el.innerHTML = `
        <span class="shrink-0">${icon}</span>
        <span class="${isAgent ? 'text-purple-400' : 'text-zinc-400'}">${d.actor}</span>
        <span class="text-zinc-600 flex-1 truncate">${d.detail || d.action.replace(/_/g,' ')}</span>
        <span class="text-zinc-700 shrink-0">${timeAgo(d.created_at)}</span>
    `;
    feed.prepend(el);
    // Keep max 50
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

// ─── Inject ─────────────────────────────────────────────────────────
function showInjectModal() { const m=document.getElementById('inject-modal'); m.classList.remove('hidden'); m.classList.add('flex'); }
function hideInjectModal() { const m=document.getElementById('inject-modal'); m.classList.add('hidden'); m.classList.remove('flex'); }

async function injectFault(type) {
    hideInjectModal();
    // Reset view for new incident
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
        const res = await fetch('/api/inject', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({fault_type:type}) });
        const d = await res.json();
        addActivity({ actor:'you', action:'fault_injected', detail:`💥 ${type}: ${d.detail||''}`, created_at:new Date().toISOString() });
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
            const p = document.getElementById('voice-player');
            p.src = `data:audio/mpeg;base64,${d.audio_b64}`;
            p.play();
        }
        addActivity({ actor:'agent', action:'voice_summary', detail:`🔊 ${d.script}`, created_at:new Date().toISOString() });
    } catch(e) { console.error(e); }
}

// Auto-refresh stats
setInterval(refreshStats, 10000);

// Poll for new incidents (catch ones missed by WebSocket)
let lastSeenIncidentId = null;
setInterval(async () => {
    if (!currentUser) return;
    try {
        const incs = await fetch('/api/incidents').then(r=>r.json());
        const active = incs.find(i => !['resolved','rejected'].includes(i.status));
        if (active && active.id !== lastSeenIncidentId && !currentIncident) {
            // Brand new incident we haven't seen
            lastSeenIncidentId = active.id;
            showIncident(active);
        }
    } catch(e) {}
}, 5000);
