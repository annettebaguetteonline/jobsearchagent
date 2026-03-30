"""Datenqualitäts-Analyse für die Job-Datenbank.

Enthält Pydantic-Modelle, Collector-Funktionen und generate_report().
Wird sowohl von scripts/data_quality_report.py (CLI) als auch von
app/api/analytics.py (API-Endpoint) importiert.
"""

from datetime import UTC, datetime
from pathlib import Path

import aiosqlite
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Pydantic-Modelle
# ---------------------------------------------------------------------------


class GeneralStats(BaseModel):
    total_jobs: int
    total_active: int
    total_expired: int
    total_companies: int
    total_sources: int
    first_seen: str | None
    last_seen: str | None
    status_breakdown: dict[str, int]


class SourceBreakdown(BaseModel):
    source_name: str
    job_count: int
    first_seen: str | None
    last_seen: str | None


class LocationQuality(BaseModel):
    jobs_with_location: int
    jobs_without_location: int
    location_coverage_pct: float
    distinct_locations: int
    plz_city_count: int
    city_only_count: int
    remote_count: int
    unparseable_count: int
    top_locations: list[dict[str, int | str]]
    per_source_coverage: list[dict[str, str | int | float]]


class CompanyQuality(BaseModel):
    total_companies: int
    address_found: int
    address_unknown: int
    address_failed: int
    with_lat_lng: int
    with_remote_policy: int


class WorkModelQuality(BaseModel):
    breakdown: dict[str, int]
    null_count: int
    null_pct: float


class SalaryQuality(BaseModel):
    with_salary_raw: int
    without_salary_raw: int
    salary_coverage_pct: float
    with_parsed_min_max: int


class RawTextQuality(BaseModel):
    with_raw_text: int
    without_raw_text: int
    raw_text_coverage_pct: float
    avg_text_length: float | None
    per_source_coverage: list[dict[str, str | int | float]]


class DuplicateAnalysis(BaseModel):
    total_jobs: int
    total_source_entries: int
    source_to_job_ratio: float
    jobs_with_multiple_sources: int
    max_sources_per_job: int


class Recommendation(BaseModel):
    category: str
    severity: str
    message: str
    affected_count: int
    affected_pct: float


class FieldStats(BaseModel):
    field: str
    null_count: int
    empty_count: int
    filled_count: int
    total: int
    coverage_pct: float


class FieldCompletenessReport(BaseModel):
    fields: list[FieldStats]


class ImputationPotentialEntry(BaseModel):
    field: str
    null_count: int
    null_with_multiple_sources: int
    null_with_raw_text: int
    rescrapable_pct: float
    llm_extractable_pct: float


class ImputationReport(BaseModel):
    fields: list[ImputationPotentialEntry]


class FilterImpactReport(BaseModel):
    stage1b_no_raw_text: int
    stage1a_no_title_no_text: int
    location_score_missing: int
    needs_reevaluation: int


class DataQualityReport(BaseModel):
    generated_at: str
    db_path: str
    general: GeneralStats
    sources: list[SourceBreakdown]
    location: LocationQuality
    companies: CompanyQuality
    work_model: WorkModelQuality
    salary: SalaryQuality
    raw_text: RawTextQuality
    duplicates: DuplicateAnalysis
    field_completeness: FieldCompletenessReport
    imputation: ImputationReport
    filter_impact: FilterImpactReport
    recommendations: list[Recommendation]


# ---------------------------------------------------------------------------
# Hilfsfunktion
# ---------------------------------------------------------------------------


async def _fetchall(db: aiosqlite.Connection, sql: str) -> list[aiosqlite.Row]:
    return list(await db.execute_fetchall(sql))


# ---------------------------------------------------------------------------
# Collector-Funktionen
# ---------------------------------------------------------------------------


