"""Pydantic schemas for API."""
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime


# ─── Auth ────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    email: str
    password: str


class UserOut(BaseModel):
    id: str
    name: str
    email: str
    role: str
    role_display: str = ""
    avatar_color: str = "#a855f7"
    is_highest_authority: bool = False
    created_at: datetime

    class Config:
        from_attributes = True


class UserProfile(BaseModel):
    id: str
    name: str
    email: str
    role: str
    role_display: str
    avatar_color: str
    is_highest_authority: bool
    permissions: dict = {}


# ─── Incidents ───────────────────────────────────────────────────────

class IncidentOut(BaseModel):
    id: str
    title: str
    description: str
    severity: str
    bug_severity: str = "medium"
    status: str
    detected_at: datetime
    resolved_at: Optional[datetime] = None
    root_cause: Optional[str] = None
    proposed_fix: Optional[str] = None
    fix_diff: Optional[str] = None
    confidence_score: float
    agent_reasoning: Optional[str] = None
    safety_check_result: Optional[str] = None
    safety_check_passed: Optional[bool] = None
    auto_resolved: bool
    error_logs: Optional[str] = None
    service_name: Optional[str] = None
    reported_by: Optional[str] = None
    assigned_to: Optional[str] = None
    cleared_by: Optional[str] = None
    cleared_at: Optional[datetime] = None
    impact_analysis: Optional[str] = None
    resolution_method: Optional[str] = None

    class Config:
        from_attributes = True


class ApprovalCreate(BaseModel):
    user_name: str
    action: str  # approve, reject, request_changes, override
    comment: Optional[str] = ""


class CommentCreate(BaseModel):
    user_name: str
    content: str


class ApprovalOut(BaseModel):
    id: str
    incident_id: str
    user_name: str
    user_role: Optional[str] = None
    action: str
    comment: str
    created_at: datetime

    class Config:
        from_attributes = True


class CommentOut(BaseModel):
    id: str
    incident_id: str
    user_name: str
    user_role: Optional[str] = None
    content: str
    created_at: datetime

    class Config:
        from_attributes = True


class ActivityOut(BaseModel):
    id: int
    incident_id: Optional[str] = None
    actor: str
    actor_role: Optional[str] = None
    action: str
    detail: str
    created_at: datetime

    class Config:
        from_attributes = True


class NotificationOut(BaseModel):
    id: str
    incident_id: Optional[str] = None
    title: str
    message: str
    type: str
    read: bool
    created_at: datetime

    class Config:
        from_attributes = True


class FaultInject(BaseModel):
    fault_type: str
    service: Optional[str] = "api"
    reported_by: Optional[str] = None


class AgentStatus(BaseModel):
    running: bool
    incidents_total: int
    incidents_resolved: int
    auto_resolved: int
    learning_records: int
    confidence_avg: float
