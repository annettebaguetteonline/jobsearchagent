"""Datenqualitäts-Report für die Job-Datenbank (CLI-Wrapper).

Die eigentliche Analyse-Logik liegt in app/db/quality.py.

Usage:
    python -m scripts.data_quality_report [--db-path ./data/jobs.db] [--output-dir ./reports/]
"""

import argparse
import asyncio
import logging
from datetime import UTC, datetime
from pathlib import Path

from app.db.quality import (
    DataQualityReport,
    generate_report,
)

logger = logging.getLogger(__name__)

# Re-export für Backwards-Kompatibilität (andere Skripte die direkt importieren)
__all__ = ["DataQualityReport", "generate_report"]


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

    if loc.top_locations:
        print("  Top-Orte (Top 10):")
        for item in loc.top_locations[:10]:
            print(f"    {item['location']:<30} {item['count']:>6,}")
    print()

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
        pct = (count / report.general.total_jobs * 100) if report.general.total_jobs > 0 else 0
        label = "[kein Wert]    " if key == "null" else f"{key:<15}"
        print(f"  {label} {count:>6,}  ({pct:>5.2f} %)")
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

    # === FIELD COMPLETENESS ===
    print("─ FELDVOLLSTÄNDIGKEIT " + "─" * 44)
    fc = report.field_completeness
    header = f"  {'Feld':<18} {'Abdeckung':>10} {'NULL':>8} {'Leer':>8} {'Befüllt':>10}"
    print(header)
    print("  " + "─" * 58)
    for f in fc.fields:
        null_pct = round(f.null_count / f.total * 100, 1) if f.total > 0 else 0.0
        empty_pct = round(f.empty_count / f.total * 100, 1) if f.total > 0 else 0.0
        print(
            f"  {f.field:<18} {f.coverage_pct:>9.1f}%"
            f" {f.null_count:>6,} ({null_pct:>4.1f}%)"
            f" {f.empty_count:>4,} ({empty_pct:>4.1f}%)"
            f" {f.filled_count:>8,}"
        )
    print()

    # === IMPUTATION POTENTIAL ===
    print("─ IMPUTATIONS-POTENTIAL " + "─" * 42)
    imp = report.imputation
    header = f"  {'Feld':<18} {'NULL':>8} {'Re-Scraping':>12} {'LLM-Extraktion':>16}"
    print(header)
    print("  " + "─" * 58)
    for e in imp.fields:
        print(
            f"  {e.field:<18} {e.null_count:>8,}"
            f" {e.null_with_multiple_sources:>6,} ({e.rescrapable_pct:>5.1f}%)"
            f" {e.null_with_raw_text:>8,} ({e.llm_extractable_pct:>5.1f}%)"
        )
    print()

    # === FILTER IMPACT ===
    print("─ FILTER-IMPACT " + "─" * 50)
    fi = report.filter_impact
    total_active = report.general.total_active
    stage1b_pct = round(fi.stage1b_no_raw_text / total_active * 100, 1) if total_active > 0 else 0.0
    loc_pct_fi = (
        round(fi.location_score_missing / total_active * 100, 1) if total_active > 0 else 0.0
    )
    print(
        f"  Stage 1b (kein raw_text):   {fi.stage1b_no_raw_text:>6,} "
        f" ({stage1b_pct:>5.1f}% der aktiven Jobs)"
    )
    print(f"  Stage 1a (kein Inhalt):     {fi.stage1a_no_title_no_text:>6,}")
    print(
        f"  Kein Pendel-Score:          {fi.location_score_missing:>6,} "
        f" ({loc_pct_fi:>5.1f}% der aktiven Jobs)"
    )
    print(f"  Re-Evaluation nötig:        {fi.needs_reevaluation:>6,}")
    print()

    # === RECOMMENDATIONS ===
    if report.recommendations:
        print("─ EMPFEHLUNGEN " + "─" * 51)
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
