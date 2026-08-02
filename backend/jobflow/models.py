from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


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
    fit_evidence: dict[str, list[EvidenceItem]] = Field(default_factory=dict)
    source_evidence: dict[str, list[str]] = Field(default_factory=dict)
    hard_gate_reasons: list[str] = Field(default_factory=list)
    requirements: list[str] = Field(default_factory=list)
    responsibilities: list[str] = Field(default_factory=list)
    technologies: list[str] = Field(default_factory=list)
    salary_min_annual: int | None = None
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
