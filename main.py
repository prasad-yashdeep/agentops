"""
AgentOps — Self-Healing DevOps Agent with Collaborative Human-in-the-Loop
Main server: serves API, dashboard, WebSocket, and runs the agent.
"""
import asyncio
import json
import os
from datetime import datetime, timezone
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Query, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from db import (init_db, SessionLocal, Incident, Approval, Comment, ActivityLog,
                LearningRecord, Notification, User, gen_id, utcnow,
                hash_password, can_approve_severity, ROLE_HIERARCHY)
from schemas import (IncidentOut, ApprovalCreate, CommentCreate, CommentOut,
                     ApprovalOut, ActivityOut, FaultInject, LoginRequest,
                     UserOut, NotificationOut)
from monitored_app import app_instance, TARGET_PORT, BL_SANDBOX_NAME
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


app = FastAPI(title="AgentOps", version="2.0.0", lifespan=lifespan)

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")


# ─── Helper: Get user by name ───────────────────────────────────────

def get_user_by_name(db, name: str) -> User | None:
    return db.query(User).filter(User.name == name).first()


def get_highest_authority(db) -> User | None:
    return db.query(User).filter(User.is_highest_authority == True).first()


async def send_clearance_report(incident, cleared_by_user, db):
    """Generate and send a clearance report to the highest authority."""
    authority = get_highest_authority(db)
    if not authority:
        return

    # Get timeline
    activities = db.query(ActivityLog).filter(
        ActivityLog.incident_id == incident.id
    ).order_by(ActivityLog.created_at.asc()).all()

    timeline_text = "\n".join([
        f"  [{a.created_at.strftime('%H:%M:%S')}] {a.actor} ({a.actor_role or 'system'}): {a.detail}"
        for a in activities
    ])

    report = (
        f"═══ BUG CLEARANCE REPORT ═══\n\n"
        f"🐛 Bug: {incident.title}\n"
        f"📋 ID: #{incident.id}\n"
        f"🔴 Severity: {incident.bug_severity.upper()}\n"
        f"📊 Impact: {incident.severity}\n\n"
        f"📝 Description: {incident.description}\n"
        f"🔍 Root Cause: {incident.root_cause or 'N/A'}\n\n"
        f"👤 Reported by: {incident.reported_by or 'Agent (auto-detected)'}\n"
        f"🔧 Assigned to: {incident.assigned_to or 'Agent'}\n"
        f"✅ Cleared by: {cleared_by_user.name} ({cleared_by_user.role})\n"
        f"🕐 Detected: {incident.detected_at.strftime('%Y-%m-%d %H:%M:%S') if incident.detected_at else 'N/A'}\n"
        f"🕐 Resolved: {incident.resolved_at.strftime('%Y-%m-%d %H:%M:%S') if incident.resolved_at else 'N/A'}\n"
        f"🕐 Cleared: {incident.cleared_at.strftime('%Y-%m-%d %H:%M:%S') if incident.cleared_at else 'N/A'}\n\n"
        f"🔧 Resolution Method: {incident.resolution_method or incident.proposed_fix or 'Auto-fix by agent'}\n\n"
        f"📜 Timeline:\n{timeline_text}\n\n"
        f"🤖 Agent Confidence: {incident.confidence_score:.0%}\n"
        f"🛡️ Safety Check: {'PASSED' if incident.safety_check_passed else 'FAILED'}\n"
    )

    # Create notification
    notif = Notification(
        id=gen_id(),
        user_id=authority.id,
        incident_id=incident.id,
        title=f"Bug #{incident.id} Cleared — {incident.bug_severity.upper()}",
        message=report,
        type="clearance_report",
    )
    db.add(notif)
    db.commit()

    # Broadcast via WebSocket
    await manager.broadcast("clearance_report", {
        "incident_id": incident.id,
        "title": incident.title,
        "severity": incident.bug_severity,
        "cleared_by": cleared_by_user.name,
        "cleared_by_role": cleared_by_user.role,
        "report": report,
        "authority": authority.name,
    })

    # Also send direct notification to authority
    await manager.send_to(authority.name, "notification", {
        "id": notif.id,
        "title": notif.title,
        "message": report,
        "type": "clearance_report",
        "incident_id": incident.id,
    })


# ─── Dashboard ───────────────────────────────────────────────────────

