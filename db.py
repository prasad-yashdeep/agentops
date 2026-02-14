"""Database models and setup."""
import uuid
import hashlib
from datetime import datetime, timezone
from sqlalchemy import create_engine, Column, String, Float, Boolean, DateTime, Text, Integer
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from config import DATABASE_URL

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def gen_id():
    return str(uuid.uuid4())[:8]


def utcnow():
    return datetime.now(timezone.utc)


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


# ─── Team Roles & Permissions ────────────────────────────────────────

ROLE_HIERARCHY = {
    "junior_dev": 1,
    "senior_dev": 2,
    "team_lead": 3,
}

# Minimum role level to approve each bug severity
SEVERITY_APPROVAL_RULES = {
    "low": "junior_dev",      # Anyone can approve
    "medium": "senior_dev",   # Senior dev or above
    "high": "senior_dev",     # Senior dev or above
    "critical": "senior_dev", # Senior dev or above
    "blocker": "team_lead",   # ONLY team lead (data loss / security)
}


def can_approve_severity(user_role: str, severity: str) -> bool:
    """Check if a user's role can approve a bug of given severity."""
    min_role = SEVERITY_APPROVAL_RULES.get(severity, "senior_dev")
    return ROLE_HIERARCHY.get(user_role, 0) >= ROLE_HIERARCHY.get(min_role, 99)


class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=gen_id)
    name = Column(String, nullable=False)
    email = Column(String, unique=True, nullable=False)
    password_hash = Column(String, nullable=False)
    role = Column(String, nullable=False, default="junior_dev")  # junior_dev, senior_dev, team_lead
    avatar_color = Column(String, default="#a855f7")
    is_highest_authority = Column(Boolean, default=False)
    created_at = Column(DateTime, default=utcnow)

    @property
    def role_display(self):
        return {"junior_dev": "Junior Developer", "senior_dev": "Senior Developer", "team_lead": "Team Lead"}.get(self.role, self.role)

    @property
    def role_level(self):
        return ROLE_HIERARCHY.get(self.role, 0)


class Incident(Base):
    __tablename__ = "incidents"

    id = Column(String, primary_key=True, default=gen_id)
    title = Column(String, nullable=False)
    description = Column(Text, default="")
    severity = Column(String, default="medium")  # low, medium, high, critical, blocker
    bug_severity = Column(String, default="medium")  # low, medium, blocker (for approval rules)
    status = Column(String, default="detected")
    detected_at = Column(DateTime, default=utcnow)
    resolved_at = Column(DateTime, nullable=True)
    root_cause = Column(Text, nullable=True)
    proposed_fix = Column(Text, nullable=True)
    fix_diff = Column(Text, nullable=True)
    confidence_score = Column(Float, default=0.0)
    agent_reasoning = Column(Text, nullable=True)
    safety_check_result = Column(Text, nullable=True)
    safety_check_passed = Column(Boolean, nullable=True)
    auto_resolved = Column(Boolean, default=False)
    error_logs = Column(Text, nullable=True)
    service_name = Column(String, nullable=True)
    # Bug tracking fields
    reported_by = Column(String, nullable=True)  # user name who triggered/reported
    assigned_to = Column(String, nullable=True)  # user name assigned to fix
    cleared_by = Column(String, nullable=True)  # user who approved clearance
    cleared_at = Column(DateTime, nullable=True)
    impact_analysis = Column(Text, nullable=True)
    resolution_method = Column(Text, nullable=True)


class Approval(Base):
    __tablename__ = "approvals"

    id = Column(String, primary_key=True, default=gen_id)
    incident_id = Column(String, nullable=False)
    user_name = Column(String, nullable=False)
    user_role = Column(String, nullable=True)
    action = Column(String, nullable=False)
    comment = Column(Text, default="")
    created_at = Column(DateTime, default=utcnow)


class Comment(Base):
    __tablename__ = "comments"

    id = Column(String, primary_key=True, default=gen_id)
    incident_id = Column(String, nullable=False)
    user_name = Column(String, nullable=False)
    user_role = Column(String, nullable=True)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=utcnow)


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(String, primary_key=True, default=gen_id)
    user_id = Column(String, nullable=False)
    incident_id = Column(String, nullable=True)
    title = Column(String, nullable=False)
    message = Column(Text, nullable=False)
    type = Column(String, default="info")  # info, warning, critical, clearance_report
    read = Column(Boolean, default=False)
    created_at = Column(DateTime, default=utcnow)


class LearningRecord(Base):
    __tablename__ = "learning_records"

    id = Column(String, primary_key=True, default=gen_id)
    incident_type = Column(String, nullable=False)
    error_pattern = Column(Text, nullable=False)
    proposed_fix_pattern = Column(Text, nullable=False)
    human_decision = Column(String, nullable=False)
    confidence_adjustment = Column(Float, default=0.0)
    created_at = Column(DateTime, default=utcnow)


class ActivityLog(Base):
    __tablename__ = "activity_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    incident_id = Column(String, nullable=True)
    actor = Column(String, nullable=False)
    actor_role = Column(String, nullable=True)
    action = Column(String, nullable=False)
    detail = Column(Text, default="")
    created_at = Column(DateTime, default=utcnow)


def init_db():
    Base.metadata.create_all(bind=engine)
    # Seed default team members
    db = SessionLocal()
    try:
        if db.query(User).count() == 0:
            team = [
                User(id="usr-bhu", name="Bhumika", email="bds9746@nyu.edu",
                     password_hash=hash_password("1234"), role="junior_dev",
                     avatar_color="#22c55e"),
                User(id="usr-yas", name="Yash", email="yp2693@nyu.edu",
                     password_hash=hash_password("1234"), role="senior_dev",
                     avatar_color="#3b82f6"),
                User(id="usr-shw", name="Shweta", email="ss19623@nyu.edu",
                     password_hash=hash_password("1234"), role="team_lead",
                     avatar_color="#a855f7", is_highest_authority=True),
            ]
            for u in team:
                db.add(u)
            db.commit()
    finally:
        db.close()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
