"""Pydantic-Modelle für die Datenbankentitäten.

Nur die Entitäten die aktuell benötigt werden (Jobs, Quellen,
Unternehmen, User, Scrape-Runs). Evaluierungen, Anschreiben usw. folgen später.
"""

from datetime import UTC, datetime

from pydantic import BaseModel

# ─── Unternehmen ──────────────────────────────────────────────────────────────


class CompanyCreate(BaseModel):
    name: str
    name_normalized: str


class Company(CompanyCreate):
    id: int
    address_status: str = "unknown"
    remote_policy: str = "unknown"
    created_at: str
    updated_at: str


# ─── User ─────────────────────────────────────────────────────────────────────


class UserCreate(BaseModel):
    id: str  # UUID als Text, vom Aufrufer generiert
    name: str
    surname: str | None = None
    profile_json: str | None = None  # Kernprofil-JSON
    profile_version: str | None = None  # SHA256 des Profils
    folder: str | None = None  # Pfad zu User-Dokumenten


class User(UserCreate):
    created_at: str
    updated_at: str


# ─── Stellen ──────────────────────────────────────────────────────────────────


class JobCreate(BaseModel):
    canonical_id: str
    title: str
    company_id: int | None = None
    location_raw: str | None = None
    location_status: str = "unknown"
    work_model: str | None = None
    salary_raw: str | None = None
    salary_min: int | None = None
    salary_max: int | None = None
    deadline: str | None = None
    first_seen_at: str
    last_seen_at: str
    status: str = "new"
    is_active: bool = True
    content_hash: str | None = None
    raw_text: str | None = None
    sector: str | None = None  # 'public'|'private'|None


class Job(JobCreate):
    id: int
    change_history: str | None = None
    created_at: str
    updated_at: str


# ─── Quellen ──────────────────────────────────────────────────────────────────


class JobSourceCreate(BaseModel):
    job_id: int
    url: str
    source_name: str
    source_type: str
    is_canonical: bool = False
    first_seen_at: str
    last_seen_at: str
    source_job_id: str | None = None  # Quell-native Job-ID für Stage-0-Dedup


class JobSource(JobSourceCreate):
    id: int
    last_checked_at: str | None = None
    is_available: bool | None = None
    content_hash: str | None = None


# ─── Scrape-Runs ──────────────────────────────────────────────────────────────


class ScrapeRunStats(BaseModel):
    fetched: int = 0
    new: int = 0
    duplicate: int = 0
    skipped: int = 0
    errors: int = 0
    expired: int = 0  # nach dem Run als abgelaufen markierte Jobs


class ScrapeRun(BaseModel):
    id: int
    started_at: str
    finished_at: str | None = None
    status: str
    sources_run: list[str] | None = None
    stats: ScrapeRunStats | None = None
    error_log: list[str] | None = None


def now_iso() -> str:
    """Aktueller UTC-Zeitstempel als ISO-8601-String."""
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