async def _collect_general_stats(db: aiosqlite.Connection) -> GeneralStats:
    rows = await _fetchall(db, "SELECT COUNT(*) as n FROM jobs")
    total_jobs = int(rows[0]["n"])

    rows = await _fetchall(db, "SELECT COUNT(*) as n FROM jobs WHERE is_active = 1")
    total_active = int(rows[0]["n"])

    rows = await _fetchall(db, "SELECT COUNT(*) as n FROM jobs WHERE status = 'expired'")
    total_expired = int(rows[0]["n"])

    rows = await _fetchall(db, "SELECT COUNT(*) as n FROM companies")
    total_companies = int(rows[0]["n"])

    rows = await _fetchall(db, "SELECT COUNT(DISTINCT source_name) as n FROM job_sources")
    total_sources = int(rows[0]["n"])

    rows = await _fetchall(
        db, "SELECT MIN(first_seen_at) as first_seen, MAX(last_seen_at) as last_seen FROM jobs"
    )
    first_seen: str | None = rows[0]["first_seen"]
    last_seen: str | None = rows[0]["last_seen"]

    rows = await _fetchall(db, "SELECT status, COUNT(*) as cnt FROM jobs GROUP BY status")
    status_breakdown: dict[str, int] = {str(r["status"]): int(r["cnt"]) for r in rows}

    return GeneralStats(
        total_jobs=total_jobs,
        total_active=total_active,
        total_expired=total_expired,
        total_companies=total_companies,
        total_sources=total_sources,
        first_seen=first_seen,
        last_seen=last_seen,
        status_breakdown=status_breakdown,
    )


async def _collect_source_breakdown(db: aiosqlite.Connection) -> list[SourceBreakdown]:
    rows = await _fetchall(
        db,
        """
        SELECT s.source_name,
               COUNT(DISTINCT s.job_id) as job_count,
               MIN(s.first_seen_at) as first_seen,
               MAX(s.last_seen_at) as last_seen
        FROM job_sources s
        GROUP BY s.source_name
        ORDER BY job_count DESC
        """,
    )
    return [
        SourceBreakdown(
            source_name=str(r["source_name"]),
            job_count=int(r["job_count"]),
            first_seen=r["first_seen"],
            last_seen=r["last_seen"],
        )
        for r in rows
    ]


async def _collect_location_quality(db: aiosqlite.Connection) -> LocationQuality:
    rows = await _fetchall(
        db,
        "SELECT COUNT(*) as n FROM jobs WHERE location_raw IS NOT NULL AND location_raw != ''",
    )
    jobs_with_location = int(rows[0]["n"])

    rows = await _fetchall(
        db,
        "SELECT COUNT(*) as n FROM jobs WHERE location_raw IS NULL OR location_raw = ''",
    )
    jobs_without_location = int(rows[0]["n"])

    total = jobs_with_location + jobs_without_location
    location_coverage_pct = round(jobs_with_location / total * 100, 2) if total > 0 else 0.0

    rows = await _fetchall(
        db,
        "SELECT COUNT(DISTINCT location_raw) as n FROM jobs WHERE location_raw IS NOT NULL",
    )
    distinct_locations = int(rows[0]["n"])

    rows = await _fetchall(
        db,
        "SELECT COUNT(*) as n FROM jobs WHERE location_raw GLOB '[0-9][0-9][0-9][0-9][0-9] *'",
    )
    plz_city_count = int(rows[0]["n"])

    rows = await _fetchall(
        db,
        """
        SELECT COUNT(*) as n FROM jobs
        WHERE location_raw IS NOT NULL
          AND (location_raw LIKE '%remote%' OR location_raw LIKE '%homeoffice%'
               OR location_raw LIKE '%home office%')
        """,
    )
    remote_count = int(rows[0]["n"])

    city_only_count = max(0, jobs_with_location - plz_city_count - remote_count)
    unparseable_count = jobs_without_location

    rows = await _fetchall(
        db,
        """
        SELECT location_raw as location, COUNT(*) as cnt
        FROM jobs
        WHERE location_raw IS NOT NULL
        GROUP BY location_raw
        ORDER BY cnt DESC
        LIMIT 20
        """,
    )
    top_locations: list[dict[str, int | str]] = [
        {"location": str(r["location"]), "count": int(r["cnt"])} for r in rows
    ]

    rows = await _fetchall(
        db,
        """
        SELECT s.source_name,
               COUNT(DISTINCT j.id) as total,
               COUNT(DISTINCT CASE WHEN j.location_raw IS NOT NULL AND j.location_raw != ''
                     THEN j.id END) as with_location
        FROM job_sources s
        JOIN jobs j ON j.id = s.job_id
        GROUP BY s.source_name
        """,
    )
    per_source_coverage: list[dict[str, str | int | float]] = []
    for r in rows:
        src_total = int(r["total"])
        with_loc = int(r["with_location"]) if r["with_location"] is not None else 0
        pct = round(with_loc / src_total * 100, 2) if src_total > 0 else 0.0
        per_source_coverage.append(
            {
                "source_name": str(r["source_name"]),
                "total": src_total,
                "with_location": with_loc,
                "coverage_pct": pct,
            }
        )

    return LocationQuality(
        jobs_with_location=jobs_with_location,
        jobs_without_location=jobs_without_location,
        location_coverage_pct=location_coverage_pct,
        distinct_locations=distinct_locations,
        plz_city_count=plz_city_count,
        city_only_count=city_only_count,
        remote_count=remote_count,
        unparseable_count=unparseable_count,
        top_locations=top_locations,
        per_source_coverage=per_source_coverage,
    )


