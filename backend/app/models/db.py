from datetime import datetime, timezone
from sqlalchemy import Column, String, Integer, DateTime, Text, JSON, ForeignKey, Boolean
from sqlalchemy.orm import relationship, declarative_base

_now = lambda: datetime.now(timezone.utc)

Base = declarative_base()


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    full_name = Column(String(255))
    hashed_password = Column(String(255), nullable=False)
    role = Column(String(20), default="user")
    department = Column(String(100), nullable=True)
    status = Column(String(20), default="active")
    last_login = Column(DateTime, nullable=True)
    failed_attempts = Column(Integer, default=0, nullable=False)
    locked_until = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime, default=_now)

    sessions = relationship("Session", back_populates="user")


class Session(Base):
    __tablename__ = "sessions"

    id = Column(String(36), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    title = Column(String(255), default="Nouvelle conversation")
    created_at = Column(DateTime, default=_now, index=True)
    updated_at = Column(DateTime, default=_now, onupdate=_now)

    user = relationship("User", back_populates="sessions")
    messages = relationship("Message", back_populates="session", cascade="all, delete-orphan")


class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(String(36), ForeignKey("sessions.id"), nullable=False)
    sender = Column(String(10), nullable=False, index=True)
    text = Column(Text, nullable=False)
    attachments = Column(JSON, nullable=True)
    guide_card = Column(JSON, nullable=True)
    feedback = Column(String(10), nullable=True)
    created_at = Column(DateTime, default=_now, index=True)

    session = relationship("Session", back_populates="messages")


class Incident(Base):
    __tablename__ = "incidents"

    id = Column(Integer, primary_key=True, index=True)
    incident_type = Column(String(100), unique=True, nullable=False, index=True)
    count = Column(Integer, default=1)
    last_seen = Column(DateTime, default=_now)


class Feedback(Base):
    __tablename__ = "feedback"

    id = Column(Integer, primary_key=True, index=True)
    message_id = Column(Integer, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    rating = Column(String(10), nullable=False, index=True)
    reason = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=_now)


class JiraTicket(Base):
    __tablename__ = "jira_tickets"

    id = Column(Integer, primary_key=True, index=True)
    key = Column(String(20), unique=True, nullable=False)
    summary = Column(String(500), nullable=False)
    description = Column(Text, nullable=True)
    priority = Column(String(20), nullable=True, default="Medium")
    status = Column(String(50), nullable=False, default="Created")
    url = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=_now)


class PlatformSetting(Base):
    __tablename__ = "platform_settings"

    section = Column(String(100), primary_key=True)
    data = Column(JSON, nullable=False, default=dict)
    updated_at = Column(DateTime, default=_now, onupdate=_now)


class MaintenanceTask(Base):
    __tablename__ = "maintenance_tasks"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    status = Column(String(50), nullable=False, default="Programmée")
    schedule = Column(String(255), nullable=True)
    last_run = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_now)


class IncidentGuide(Base):
    __tablename__ = "incident_guides"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(500), nullable=False)
    description = Column(Text, nullable=True)
    category = Column(String(50), nullable=False, default="Infrastructure")
    severity = Column(String(5), nullable=False, default="P2")
    status = Column(String(20), nullable=False, default="Ouvert")
    tags = Column(JSON, nullable=True)
    generated_from = Column(String(255), nullable=True)
    is_draft = Column(Boolean, default=False)
    triggered_by = Column(String(255), nullable=True)
    occurrences = Column(Integer, default=1)
    review_note = Column(Text, nullable=True)
    specs = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"

    id = Column(Integer, primary_key=True, index=True)
    token = Column(String(64), unique=True, nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    expires_at = Column(DateTime, nullable=False)
    used = Column(Boolean, default=False)
    created_at = Column(DateTime, default=_now)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    action = Column(String(100), nullable=False)
    resource = Column(String(100), nullable=True)
    detail = Column(Text, nullable=True)
    ip_address = Column(String(45), nullable=True)
    created_at = Column(DateTime, default=_now, index=True)
