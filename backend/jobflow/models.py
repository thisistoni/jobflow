from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, SecretStr, field_validator, model_validator


Rating = Literal["good", "maybe", "bad"]
JobStatus = Literal["inbox", "good", "maybe", "bad"]


class FeedbackOut(BaseModel):
    rating: Rating
    reasons: list[str] = Field(default_factory=list)
    note: str = ""
    updated_at: str


class ApplicationPackOut(BaseModel):
    status: Literal["preparing", "ready", "failed"]
    resume_id: str | None = None
    resume_name: str | None = None
    resume_pdf_pages: int | None = None
    letter_subject: str | None = None
    letter_body: str | None = None
    error: str | None = None
    updated_at: str


class JobListItem(BaseModel):
    id: str
    title: str
    company: str
    location: str | None = None
    score: int | None = None
    verdict: str | None = None
    confidence: str | None = None
    status: JobStatus
    summary: str | None = None
    salary_display: str | None = None
    work_mode: str | None = None
    missing_info: list[str] = Field(default_factory=list)
    source_url: str
    feedback: FeedbackOut | None = None
    pack_status: Literal["preparing", "ready", "failed"] | None = None


class EvidenceItem(BaseModel):
    origin: str | None = None
    text: str
    profile_fact_ref: str | None = None


class JobDetail(JobListItem):
    source_name: str | None = None
    raw_description: str | None = None
    extracted_description: str | None = None
    fit_evidence: dict[str, list[EvidenceItem]] = Field(default_factory=dict)
    source_evidence: dict[str, list[str]] = Field(default_factory=dict)
    hard_gate_reasons: list[str] = Field(default_factory=list)
    requirements: list[str] = Field(default_factory=list)
    responsibilities: list[str] = Field(default_factory=list)
    technologies: list[str] = Field(default_factory=list)
    salary_min_annual: int | None = None
    salary_max_annual: int | None = None
    salary_currency: str | None = None
    home_office_days: int | None = None
    language_environment: str | None = None
    imported_state: str | None = None
    first_seen_at: str
    updated_at: str
    reviewed_at: str | None = None
    application_pack: ApplicationPackOut | None = None


class FeedbackIn(BaseModel):
    rating: Rating
    reasons: list[str] = Field(default_factory=list, max_length=8)
    note: str = Field(default="", max_length=1200)


class JobIngestIn(BaseModel):
    source_url: str = Field(min_length=1)
    source_id: str | None = Field(default=None, max_length=120)
    title: str = Field(min_length=1, max_length=500)
    company: str = Field(min_length=1, max_length=300)
    location: str | None = Field(default=None, max_length=300)
    description: str | None = None
    raw_description: str | None = None
    extracted_description: str | None = None
    source_name: str | None = Field(default=None, max_length=120)
    first_seen_at: str | None = None

    @field_validator("title", "company", "location", "source_name", mode="before")
    @classmethod
    def clean_short_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = " ".join(str(value).split())
        return text or None

    @model_validator(mode="after")
    def copy_description(self) -> "JobIngestIn":
        if self.description and not self.extracted_description:
            self.extracted_description = self.description
        return self


class JobAnalysisIn(BaseModel):
    score: int = Field(ge=0, le=100)
    verdict: str = Field(min_length=1, max_length=80)
    confidence: str | None = Field(default=None, max_length=80)
    summary: str | None = None
    fit_evidence: dict[str, list[EvidenceItem]] = Field(default_factory=dict)
    missing_info: list[str] = Field(default_factory=list)
    hard_gate_reasons: list[str] = Field(default_factory=list)
    requirements: list[str] = Field(default_factory=list)
    responsibilities: list[str] = Field(default_factory=list)
    technologies: list[str] = Field(default_factory=list)
    salary_display: str | None = None
    salary_min_annual: int | None = Field(default=None, ge=0)
    salary_max_annual: int | None = Field(default=None, ge=0)
    salary_currency: str | None = Field(default=None, max_length=12)
    work_mode: str | None = Field(default=None, max_length=80)
    home_office_days: int | None = Field(default=None, ge=0, le=7)
    language_environment: str | None = Field(default=None, max_length=120)
    source_evidence: dict[str, list[str]] = Field(default_factory=dict)


class Preferences(BaseModel):
    target_locations: list[str] = Field(default_factory=list)
    work_modes: list[str] = Field(default_factory=list)
    min_home_office_days: int | None = Field(default=None, ge=0, le=7)
    salary_currency: str = "EUR"
    salary_target_min: int | None = Field(default=None, ge=0)
    salary_target_max: int | None = Field(default=None, ge=0)
    acceptable_salary_min: int | None = Field(default=None, ge=0)
    role_families: list[str] = Field(default_factory=list)
    priority_role_families: list[str] = Field(default_factory=list)
    priorities: list[str] = Field(default_factory=list)
    hard_rules: list[str] = Field(default_factory=list)
    discovery_queries: list[str] = Field(default_factory=list)
    discovery_limit_per_query: int = Field(default=5, ge=1, le=20)
    language_preference: str | None = None
    application_language: str | None = None
    manual_submission_only: bool = True
    updated_at: str | None = None

    @model_validator(mode="after")
    def require_manual_submission(self) -> "Preferences":
        if not self.manual_submission_only:
            raise ValueError("JobFlow requires explicit approval before external applications")
        return self