async def _collect_company_quality(db: aiosqlite.Connection) -> CompanyQuality:
    rows = await _fetchall(db, "SELECT COUNT(*) as n FROM companies")
    total_companies = int(rows[0]["n"])

    rows = await _fetchall(
        db,
        "SELECT address_status, COUNT(*) as cnt FROM companies GROUP BY address_status",
    )
    address_counts: dict[str, int] = {str(r["address_status"]): int(r["cnt"]) for r in rows}
    address_found = address_counts.get("found", 0)
    address_unknown = address_counts.get("unknown", 0)
    address_failed = address_counts.get("failed", 0)

    rows = await _fetchall(
        db,
        "SELECT COUNT(*) as n FROM companies WHERE lat IS NOT NULL AND lng IS NOT NULL",
    )
    with_lat_lng = int(rows[0]["n"])

    rows = await _fetchall(
        db,
        "SELECT COUNT(*) as n FROM companies WHERE remote_policy != 'unknown'",
    )
    with_remote_policy = int(rows[0]["n"])

    return CompanyQuality(
        total_companies=total_companies,
        address_found=address_found,
        address_unknown=address_unknown,
        address_failed=address_failed,
        with_lat_lng=with_lat_lng,
        with_remote_policy=with_remote_policy,
    )


async def _collect_work_model_quality(
    db: aiosqlite.Connection, total_jobs: int
) -> WorkModelQuality:
    rows = await _fetchall(db, "SELECT work_model, COUNT(*) as cnt FROM jobs GROUP BY work_model")
    breakdown: dict[str, int] = {}
    null_count = 0
    for r in rows:
        key = str(r["work_model"]) if r["work_model"] is not None else "null"
        cnt = int(r["cnt"])
        if r["work_model"] is None:
            null_count = cnt
        breakdown[key] = cnt

    null_pct = round(null_count / total_jobs * 100, 2) if total_jobs > 0 else 0.0

    return WorkModelQuality(breakdown=breakdown, null_count=null_count, null_pct=null_pct)


async def _collect_salary_quality(db: aiosqlite.Connection, total_jobs: int) -> SalaryQuality:
    rows = await _fetchall(
        db,
        "SELECT COUNT(*) as n FROM jobs WHERE salary_raw IS NOT NULL AND salary_raw != ''",
    )
    with_salary_raw = int(rows[0]["n"])
    without_salary_raw = total_jobs - with_salary_raw
    salary_coverage_pct = round(with_salary_raw / total_jobs * 100, 2) if total_jobs > 0 else 0.0

    rows = await _fetchall(db, "SELECT COUNT(*) as n FROM jobs WHERE salary_min IS NOT NULL")
    with_parsed_min_max = int(rows[0]["n"])

    return SalaryQuality(
        with_salary_raw=with_salary_raw,
        without_salary_raw=without_salary_raw,
        salary_coverage_pct=salary_coverage_pct,
        with_parsed_min_max=with_parsed_min_max,
    )


