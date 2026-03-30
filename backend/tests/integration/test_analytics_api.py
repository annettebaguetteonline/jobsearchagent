"""Integrationstests für Analytics-Aggregation-Endpoints."""

import pytest

from app.db.database import get_db, init_db
from app.db.models import (
    CompanyCreate,
    EvaluationCreate,
    FeedbackCreate,
    JobCreate,
    JobSkillCreate,
    JobSourceCreate,
    UserCreate,
)
from app.db.queries import (
    create_user,
    insert_feedback,
    insert_job,
    insert_job_source,
    upsert_company,
    upsert_evaluation,
    upsert_job_skills,
)

USER_ID = "test-user-0001"
TS = "2026-03-20T10:00:00Z"


async def _setup_analytics_data(db) -> list[int]:  # type: ignore[type-arg]
    """Testdaten für Analytics: 3 Jobs mit Skills, Evaluierungen, Feedback."""
    await create_user(db, UserCreate(id=USER_ID, name="Test"))
    cid = await upsert_company(db, CompanyCreate(name="TechCorp", name_normalized="techcorp"))

    jobs: list[int] = []
    for i, (title, salary_min, salary_max) in enumerate(
        [
            ("Python Dev", 60000, 80000),
            ("Java Dev", 50000, 70000),
            ("DevOps Engineer", 70000, 90000),
        ]
    ):
        jid = await insert_job(
            db,
            JobCreate(
                canonical_id=f"ana-{i}",
                title=title,
                company_id=cid,
                salary_min=salary_min,
                salary_max=salary_max,
                first_seen_at=TS,
                last_seen_at=TS,
            ),
        )
        await upsert_evaluation(
            db,
            EvaluationCreate(
                job_id=jid,
                user_id=USER_ID,
                stage1_pass=True,
                eval_strategy="structured_core",
                evaluated_at=TS,
            ),
        )
        await db.execute(
            "UPDATE evaluations SET stage2_score = ? WHERE job_id = ?",
            (7.0 + i, jid),
        )
        await db.commit()
        jobs.append(jid)

    # Job-Sources (für source-scores)
    for i, jid in enumerate(jobs):
        await insert_job_source(
            db,
            JobSourceCreate(
                job_id=jid,
                url=f"https://example.com/job-{i}",
                source_name="stepstone" if i < 2 else "indeed",
                source_type="aggregator",
                first_seen_at=TS,
                last_seen_at=TS,
            ),
        )

    # Skills
    await upsert_job_skills(
        db,
        jobs[0],
        [
            JobSkillCreate(job_id=jobs[0], skill="Python", skill_type="required"),
            JobSkillCreate(job_id=jobs[0], skill="Docker", skill_type="nice_to_have"),
        ],
    )
    await upsert_job_skills(
        db,
        jobs[1],
        [
            JobSkillCreate(job_id=jobs[1], skill="Java", skill_type="required"),
            JobSkillCreate(job_id=jobs[1], skill="Docker", skill_type="required"),
        ],
    )
    await upsert_job_skills(
        db,
        jobs[2],
        [
            JobSkillCreate(job_id=jobs[2], skill="Docker", skill_type="required"),
            JobSkillCreate(job_id=jobs[2], skill="Kubernetes", skill_type="required"),
        ],
    )

    # Feedback (für model-calibration)
    await insert_feedback(
        db,
        FeedbackCreate(
            job_id=jobs[0],
            user_id=USER_ID,
            decision="APPLY",
            model_score=7.0,
            score_delta=2.0,
            decided_at=TS,
        ),
    )

    return jobs


# ─── Funnel ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_funnel_counts(tmp_db):
    """Funnel zählt aktive Jobs, Evaluierungen und Stage-Durchläufe."""
    await init_db(tmp_db)
    async for db in get_db(tmp_db):
        await _setup_analytics_data(db)

        # Aktive Jobs
        cur = await db.execute("SELECT COUNT(*) as cnt FROM jobs WHERE is_active = 1")
        row = await cur.fetchone()
        assert row["cnt"] == 3

        # Stage 1 bestanden
        cur = await db.execute(
            "SELECT COUNT(*) as cnt FROM evaluations WHERE user_id = ? AND stage1_pass = 1",
            (USER_ID,),
        )
        row = await cur.fetchone()
        assert row["cnt"] == 3

        # Stage 2 bewertet
        cur = await db.execute(
            "SELECT COUNT(*) as cnt FROM evaluations"
            " WHERE user_id = ? AND stage2_score IS NOT NULL",
            (USER_ID,),
        )
        row = await cur.fetchone()
        assert row["cnt"] == 3


# ─── Salary Distribution ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_salary_distribution(tmp_db):
    """Alle 3 Jobs haben Gehaltsdaten."""
    await init_db(tmp_db)
    async for db in get_db(tmp_db):
        await _setup_analytics_data(db)

        cur = await db.execute(
            "SELECT COUNT(*) as cnt FROM jobs"
            " WHERE (salary_min IS NOT NULL OR salary_max IS NOT NULL) AND is_active = 1"
        )
        row = await cur.fetchone()
        assert row["cnt"] == 3


@pytest.mark.asyncio
async def test_salary_bins(tmp_db):
    """Salary-Bins werden korrekt berechnet (bin_size=10000)."""
    await init_db(tmp_db)
    async for db in get_db(tmp_db):
        await _setup_analytics_data(db)

        bin_size = 10000
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
        assert len(rows) >= 2  # 50k, 60k, 70k → mindestens 2 Bins