@app.get("/")
async def dashboard():
    return FileResponse("static/index.html")


# ─── Auth ────────────────────────────────────────────────────────────

@app.post("/api/auth/login")
async def login(body: LoginRequest):
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == body.email).first()
        if not user or user.password_hash != hash_password(body.password):
            raise HTTPException(401, "Invalid email or password")
        return {
            "token": user.id,
            "user": {
                "id": user.id,
                "name": user.name,
                "email": user.email,
                "role": user.role,
                "role_display": user.role_display,
                "avatar_color": user.avatar_color,
                "is_highest_authority": user.is_highest_authority,
                "permissions": {
                    "can_approve_low": can_approve_severity(user.role, "low"),
                    "can_approve_medium": can_approve_severity(user.role, "medium"),
                    "can_approve_blocker": can_approve_severity(user.role, "blocker"),
                    "can_inject_faults": user.role in ("senior_dev", "team_lead"),
                    "can_assign": user.role in ("senior_dev", "team_lead"),
                    "can_view_reports": user.role == "team_lead",
                },
            },
        }
    finally:
        db.close()


@app.get("/api/auth/me")
async def get_me(token: str = Query(...)):
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == token).first()
        if not user:
            raise HTTPException(401, "Invalid token")
        return {
            "id": user.id,
            "name": user.name,
            "email": user.email,
            "role": user.role,
            "role_display": user.role_display,
            "avatar_color": user.avatar_color,
            "is_highest_authority": user.is_highest_authority,
            "permissions": {
                "can_approve_low": can_approve_severity(user.role, "low"),
                "can_approve_medium": can_approve_severity(user.role, "medium"),
                "can_approve_blocker": can_approve_severity(user.role, "blocker"),
                "can_inject_faults": user.role in ("senior_dev", "team_lead"),
                "can_assign": user.role in ("senior_dev", "team_lead"),
                "can_view_reports": user.role == "team_lead",
            },
        }
    finally:
        db.close()


@app.get("/api/team", response_model=list[UserOut])
async def list_team():
    db = SessionLocal()
    try:
        users = db.query(User).order_by(User.role.desc()).all()
        result = []
        for u in users:
            result.append({
                "id": u.id, "name": u.name, "email": u.email,
                "role": u.role, "role_display": u.role_display,
                "avatar_color": u.avatar_color,
                "is_highest_authority": u.is_highest_authority,
                "created_at": u.created_at,
            })
        return result
    finally:
        db.close()


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


# ─── Approvals (Role-Based) ─────────────────────────────────────────

@app.post("/api/incidents/{incident_id}/approve")
async def approve_incident(incident_id: str, body: ApprovalCreate):
    db = SessionLocal()
    try:
        # Look up user for role-based checks
        user = get_user_by_name(db, body.user_name)
        incident = db.query(Incident).filter(Incident.id == incident_id).first()

        if not incident:
            raise HTTPException(404, "Incident not found")

        # Role-based approval check for approve action
        if body.action == "approve" and user:
            bug_sev = incident.bug_severity or "medium"
            if not can_approve_severity(user.role, bug_sev):
                min_role = {"low": "Junior Developer", "medium": "Senior Developer",
                           "blocker": "Team Lead"}.get(bug_sev, "Team Lead")
                raise HTTPException(403,
                    f"🚫 {bug_sev.upper()} severity bugs can only be approved by {min_role} or above. "
                    f"Your role: {user.role_display}")
    finally:
        db.close()

    result = await agent.handle_approval(incident_id, body.user_name, body.action, body.comment or "")
    if "error" in result:
        raise HTTPException(400, result["error"])

    # If approved/resolved, send clearance report
    if body.action in ("approve", "override"):
        db = SessionLocal()
        try:
            incident = db.query(Incident).filter(Incident.id == incident_id).first()
            user = get_user_by_name(db, body.user_name)
            if incident and user:
                incident.cleared_by = body.user_name
                incident.cleared_at = utcnow()
                incident.resolution_method = body.comment or "Approved agent's proposed fix"
                db.commit()
                await send_clearance_report(incident, user, db)
        finally:
            db.close()

    return result


@app.get("/api/incidents/{incident_id}/approvals", response_model=list[ApprovalOut])
async def get_approvals(incident_id: str):
    db = SessionLocal()
    try:
        return db.query(Approval).filter(Approval.incident_id == incident_id).order_by(Approval.created_at.desc()).all()
    finally:
        db.close()