async def _collect_raw_text_quality(db: aiosqlite.Connection, total_jobs: int) -> RawTextQuality:
    rows = await _fetchall(
        db,
        "SELECT COUNT(*) as n FROM jobs WHERE raw_text IS NOT NULL AND raw_text != ''",
    )
    with_raw_text = int(rows[0]["n"])
    without_raw_text = total_jobs - with_raw_text
    raw_text_coverage_pct = round(with_raw_text / total_jobs * 100, 2) if total_jobs > 0 else 0.0

    rows = await _fetchall(
        db,
        "SELECT AVG(LENGTH(raw_text)) as avg_len"
        " FROM jobs WHERE raw_text IS NOT NULL AND raw_text != ''",
    )
    avg_len_raw = rows[0]["avg_len"]
    avg_text_length: float | None = (
        round(float(avg_len_raw), 1) if avg_len_raw is not None else None
    )

    rows = await _fetchall(
        db,
        """
        SELECT s.source_name,
               COUNT(DISTINCT j.id) as total,
               COUNT(DISTINCT CASE WHEN j.raw_text IS NOT NULL AND j.raw_text != ''
                     THEN j.id END) as with_text
        FROM job_sources s
        JOIN jobs j ON j.id = s.job_id
        GROUP BY s.source_name
        """,
    )
    per_source_coverage: list[dict[str, str | int | float]] = []
    for r in rows:
        src_total = int(r["total"])
        with_text = int(r["with_text"]) if r["with_text"] is not None else 0
        pct = round(with_text / src_total * 100, 2) if src_total > 0 else 0.0
        per_source_coverage.append(
            {
                "source_name": str(r["source_name"]),
                "total": src_total,
                "with_text": with_text,
                "coverage_pct": pct,
            }
        )

    return RawTextQuality(
        with_raw_text=with_raw_text,
        without_raw_text=without_raw_text,
        raw_text_coverage_pct=raw_text_coverage_pct,
        avg_text_length=avg_text_length,
        per_source_coverage=per_source_coverage,
    )


async def _collect_duplicate_analysis(
    db: aiosqlite.Connection, total_jobs: int
) -> DuplicateAnalysis:
    rows = await _fetchall(db, "SELECT COUNT(*) as n FROM job_sources")
    total_source_entries = int(rows[0]["n"])

    source_to_job_ratio = round(total_source_entries / total_jobs, 2) if total_jobs > 0 else 0.0

    rows = await _fetchall(
        db,
        "SELECT COUNT(*) as n"
        " FROM (SELECT job_id FROM job_sources GROUP BY job_id HAVING COUNT(*) > 1)",
    )
    jobs_with_multiple_sources = int(rows[0]["n"])

    rows = await _fetchall(
        db,
        "SELECT MAX(c) as mx FROM (SELECT COUNT(*) as c FROM job_sources GROUP BY job_id)",
    )
    max_raw = rows[0]["mx"]
    max_sources_per_job = int(max_raw) if max_raw is not None else 0

    return DuplicateAnalysis(
        total_jobs=total_jobs,
        total_source_entries=total_source_entries,
        source_to_job_ratio=source_to_job_ratio,
        jobs_with_multiple_sources=jobs_with_multiple_sources,
        max_sources_per_job=max_sources_per_job,
    )


