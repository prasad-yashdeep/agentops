# 🔧 AgentOps — Self-Healing DevOps with Collaborative Human-in-the-Loop

> **DevOps incidents shouldn't be solo. Our agent does the heavy lifting, your team makes the calls — together.**

An AI agent that monitors your services in real-time, diagnoses failures, proposes fixes, tests them in isolated sandboxes, validates safety, and lets your engineering team collaborate on the response — all from a shared war room dashboard.

![Track 1: Build an Agent](https://img.shields.io/badge/Track_1-Build_an_Agent-6c5ce7?style=for-the-badge)
![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=for-the-badge&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?style=for-the-badge&logo=fastapi)

## 🏗️ Architecture

```
┌──────────────────────────────────────────────────────┐
│                  MONITORED SERVICES                   │
│         api • database • auth • cache • worker        │
└──────────────┬───────────────────────────────────────┘
               │ health checks every 5s
               ▼
┌──────────────────────────────────────────────────────┐
│               🤖 AGENT CORE (Claude)                  │
│                                                       │
│  detect → diagnose → generate fix → test → decide     │
└──────┬───────────┬──────────────┬────────────────────┘
       │           │              │
       ▼           ▼              ▼
┌──────────┐ ┌──────────┐ ┌──────────────────┐
│  BLAXEL  │ │  WHITE   │ │   CONFIDENCE     │
│ SANDBOX  │ │ CIRCLE   │ │   SCORING +      │
│          │ │ AI       │ │   LEARNING       │
│ Isolated │ │ Safety   │ │                  │
│ fix      │ │ check    │ │ >85% → auto-fix  │
│ testing  │ │ before   │ │ 50-85% → review  │
│          │ │ deploy   │ │ <50% → escalate  │
└──────────┘ └──────────┘ └────────┬─────────┘
                                   │
                                   ▼
┌──────────────────────────────────────────────────────┐
│            👥 COLLABORATIVE DASHBOARD                 │
│                                                       │
│  [Dev 1]        [Dev 2]        [Dev 3]               │
│  ✅ Approve     💬 Comment     ✏️ Override             │
│                                                       │
│  Real-time WebSocket • Live presence • Activity feed  │
└──────────────────────────────────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────────────────┐
│           🔊 ELEVENLABS VOICE ALERTS                  │
│    Critical incidents → spoken alerts to engineers     │
└──────────────────────────────────────────────────────┘
```

## ⚡ Quick Start

```bash
# 1. Clone
git clone https://github.com/yashdeepPrasad/agentops.git
cd agentops

# 2. Setup
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 3. Configure
cp .env.example .env
# Edit .env with your API keys (see Configuration below)

# 4. Run
python main.py
```

Open **http://localhost:8000** — that's your war room.

## 🔑 Configuration

| Key | Required? | What it does |
|-----|-----------|-------------|
| `ANTHROPIC_API_KEY` | **Optional** | Claude-powered diagnosis & fix generation. Without it, a rich rule-based engine handles everything. Add it to unlock LLM reasoning. |
| `BLAXEL_API_KEY` | **Optional** | Persistent cloud sandboxes for isolated fix testing (resume in <25ms). Falls back to local subprocess. |
| `WHITECIRCLE_API_KEY` | **Optional** | AI safety validation of proposed fixes. Falls back to built-in safety checks (destructive commands, data loss, security, credentials). |
| `ELEVENLABS_API_KEY` | **Optional** | Voice alerts for critical incidents. Skips if not set. |

**Everything works with zero API keys** — the built-in engines are production-quality. Each API key unlocks additional capabilities.

### Adding Anthropic (Claude)

To enable AI-powered diagnosis and fix generation:

```bash
# In your .env file:
ANTHROPIC_API_KEY=sk-ant-your-key-here
CLAUDE_MODEL=claude-sonnet-4-20250514  # or claude-3-haiku for faster responses
```

The agent will automatically use Claude for root cause analysis and fix generation when the key is present, and fall back to the rule-based engine if the API is unreachable.

## 🎮 Demo Flow

1. **Open the dashboard** at `http://localhost:8000`
2. **Enter your name** to join the war room
3. **Click 💥 Inject Fault** to simulate a failure:
   - 💀 **Crash** — OOMKilled process (exit code 137)
   - 🐌 **Slow** — 5s response time, connection pool exhaustion
   - ⚙️ **Bad Config** — Invalid DATABASE_URL
   - 📈 **Memory Leak** — 92% memory, GC thrashing
   - 🔗 **Dependency Down** — Upstream 503
4. **Watch the agent** detect → diagnose → propose fix in real-time
5. **Collaborate** with your team:
   - ✅ **Approve** — deploy the fix
   - ❌ **Reject** — with reason
   - ✏️ **Override** — substitute your own fix
   - 💬 **Request Changes** — agent incorporates your feedback
   - 💬 **Comment** — discuss with teammates
6. **🔊 Voice Summary** — hear an ElevenLabs status report
7. **Inject multiple faults** across different services to see the agent handle concurrent incidents

### Multi-User Demo
Open the dashboard on **multiple devices/browsers** — each person enters a different name. Everyone sees the same incidents, approvals, and comments in real-time. Live presence shows who's online and what they're viewing.

## 🧠 How It Works

### Confidence-Based Escalation

The agent doesn't just auto-fix everything — it knows when to ask for help:

| Confidence | Action | Why |
|-----------|--------|-----|
| **>85%** + safety passed + tests passed | 🚀 Auto-deploys | High confidence, safe, verified |
| **50-85%** | 🔧 Proposes fix, waits for approval | Medium confidence, needs human judgment |
| **<50%** | ⚠️ Escalates with voice alert | Low confidence, needs expert review |

### Learning System

Every human decision (approve/reject/override) is recorded. Over time, the agent:
- **Boosts confidence** for fix patterns that humans consistently approve
- **Lowers confidence** for patterns that get rejected
- Effectively learns your team's preferences and risk tolerance

### Safety Pipeline (White Circle AI)

Before any fix is deployed, it passes through safety checks:
- ✅ No destructive commands (`rm -rf`, `DROP TABLE`, etc.)
- ✅ No data loss potential
- ✅ No security regressions (`chmod 777`, credential exposure)
- ✅ No credential leaks in fix code
- ✅ Rollback possibility assessment

## 🏆 Sponsor Stack

| Sponsor | Integration | Role |
|---------|------------|------|
| **Blaxel** (YCX25) | `blaxel` Python SDK | Persistent cloud sandboxes — agent spins up isolated VMs to reproduce bugs and test fixes. Resume from standby in <25ms. |
| **Anthropic** | Claude API | AI reasoning engine — root cause analysis, fix generation, feedback incorporation |
| **White Circle AI** | Safety API + built-in | Control layer that validates agent outputs before deployment — catches dangerous fixes |
| **ElevenLabs** | TTS API | Voice alerts for critical incidents — engineers hear what's happening without looking at a screen |

## 📡 API Reference

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Dashboard UI |
| `/api/incidents` | GET | List incidents (filter: `?status=detected`) |
| `/api/incidents/:id` | GET | Incident detail |
| `/api/incidents/:id/approve` | POST | Approve/reject/override a fix |
| `/api/incidents/:id/comments` | POST | Add a comment |
| `/api/incidents/:id/comments` | GET | List comments |
| `/api/incidents/:id/approvals` | GET | Approval history |
| `/api/activity` | GET | Activity feed (filter: `?incident_id=...`) |
| `/api/inject` | POST | Inject fault: `{"fault_type": "crash", "service": "api"}` |
| `/api/health` | GET | All services health status |
| `/api/services` | GET | List monitored services |
| `/api/agent/status` | GET | Agent stats (incidents, confidence, learning) |
| `/api/agent/start` | POST | Start agent |
| `/api/agent/stop` | POST | Stop agent |
| `/api/learning` | GET | Learning records and stats |
| `/api/voice/summary` | GET | Generate voice summary |
| `/ws/:username` | WS | WebSocket for real-time updates |

## 🛠️ Tech Stack

- **Backend**: Python, FastAPI, SQLAlchemy, SQLite
- **Agent**: Anthropic Claude (with rule-based fallback)
- **Sandbox**: Blaxel SDK (with local subprocess fallback)
- **Safety**: White Circle AI (with built-in checks fallback)
- **Voice**: ElevenLabs TTS API
- **Frontend**: Vanilla JS, Tailwind CSS, WebSocket
- **Real-time**: WebSocket broadcast + live presence tracking

## 📁 Project Structure

```
agentops/
├── main.py              # FastAPI server — API, WebSocket, dashboard
├── agent_core.py        # AI agent — monitor → diagnose → fix → learn
├── monitored_app.py     # Simulated microservices with fault injection
├── sandbox.py           # Blaxel SDK integration (+ local fallback)
├── safety_check.py      # White Circle AI safety validation
├── voice_alerts.py      # ElevenLabs TTS voice alerts
├── ws_manager.py        # WebSocket real-time broadcast + presence
├── db.py                # SQLite models (incidents, approvals, learning)
├── schemas.py           # Pydantic API schemas
├── config.py            # Environment configuration
├── static/
│   ├── index.html       # Collaborative dashboard UI
│   └── app.js           # Frontend WebSocket + incident management
├── .env.example         # Configuration template
├── requirements.txt     # Python dependencies
└── run.sh               # Quick start script
```

## Built at [Iterate](https://iterate.world) x CBS AI Club Hackathon @ Columbia Business School
