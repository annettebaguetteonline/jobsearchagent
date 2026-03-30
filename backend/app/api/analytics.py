"""Analytics-API: Voraggregierte Daten für Dashboard-Charts."""

import logging

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.core.config import settings
from app.db.database import get_db
from app.db.quality import DataQualityReport

logger = logging.getLogger(__name__)
router = APIRouter()


# ─── Response-Modelle ────────────────────────────────────────────────────────


class FunnelStep(BaseModel):
    stage: str
    count: int


class FunnelResponse(BaseModel):
    steps: list[FunnelStep]


class SalaryBin(BaseModel):
    range_start: int
    range_end: int
    count: int


class SalaryDistributionResponse(BaseModel):
    bins: list[SalaryBin]
    total_with_salary: int
    total_without_salary: int


class SourceScore(BaseModel):
    source_name: str
    avg_score: float
    job_count: int


class SourceScoresResponse(BaseModel):
    sources: list[SourceScore]


class SkillTrend(BaseModel):
    skill: str
    period: str
    count: int


class SkillTrendsResponse(BaseModel):
    trends: list[SkillTrend]
    top_skills: list[str]


class NetworkNode(BaseModel):
    id: str
    count: int
    skill_type: str | None = None


class NetworkLink(BaseModel):
    source: str
    target: str
    weight: int


class SkillNetworkResponse(BaseModel):
    nodes: list[NetworkNode]
    links: list[NetworkLink]


class CalibrationEntry(BaseModel):
    strategy: str
    avg_score_delta: float
    sample_count: int
    avg_model_score: float


class CalibrationResponse(BaseModel):
    entries: list[CalibrationEntry]


# ─── Endpoints ──────────────────────────────────────────────────────────────


@router.get("/funnel")
async def get_funnel(user_id: str) -> FunnelResponse:
    """Pipeline-Funnel: Gefunden → Evaluiert → Stage1 → Stage2 → Beworben → Interview."""
    async for db in get_db():
        steps: list[FunnelStep] = []

        # Gesamt aktive Jobs
        cur = await db.execute("SELECT COUNT(*) as cnt FROM jobs WHERE is_active = 1")
        row = await cur.fetchone()
        steps.append(FunnelStep(stage="Gefunden", count=row["cnt"] if row else 0))

        # Evaluiert
        cur = await db.execute(
            "SELECT COUNT(*) as cnt FROM evaluations WHERE user_id = ?", (user_id,)
        )
        row = await cur.fetchone()
        steps.append(FunnelStep(stage="Evaluiert", count=row["cnt"] if row else 0))

        # Stage 1 bestanden
        cur = await db.execute(
            "SELECT COUNT(*) as cnt FROM evaluations WHERE user_id = ? AND stage1_pass = 1",
            (user_id,),
        )
        row = await cur.fetchone()
        steps.append(FunnelStep(stage="Stage 1 bestanden", count=row["cnt"] if row else 0))

        # Stage 2 bewertet
        cur = await db.execute(
            "SELECT COUNT(*) as cnt FROM evaluations"
            " WHERE user_id = ? AND stage2_score IS NOT NULL",
            (user_id,),
        )
        row = await cur.fetchone()
        steps.append(FunnelStep(stage="Stage 2 bewertet", count=row["cnt"] if row else 0))

        # Status-basierte Stufen
        for stage_name, statuses in [
            ("Beworben", ("applying", "applied")),
            ("Interview", ("interview",)),
            ("Angebot", ("offer",)),
        ]:
            placeholders = ",".join("?" for _ in statuses)
            cur = await db.execute(
                f"SELECT COUNT(*) as cnt FROM jobs"  # noqa: S608
                f" WHERE status IN ({placeholders})",
                statuses,
            )
            row = await cur.fetchone()
            steps.append(FunnelStep(stage=stage_name, count=row["cnt"] if row else 0))

        return FunnelResponse(steps=steps)
    raise RuntimeError("Keine Datenbankverbindung verfügbar")


@router.get("/salary-distribution")
async def get_salary_distribution(
    bin_size: int = Query(default=10000, ge=1000, le=50000),
) -> SalaryDistributionResponse:
    """Gehaltsverteilung als Histogram-Bins."""
    async for db in get_db():
        cur = await db.execute(
            """
            SELECT
                CAST((COALESCE(salary_min, salary_max) / ?) * ? AS INTEGER) as range_start,
                COUNT(*) as cnt
            FROM jobs
            WHERE (salary_min IS NOT NULL OR salary_max IS NOT NULL)
              AND is_active = 1
            GROUP BY range_start
            ORDER BY range_start
            """,
            (bin_size, bin_size),
        )
        rows = await cur.fetchall()

        bins = [
            SalaryBin(
                range_start=r["range_start"],
                range_end=r["range_start"] + bin_size,
                count=r["cnt"],
            )
            for r in rows
        ]

        cur = await db.execute(
            "SELECT COUNT(*) as cnt FROM jobs"
            " WHERE (salary_min IS NOT NULL OR salary_max IS NOT NULL) AND is_active = 1"
        )
        row_with = await cur.fetchone()
        with_salary = row_with["cnt"] if row_with else 0

        cur = await db.execute(
            "SELECT COUNT(*) as cnt FROM jobs"
            " WHERE salary_min IS NULL AND salary_max IS NULL AND is_active = 1"
        )
        row_without = await cur.fetchone()
        without_salary = row_without["cnt"] if row_without else 0

        return SalaryDistributionResponse(
            bins=bins, total_with_salary=with_salary, total_without_salary=without_salary
        )
    raise RuntimeError("Keine Datenbankverbindung verfügbar")