async def _collect_field_completeness(
    db: aiosqlite.Connection, total_jobs: int
) -> FieldCompletenessReport:
    text_fields = {
        "work_model",
        "salary_raw",
        "location_raw",
        "deadline",
        "sector",
        "raw_text",
        "content_hash",
        "change_history",
    }
    numeric_fields = {"salary_min", "salary_max"}
    all_fields = list(text_fields) + list(numeric_fields)

    field_stats: list[FieldStats] = []
    for field in all_fields:
        rows = await _fetchall(
            db,
            f"SELECT COUNT(*) FILTER (WHERE {field} IS NULL) as null_count,"  # noqa: S608
            f"       COUNT(*) FILTER (WHERE {field} = '') as empty_count"
            " FROM jobs",
        )
        null_count = int(rows[0]["null_count"])
        empty_count = int(rows[0]["empty_count"]) if field in text_fields else 0
        filled_count = total_jobs - null_count - empty_count
        coverage_pct = round(filled_count / total_jobs * 100, 2) if total_jobs > 0 else 0.0
        field_stats.append(
            FieldStats(
                field=field,
                null_count=null_count,
                empty_count=empty_count,
                filled_count=filled_count,
                total=total_jobs,
                coverage_pct=coverage_pct,
            )
        )

    field_stats.sort(key=lambda f: f.coverage_pct)
    return FieldCompletenessReport(fields=field_stats)


async def _collect_imputation_potential(db: aiosqlite.Connection) -> ImputationReport:
    target_fields = ["work_model", "salary_raw", "location_raw", "raw_text"]
    entries: list[ImputationPotentialEntry] = []

    for field in target_fields:
        null_condition = f"(j.{field} IS NULL OR j.{field} = '')"
        has_text_col = (
            "0"
            if field == "raw_text"
            else "COUNT(*) FILTER (WHERE j.raw_text IS NOT NULL AND j.raw_text != '')"
        )
        rows = await _fetchall(
            db,
            f"""
            SELECT
                COUNT(*) as null_count,
                COUNT(*) FILTER (WHERE src_count > 1) as multi_src,
                {has_text_col} as has_text
            FROM jobs j
            JOIN (
                SELECT job_id, COUNT(*) as src_count FROM job_sources GROUP BY job_id
            ) s ON s.job_id = j.id
            WHERE {null_condition}
            """,  # noqa: S608
        )
        null_count = int(rows[0]["null_count"])
        multi_src = int(rows[0]["multi_src"])
        has_text = int(rows[0]["has_text"])
        rescrapable_pct = round(multi_src / null_count * 100, 2) if null_count > 0 else 0.0
        llm_pct = round(has_text / null_count * 100, 2) if null_count > 0 else 0.0
        entries.append(
            ImputationPotentialEntry(
                field=field,
                null_count=null_count,
                null_with_multiple_sources=multi_src,
                null_with_raw_text=has_text,
                rescrapable_pct=rescrapable_pct,
                llm_extractable_pct=llm_pct,
            )
        )

    return ImputationReport(fields=entries)


async def _collect_filter_impact(db: aiosqlite.Connection) -> FilterImpactReport:
    rows = await _fetchall(
        db,
        "SELECT COUNT(*) as n FROM jobs"
        " WHERE (raw_text IS NULL OR raw_text = '') AND is_active = 1",
    )
    stage1b_no_raw_text = int(rows[0]["n"])

    rows = await _fetchall(
        db,
        "SELECT COUNT(*) as n FROM jobs"
        " WHERE (raw_text IS NULL OR raw_text = '')"
        " AND (title IS NULL OR title = '') AND is_active = 1",
    )
    stage1a_no_title_no_text = int(rows[0]["n"])

    rows = await _fetchall(
        db,
        """
        SELECT COUNT(*) as n FROM jobs j
        LEFT JOIN companies c ON c.id = j.company_id
        WHERE j.is_active = 1 AND (c.lat IS NULL OR c.lng IS NULL)
        """,
    )
    location_score_missing = int(rows[0]["n"])

    rows = await _fetchall(
        db,
        "SELECT COUNT(*) as n FROM evaluations WHERE needs_reevaluation = 1",
    )
    needs_reevaluation = int(rows[0]["n"])

    return FilterImpactReport(
        stage1b_no_raw_text=stage1b_no_raw_text,
        stage1a_no_title_no_text=stage1a_no_title_no_text,
        location_score_missing=location_score_missing,
        needs_reevaluation=needs_reevaluation,
    )


