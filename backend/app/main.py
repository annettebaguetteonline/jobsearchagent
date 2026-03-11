"""Job Search Agent — FastAPI-Applikationsfabrik."""

from fastapi import FastAPI

from app.api import cover_letters, evaluation, jobs, scrape
from app.core.logging import configure_logging


def create_app() -> FastAPI:
    """Erstelle und konfiguriere die FastAPI-Applikation."""
    configure_logging()

    app = FastAPI(
        title="Job Search Agent",
        description="Automatisierter Scraper und Evaluator für deutsche Stellenbörsen",
        version="0.1.0",
    )

    app.include_router(jobs.router, prefix="/api/jobs", tags=["jobs"])
    app.include_router(scrape.router, prefix="/api/scrape", tags=["scrape"])
    app.include_router(evaluation.router, prefix="/api/evaluation", tags=["evaluation"])
    app.include_router(
        cover_letters.router, prefix="/api/cover-letters", tags=["cover-letters"]
    )

    return app


app = create_app()