# ─── Bug Assignment ─────────────────────────────────────────────────

@app.post("/api/incidents/{incident_id}/assign")
async def assign_incident(incident_id: str, user_name: str = Query(...), assigned_to: str = Query(...)):
    db = SessionLocal()
    try:
        assigner = get_user_by_name(db, user_name)
        if not assigner or assigner.role not in ("senior_dev", "team_lead"):
            raise HTTPException(403, "Only Senior Developers and Team Leads can assign bugs")

        incident = db.query(Incident).filter(Incident.id == incident_id).first()
        if not incident:
            raise HTTPException(404, "Incident not found")

        incident.assigned_to = assigned_to
        activity = ActivityLog(
            incident_id=incident_id, actor=user_name,
            actor_role=assigner.role if assigner else None,
            action="assigned",
            detail=f"Assigned to {assigned_to}",
        )
        db.add(activity)
        db.commit()

        await manager.broadcast("incident_update", {
            "id": incident_id, "assigned_to": assigned_to,
        })
        await manager.broadcast("activity", {
            "actor": user_name, "actor_role": assigner.role,
            "action": "assigned", "detail": f"Assigned to {assigned_to}",
            "created_at": str(activity.created_at),
        })

        return {"status": "assigned", "assigned_to": assigned_to}
    finally:
        db.close()


# ─── Comments ────────────────────────────────────────────────────────