# ---------------------------------------------------------------------------
# Empfehlungs-Logik
# ---------------------------------------------------------------------------


def _generate_recommendations(report: DataQualityReport) -> list[Recommendation]:
    recs: list[Recommendation] = []

    loc_pct = report.location.location_coverage_pct
    if loc_pct < 90.0:
        missing_sources = [
            str(s["source_name"])
            for s in report.location.per_source_coverage
            if float(s["coverage_pct"]) < 100.0
        ]
        recs.append(
            Recommendation(
                category="location",
                severity="high",
                message=(
                    f"{100 - loc_pct:.1f}% der Jobs ohne Location. "
                    f"Quellen ohne vollständige Location: {missing_sources}. "
                    "Extraktion aus raw_text empfohlen."
                ),
                affected_count=report.location.jobs_without_location,
                affected_pct=round(100 - loc_pct, 2),
            )
        )
    elif loc_pct < 95.0:
        missing_sources = [
            str(s["source_name"])
            for s in report.location.per_source_coverage
            if float(s["coverage_pct"]) < 100.0
        ]
        recs.append(
            Recommendation(
                category="location",
                severity="medium",
                message=(
                    f"{100 - loc_pct:.1f}% der Jobs ohne Location. "
                    f"Quellen ohne vollständige Location: {missing_sources}. "
                    "Extraktion aus raw_text empfohlen."
                ),
                affected_count=report.location.jobs_without_location,
                affected_pct=round(100 - loc_pct, 2),
            )
        )

    for src in report.location.per_source_coverage:
        if float(src["coverage_pct"]) == 0.0 and int(src["total"]) > 0:
            recs.append(
                Recommendation(
                    category="location",
                    severity="high",
                    message=(
                        f"Quelle '{src['source_name']}' liefert keine Locations. "
                        "Parser oder Scraper anpassen."
                    ),
                    affected_count=int(src["total"]),
                    affected_pct=100.0,
                )
            )

    wm_null_pct = report.work_model.null_pct
    wm_msg = "Work-Model-Erkennung aus raw_text implementieren (detect_work_model_from_text)"
    if wm_null_pct > 50.0:
        recs.append(
            Recommendation(
                category="work_model",
                severity="high",
                message=wm_msg,
                affected_count=report.work_model.null_count,
                affected_pct=round(wm_null_pct, 2),
            )
        )
    elif wm_null_pct > 20.0:
        recs.append(
            Recommendation(
                category="work_model",
                severity="medium",
                message=wm_msg,
                affected_count=report.work_model.null_count,
                affected_pct=round(wm_null_pct, 2),
            )
        )

    rt_pct = report.raw_text.raw_text_coverage_pct
    if rt_pct < 80.0 or rt_pct < 95.0:
        missing_sources = [
            str(s["source_name"])
            for s in report.raw_text.per_source_coverage
            if float(s["coverage_pct"]) < 100.0
        ]
        severity = "high" if rt_pct < 80.0 else "medium"
        recs.append(
            Recommendation(
                category="raw_text",
                severity=severity,
                message=(
                    f"Quellen {missing_sources} liefern keinen Volltext."
                    " Detail-Fetching verbessern."
                ),
                affected_count=report.raw_text.without_raw_text,
                affected_pct=round(100 - rt_pct, 2),
            )
        )

    for src in report.raw_text.per_source_coverage:
        if float(src["coverage_pct"]) == 0.0 and int(src["total"]) > 0:
            recs.append(
                Recommendation(
                    category="raw_text",
                    severity="medium",
                    message=f"Quelle '{src['source_name']}' liefert keinen Volltext.",
                    affected_count=int(src["total"]),
                    affected_pct=100.0,
                )
            )

    sal_pct = report.salary.salary_coverage_pct
    if sal_pct < 20.0:
        recs.append(
            Recommendation(
                category="salary",
                severity="low",
                message=(
                    f"Gehaltsdaten spärlich ({sal_pct:.1f}%). Ggf. Salary-Extraktion aus Volltext."
                ),
                affected_count=report.salary.without_salary_raw,
                affected_pct=round(100 - sal_pct, 2),
            )
        )

    total_active = report.general.total_active
    if total_active > 0:
        rt_gap_pct = report.filter_impact.stage1b_no_raw_text / total_active * 100
        if rt_gap_pct > 30.0:
            recs.append(
                Recommendation(
                    category="filter_impact",
                    severity="high",
                    message=(
                        f"{rt_gap_pct:.1f}% der aktiven Jobs haben keinen raw_text."
                        " Stage 1b LLM-Filter überspringt diese Jobs."
                    ),
                    affected_count=report.filter_impact.stage1b_no_raw_text,
                    affected_pct=round(rt_gap_pct, 2),
                )
            )
        loc_miss_pct = report.filter_impact.location_score_missing / total_active * 100
        if loc_miss_pct > 50.0:
            recs.append(
                Recommendation(
                    category="filter_impact",
                    severity="medium",
                    message=(
                        f"{loc_miss_pct:.1f}% der aktiven Jobs ohne Firmen-Koordinaten."
                        " Kein Pendel-Score berechenbar."
                    ),
                    affected_count=report.filter_impact.location_score_missing,
                    affected_pct=round(loc_miss_pct, 2),
                )
            )

    for entry in report.imputation.fields:
        if entry.field in ("work_model", "location_raw") and entry.llm_extractable_pct > 50.0:
            recs.append(
                Recommendation(
                    category="imputation",
                    severity="medium",
                    message=(
                        f"Feld '{entry.field}': {entry.llm_extractable_pct:.1f}% der Null-Jobs"
                        f" haben raw_text → LLM-Extraktion könnte {entry.null_with_raw_text}"
                        " Einträge befüllen."
                    ),
                    affected_count=entry.null_with_raw_text,
                    affected_pct=entry.llm_extractable_pct,
                )
            )

    if report.companies.total_companies > 0:
        unknown_pct = report.companies.address_unknown / report.companies.total_companies * 100
        if unknown_pct > 90.0:
            recs.append(
                Recommendation(
                    category="general",
                    severity="high",
                    message=(
                        "Firmen-Adressen fast vollständig unaufgelöst."
                        " Location Pipeline implementieren."
                    ),
                    affected_count=report.companies.address_unknown,
                    affected_pct=round(unknown_pct, 2),
                )
            )

    return recs


