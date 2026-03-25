"""Datenqualitäts-Report für die Job-Datenbank.

Usage:
    python -m scripts.data_quality_report [--db-path ./data/jobs.db] [--output-dir ./reports/]
"""

import argparse
import asyncio
import logging
from datetime import UTC, datetime
from pathlib import Path

import aiosqlite
from pydantic import BaseModel

logger = logging.getLogger(__name__)


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
    recommendations: list[Recommendation]


# ---------------------------------------------------------------------------
# Hilfsfunktion
# ---------------------------------------------------------------------------


async def _fetchall(db: aiosqlite.Connection, sql: str) -> list[aiosqlite.Row]:
    """Execute a query and return results as a plain list."""
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

    return WorkModelQuality(
        breakdown=breakdown,
        null_count=null_count,
        null_pct=null_pct,
    )


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


# ---------------------------------------------------------------------------
# Empfehlungs-Logik
# ---------------------------------------------------------------------------


def _generate_recommendations(report: DataQualityReport) -> list[Recommendation]:
    recs: list[Recommendation] = []

    # Location coverage
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

    # Sources with 0% location coverage
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

    # Work model nulls
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

    # Raw text coverage
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

    # Sources with 0% raw text coverage
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

    # Salary coverage
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

    # Company address resolution
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
# Verbose Output Formatierung
# ---------------------------------------------------------------------------


