import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models import AuditEventType, AuditStatus, RecommendationStatus, UserRole

DOMAIN_RE = re.compile(r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")


class UserOut(BaseModel):
    id: str
    email: str
    org_id: str
    organization_name: str
    role: UserRole


class AuthConfigOut(BaseModel):
    mock_auth_enabled: bool
    oidc_enabled: bool
    oidc_login_url: str | None


class SessionCreate(BaseModel):
    user_id: str = Field(min_length=1, max_length=32)


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    domain: str
    competitors: list[str] = Field(default_factory=list, max_length=10)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Project name cannot be empty")
        return value

    @field_validator("domain")
    @classmethod
    def valid_domain(cls, value: str) -> str:
        value = value.lower().strip().removeprefix("https://").removeprefix("http://").rstrip("/")
        if not DOMAIN_RE.fullmatch(value):
            raise ValueError("Enter a valid domain such as example.com")
        return value

    @field_validator("competitors")
    @classmethod
    def valid_competitors(cls, values: list[str]) -> list[str]:
        cleaned: list[str] = []
        for value in values:
            domain = (
                value.lower().strip().removeprefix("https://").removeprefix("http://").rstrip("/")
            )
            if not DOMAIN_RE.fullmatch(domain):
                raise ValueError(f"Invalid competitor domain: {value}")
            if domain not in cleaned:
                cleaned.append(domain)
        return cleaned


class AuditSummary(BaseModel):
    id: str
    status: AuditStatus
    visibility_score: int | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ProjectOut(BaseModel):
    id: str
    name: str
    domain: str
    competitors: list[str]
    created_at: datetime
    updated_at: datetime
    latest_audit: AuditSummary | None = None

    model_config = ConfigDict(from_attributes=True)


class ProjectPage(BaseModel):
    items: list[ProjectOut]
    next_cursor: str | None


class AuditPage(BaseModel):
    items: list[AuditSummary]
    next_cursor: str | None


class AuditPageOut(BaseModel):
    id: str
    url: str
    title: str
    status_code: int
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class AnalyzedPagePage(BaseModel):
    items: list[AuditPageOut]
    next_cursor: str | None


class AuditPromptOut(BaseModel):
    id: str
    prompt: str
    mentioned_brand: bool
    competitors_mentioned: list[str]
    source: str
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class AuditPromptPage(BaseModel):
    items: list[AuditPromptOut]
    next_cursor: str | None


class FindingOut(BaseModel):
    id: str
    audit_id: str
    project_id: str
    project_name: str
    severity: str
    category: str
    title: str
    description: str
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class FindingPage(BaseModel):
    items: list[FindingOut]
    next_cursor: str | None


class RecommendationOut(BaseModel):
    id: str
    audit_id: str
    priority: str
    title: str
    description: str
    status: RecommendationStatus
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


class RecommendationUpdate(BaseModel):
    status: RecommendationStatus


class RecommendationPage(BaseModel):
    items: list[RecommendationOut]
    next_cursor: str | None


class EventOut(BaseModel):
    id: str
    event_type: AuditEventType
    message: str
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class EventPage(BaseModel):
    items: list[EventOut]
    next_cursor: str | None


class AuditStatusOut(BaseModel):
    id: str
    project_id: str
    status: AuditStatus
    visibility_score: int | None
    error_message: str | None
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AuditOut(BaseModel):
    id: str
    project_id: str
    status: AuditStatus
    visibility_score: int | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    pages: list[AuditPageOut] = Field(default_factory=list)
    prompts: list[AuditPromptOut] = Field(default_factory=list)
    findings: list[FindingOut] = Field(default_factory=list)
    recommendations: list[RecommendationOut] = Field(default_factory=list)
    events: list[EventOut] = Field(default_factory=list)
    page_count: int = 0
    prompt_count: int = 0
    finding_count: int = 0
    recommendation_count: int = 0
    event_count: int = 0
    pages_next_cursor: str | None = None
    prompts_next_cursor: str | None = None
    findings_next_cursor: str | None = None
    recommendations_next_cursor: str | None = None
    events_next_cursor: str | None = None

    model_config = ConfigDict(from_attributes=True)


class ErrorDetail(BaseModel):
    code: str
    message: str
    request_id: str


class ErrorResponse(BaseModel):
    error: ErrorDetail