# ---------------------------------------------------------------------------
# Haupt-Funktion
# ---------------------------------------------------------------------------


async def generate_report(db_path: Path) -> DataQualityReport:
    """Verbinde mit DB und erstelle den vollständigen Qualitäts-Report."""
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA foreign_keys=ON")

        general = await _collect_general_stats(db)
        sources = await _collect_source_breakdown(db)
        location = await _collect_location_quality(db)
        companies = await _collect_company_quality(db)
        work_model = await _collect_work_model_quality(db, general.total_jobs)
        salary = await _collect_salary_quality(db, general.total_jobs)
        raw_text = await _collect_raw_text_quality(db, general.total_jobs)
        duplicates = await _collect_duplicate_analysis(db, general.total_jobs)
        field_completeness = await _collect_field_completeness(db, general.total_jobs)
        imputation = await _collect_imputation_potential(db)
        filter_impact = await _collect_filter_impact(db)

    report = DataQualityReport(
        generated_at=datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        db_path=str(db_path.resolve()),
        general=general,
        sources=sources,
        location=location,
        companies=companies,
        work_model=work_model,
        salary=salary,
        raw_text=raw_text,
        duplicates=duplicates,
        field_completeness=field_completeness,
        imputation=imputation,
        filter_impact=filter_impact,
        recommendations=[],
    )
    report.recommendations = _generate_recommendations(report)
    return report
