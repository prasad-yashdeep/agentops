"""
AgentOps — Self-Healing DevOps Agent with Collaborative Human-in-the-Loop
Main server: serves API, dashboard, WebSocket, and runs the agent.
"""
import asyncio
import json
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from db import init_db, SessionLocal, Incident, Approval, Comment, ActivityLog, LearningRecord, gen_id
from schemas import IncidentOut, ApprovalCreate, CommentCreate, CommentOut, ApprovalOut, ActivityOut, FaultInject
from monitored_app import app_instance, TARGET_PORT
from agent_core import agent
from ws_manager import manager
from voice_alerts import voice_alerts
from safety_check import safety_checker
from config import HOST, PORT


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    agent_task = asyncio.create_task(agent.start())
    yield
    await agent.stop()
    await app_instance.stop()
    agent_task.cancel()


app = FastAPI(title="AgentOps", version="1.0.0", lifespan=lifespan)

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")


# ─── Dashboard ───────────────────────────────────────────────────────

@app.get("/")
async def dashboard():
    return FileResponse("static/index.html")


# ─── WebSocket ───────────────────────────────────────────────────────

@app.websocket("/ws/{user_name}")
async def websocket_endpoint(websocket: WebSocket, user_name: str):
    await manager.connect(websocket, user_name)
    try:
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)

            if msg.get("type") == "viewing":
                manager.set_viewing(user_name, msg.get("incident_id"))
                await manager.broadcast_presence()

            elif msg.get("type") == "typing":
                await manager.broadcast("user_typing", {
                    "user": user_name, "incident_id": msg.get("incident_id"),
                })
    except WebSocketDisconnect:
        manager.disconnect(user_name)
        await manager.broadcast_presence()


# ─── Incidents API ───────────────────────────────────────────────────

@app.get("/api/incidents", response_model=list[IncidentOut])
async def list_incidents(status: str | None = None, limit: int = 50):
    db = SessionLocal()
    try:
        q = db.query(Incident).order_by(Incident.detected_at.desc())
        if status:
            q = q.filter(Incident.status == status)
        return q.limit(limit).all()
    finally:
        db.close()


@app.get("/api/incidents/{incident_id}", response_model=IncidentOut)
async def get_incident(incident_id: str):
    db = SessionLocal()
    try:
        incident = db.query(Incident).filter(Incident.id == incident_id).first()
        if not incident:
            raise HTTPException(404, "Incident not found")
        return incident
    finally:
        db.close()


# ─── Approvals ───────────────────────────────────────────────────────

@app.post("/api/incidents/{incident_id}/approve")
async def approve_incident(incident_id: str, body: ApprovalCreate):
    result = await agent.handle_approval(incident_id, body.user_name, body.action, body.comment or "")
    if "error" in result:
        raise HTTPException(400, result["error"])
    return result


@app.get("/api/incidents/{incident_id}/approvals", response_model=list[ApprovalOut])
async def get_approvals(incident_id: str):
    db = SessionLocal()
    try:
        return db.query(Approval).filter(Approval.incident_id == incident_id).order_by(Approval.created_at.desc()).all()
    finally:
        db.close()


# ─── Comments ────────────────────────────────────────────────────────

@app.post("/api/incidents/{incident_id}/comments", response_model=CommentOut)
async def add_comment(incident_id: str, body: CommentCreate):
    db = SessionLocal()
    try:
        comment = Comment(
            id=gen_id(), incident_id=incident_id,
            user_name=body.user_name, content=body.content,
        )
        db.add(comment)
        db.commit()
        db.refresh(comment)

        await manager.broadcast("new_comment", {
            "id": comment.id, "incident_id": incident_id,
            "user_name": body.user_name, "content": body.content,
            "created_at": str(comment.created_at),
        })
        return comment
    finally:
        db.close()


@app.get("/api/incidents/{incident_id}/comments", response_model=list[CommentOut])
async def get_comments(incident_id: str):
    db = SessionLocal()
    try:
        return db.query(Comment).filter(Comment.incident_id == incident_id).order_by(Comment.created_at.asc()).all()
    finally:
        db.close()


# ─── Activity Feed ───────────────────────────────────────────────────

@app.get("/api/activity", response_model=list[ActivityOut])
async def get_activity(incident_id: str | None = None, limit: int = 100):
    db = SessionLocal()
    try:
        q = db.query(ActivityLog).order_by(ActivityLog.created_at.desc())
        if incident_id:
            q = q.filter(ActivityLog.incident_id == incident_id)
        return q.limit(limit).all()
    finally:
        db.close()


# ─── Fault Injection (Demo) ─────────────────────────────────────────

@app.post("/api/inject")
async def inject_fault(body: FaultInject):
    result = await app_instance.inject_fault(body.fault_type)
    await manager.broadcast("fault_injected", result)
    return result


@app.post("/api/clear")
async def clear_faults():
    result = await app_instance.apply_fix(app_instance.active_fault or "unknown")
    return result


@app.get("/api/health")
async def get_health():
    return await app_instance.health_check()


@app.get("/api/target-app")
async def target_app_info():
    return {
        "running": app_instance.is_running(),
        "port": TARGET_PORT,
        "url": f"http://localhost:{TARGET_PORT}",
        "active_fault": app_instance.active_fault,
        "logs_tail": app_instance.get_logs(limit=10),
    }


# ─── Agent Status ────────────────────────────────────────────────────

@app.get("/api/agent/status")
async def agent_status():
    return agent.get_stats()


@app.post("/api/agent/stop")
async def stop_agent():
    await agent.stop()
    return {"status": "stopped"}


@app.post("/api/agent/start")
async def start_agent():
    if not agent.running:
        asyncio.create_task(agent.start())
    return {"status": "started"}


# ─── Voice Alert ─────────────────────────────────────────────────────

@app.get("/api/voice/summary")
async def voice_summary():
    stats = agent.get_stats()
    summary = await voice_alerts.generate_summary(stats)
    return summary


# ─── Learning Stats ──────────────────────────────────────────────────

@app.get("/api/learning")
async def learning_stats():
    db = SessionLocal()
    try:
        records = db.query(LearningRecord).order_by(LearningRecord.created_at.desc()).limit(50).all()
        return {
            "total": len(records),
            "records": [
                {
                    "id": r.id,
                    "incident_type": r.incident_type,
                    "human_decision": r.human_decision,
                    "confidence_adjustment": r.confidence_adjustment,
                    "created_at": str(r.created_at),
                }
                for r in records
            ],
            "summary": {
                "approved": sum(1 for r in records if r.human_decision == "approved"),
                "rejected": sum(1 for r in records if r.human_decision == "rejected"),
                "modified": sum(1 for r in records if r.human_decision == "modified"),
            },
        }
    finally:
        db.close()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=HOST, port=PORT)