@router.get("/source-scores")
async def get_source_scores(user_id: str) -> SourceScoresResponse:
    """Durchschnittlicher Score pro Quelle."""
    async for db in get_db():
        cur = await db.execute(
            """
            SELECT s.source_name,
                   AVG(e.stage2_score) as avg_score,
                   COUNT(*) as job_count
            FROM job_sources s
            JOIN evaluations e ON e.job_id = s.job_id AND e.user_id = ?
            WHERE e.stage2_score IS NOT NULL
            GROUP BY s.source_name
            ORDER BY avg_score DESC
            """,
            (user_id,),
        )
        rows = await cur.fetchall()
        sources = [
            SourceScore(
                source_name=r["source_name"],
                avg_score=round(r["avg_score"], 2),
                job_count=r["job_count"],
            )
            for r in rows
        ]
        return SourceScoresResponse(sources=sources)
    raise RuntimeError("Keine Datenbankverbindung verfügbar")


@router.get("/skill-trends")
async def get_skill_trends(
    top_n: int = Query(default=10, le=30),
) -> SkillTrendsResponse:
    """Top-N Skills über Zeit (aus skill_trends Tabelle)."""
    async for db in get_db():
        top_cur = await db.execute(
            """
            SELECT skill, SUM(job_count) as total
            FROM skill_trends
            GROUP BY skill
            ORDER BY total DESC
            LIMIT ?
            """,
            (top_n,),
        )
        top_rows = await top_cur.fetchall()
        top_skills = [r["skill"] for r in top_rows]

        if not top_skills:
            return SkillTrendsResponse(trends=[], top_skills=[])

        placeholders = ",".join("?" for _ in top_skills)
        cur = await db.execute(
            f"""
            SELECT skill, period_start as period, job_count as count
            FROM skill_trends
            WHERE skill IN ({placeholders})
            ORDER BY period_start, skill
            """,  # noqa: S608
            tuple(top_skills),
        )
        rows = await cur.fetchall()
        trends = [SkillTrend(skill=r["skill"], period=r["period"], count=r["count"]) for r in rows]

        return SkillTrendsResponse(trends=trends, top_skills=top_skills)
    raise RuntimeError("Keine Datenbankverbindung verfügbar")


@router.get("/skill-network")
async def get_skill_network(
    min_cooccurrence: int = Query(default=2, ge=1),
    max_nodes: int = Query(default=50, le=200),
) -> SkillNetworkResponse:
    """Skill-Co-Occurrence-Netzwerk für D3.js Force-Graph.

    Nodes = Skills, Links = gemeinsames Auftreten in Stellenanzeigen.
    """
    async for db in get_db():
        node_cur = await db.execute(
            """
            SELECT skill, COUNT(*) as cnt,
                   MAX(skill_type) as skill_type
            FROM job_skills
            GROUP BY skill
            ORDER BY cnt DESC
            LIMIT ?
            """,
            (max_nodes,),
        )
        node_rows = await node_cur.fetchall()
        nodes = [
            NetworkNode(id=r["skill"], count=r["cnt"], skill_type=r["skill_type"])
            for r in node_rows
        ]
        skill_set = {n.id for n in nodes}

        if len(skill_set) < 2:
            return SkillNetworkResponse(nodes=nodes, links=[])

        placeholders = ",".join("?" for _ in skill_set)
        skill_params = tuple(skill_set)
        link_cur = await db.execute(
            f"""
            SELECT a.skill as source, b.skill as target, COUNT(*) as weight
            FROM job_skills a
            JOIN job_skills b ON a.job_id = b.job_id AND a.skill < b.skill
            WHERE a.skill IN ({placeholders}) AND b.skill IN ({placeholders})
            GROUP BY a.skill, b.skill
            HAVING weight >= ?
            ORDER BY weight DESC
            """,  # noqa: S608
            (*skill_params, *skill_params, min_cooccurrence),
        )
        link_rows = await link_cur.fetchall()
        links = [
            NetworkLink(source=r["source"], target=r["target"], weight=r["weight"])
            for r in link_rows
        ]

        return SkillNetworkResponse(nodes=nodes, links=links)
    raise RuntimeError("Keine Datenbankverbindung verfügbar")


@router.get("/model-calibration")
async def get_model_calibration(user_id: str) -> CalibrationResponse:
    """Score-Delta-Statistiken pro Evaluierungsstrategie.

    Misst die Abweichung zwischen Modell-Score und Nutzer-Entscheidung.
    """
    async for db in get_db():
        cur = await db.execute(
            """
            SELECT e.eval_strategy as strategy,
                   AVG(f.score_delta) as avg_score_delta,
                   COUNT(*) as sample_count,
                   AVG(f.model_score) as avg_model_score
            FROM feedback f
            JOIN evaluations e ON e.job_id = f.job_id AND e.user_id = f.user_id
            WHERE f.user_id = ?
              AND f.score_delta IS NOT NULL
              AND e.eval_strategy IS NOT NULL
            GROUP BY e.eval_strategy
            """,
            (user_id,),
        )
        rows = await cur.fetchall()
        entries = [
            CalibrationEntry(
                strategy=r["strategy"],
                avg_score_delta=round(r["avg_score_delta"], 2),
                sample_count=r["sample_count"],
                avg_model_score=round(r["avg_model_score"], 2),
            )
            for r in rows
        ]
        return CalibrationResponse(entries=entries)
    raise RuntimeError("Keine Datenbankverbindung verfügbar")


@router.get("/data-quality")
async def get_data_quality_report() -> DataQualityReport:  # type: ignore[return]
    """
    Vollständiger Datenqualitäts-Report:
     - Feldvollständigkeit,
     - Imputations-Potential,
     - Filter-Impact.
    """
    from app.db.quality import generate_report

    return await generate_report(settings.db_path)
