from pydantic import BaseModel, field_validator, EmailStr, Field
from typing import Optional, List, Any
from datetime import datetime


# ─── Auth ──────────────────────────────────────────────
class LoginRequest(BaseModel):
    email: str = Field(..., max_length=255)
    password: str = Field(..., max_length=256)

class LoginResponse(BaseModel):
    message: str
    user: dict

class UserResponse(BaseModel):
    id: int
    email: str
    full_name: Optional[str] = None
    role: Optional[str] = None
    department: Optional[str] = None
    status: Optional[str] = None

# ─── Password Reset ────────────────────────────────────
class ForgotPasswordRequest(BaseModel):
    email: str = Field(..., max_length=255)

class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def password_min_length(cls, v: str) -> str:
        if len(v) < 12:
            raise ValueError("Le mot de passe doit contenir au moins 12 caractères")
        return v

# ─── Chat ──────────────────────────────────────────────
class ChatRequest(BaseModel):
    message: str = Field(..., max_length=4000)
    session_id: Optional[str] = Field(None, max_length=64)

class ChatResponse(BaseModel):
    reply: str
    session_id: str
    guide_card: Optional[dict] = None
    sources: Optional[List[str]] = None   # KB source IDs used (empty when Groq answered freely)

# ─── Feedback ──────────────────────────────────────────
class FeedbackRequest(BaseModel):
    message_id: int
    rating: str
    reason: Optional[str] = None

class FeedbackResponse(BaseModel):
    status: str
    message: str

# ─── Sessions / History ────────────────────────────────
class SessionResponse(BaseModel):
    id: str
    title: str
    created_at: datetime
    updated_at: Optional[datetime] = None

class MessageResponse(BaseModel):
    id: int
    sender: str
    text: str
    feedback: Optional[str] = None
    created_at: datetime

# ─── Jira ──────────────────────────────────────────────
class JiraTicketRequest(BaseModel):
    summary: str
    description: str
    priority: Optional[str] = "Medium"

class JiraTicketResponse(BaseModel):
    key: str
    status: str
    url: Optional[str] = None

# ─── Terminal ──────────────────────────────────────────
class TerminalRequest(BaseModel):
    command: str = Field(..., max_length=2000)
    async_exec: Optional[bool] = False

class TerminalResponse(BaseModel):
    output: str
    exit_code: int
    execution_id: Optional[str] = None

# ─── Admin ─────────────────────────────────────────────
class ConfigUpdate(BaseModel):
    key: str
    value: Any

class ServiceRestart(BaseModel):
    service_id: str

# ─── Admin Users ───────────────────────────────────────
class AdminUserResponse(BaseModel):
    id: int
    name: Optional[str] = None
    email: str
    role: str
    status: str
    department: Optional[str] = None
    last_login: Optional[str] = None
    created_at: datetime

class CreateUserRequest(BaseModel):
    name: str
    email: str
    password: str
    role: Optional[str] = "user"
    department: Optional[str] = None

    @field_validator("password")
    @classmethod
    def password_min_length(cls, v: str) -> str:
        if len(v) < 12:
            raise ValueError("Le mot de passe doit contenir au moins 12 caractères")
        return v

class UpdateUserRequest(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    role: Optional[str] = None
    status: Optional[str] = None
    department: Optional[str] = None

# ─── User Profile / Settings ──────────────────────────
class UpdateProfileRequest(BaseModel):
    full_name: Optional[str] = None
    department: Optional[str] = None
    language: Optional[str] = None

class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def password_min_length(cls, v: str) -> str:
        if len(v) < 12:
            raise ValueError("Le nouveau mot de passe doit contenir au moins 12 caractères")
        return v

# ─── Admin Maintenance ─────────────────────────────────
class MaintenanceActionResponse(BaseModel):
    status: str
    message: str
    details: Optional[dict] = None

# ─── Admin Dashboard Stats ─────────────────────────────
class DashboardStatsResponse(BaseModel):
    total_users: int
    active_sessions_today: int
    total_messages: int
    total_incidents: int
    recent_activity: List[dict]
