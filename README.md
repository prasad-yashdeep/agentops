# 🔧 AgentOps — Self-Healing DevOps Agent

> **AI-powered incident detection, diagnosis, and auto-fix with collaborative human-in-the-loop.**

AgentOps monitors a live production e-commerce application, detects failures in real time, uses Claude AI to diagnose root causes and generate fixes, validates safety through White Circle AI, and auto-deploys fixes when confidence is high — or escalates to the team for approval when the risk is too great.

Built in 5 hours at the **Iterate x CBS AI Club Hackathon** at Columbia Business School.

![Track 1: Build an Agent](https://img.shields.io/badge/Track_1-Build_an_Agent-6c5ce7?style=for-the-badge)
![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=for-the-badge&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?style=for-the-badge&logo=fastapi)

---

## 🌐 Live Demo

> **Deployed and running — try it now!**

| Link | Description |
|---|---|
| [**🖥️ Dashboard**](https://her-believe-page-bean.trycloudflare.com) | Main AgentOps dashboard — login, inject faults, watch AI auto-heal |
| [**🛒 Shop**](https://her-believe-page-bean.trycloudflare.com/shop) | E-commerce storefront — browse products, add to cart, checkout |
| [**📡 Live API**](https://her-believe-page-bean.trycloudflare.com/live) | Real-time API viewer — products, orders, analytics, users (auto-refreshes) |
| [**☁️ Blaxel Sandbox**](https://app.blaxel.ai) | `agentops-ecom` sandbox running the target e-commerce app |

**Team Logins:** Bhumika (`bds9746@nyu.edu`) · Yash (`yp2693@nyu.edu`) · Shweta (`ss19623@nyu.edu`) — password: `1234`

---

## 🎯 The Problem

Production incidents are stressful, time-consuming, and often happen at the worst times. Engineers scramble to diagnose issues, worry about making things worse with a fix, and lack visibility into what's happening across the team. Traditional monitoring tools alert you — but they don't *fix* anything.

## 💡 Our Solution

AgentOps is a **self-healing DevOps agent** that:
1. **Detects** failures via continuous health monitoring (every 5s)
2. **Diagnoses** root causes using Claude AI with full traceback analysis
3. **Generates** targeted fixes with code diffs
4. **Validates** fix safety through White Circle AI guardrails
5. **Auto-deploys** when confidence > 85% and severity is non-critical
6. **Escalates** to the team with role-based approval for critical/blocker issues
7. **Learns** from human decisions to improve future confidence scoring

All of this happens on a **real running application** — not a simulation.

---

## 🏗️ Architecture

```
┌─────────────────┐     ┌──────────────────┐     ┌───────────────┐
│  E-Commerce App  │────▶│  AgentOps Server  │────▶│   Claude AI   │
│  (Blaxel Sandbox)│     │  (FastAPI + WS)   │     │  (Diagnosis)  │
│  Port 3000       │     │  Port 8000        │     │               │
└─────────────────┘     └────────┬───────────┘     └───────┬───────┘
                                 │                          │
                    ┌────────────▼──────────┐    ┌─────────▼────────┐
                    │  WebSocket Dashboard  │    │  White Circle AI  │
                    │  Real-time updates    │    │  Safety Validation│
                    │  Role-based auth      │    │  Policy Engine    │
                    └───────────────────────┘    └──────────────────┘
                                 │
                    ┌────────────▼──────────┐
                    │    ElevenLabs TTS     │
                    │    Voice Alerts       │
                    └───────────────────────┘
```

### Confidence-Based Escalation
| Confidence | Severity | Action |
|---|---|---|
| **≥ 85%** | Medium/Low | 🤖 **Auto-fix** — deployed without human approval |
| **≥ 85%** | Blocker | 🔒 **Team Lead approval required** — too risky for auto |
| **50-85%** | Any | 👥 **Human review** — team decides |
| **< 50%** | Any | ⚠️ **Escalate** — needs expert investigation |

---

## 🛠️ Sponsor Integrations

### 🧊 Blaxel — Sandboxed Runtime
- Target e-commerce app runs inside a **Blaxel persistent sandbox** (`agentops-ecom`)
- All file operations (read/write handler.py, config.json) go through Blaxel SDK
- Process management (start/stop/kill) via Blaxel process API
- Isolated code testing sandbox (`agentops-sandbox`) for validating fixes before deployment

### 🧠 Anthropic Claude — AI Reasoning
- **Root cause diagnosis**: Analyzes health check errors, tracebacks, and source code
- **Fix generation**: Produces targeted code diffs with file + line identification
- **Confidence scoring**: Claude-diagnosed issues get a trust boost (+15%) over rule-based fallback
- Model: `claude-sonnet-4-20250514` with structured JSON output
- Graceful fallback: Rich rule-based engine works when API is unavailable

### 🛡️ White Circle AI — Safety Validation
- Every proposed fix passes through White Circle's guardrail API before deployment
- Endpoint: `POST /api/session/check` with deployment-specific policies
- Custom policy: **AgentOps Safety Guard** — flags destructive commands, credential exposure, data loss, security regressions
- Allows: process restarts, file restores from backup, config rollbacks
- Double verification enabled for production safety

### 🔊 ElevenLabs — Voice Alerts
- Critical/high severity incidents trigger voice alerts via ElevenLabs TTS
- Model: `eleven_flash_v2_5` for low-latency alerts
- Audio delivered via WebSocket to all connected dashboard users
- Alert script includes: incident title, severity, root cause summary, proposed fix

---

## 🎮 Features

### Real Fault Injection (Not Simulated!)
| Fault Type | What It Does | Severity |
|---|---|---|
| **Crash** | Kills the app process (OOM simulation) | 🔴 BLOCKER |
| **Bad Config** | Corrupts config.json with invalid JSON | 🔴 BLOCKER |
| **Bug** | Injects NameError in handler.py validate() | 🟡 MEDIUM |
| **Slow** | Adds time.sleep(10) to handler.py | 🟡 MEDIUM |

### Role-Based Team Authentication
| Role | User | Can Approve |
|---|---|---|
| **Team Lead** ⭐ | Shweta | All bugs (including BLOCKER) |
| **Senior Dev** ⚡ | Yash | Medium + Low severity |
| **Junior Dev** 🚀 | Bhumika | Low severity only |

### Dashboard Tabs
- **Incidents**: Real-time incident timeline with detection → diagnosis → fix → deploy flow
- **Analytics**: Resolution rate, auto-fix rate, avg resolution time, severity breakdown
- **Team**: Member profiles, role badges, permissions matrix
- **Reports**: Clearance reports (auto-generated on bug resolution, sent to team lead)

### Additional Features
- **GitHub Deep Links**: Every fix links to the exact file and line in the repo
- **Human-Readable Explanations**: Plain English explanations with analogies for non-technical stakeholders
- **Impact Analysis**: Automated blast radius assessment for each fault type
- **Notification System**: Bell badge with unread count, clearance reports auto-sent to team lead
- **Learning System**: Records human approve/reject decisions to adjust future confidence
- **E-Commerce Shop**: Full storefront with cart, checkout, live analytics
- **Live API Viewer**: Real-time view of all API endpoints with auto-refresh

---

## 🚀 Quick Start

### Prerequisites
- Python 3.10+
- Blaxel account + API key
- Anthropic API key (optional — rule-based fallback works without it)
- White Circle AI API key + deployment ID
- ElevenLabs API key (optional — for voice alerts)

### Setup
```bash
# Clone
git clone https://github.com/prasad-yashdeep/agentops.git
cd agentops

# Virtual environment
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Configure
cp .env.example .env
# Edit .env with your API keys

# Run
python3 main.py
```

### Environment Variables
```env
# Blaxel — Sandboxed Runtime
BL_API_KEY=your_blaxel_key
BL_WORKSPACE=your_workspace

# Anthropic — AI Reasoning
ANTHROPIC_API_KEY=sk-ant-api03-...

# White Circle AI — Safety Validation
WHITECIRCLE_API_KEY=wc-...
WHITECIRCLE_API_URL=https://us.whitecircle.ai/api
WHITECIRCLE_DEPLOYMENT_ID=your_deployment_id

# ElevenLabs — Voice Alerts
ELEVENLABS_API_KEY=sk_...
ELEVENLABS_VOICE_ID=21m00Tcm4TlvDq8ikWAM
```

### Access
- **Dashboard**: http://localhost:8000
- **Live App**: http://localhost:8000/live
- **Shop**: http://localhost:8000/shop
- **Team Logins**: Bhumika / Yash / Shweta (password: `1234`)

---

## 📁 Project Structure

```
agentops/
├── main.py              # FastAPI server, auth, proxy, analytics, WebSocket
├── agent_core.py        # Agent brain: monitoring, diagnosis, fix generation, confidence
├── monitored_app.py     # Blaxel SDK integration, fault injection, health checks
├── safety_check.py      # White Circle AI integration + local safety engine fallback
├── voice_alerts.py      # ElevenLabs TTS voice alert generation
├── sandbox.py           # Blaxel sandbox for isolated code testing
├── db.py                # SQLite models: User, Incident, Notification, LearningRecord
├── schemas.py           # Pydantic schemas
├── config.py            # Environment variable loading
├── static/
│   ├── index.html       # Dashboard: login, incidents, analytics, team, reports
│   ├── app.js           # Frontend: WebSocket, auth, tabs, role-based UI
│   ├── live.html        # Live API viewer (auto-refresh 5s)
│   └── shop.html        # E-commerce storefront with checkout
└── target_app/
    ├── server.py         # Target e-commerce HTTP server
    ├── handler.py        # Request handler (products, orders, analytics, users)
    ├── handler.py.bak    # Known-good backup for fault recovery
    ├── config.json       # App configuration
    └── config.json.bak   # Known-good config backup
```

---

## 🧪 Demo Flow

1. **Login** as Shweta (Team Lead) → see clean dashboard
2. **Inject Bug** → watch agent detect NameError in seconds
3. **Claude diagnoses** → identifies handler.py line 54, generates fix diff
4. **White Circle validates** → "✅ SAFE — no policies flagged"
5. **Auto-deploys** → confidence 95%, medium severity → no human needed
6. **App recovers** → healthy in ~30 seconds
7. **Inject Crash** → process killed (BLOCKER severity)
8. **Agent diagnoses** → confidence 90%, but BLOCKER → needs Team Lead
9. **Shweta approves** → fix deploys, clearance report generated
10. **Try as Bhumika** → can't approve BLOCKER → "Insufficient clearance"

---

## 👥 Team

- **Yash Prasad** — Architecture, agent core, full-stack development
- **Shweta** — Testing, role-based access design, demo flow
- **Bhumika** — UI/UX, team collaboration features

---

## 📄 License

MIT