def _print_verbose(report: DataQualityReport) -> None:
    """Formatiere und drucke den Report in lesbarem Format."""
    sep_line = "═" * 65

    # Header
    print(sep_line)
    print(f"  DATA QUALITY REPORT  —  {report.generated_at}")
    print(f"  DB: {report.db_path}")
    print(sep_line)
    print()

    # === OVERVIEW ===
    print("─ ÜBERSICHT " + "─" * 54)
    general = report.general
    print(
        f"  Jobs gesamt:    {general.total_jobs:>6,}  "
        f"(aktiv: {general.total_active:>6,}  |  "
        f"abgelaufen: {general.total_expired:>6,})"
    )
    print(f"  Firmen:         {general.total_companies:>6,}")
    print(f"  Quellen:        {general.total_sources:>6,}")
    first_str = general.first_seen or "—"
    last_str = general.last_seen or "—"
    print(f"  Zeitraum:       {first_str}  →  {last_str}")
    print()

    # === SOURCES ===
    print("─ QUELLEN " + "─" * 56)
    if report.sources:
        header = f"  {'Quelle':<18} {'Jobs':>8} {'Erste Sichtung':<18} {'Letzte Sichtung':<18}"
        print(header)
        print("  " + "─" * 63)
        for src in report.sources:
            first_str = src.first_seen or "—"
            last_str = src.last_seen or "—"
            print(f"  {src.source_name:<18} {src.job_count:>8} {first_str:<18} {last_str:<18}")
    print()

    # === LOCATION ===
    print("─ LOCATION " + "─" * 55)
    loc = report.location
    total_jobs_with_or_without = loc.jobs_with_location + loc.jobs_without_location
    print(
        f"  Abdeckung:      {loc.jobs_with_location:>6,} / {total_jobs_with_or_without:>6,}  "
        f"({loc.location_coverage_pct:>5.1f} %)"
    )
    print(f"  Distinct:       {loc.distinct_locations:>6,} verschiedene Orte")
    print(
        f"  Art:            PLZ+Stadt: {loc.plz_city_count:>6,}  |  "
        f"Nur Stadt: {loc.city_only_count:>6,}  |  "
        f"Remote: {loc.remote_count:>6,}  |  "
        f"Unklar: {loc.unparseable_count:>6,}"
    )
    print()

    # Top locations (top 10)
    if loc.top_locations:
        print("  Top-Orte (Top 10):")
        top_10 = loc.top_locations[:10]
        for item in top_10:
            print(f"    {item['location']:<30} {item['count']:>6,}")
    print()

    # Per-source location coverage
    if loc.per_source_coverage:
        print("  Pro Quelle:")
        header = f"  {'Quelle':<18} {'Gesamt':>8} {'Mit Ort':>8} {'Abdeckung':>10}"
        print(header)
        print("  " + "─" * 48)
        for src in loc.per_source_coverage:
            print(
                f"  {src['source_name']:<18} {src['total']:>8} "
                f"{src['with_location']:>8} {src['coverage_pct']:>9.1f} %"
            )
    print()

    # === COMPANIES ===
    print("─ FIRMEN " + "─" * 57)
    comp = report.companies
    print(f"  Gesamt:         {comp.total_companies:>6,}")
    print(
        f"  Adresse:        {comp.address_found:>6,} gefunden  |  "
        f"{comp.address_unknown:>6,} unbekannt  |  "
        f"{comp.address_failed:>6,} fehlgeschlagen"
    )
    print(f"  Koordinaten:    {comp.with_lat_lng:>6,} mit Lat/Lng")
    print(f"  Remote-Policy:  {comp.with_remote_policy:>6,} bekannt")
    print()

    # === WORK MODEL ===
    print("─ ARBEITSMODELL " + "─" * 50)
    wm = report.work_model
    for key, count in sorted(wm.breakdown.items()):
        if key == "null":
            pct = (count / report.general.total_jobs * 100) if report.general.total_jobs > 0 else 0
            print(f"  [kein Wert]     {count:>6,}  ({pct:>5.2f} %)")
        else:
            pct = (count / report.general.total_jobs * 100) if report.general.total_jobs > 0 else 0
            print(f"  {key:<15} {count:>6,}  ({pct:>5.2f} %)")
    print()

    # === SALARY ===
    print("─ GEHALT " + "─" * 57)
    sal = report.salary
    total_with_or_without_salary = sal.with_salary_raw + sal.without_salary_raw
    print(
        f"  Rohtext:        {sal.with_salary_raw:>6,} / {total_with_or_without_salary:>6,}  "
        f"({sal.salary_coverage_pct:>5.1f} %)"
    )
    print(f"  Min/Max:        {sal.with_parsed_min_max:>6,} geparst")
    print()

    # === RAW TEXT ===
    print("─ ROH-TEXT " + "─" * 55)
    rt = report.raw_text
    print(
        f"  Abdeckung:      {rt.with_raw_text:>6,} / {rt.with_raw_text + rt.without_raw_text:>6,}  "
        f"({rt.raw_text_coverage_pct:>5.1f} %)"
    )
    avg_str = f"{rt.avg_text_length:,.0f}" if rt.avg_text_length is not None else "—"
    print(f"  Ø Länge:        {avg_str:>6} Zeichen")
    print()

    # Per-source raw text coverage
    if rt.per_source_coverage:
        print("  Pro Quelle:")
        header = f"  {'Quelle':<18} {'Gesamt':>8} {'Mit Text':>8} {'Abdeckung':>10}"
        print(header)
        print("  " + "─" * 48)
        for src in rt.per_source_coverage:
            print(
                f"  {src['source_name']:<18} {src['total']:>8} "
                f"{src['with_text']:>8} {src['coverage_pct']:>9.1f} %"
            )
    print()

    # === DUPLICATES ===
    print("─ DUPLIKATE " + "─" * 54)
    dup = report.duplicates
    print(f"  Jobs:           {dup.total_jobs:>6,}")
    print(f"  Quell-Einträge: {dup.total_source_entries:>6,}")
    print(f"  Ratio:          {dup.source_to_job_ratio:>6.2f} Quellen/Job")
    print(
        f"  Multi-Source:   {dup.jobs_with_multiple_sources:>6,} Jobs  "
        f"(max. {dup.max_sources_per_job} Quellen pro Job)"
    )
    print()

    # === RECOMMENDATIONS ===
    if report.recommendations:
        print("─ EMPFEHLUNGEN " + "─" * 51)
        # Sort by severity (HIGH > MEDIUM > LOW)
        severity_order = {"high": 0, "medium": 1, "low": 2}
        sorted_recs = sorted(
            report.recommendations, key=lambda r: (severity_order.get(r.severity, 3), r.category)
        )

        for rec in sorted_recs:
            severity_label = rec.severity.upper()
            if len(severity_label) == 3:
                severity_label = f"{severity_label} "
            print(
                f"  [{severity_label}]  {rec.category:<12} "
                f"{rec.affected_pct:>5.1f}% ({rec.affected_count:>6,} Jobs)"
            )
            print(f"           {rec.message}")
        print()


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
        recommendations=[],
    )
    report.recommendations = _generate_recommendations(report)
    return report


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Datenqualitäts-Report für die Job-Datenbank")
    parser.add_argument("--db-path", type=Path, default=Path("./data/jobs.db"))
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("-v", "--verbose", action="store_true", help="Lesbarer Report statt JSON")
    args = parser.parse_args()

    if not args.db_path.exists():
        logger.error("DB nicht gefunden: %s", args.db_path)
        raise SystemExit(1)

    logger.info("Analysiere Datenbank: %s", args.db_path)
    report = await generate_report(args.db_path)

    json_output = report.model_dump_json(indent=2)
    if args.verbose:
        _print_verbose(report)
    else:
        print(json_output)

    if args.output_dir:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(UTC).strftime("%Y-%m-%d")
        out = args.output_dir / f"data_quality_{ts}.json"
        out.write_text(json_output)
        logger.info("Report gespeichert: %s", out)


if __name__ == "__main__":
    asyncio.run(main())