# ─── Source Scores ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_source_scores(tmp_db):
    """Durchschnittlicher Score pro Quelle wird korrekt berechnet."""
    await init_db(tmp_db)
    async for db in get_db(tmp_db):
        await _setup_analytics_data(db)

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
            (USER_ID,),
        )
        rows = await cur.fetchall()
        assert len(rows) == 2  # stepstone + indeed
        source_names = {r["source_name"] for r in rows}
        assert source_names == {"stepstone", "indeed"}


# ─── Skill Co-Occurrence ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_skill_cooccurrence(tmp_db):
    """Docker kommt in 3 Jobs vor, Co-Occurrence-Paare existieren."""
    await init_db(tmp_db)
    async for db in get_db(tmp_db):
        await _setup_analytics_data(db)

        # Docker in allen 3 Jobs
        cur = await db.execute("SELECT COUNT(*) as cnt FROM job_skills WHERE skill = 'Docker'")
        row = await cur.fetchone()
        assert row["cnt"] == 3

        # Co-Occurrence: Docker+Python, Docker+Java, Docker+Kubernetes
        cur = await db.execute(
            """
            SELECT a.skill as source, b.skill as target, COUNT(*) as weight
            FROM job_skills a
            JOIN job_skills b ON a.job_id = b.job_id AND a.skill < b.skill
            GROUP BY a.skill, b.skill
            HAVING weight >= 1
            """
        )
        rows = await cur.fetchall()
        assert len(rows) >= 3


@pytest.mark.asyncio
async def test_skill_network_nodes(tmp_db):
    """Skill-Network gibt Nodes mit korrekten Counts zurück."""
    await init_db(tmp_db)
    async for db in get_db(tmp_db):
        await _setup_analytics_data(db)

        cur = await db.execute(
            """
            SELECT skill, COUNT(*) as cnt, MAX(skill_type) as skill_type
            FROM job_skills
            GROUP BY skill
            ORDER BY cnt DESC
            """
        )
        rows = await cur.fetchall()
        skills = {r["skill"]: r["cnt"] for r in rows}
        assert skills["Docker"] == 3
        assert skills["Python"] == 1


# ─── Skill Trends ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_skill_trends_empty(tmp_db):
    """Leere skill_trends Tabelle gibt leere Liste zurück."""
    await init_db(tmp_db)
    async for db in get_db(tmp_db):
        cur = await db.execute("SELECT COUNT(*) as cnt FROM skill_trends")
        row = await cur.fetchone()
        assert row["cnt"] == 0


@pytest.mark.asyncio
async def test_skill_trends_with_data(tmp_db):
    """skill_trends mit Daten gibt Top-N korrekt zurück."""
    await init_db(tmp_db)
    async for db in get_db(tmp_db):
        # Testdaten einfügen
        await db.execute(
            "INSERT INTO skill_trends (skill, period_start, job_count) VALUES (?, ?, ?)",
            ("Python", "2026-W10", 15),
        )
        await db.execute(
            "INSERT INTO skill_trends (skill, period_start, job_count) VALUES (?, ?, ?)",
            ("Python", "2026-W11", 20),
        )
        await db.execute(
            "INSERT INTO skill_trends (skill, period_start, job_count) VALUES (?, ?, ?)",
            ("Docker", "2026-W10", 10),
        )
        await db.commit()

        # Top 2
        cur = await db.execute(
            """
            SELECT skill, SUM(job_count) as total
            FROM skill_trends
            GROUP BY skill
            ORDER BY total DESC
            LIMIT 2
            """
        )
        rows = await cur.fetchall()
        assert len(rows) == 2
        assert rows[0]["skill"] == "Python"  # 35 total
        assert rows[1]["skill"] == "Docker"  # 10 total


# ─── Model Calibration ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_model_calibration(tmp_db):
    """Feedback mit score_delta wird pro eval_strategy aggregiert."""
    await init_db(tmp_db)
    async for db in get_db(tmp_db):
        await _setup_analytics_data(db)

        cur = await db.execute(
            """
            SELECT e.eval_strategy, AVG(f.score_delta) as avg_delta, COUNT(*) as cnt
            FROM feedback f
            JOIN evaluations e ON e.job_id = f.job_id AND e.user_id = f.user_id
            WHERE f.user_id = ? AND f.score_delta IS NOT NULL
            GROUP BY e.eval_strategy
            """,
            (USER_ID,),
        )
        rows = await cur.fetchall()
        assert len(rows) >= 1
        assert rows[0]["eval_strategy"] == "structured_core"
        assert rows[0]["avg_delta"] == 2.0


@pytest.mark.asyncio
async def test_model_calibration_empty(tmp_db):
    """Ohne Feedback gibt model-calibration leere Liste zurück."""
    await init_db(tmp_db)
    async for db in get_db(tmp_db):
        await create_user(db, UserCreate(id="empty-user", name="Empty"))

        cur = await db.execute(
            """
            SELECT e.eval_strategy, AVG(f.score_delta) as avg_delta
            FROM feedback f
            JOIN evaluations e ON e.job_id = f.job_id AND e.user_id = f.user_id
            WHERE f.user_id = ? AND f.score_delta IS NOT NULL
            GROUP BY e.eval_strategy
            """,
            ("empty-user",),
        )
        rows = await cur.fetchall()
        assert len(rows) == 0
