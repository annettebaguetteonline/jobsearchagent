# Contributing Guide – Job Search Agent

**Version:** 0.2  
**Stand:** März 2026

---

## Inhaltsverzeichnis

1. [Schnellstart](#1-schnellstart)
2. [Repo-Struktur](#2-repo-struktur)
3. [Makefile-Referenz](#3-makefile-referenz)
4. [Entwicklungsworkflow](#4-entwicklungsworkflow)
5. [Branch- & Commit-Strategie](#5-branch---commit-strategie)
6. [Testing](#6-testing)
7. [Linting & Formatierung](#7-linting--formatierung)
8. [GitHub Actions](#8-github-actions)
9. [GitHub Repository-Einstellungen](#9-github-repository-einstellungen)
10. [Architecture Decision Records](#10-architecture-decision-records)
11. [Für Einsteiger](#11-für-einsteiger)

---

## 1. Schnellstart

```bash
# Repo klonen
git clone https://github.com/DEIN-USERNAME/job-agent.git
cd job-agent

# Einmalige Einrichtung
make setup

# API-Key als Secret ablegen (nicht in .env!)
mkdir -p secrets
echo "sk-ant-..." > secrets/anthropic_key.txt
# secrets/ ist git-ignored

# Ollama-Modelle laden (einmalig, ~8GB Download)
ollama pull mistral-nemo:12b
ollama pull nomic-embed-text

# Lokale Entwicklungsumgebung starten
make dev
```

Nach `make dev` läuft:
- Backend:  http://localhost:8000
- API-Docs: http://localhost:8000/docs
- Frontend: http://localhost:5173  (Vite Dev Server, nativ)

> Im Entwicklungsalltag läuft **nur ein Container** (Backend).
> Das Frontend wird nativ mit Vite gestartet – kein nginx nötig.

---

## 2. Repo-Struktur

```
job-agent/
├── .github/
│   ├── workflows/
│   │   ├── ci.yml                  # Haupt-Pipeline: lint, typecheck, test
│   │   ├── security.yml            # Security-Scans (wöchentlich)
│   │   └── pr-checks.yml           # Schnelle Checks nur für PRs
│   ├── PULL_REQUEST_TEMPLATE.md    # PR-Vorlage
│   ├── CODEOWNERS                  # Wer reviewed was
│   └── dependabot.yml              # Automatische Dependency-Updates
│
├── backend/
│   ├── app/
│   │   ├── api/                    # FastAPI Router
│   │   │   ├── jobs.py
│   │   │   ├── scrape.py
│   │   │   ├── evaluation.py
│   │   │   ├── companies.py
│   │   │   └── cover_letters.py
│   │   ├── scraper/
│   │   │   ├── base.py
│   │   │   ├── portals/
│   │   │   └── generic/
│   │   ├── evaluator/
│   │   │   ├── pipeline.py
│   │   │   ├── rag.py
│   │   │   ├── stage1.py
│   │   │   └── stage2.py
│   │   ├── writer/
│   │   │   ├── generator.py
│   │   │   └── latex.py
│   │   ├── location/
│   │   │   ├── transit.py
│   │   │   └── resolver.py
│   │   ├── db/
│   │   │   ├── models.py           # Pydantic-Modelle
│   │   │   ├── queries.py          # SQL-Queries
│   │   │   └── migrations/         # Schema-Versionierung
│   │   └── core/
│   │       ├── config.py           # Settings aus .env
│   │       └── logging.py
│   ├── tests/
│   │   ├── unit/                   # Isolierte Tests, keine externen Deps
│   │   ├── integration/            # Mit Test-DB, externe APIs gemockt
│   │   └── fixtures/               # Gespeicherte HTML-Seiten für Scraper-Tests
│   ├── Dockerfile
│   ├── pyproject.toml              # Dependencies + Tool-Konfiguration
│   └── ruff.toml                   # Linting-Konfiguration
│
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   │   ├── ui/                 # shadcn/ui Basis-Komponenten
│   │   │   ├── jobs/               # Job-spezifische Komponenten
│   │   │   ├── charts/             # Analytics-Charts
│   │   │   └── clarification/      # Klärungsbedarf-Komponenten
│   │   ├── pages/
│   │   │   ├── Overview.tsx
│   │   │   ├── Jobs.tsx
│   │   │   ├── Clarification.tsx
│   │   │   ├── Analytics.tsx
│   │   │   └── Control.tsx
│   │   ├── api/                    # TanStack Query Hooks
│   │   ├── types/
│   │   │   └── api.ts              # Auto-generiert aus OpenAPI-Schema
│   │   └── lib/                    # Hilfsfunktionen
│   ├── tests/
│   │   ├── unit/                   # Vitest + Testing Library
│   │   └── e2e/                    # Playwright (ab Phase 2)
│   ├── Dockerfile
│   ├── package.json
│   ├── tsconfig.json
│   └── vite.config.ts
│
├── docs/
│   ├── design/
│   │   └── job_agent_design.md     # System-Designdokument
│   ├── adr/                        # Architecture Decision Records
│   │   ├── 001-sqlite-over-postgres.md
│   │   ├── 002-ollama-native.md
│   │   ├── 003-monorepo.md
│   │   ├── 004-evaluation-ab-test.md
│   │   ├── 005-texlive-in-backend.md
│   │   └── 006-ddg-over-searxng.md
│   └── api/
│       └── openapi.json            # Auto-generiert, in Git eingecheckt
│
├── infrastructure/
│   ├── docker-compose.yml
│   ├── docker-compose.prod.yml
│   └── secrets/                        # git-ignored
│       └── anthropic_key.txt           # nur der reine Key-Wert
│
├── scripts/
│   ├── setup.sh                    # Einmalige Einrichtung
│   ├── generate_schema.py          # OpenAPI-Schema exportieren
│   ├── seed_feedback.py            # Seed-Daten für Feedback-Loop
│   └── migrate.py                  # DB-Migrationen ausführen
│
├── .env.example                    # Vorlage (in Git)
├── .env                            # Echte Werte (git-ignored)
├── .gitignore
├── Makefile
└── README.md
```

---

## 3. Makefile-Referenz

Alle häufigen Aufgaben sind über `make` erreichbar:

```makefile
# Entwicklung
make setup        # Einmalige Einrichtung (venv, npm install, pre-commit)
make dev          # Backend-Container + Vite Dev Server starten
                  #   → docker compose up -d backend
                  #   → cd frontend && npm run dev

# Qualitätssicherung
make lint         # ruff check + ruff format (Backend) und ESLint (Frontend)
make types        # OpenAPI-Schema → frontend/src/types/api.ts generieren
make test         # Alle Tests (Backend + Frontend)
make test-backend # Nur pytest
make test-frontend # Nur Vitest

# Datenbank
make migrate      # DB-Migrationen ausführen

# Produktion
make prod         # docker compose -f docker-compose.prod.yml up -d
```

> `make dev` startet **einen Container** (Backend inkl. TeX Live)
> plus den Vite Dev Server nativ. Kein Frontend-Container in der
> Entwicklung nötig.

---

## 4. Entwicklungsworkflow

### Täglicher Workflow

```bash
# 1. Aktuellen Stand holen
git checkout main && git pull

# 2. Feature-Branch erstellen
git checkout -b feature/scraper-interamt

# 3. Entwickeln + regelmäßig committen
git add -p                          # Interaktiv stagen
git commit -m "feat(scraper): add interamt base structure"

# 4. Vor dem Push: lokal prüfen
make lint
make test

# 5. Push + PR öffnen
git push -u origin feature/scraper-interamt
# → GitHub PR-Link erscheint im Terminal
```

### API-Typen synchronisieren

Wann immer sich das Backend-API ändert:

```bash
make types
# Prüft ob src/types/api.ts aktuell ist
# Bei Abweichung: generiert neue Typen automatisch
```

> Der CI-Check schlägt fehl wenn die generierten Typen nicht
> mit dem aktuellen Schema übereinstimmen – das ist gewollt.

### Datenbank-Migrationen

```bash
# Neue Migration erstellen
python scripts/migrate.py create "add_profile_version_to_evaluations"

# Migrationen ausführen
make migrate
```

Migrationen liegen unter `backend/app/db/migrations/` und werden
versioniert in Git eingecheckt.

---

## 5. Branch- & Commit-Strategie

### Branch-Namenskonvention

```
feature/   → neue Funktionalität       feature/scraper-interamt
fix/       → Bugfix                     fix/latex-ampersand-escaping
refactor/  → kein Bug, kein Feature    refactor/evaluation-pipeline
docs/      → nur Dokumentation         docs/update-adr-003
test/      → nur Tests                 test/integration-scraper
chore/     → Dependencies, Config      chore/bump-anthropic-0.25
```

### Commit-Format (Conventional Commits)

```
<typ>(<bereich>): <kurze Beschreibung>

[optionaler längerer Body]

[optionale Footer: Breaking Changes, Issue-Refs]
```

**Typen:**

| Typ | Bedeutung | Beispiel |
|---|---|---|
| `feat` | Neue Funktionalität | `feat(scraper): add interamt scraper` |
| `fix` | Bugfix | `fix(latex): escape ampersand in names` |
| `test` | Tests hinzufügen/ändern | `test(evaluator): add stage2 mock tests` |
| `refactor` | Code-Umbau ohne Verhaltensänderung | `refactor(rag): extract chunk logic` |
| `docs` | Dokumentation | `docs(adr): add decision for sqlite` |
| `chore` | Dependencies, CI, Config | `chore(deps): bump anthropic to 0.25` |
| `perf` | Performance-Verbesserung | `perf(db): add index on jobs.deadline` |

**Beispiele:**

```bash
git commit -m "feat(scraper): add interamt.de portal scraper

Implements Typ-A scraper for interamt.de with:
- Pagination support
- Detail page fetching for full job text
- Random delays for anti-detection

Closes #12"

git commit -m "fix(location): handle missing transit API response

transit.py now falls back to transport.rest if db_rest
returns a 5xx error. Adds retry with exponential backoff.

Fixes #34"
```

### Pull Request Regeln

- `main` ist protected – direkte Commits sind gesperrt
- Jeder PR braucht mindestens **1 Approval**
- CI muss grün sein bevor Merge möglich ist
- PRs sollten klein und fokussiert sein (ein Feature pro PR)
- PR-Titel folgt ebenfalls Conventional Commits Format

---

## 6. Testing

### Testpyramide

```
         ╱  E2E   ╲        Phase 2: Playwright, nur kritische Flows
        ╱───────────╲
       ╱ Integration ╲      Mit Test-DB, externe APIs gemockt
      ╱───────────────╲
     ╱      Unit       ╲    Isoliert, schnell, viele
    ╱───────────────────╲
```

### Backend Tests ausführen

```bash
# Alle Tests
make test

# Nur Unit Tests (schnell, ~5s)
cd backend && pytest tests/unit/ -v

# Nur Integration Tests
cd backend && pytest tests/integration/ -v

# Mit Coverage-Report
cd backend && pytest --cov=app --cov-report=html
open htmlcov/index.html

# Einzelne Testdatei
cd backend && pytest tests/unit/test_deduplication.py -v

# Tests mit Keyword-Filter
cd backend && pytest -k "test_canonical" -v
```

### Frontend Tests ausführen

```bash
# Alle Tests
cd frontend && npm run test

# Watch-Modus (während Entwicklung)
cd frontend && npm run test:watch

# Mit Coverage
cd frontend && npm run test:coverage
```

### Was wird getestet

#### Backend Unit Tests (`tests/unit/`)

Isoliert, keine Datenbankverbindung, keine externen Calls.
Alles was externe Deps braucht wird gemockt.

```python
# tests/unit/test_deduplication.py
def test_canonical_id_normalization():
    """Gleiche Stelle mit Titel-Varianten → gleiche canonical_id"""
    id1 = compute_canonical_id(
        "Senior Backend Engineer (m/w/d)", "Muster GmbH", "Frankfurt"
    )
    id2 = compute_canonical_id(
        "Senior Backend Engineer", "Muster GmbH", "Frankfurt"
    )
    assert id1 == id2

def test_canonical_id_different_companies():
    """Gleicher Titel, andere Firma → unterschiedliche ID"""
    id1 = compute_canonical_id("Python Developer", "Firma A", "Berlin")
    id2 = compute_canonical_id("Python Developer", "Firma B", "Berlin")
    assert id1 != id2

# tests/unit/test_location_score.py
def test_full_remote_always_max_score():
    assert location_score(transit_min=120, model="full_remote") == 1.0

def test_hybrid_penalization_less_than_onsite():
    onsite  = location_score(transit_min=45, model="onsite")
    hybrid  = location_score(transit_min=45, model="hybrid_1x")
    assert hybrid > onsite

def test_score_above_acceptable_threshold_drops():
    score_ok  = location_score(transit_min=55, model="onsite", max_min=60)
    score_bad = location_score(transit_min=90, model="onsite", max_min=60)
    assert score_ok > score_bad

# tests/unit/test_latex.py
def test_escape_ampersand():
    assert escape_latex("AT&T") == r"AT\&T"

def test_escape_percentage():
    assert escape_latex("100% remote") == r"100\% remote"

def test_escape_dollar():
    assert escape_latex("$80k") == r"\$80k"

def test_escape_cpp_unchanged():
    # + ist kein LaTeX-Sonderzeichen
    assert escape_latex("C++") == "C++"
```

#### Backend Integration Tests (`tests/integration/`)

Mit echter SQLite-Testdatenbank in einem temporären Verzeichnis.
Externe APIs (Ollama, Anthropic, ÖPNV) werden gemockt.

```python
# tests/integration/conftest.py
import pytest
from pathlib import Path
from app.db.queries import init_db

@pytest.fixture
def test_db(tmp_path):
    """Frische SQLite-DB für jeden Test – keine Seiteneffekte"""
    db_path = tmp_path / "test.db"
    init_db(db_path)
    return db_path

@pytest.fixture
def mock_ollama(respx_mock):
    """Ollama-API mocken – kein laufendes Ollama nötig"""
    respx_mock.post("http://localhost:11434/api/generate").mock(
        return_value=httpx.Response(200, json={
            "response": '{"score": 0.8, "reason": "Passt gut"}'
        })
    )

@pytest.fixture
def mock_anthropic(mocker):
    """Anthropic-API mocken – keine echten API-Kosten in Tests"""
    mock = mocker.patch("anthropic.Anthropic")
    mock.return_value.messages.create.return_value = MagicMock(
        content=[MagicMock(text=json.dumps({
            "score": 7.5,
            "recommendation": "APPLY",
            "match_reasons": ["Python-Erfahrung"],
            "missing_skills": [],
        }))]
    )
    return mock

# tests/integration/test_evaluation_pipeline.py
async def test_new_job_gets_evaluated(test_db, mock_ollama, mock_anthropic):
    job = Job(
        url="https://example.com/job/1",
        title="Senior Engineer",
        company="Test GmbH",
        location="Frankfurt",
        source="test",
        raw_text="Python, Kubernetes, 5 Jahre Erfahrung gesucht."
    )
    job_id = upsert_job(job, db_path=test_db)
    evaluation = await evaluate_job(job, job_id, db_path=test_db)

    assert evaluation.stage1_pass == True
    assert evaluation.stage2_score == 7.5
    assert evaluation.stage2_recommendation == "APPLY"

async def test_duplicate_job_inserted_once(test_db, mock_ollama, mock_anthropic):
    job = Job(url="https://example.com/job/1", title="Engineer",
              company="Firma", location="Berlin", source="test", raw_text="...")
    id1 = upsert_job(job, db_path=test_db)
    id2 = upsert_job(job, db_path=test_db)  # Duplikat

    assert id1 is not None
    assert id2 is None  # Duplikat wurde ignoriert
```

#### Scraper Tests – HTML-Fixtures

Scraper werden gegen **gespeicherte HTML-Seiten** getestet –
kein Live-Scraping in der CI-Pipeline.

```
tests/fixtures/
  interamt_search_result.html      # Gespeicherte Suchergebnisseite
  interamt_detail_page.html        # Gespeicherte Detailseite
  karriere_hessen_result.html
  stepstone_rss_feed.xml
```

```python
# tests/integration/test_scraper_interamt.py
async def test_interamt_extracts_jobs(httpx_mock):
    fixture = Path("tests/fixtures/interamt_search_result.html").read_text()
    httpx_mock.get("https://interamt.de/koop/app/stellenangebote").mock(
        return_value=httpx.Response(200, text=fixture)
    )
    scraper = InteramtScraper(config=TEST_CONFIG)
    jobs = [job async for job in scraper.fetch_jobs()]

    assert len(jobs) > 0
    assert all(job.title for job in jobs)
    assert all(job.url.startswith("https://interamt.de") for job in jobs)
    assert all(job.company for job in jobs)
```

> **Fixtures aktuell halten:** Wenn ein Scraper kaputt geht,
> ist der erste Schritt die Fixture-HTML zu aktualisieren.
> Das ist gleichzeitig ein Frühwarnsystem für Layout-Änderungen.

#### Frontend Unit Tests

```typescript
// tests/unit/JobScore.test.tsx
import { render, screen } from '@testing-library/react'
import { JobScore } from '@/components/jobs/JobScore'

test('zeigt grünes Icon bei Score >= 7', () => {
  render(<JobScore score={8.5} />)
  expect(screen.getByTestId('score-icon'))
    .toHaveClass('text-green-500')
})

test('zeigt rotes Icon bei Score < 5', () => {
  render(<JobScore score={3.2} />)
  expect(screen.getByTestId('score-icon'))
    .toHaveClass('text-red-500')
})

test('zeigt Score-Wert als Text', () => {
  render(<JobScore score={7.4} />)
  expect(screen.getByText('7.4')).toBeInTheDocument()
})

// tests/unit/lib/location.test.ts
import { formatTransitTime, getWorkModelLabel } from '@/lib/location'

test('formatiert Minuten unter einer Stunde', () => {
  expect(formatTransitTime(34)).toBe('34 min')
})

test('formatiert Minuten über einer Stunde', () => {
  expect(formatTransitTime(90)).toBe('1h 30min')
})

test('gibt korrektes Label für Arbeitsmodell zurück', () => {
  expect(getWorkModelLabel('hybrid_2_3x')).toBe('Hybrid 2–3x/Woche')
  expect(getWorkModelLabel('full_remote')).toBe('Full Remote')
})
```

### Coverage-Ziele

| Bereich | Ziel | Begründung |
|---|---|---|
| `evaluator/` | ≥ 85% | Kern des Systems, kritisch |
| `db/queries.py` | ≥ 90% | Datenintegrität |
| `location/` | ≥ 80% | Komplexe Logik |
| `scraper/` | ≥ 60% | Externe Deps, schwerer testbar |
| `writer/` | ≥ 70% | LLM-Ausgaben variabel |
| Frontend `lib/` | ≥ 80% | Reine Logik-Funktionen |
| Frontend Komponenten | ≥ 60% | UI schwerer automatisiert testbar |

Coverage ist ein Hilfsmittel, kein Selbstzweck.
100% Coverage mit schlechten Tests ist wertlos.

---

## 7. Linting & Formatierung

### Backend

**ruff** übernimmt Linting und Formatierung in einem Tool:

```toml
# backend/ruff.toml
line-length = 100
target-version = "py312"

[lint]
select = [
    "E",    # pycodestyle errors
    "F",    # pyflakes
    "I",    # isort (Import-Sortierung)
    "N",    # pep8-naming
    "UP",   # pyupgrade (moderne Python-Syntax)
    "B",    # flake8-bugbear (häufige Bugs)
    "S",    # flake8-bandit (Security)
    "ANN",  # Type Annotations
]
ignore = [
    "ANN101",  # self braucht keine Annotation
    "S101",    # assert in Tests erlaubt
]

[lint.per-file-ignores]
"tests/**" = ["S", "ANN"]  # Security + Annotations in Tests lockerer
```

```bash
# Prüfen
cd backend && ruff check .

# Automatisch fixen
cd backend && ruff check --fix .

# Formatieren
cd backend && ruff format .
```

**mypy** für Type Checking:

```ini
# backend/pyproject.toml
[tool.mypy]
python_version = "3.12"
strict = true
ignore_missing_imports = true
exclude = ["tests/"]
```

### Frontend

**ESLint** für Linting, **Prettier** für Formatierung:

```json
// frontend/.eslintrc.json
{
  "extends": [
    "eslint:recommended",
    "plugin:@typescript-eslint/recommended-type-checked",
    "plugin:react-hooks/recommended"
  ],
  "rules": {
    "@typescript-eslint/no-explicit-any": "error",
    "@typescript-eslint/no-unused-vars": "error",
    "react-hooks/exhaustive-deps": "warn"
  }
}
```

```json
// frontend/.prettierrc
{
  "semi": false,
  "singleQuote": true,
  "tabWidth": 2,
  "trailingComma": "es5",
  "printWidth": 100
}
```

### Pre-commit Hooks (lokal)

Verhindert dass unlinteter Code überhaupt gepusht wird:

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.3.0
    hooks:
      - id: ruff
        args: [--fix]
      - id: ruff-format

  - repo: https://github.com/pre-commit/mirrors-mypy
    rev: v1.9.0
    hooks:
      - id: mypy
        additional_dependencies: [types-all]

  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v4.5.0
    hooks:
      - id: check-merge-conflict
      - id: check-added-large-files
        args: [--maxkb=500]
      - id: detect-private-key
```

```bash
# Einmalig einrichten
pip install pre-commit
pre-commit install

# Manuell auf allen Dateien ausführen
pre-commit run --all-files
```

---

## 8. GitHub Actions

### ci.yml – Haupt-Pipeline

Läuft bei jedem Push auf `main` und bei allen PRs.

```yaml
# .github/workflows/ci.yml
name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

# Verhindert parallele Runs für denselben Branch
concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true

jobs:
  # ── Backend ────────────────────────────────────────────────
  backend:
    name: Backend – Lint, Types, Tests
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: backend

    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: "pip"

      - name: Install dependencies
        run: pip install -e ".[dev]"

      - name: Lint (ruff)
        run: ruff check .

      - name: Format check (ruff)
        run: ruff format --check .

      - name: Type check (mypy)
        run: mypy app/

      - name: Unit tests
        run: pytest tests/unit/ -v --tb=short

      - name: Integration tests
        run: pytest tests/integration/ -v --tb=short

      - name: Coverage
        run: pytest --cov=app --cov-report=xml --cov-fail-under=70

      - uses: codecov/codecov-action@v4
        if: always()
        with:
          file: coverage.xml
          flags: backend

  # ── Frontend ───────────────────────────────────────────────
  frontend:
    name: Frontend – Lint, Types, Tests
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: frontend

    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-node@v4
        with:
          node-version: "20"
          cache: "npm"
          cache-dependency-path: frontend/package-lock.json

      - name: Install dependencies
        run: npm ci

      - name: Type check
        run: npm run type-check

      - name: Lint (ESLint)
        run: npm run lint

      - name: Format check (Prettier)
        run: npm run format:check

      - name: Unit tests (Vitest)
        run: npm run test -- --run

      - name: Coverage
        run: npm run test:coverage

      - uses: codecov/codecov-action@v4
        if: always()
        with:
          flags: frontend

  # ── API-Schema-Konsistenz ──────────────────────────────────
  schema-sync:
    name: API Schema aktuell?
    runs-on: ubuntu-latest
    needs: [backend]

    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: "pip"

      - run: pip install -e ".[dev]"
        working-directory: backend

      - name: Schema generieren und vergleichen
        run: |
          cd backend && python scripts/generate_schema.py \
            --output /tmp/current_schema.json
          diff docs/api/openapi.json /tmp/current_schema.json || \
            (echo "❌ OpenAPI-Schema veraltet!" \
             echo "   Bitte 'make types' ausführen und committen." \
             && exit 1)

  # ── Build-Check ────────────────────────────────────────────
  build:
    name: Docker Build
    runs-on: ubuntu-latest
    needs: [backend, frontend]
    # Nur auf main, nicht bei jedem PR (spart Zeit)
    if: github.ref == 'refs/heads/main'

    steps:
      - uses: actions/checkout@v4

      - name: Build Backend Image
        run: docker build backend/ -t job-agent-backend:test

      - name: Build Frontend Image
        run: docker build frontend/ -t job-agent-frontend:test
```

### security.yml – Security-Scans

Läuft wöchentlich und bei Pushes auf `main`.
Getrennt von CI damit ein Security-Fund die normale
Entwicklung nicht blockiert – aber trotzdem sichtbar ist.

```yaml
# .github/workflows/security.yml
name: Security

on:
  push:
    branches: [main]
  schedule:
    - cron: "0 8 * * 1"   # Montags 08:00 UTC
  workflow_dispatch:        # Manuell triggerbar

jobs:
  python-audit:
    name: Python Dependency Audit
    runs-on: ubuntu-latest

    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: pip-audit
        run: |
          pip install pip-audit
          pip-audit -r backend/requirements.txt \
            --format json --output pip-audit-report.json
        continue-on-error: true

      - uses: actions/upload-artifact@v4
        with:
          name: pip-audit-report
          path: pip-audit-report.json

  python-sast:
    name: Python Static Analysis (bandit)
    runs-on: ubuntu-latest

    steps:
      - uses: actions/checkout@v4

      - run: pip install bandit[toml]

      - name: Bandit SAST
        run: |
          bandit -r backend/app/ \
            -ll \
            -f json \
            -o bandit-report.json
        continue-on-error: true

      - uses: actions/upload-artifact@v4
        with:
          name: bandit-report
          path: bandit-report.json

  npm-audit:
    name: NPM Dependency Audit
    runs-on: ubuntu-latest

    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: "20"

      - run: cd frontend && npm ci

      - name: npm audit
        run: cd frontend && npm audit --audit-level=high
        continue-on-error: true

  secrets-scan:
    name: Secret Scanning (TruffleHog)
    runs-on: ubuntu-latest

    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0   # Komplette History scannen

      - uses: trufflesecurity/trufflehog@main
        with:
          extra_args: --only-verified
```

### pr-checks.yml – Schnelle PR-Validierung

Läuft nur bei PRs, sehr schnell (~1 Min).
Gibt früh Feedback ohne die volle CI abzuwarten.

```yaml
# .github/workflows/pr-checks.yml
name: PR Checks

on:
  pull_request:
    branches: [main]

jobs:
  pr-title:
    name: PR-Titel prüfen (Conventional Commits)
    runs-on: ubuntu-latest

    steps:
      - uses: amannn/action-semantic-pull-request@v5
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        with:
          types: |
            feat
            fix
            refactor
            test
            docs
            chore
            perf

  changed-files:
    name: Geänderte Dateien analysieren
    runs-on: ubuntu-latest

    steps:
      - uses: actions/checkout@v4

      - uses: dorny/paths-filter@v3
        id: changes
        with:
          filters: |
            backend:
              - 'backend/**'
            frontend:
              - 'frontend/**'
            schema:
              - 'backend/app/api/**'
            docs:
              - 'docs/**'

      - name: Hinweis bei API-Änderung ohne Schema-Update
        if: steps.changes.outputs.schema == 'true'
        run: |
          echo "⚠️  API-Dateien geändert."
          echo "   Bitte prüfen ob 'make types' ausgeführt wurde."

  size-check:
    name: PR-Größe prüfen
    runs-on: ubuntu-latest

    steps:
      - uses: codelytv/pr-size-labeler@v1
        with:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          xs_label: "size: XS"
          xs_max_size: 30
          s_label: "size: S"
          s_max_size: 100
          m_label: "size: M"
          m_max_size: 300
          l_label: "size: L"
          l_max_size: 500
          xl_label: "size: XL"
          fail_if_xl: false   # XL ist Warnung, kein Fehler
```

### dependabot.yml – Automatische Dependency-Updates

```yaml
# .github/dependabot.yml
version: 2

updates:
  # Python Backend
  - package-ecosystem: "pip"
    directory: "/backend"
    schedule:
      interval: "weekly"
      day: "monday"
      time: "08:00"
      timezone: "Europe/Berlin"
    groups:
      # Entwicklungs-Dependencies zusammen updaten
      dev-dependencies:
        patterns: ["pytest*", "ruff", "mypy*"]
    ignore:
      # Anthropic-Updates manuell prüfen (API-Änderungen möglich)
      - dependency-name: "anthropic"
        update-types: ["version-update:semver-major"]

  # Frontend
  - package-ecosystem: "npm"
    directory: "/frontend"
    schedule:
      interval: "weekly"
      day: "monday"
      time: "08:00"
      timezone: "Europe/Berlin"
    groups:
      react-ecosystem:
        patterns: ["react", "react-*", "@types/react*"]
      tanstack:
        patterns: ["@tanstack/*"]
      testing:
        patterns: ["vitest", "@testing-library/*", "@vitest/*"]

  # GitHub Actions selbst aktuell halten
  - package-ecosystem: "github-actions"
    directory: "/"
    schedule:
      interval: "monthly"
```

---

## 9. GitHub Repository-Einstellungen

Diese Einstellungen einmalig unter
**Settings → Branches / Pull Requests** konfigurieren:

### Branch Protection für `main`

**Settings → Branches → Add rule → Branch name pattern: `main`**

```
✅ Require a pull request before merging
   ✅ Require approvals: 1
   ✅ Dismiss stale pull request approvals when new commits are pushed
   ☐ Require review from Code Owners  (optional, CODEOWNERS vorhanden)

✅ Require status checks to pass before merging
   ✅ Require branches to be up to date before merging
   
   Required status checks (nach erstem CI-Lauf auswählen):
   ✅ Backend – Lint, Types, Tests
   ✅ Frontend – Lint, Types, Tests
   ✅ API Schema aktuell?
   ✅ PR-Titel prüfen (Conventional Commits)

✅ Require conversation resolution before merging
✅ Do not allow bypassing the above settings
```

### Merge-Strategie

**Settings → General → Pull Requests**

```
☐ Allow merge commits          → deaktivieren (kein merge commit noise)
✅ Allow squash merging         → aktivieren (saubere History)
   Default commit message: Pull request title and description
☐ Allow rebase merging         → nach Geschmack (optional)

✅ Automatically delete head branches   → aktivieren
   (Branch nach Merge automatisch löschen)
```

### Weitere Einstellungen

**Settings → General**
```
✅ Issues aktivieren
✅ Projects aktivieren (für Roadmap/Kanban)
☐ Wiki → nicht nötig (docs/ Ordner reicht)
```

**Settings → Security**
```
✅ Dependency graph aktivieren
✅ Dependabot alerts aktivieren
✅ Dependabot security updates aktivieren
✅ Secret scanning aktivieren
✅ Push protection aktivieren  (verhindert accidentelles Pushen von Secrets)
```

**Settings → Code and automation → Actions**
```
✅ Allow all actions and reusable workflows
   (oder restriktiver: nur verified creators)
```

### CODEOWNERS einrichten

```
# .github/CODEOWNERS
# Standardmäßig beide als Owner
*                           @username1 @username2

# Kritische Backend-Komponenten
backend/app/evaluator/      @username1
backend/app/scraper/        @username1
backend/app/db/             @username1

# Frontend – Lernbereich für username2
frontend/src/components/    @username2
frontend/src/pages/         @username2

# Infrastruktur immer beide
infrastructure/             @username1 @username2
.github/                    @username1 @username2
```

### PR-Template

```markdown
<!-- .github/PULL_REQUEST_TEMPLATE.md -->
## Was ändert dieser PR?

<!-- Kurze Beschreibung der Änderung -->

## Typ

- [ ] `feat` – neue Funktionalität
- [ ] `fix` – Bugfix
- [ ] `refactor` – Umbau ohne Verhaltensänderung
- [ ] `test` – Tests hinzugefügt/geändert
- [ ] `docs` – Dokumentation
- [ ] `chore` – Dependencies, Config

## Warum?

<!-- Kontext und Motivation falls nicht selbsterklärend -->

## Testing

- [ ] Unit Tests hinzugefügt / angepasst
- [ ] Integration Tests hinzugefügt / angepasst
- [ ] Manuell getestet: _kurze Beschreibung_

## Checkliste

- [ ] `make lint` läuft ohne Fehler
- [ ] `make test` läuft ohne Fehler
- [ ] OpenAPI-Schema aktualisiert (`make types`) – falls API geändert
- [ ] Designdokument aktualisiert – falls Architektur geändert
- [ ] KEIN API-Key oder Secret im Code

## Screenshots / Output

<!-- Falls relevant: Terminal-Output, Dashboard-Screenshot, etc. -->
```

---

## 10. Architecture Decision Records

ADRs dokumentieren **warum** eine Entscheidung getroffen wurde –
nicht nur was entschieden wurde. Format ist bewusst kurz gehalten.

```markdown
<!-- docs/adr/001-sqlite-over-postgres.md -->
# ADR-001: SQLite statt PostgreSQL

**Status:** Akzeptiert  
**Datum:** März 2025  
**Beteiligte:** beide

## Kontext

Das System läuft lokal auf einem einzelnen Rechner.
Kein Concurrent-Write-Problem, kein Multi-User-Zugriff.

## Entscheidung

SQLite als einzige relationale Datenbank.

## Begründung

- Kein separater Datenbankservice nötig
- Backup = eine Datei kopieren (`cp jobs.db jobs.db.backup`)
- Ausreichend für das Abfragevolumen (~200 neue Stellen täglich)
- Einfacheres lokales Setup für Entwicklung

## Konsequenzen

- Migration zu PostgreSQL nötig falls:
  - Multi-User-Zugriff entsteht
  - Concurrent Writes zum Problem werden
  - Volltextsuche über FTS5 hinaus benötigt wird
- SQLite FTS5-Extension verfügbar für Volltext-Suche falls nötig
```

Weitere ADRs anlegen für:
- `002-ollama-native-vs-docker.md`
- `003-monorepo-structure.md`
- `004-evaluation-ab-test-strategy.md`
- `005-rag-chromadb-embedded.md`

---

## 11. Für Einsteiger

Dieser Abschnitt richtet sich an Personen die neu ins Projekt einsteigen.

### Lokale Umgebung einrichten

```bash
# 1. Voraussetzungen prüfen
python --version    # >= 3.12
node --version      # >= 20
docker --version    # >= 24
ollama --version    # installiert? sonst: curl -fsSL https://ollama.ai/install.sh | sh

# 2. Repo klonen + Setup
git clone https://github.com/DEIN-USERNAME/job-agent.git
cd job-agent
make setup

# 3. .env ausfüllen (keine API-Keys, nur Config)
cp .env.example .env

# 4. API-Key sicher ablegen
mkdir -p secrets
echo "sk-ant-..." > secrets/anthropic_key.txt

# 5. Ollama-Modelle laden (einmalig, ~8GB Download)
ollama pull mistral-nemo:12b
ollama pull nomic-embed-text

# 6. Starten
make dev
```

### Erster eigener Beitrag

```bash
# 1. Issue aussuchen (Label: good-first-issue)
# 2. Branch erstellen
git checkout -b feature/mein-erstes-feature

# 3. Änderungen machen

# 4. Tests prüfen
make test

# 5. Linting prüfen
make lint

# 6. Commit
git add -p
git commit -m "feat(frontend): add score color indicator to job list"

# 7. Push + PR öffnen
git push -u origin feature/mein-erstes-feature
```

### Häufige Probleme

**`make lint` schlägt fehl:**
```bash
cd backend && ruff check --fix .   # Automatisch fixen
cd backend && ruff format .
```

**Tests schlagen fehl wegen fehlender DB:**
```bash
make migrate    # DB-Schema anlegen
```

**API-Typen veraltet:**
```bash
make types      # Neu generieren
git add frontend/src/types/api.ts
git commit -m "chore: update generated API types"
```

**Ollama nicht erreichbar:**
```bash
ollama serve    # Ollama-Server starten (falls nicht als Service)
```

### Nützliche Ressourcen

- [FastAPI Docs](https://fastapi.tiangolo.com)
- [React Docs](https://react.dev)
- [shadcn/ui Komponenten](https://ui.shadcn.com)
- [TanStack Query](https://tanstack.com/query)
- [Conventional Commits](https://www.conventionalcommits.org)
- [Pytest Dokumentation](https://docs.pytest.org)
- [Vitest Dokumentation](https://vitest.dev)

---

*Fragen? Issue öffnen oder direkt im PR kommentieren.*