class ActivityItem(BaseModel):
    id: str
    kind: str
    title: str
    body: str = ""
    job_id: str | None = None
    created_at: str


class DailyPulseItem(BaseModel):
    date: str
    count: int = Field(ge=0)


class DashboardPulseOut(BaseModel):
    days: list[DailyPulseItem]
    today_count: int = Field(ge=0)


class DiscoverySearchIn(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    limit: int = Field(default=5, ge=1, le=20)

    @field_validator("query", mode="before")
    @classmethod
    def clean_query(cls, value: str) -> str:
        return " ".join(str(value).split())


class DiscoveryScrapeIn(BaseModel):
    url: str = Field(min_length=1)

    @field_validator("url", mode="before")
    @classmethod
    def clean_url(cls, value: str) -> str:
        return str(value).strip()


class DiscoverySearchResult(BaseModel):
    url: str
    title: str
    description: str = ""


class DiscoveryRunResult(DiscoverySearchResult):
    source: str = "open_web"
    matched_queries: list[str] = Field(default_factory=list)


class DiscoveryRunOut(BaseModel):
    run_id: str
    queries: list[str]
    limit_per_query: int
    results: list[DiscoveryRunResult]
    jobs_added: int = 0
    jobs_evaluated: int = 0
    packs_prepared: int = 0


class DiscoverySourceConfig(BaseModel):
    id: str
    label: str
    enabled: bool
    status: Literal["available", "setup_required", "manual", "disabled", "failing"]
    detail: str = ""


class DiscoveryScheduleConfig(BaseModel):
    enabled: bool = True
    timezone: str = "Europe/Vienna"
    times: list[str] = Field(default_factory=lambda: ["07:00", "13:00", "19:00"])

    @field_validator("times", mode="before")
    @classmethod
    def clean_times(cls, value: object) -> list[str]:
        values = value if isinstance(value, list) else []
        cleaned: list[str] = []
        for item in values:
            text = str(item).strip()
            parts = text.split(":")
            if len(parts) != 2 or not all(part.isdigit() for part in parts):
                raise ValueError("Schedule times must use HH:MM")
            hour, minute = (int(part) for part in parts)
            if not 0 <= hour <= 23 or not 0 <= minute <= 59:
                raise ValueError("Schedule times must use HH:MM")
            normalized = f"{hour:02d}:{minute:02d}"
            if normalized not in cleaned:
                cleaned.append(normalized)
        if not cleaned:
            raise ValueError("At least one discovery time is required")
        return sorted(cleaned)


class DiscoveryConfigIn(BaseModel):
    schedule: DiscoveryScheduleConfig
    sources_enabled: dict[str, bool] = Field(default_factory=dict)


class DiscoveryRunSummary(BaseModel):
    id: str
    trigger: Literal["manual", "scheduled"]
    status: Literal["running", "succeeded", "failed"]
    started_at: str
    finished_at: str | None = None
    queries: list[str] = Field(default_factory=list)
    candidate_count: int = 0
    unique_count: int = 0
    jobs_added: int = 0
    jobs_evaluated: int = 0
    packs_prepared: int = 0
    error: str | None = None


class DiscoveryOperationsOut(BaseModel):
    schedule: DiscoveryScheduleConfig
    sources: list[DiscoverySourceConfig]
    generated_queries: list[str]
    next_run_at: str | None = None
    last_run: DiscoveryRunSummary | None = None
    recent_runs: list[DiscoveryRunSummary] = Field(default_factory=list)


class ReactiveResumeReference(BaseModel):
    id: str
    name: str
    template: str | None = None
    updated_at: str | None = None


class ReactiveResumeOption(BaseModel):
    id: str
    name: str
    updated_at: str | None = None
    historical_source: bool = False


class ReactiveResumeStatus(BaseModel):
    encryption_ready: bool
    configured: bool
    verified: bool
    base_url: str
    configured_at: str | None = None
    last_verified_at: str | None = None
    last_error: str | None = None
    reference: ReactiveResumeReference | None = None
    available_resumes: list[ReactiveResumeOption] = Field(default_factory=list)


class ReactiveResumeConnectIn(BaseModel):
    api_key: SecretStr
    base_url: str = "https://rxresu.me/api/openapi"


class ReactiveResumeReferenceIn(BaseModel):
    resume_id: str = Field(min_length=1, max_length=200)


class DiscoveryScrapeResult(BaseModel):
    url: str
    markdown: str
    metadata: dict[str, object] = Field(default_factory=dict)
