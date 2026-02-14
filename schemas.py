"""Pydantic schemas for API."""
from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class IncidentOut(BaseModel):
    id: str
    title: str
    description: str
    severity: str
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
    action: str
    comment: str
    created_at: datetime

    class Config:
        from_attributes = True


class CommentOut(BaseModel):
    id: str
    incident_id: str
    user_name: str
    content: str
    created_at: datetime

    class Config:
        from_attributes = True


class ActivityOut(BaseModel):
    id: int
    incident_id: Optional[str] = None
    actor: str
    action: str
    detail: str
    created_at: datetime

    class Config:
        from_attributes = True


class FaultInject(BaseModel):
    fault_type: str  # crash, slow, bad_config, memory_leak, dependency_down
    service: Optional[str] = "api"


class AgentStatus(BaseModel):
    running: bool
    incidents_total: int
    incidents_resolved: int
    auto_resolved: int
    learning_records: int
    confidence_avg: float
