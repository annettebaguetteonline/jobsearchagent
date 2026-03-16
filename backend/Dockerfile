FROM python:3.13-slim AS base

RUN apt-get update && apt-get install -y --no-install-recommends \
    texlive-latex-base \
    texlive-latex-extra \
    texlive-fonts-recommended \
    texlive-lang-german \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Non-root-User für Playwright-Sandbox
RUN groupadd --gid 1001 appgroup \
    && useradd --uid 1001 --gid appgroup --shell /bin/bash --create-home appuser

WORKDIR /app

COPY pyproject.toml .
RUN pip install --no-cache-dir -e .

# Playwright-Browser als root installieren (benötigt System-Deps)
# PLAYWRIGHT_BROWSERS_PATH → systemweiter Pfad, damit alle User den Browser finden
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
RUN pip install playwright && playwright install chromium --with-deps \
    && chmod -R 755 /ms-playwright

USER appuser

COPY --chown=appuser:appgroup app/ ./app/

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
