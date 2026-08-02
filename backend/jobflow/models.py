from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


Rating = Literal["good", "maybe", "bad"]
JobStatus = Literal["inbox", "good", "maybe", "bad"]


class FeedbackOut(BaseModel):
    rating: Rating
    reasons: list[str] = Field(default_factory=list)
    note: str = ""
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


class FeedbackIn(BaseModel):
    rating: Rating
    reasons: list[str] = Field(default_factory=list, max_length=8)
    note: str = Field(default="", max_length=1200)


class JobIngestIn(BaseModel):
    source_url: str = Field(min_length=1)
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
    priorities: list[str] = Field(default_factory=list)
    hard_rules: list[str] = Field(default_factory=list)
    language_preference: str | None = None
    application_language: str | None = None
    manual_submission_only: bool = True
    updated_at: str | None = None


class ActivityItem(BaseModel):
    id: str
    kind: str
    title: str
    body: str = ""
    job_id: str | None = None
    created_at: str