@app.post("/api/incidents/{incident_id}/comments", response_model=CommentOut)
async def add_comment(incident_id: str, body: CommentCreate):
    db = SessionLocal()
    try:
        user = get_user_by_name(db, body.user_name)
        comment = Comment(
            id=gen_id(), incident_id=incident_id,
            user_name=body.user_name,
            user_role=user.role if user else None,
            content=body.content,
        )
        db.add(comment)
        db.commit()
        db.refresh(comment)

        await manager.broadcast("new_comment", {
            "id": comment.id, "incident_id": incident_id,
            "user_name": body.user_name, "user_role": user.role if user else None,
            "content": body.content,
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


# ─── Notifications ───────────────────────────────────────────────────

@app.get("/api/notifications")
async def get_notifications(user_name: str = Query(...), limit: int = 50):
    db = SessionLocal()
    try:
        user = get_user_by_name(db, user_name)
        if not user:
            return []
        notifs = db.query(Notification).filter(
            Notification.user_id == user.id
        ).order_by(Notification.created_at.desc()).limit(limit).all()
        return [{
            "id": n.id, "incident_id": n.incident_id,
            "title": n.title, "message": n.message,
            "type": n.type, "read": n.read,
            "created_at": str(n.created_at),
        } for n in notifs]
    finally:
        db.close()


@app.post("/api/notifications/{notif_id}/read")
async def mark_notification_read(notif_id: str):
    db = SessionLocal()
    try:
        notif = db.query(Notification).filter(Notification.id == notif_id).first()
        if notif:
            notif.read = True
            db.commit()
        return {"status": "ok"}
    finally:
        db.close()


# ─── Fault Injection (Demo) ─────────────────────────────────────────

@app.post("/api/inject")
async def inject_fault(body: FaultInject):
    result = await app_instance.inject_fault(body.fault_type)
    # Store reported_by if provided
    if body.reported_by:
        result["reported_by"] = body.reported_by
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
        "port": app_instance.app_port,
        "mode": app_instance.mode,
        "sandbox": BL_SANDBOX_NAME if app_instance.mode == "blaxel" else None,
        "active_fault": app_instance.active_fault,
        "logs_tail": app_instance.get_logs(limit=10),
    }


# ─── Live App Proxy (forwards to Blaxel sandbox or local target) ─────

@app.get("/app/{path:path}")
async def proxy_app_get(path: str):
    """Proxy GET requests to the target app."""
    try:
        if app_instance.mode == "blaxel" and app_instance.sandbox:
            r = await app_instance.sandbox.process.exec({
                "command": f"curl -s -m 5 http://127.0.0.1:{app_instance.app_port}/{path}",
                "wait_for_completion": True, "timeout": 8,
            })
            logs = r.logs or ""
            try:
                return JSONResponse(content=json.loads(logs))
            except json.JSONDecodeError:
                return JSONResponse(content={"raw": logs[:2000], "error": "non-JSON response"}, status_code=502)
        else:
            import httpx
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(f"http://127.0.0.1:{app_instance.app_port}/{path}")
                return JSONResponse(content=resp.json(), status_code=resp.status_code)
    except Exception as e:
        return JSONResponse(content={"error": str(e), "status": "app_unreachable"}, status_code=503)


@app.post("/app/{path:path}")
async def proxy_app_post(path: str, request: Request):
    """Proxy POST requests to the target app (orders, checkout, users)."""
    try:
        body = await request.body()
        body_str = body.decode() if body else "{}"

        if app_instance.mode == "blaxel" and app_instance.sandbox:
            escaped_body = body_str.replace("'", "'\\''")
            r = await app_instance.sandbox.process.exec({
                "command": f"curl -s -m 5 -X POST -H 'Content-Type: application/json' -d '{escaped_body}' http://127.0.0.1:{app_instance.app_port}/{path}",
                "wait_for_completion": True, "timeout": 8,
            })
            logs = r.logs or ""
            try:
                return JSONResponse(content=json.loads(logs))
            except json.JSONDecodeError:
                return JSONResponse(content={"raw": logs[:2000], "error": "non-JSON response"}, status_code=502)
        else:
            import httpx
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.post(
                    f"http://127.0.0.1:{app_instance.app_port}/{path}",
                    content=body, headers={"Content-Type": "application/json"},
                )
                return JSONResponse(content=resp.json(), status_code=resp.status_code)
    except Exception as e:
        return JSONResponse(content={"error": str(e), "status": "app_unreachable"}, status_code=503)


@app.get("/live")
async def live_app_page():
    return FileResponse(os.path.join(os.path.dirname(__file__), "static", "live.html"))


@app.get("/shop")
async def shop_page():
    return FileResponse(os.path.join(os.path.dirname(__file__), "static", "shop.html"))


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


# ─── Analytics ───────────────────────────────────────────────────────

@app.get("/api/analytics/dashboard")
async def analytics_dashboard():
    db = SessionLocal()
    try:
        incidents = db.query(Incident).all()
        total = len(incidents)
        resolved = len([i for i in incidents if i.status == "resolved"])
        auto_resolved = len([i for i in incidents if i.auto_resolved])
        rejected = len([i for i in incidents if i.status == "rejected"])
        active = len([i for i in incidents if i.status not in ("resolved", "rejected")])

        # Bug severity breakdown
        severity_counts = {}
        for i in incidents:
            sev = i.bug_severity or "medium"
            severity_counts[sev] = severity_counts.get(sev, 0) + 1

        # Resolution time stats
        resolution_times = []
        for i in incidents:
            if i.resolved_at and i.detected_at:
                delta = (i.resolved_at - i.detected_at).total_seconds()
                resolution_times.append(delta)

        avg_resolution = sum(resolution_times) / len(resolution_times) if resolution_times else 0

        # Team performance
        team_stats = {}
        approvals = db.query(Approval).all()
        for a in approvals:
            if a.user_name not in team_stats:
                team_stats[a.user_name] = {"approvals": 0, "rejections": 0, "role": a.user_role or "unknown"}
            if a.action == "approve":
                team_stats[a.user_name]["approvals"] += 1
            elif a.action == "reject":
                team_stats[a.user_name]["rejections"] += 1

        # Recent clearances
        recent_cleared = db.query(Incident).filter(
            Incident.cleared_by != None
        ).order_by(Incident.cleared_at.desc()).limit(10).all()

        return {
            "summary": {
                "total": total,
                "resolved": resolved,
                "auto_resolved": auto_resolved,
                "rejected": rejected,
                "active": active,
                "resolution_rate": round(resolved / max(total, 1) * 100, 1),
                "auto_fix_rate": round(auto_resolved / max(resolved, 1) * 100, 1),
            },
            "severity_breakdown": severity_counts,
            "avg_resolution_seconds": round(avg_resolution, 1),
            "team_performance": team_stats,
            "recent_clearances": [
                {
                    "id": i.id, "title": i.title, "severity": i.bug_severity,
                    "cleared_by": i.cleared_by, "cleared_at": str(i.cleared_at),
                    "resolution_method": i.resolution_method,
                }
                for i in recent_cleared
            ],
        }
    finally:
        db.close()


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
