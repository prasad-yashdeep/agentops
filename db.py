"""Database models and setup."""
import uuid
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


class Incident(Base):
    __tablename__ = "incidents"

    id = Column(String, primary_key=True, default=gen_id)
    title = Column(String, nullable=False)
    description = Column(Text, default="")
    severity = Column(String, default="medium")  # low, medium, high, critical
    status = Column(String, default="detected")
    # detected -> diagnosing -> fix_proposed -> awaiting_approval -> approved -> deploying -> resolved | rejected
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


class Approval(Base):
    __tablename__ = "approvals"

    id = Column(String, primary_key=True, default=gen_id)
    incident_id = Column(String, nullable=False)
    user_name = Column(String, nullable=False)
    action = Column(String, nullable=False)  # approve, reject, request_changes, override
    comment = Column(Text, default="")
    created_at = Column(DateTime, default=utcnow)


class Comment(Base):
    __tablename__ = "comments"

    id = Column(String, primary_key=True, default=gen_id)
    incident_id = Column(String, nullable=False)
    user_name = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=utcnow)


class LearningRecord(Base):
    __tablename__ = "learning_records"

    id = Column(String, primary_key=True, default=gen_id)
    incident_type = Column(String, nullable=False)
    error_pattern = Column(Text, nullable=False)
    proposed_fix_pattern = Column(Text, nullable=False)
    human_decision = Column(String, nullable=False)  # approved, rejected, modified
    confidence_adjustment = Column(Float, default=0.0)
    created_at = Column(DateTime, default=utcnow)


class ActivityLog(Base):
    __tablename__ = "activity_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    incident_id = Column(String, nullable=True)
    actor = Column(String, nullable=False)  # "agent" or user name
    action = Column(String, nullable=False)
    detail = Column(Text, default="")
    created_at = Column(DateTime, default=utcnow)


def init_db():
    Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
