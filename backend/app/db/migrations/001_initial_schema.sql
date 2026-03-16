-- Migration 001: Initiales Datenbankschema
-- Alle Tabellen und Indizes für den Job Search Agent

-- ─── Unternehmen ────────────────────────────────────────────────────────────

CREATE TABLE companies (
    id                    INTEGER PRIMARY KEY,
    name                  TEXT NOT NULL,
    name_normalized       TEXT NOT NULL,
    name_aliases          TEXT,              -- JSON-Array
    address_street        TEXT,
    address_city          TEXT,
    address_zip           TEXT,
    lat                   REAL,
    lng                   REAL,
    address_status        TEXT DEFAULT 'unknown',  -- 'unknown'|'found'|'failed'
    address_source        TEXT,             -- 'db'|'impressum'|'searxng'|'nominatim'
    agent_findings        TEXT,             -- JSON: Zwischenergebnisse der Adressrecherche
    remote_policy         TEXT DEFAULT 'unknown',  -- 'unknown'|'remote'|'hybrid'|'onsite'
    careers_url           TEXT,
    ats_system            TEXT,             -- 'lever'|'greenhouse'|'personio'|'softgarden'|...
    created_at            TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at            TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE transit_cache (
    company_id      INTEGER NOT NULL REFERENCES companies(id),
    origin_hash     TEXT NOT NULL,           -- SHA256-Hash der Heimatadresse (nie im Klartext)
    transit_minutes INTEGER NOT NULL,
    api_used        TEXT,                    -- 'db_rest'|'transport_rest'
    cached_at       TEXT NOT NULL,
    expires_at      TEXT NOT NULL,
    UNIQUE(company_id, origin_hash)
);

-- ─── Stellen & Quellen ──────────────────────────────────────────────────────

CREATE TABLE jobs (
    id                  INTEGER PRIMARY KEY,
    canonical_id        TEXT UNIQUE NOT NULL, -- SHA256(norm_title|norm_company|norm_location)
    title               TEXT NOT NULL,
    company_id          INTEGER REFERENCES companies(id),
    location_raw        TEXT,
    location_status     TEXT NOT NULL DEFAULT 'unknown',  -- 'unknown'|'resolved'|'failed'
    work_model          TEXT,               -- 'remote'|'hybrid'|'onsite'|'unknown'
    hybrid_days_hint    INTEGER,            -- Tage/Woche vor Ort (falls bekannt)
    salary_raw          TEXT,
    salary_min          INTEGER,
    salary_max          INTEGER,
    deadline            TEXT,               -- ISO-8601-Datum
    first_seen_at       TEXT NOT NULL,
    last_seen_at        TEXT NOT NULL,
    status              TEXT NOT NULL DEFAULT 'new',
    -- 'new'|'reviewed'|'applying'|'applied'|'interview'|'offer'|'rejected'|'expired'|'ignored'
    is_active           INTEGER NOT NULL DEFAULT 1,  -- Boolean (SQLite)
    content_hash        TEXT,
    raw_text            TEXT,
    change_history      TEXT,              -- JSON-Array von Änderungen
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE job_sources (
    id              INTEGER PRIMARY KEY,
    job_id          INTEGER NOT NULL REFERENCES jobs(id),
    url             TEXT UNIQUE NOT NULL,
    source_name     TEXT NOT NULL,         -- 'stepstone'|'indeed'|'service_bund'|...
    source_type     TEXT NOT NULL,         -- 'aggregator'|'portal'|'direct'|'ats'
    is_canonical    INTEGER NOT NULL DEFAULT 0,  -- Boolean
    first_seen_at   TEXT NOT NULL,
    last_seen_at    TEXT NOT NULL,
    last_checked_at TEXT,
    is_available    INTEGER,               -- Boolean, NULL = unbekannt
    content_hash    TEXT
);

-- ─── Evaluierungen ──────────────────────────────────────────────────────────

CREATE TABLE evaluations (
    id                        INTEGER PRIMARY KEY,
    job_id                    INTEGER UNIQUE NOT NULL REFERENCES jobs(id),
    eval_strategy             TEXT,        -- 'full_profile'|'structured_core'|'rag_hybrid'
    stage1_pass               INTEGER,     -- Boolean
    stage1_reason             TEXT,
    stage1_model              TEXT,
    stage1_ms                 INTEGER,
    stage2_score              REAL,        -- 1.0–10.0
    stage2_score_breakdown    TEXT,        -- JSON: {skills, level, domain, location, potential}
    stage2_recommendation     TEXT,        -- 'APPLY'|'MAYBE'|'SKIP'
    stage2_match_reasons      TEXT,        -- JSON-Array
    stage2_missing_skills     TEXT,        -- JSON-Array
    stage2_salary_estimate    TEXT,
    stage2_summary            TEXT,
    stage2_application_tips   TEXT,        -- JSON-Array
    stage2_model              TEXT,
    stage2_tokens_used        INTEGER,
    stage2_ms                 INTEGER,
    location_score            REAL,
    location_effective_minutes INTEGER,
    evaluated_at              TEXT NOT NULL,
    profile_version           TEXT,        -- Hash des Kernprofils zum Zeitpunkt der Evaluierung
    needs_reevaluation        INTEGER NOT NULL DEFAULT 0  -- Boolean
);

-- ─── Feedback-Loop ──────────────────────────────────────────────────────────

CREATE TABLE feedback (
    id                        INTEGER PRIMARY KEY,
    job_id                    INTEGER NOT NULL REFERENCES jobs(id),
    decision                  TEXT NOT NULL,  -- 'APPLY'|'MAYBE'|'IGNORE'|'SKIP'
    reasoning                 TEXT,           -- PRIVAT – wird beim Export entfernt
    model_score               REAL,
    model_recommendation      TEXT,
    score_delta               REAL,           -- decision_score - model_score
    job_snapshot              TEXT,           -- JSON (anonymisiert exportierbar)
    model_reasoning_snapshot  TEXT,
    decided_at                TEXT NOT NULL,
    feedback_version          INTEGER,
    is_seed                   INTEGER NOT NULL DEFAULT 0  -- Boolean
);

CREATE TABLE preference_patterns (
    id              INTEGER PRIMARY KEY,
    pattern_type    TEXT NOT NULL,         -- 'avoid_keyword'|'prefer_size'|...
    pattern_key     TEXT NOT NULL,
    pattern_value   TEXT,
    confidence      REAL,
    sample_count    INTEGER,
    last_updated    TEXT,
    is_active       INTEGER NOT NULL DEFAULT 1  -- Boolean
);

-- ─── Anschreiben ────────────────────────────────────────────────────────────

CREATE TABLE cover_letters (
    id                      INTEGER PRIMARY KEY,
    job_id                  INTEGER NOT NULL REFERENCES jobs(id),
    version                 INTEGER NOT NULL DEFAULT 1,
    subject                 TEXT,
    salutation              TEXT,
    body                    TEXT NOT NULL,   -- JSON mit Absätzen (siehe Design-Dokument)
    closing                 TEXT,
    model_used              TEXT,
    tokens_used             INTEGER,
    profile_version         TEXT,
    rag_chunks_used         TEXT,            -- JSON-Array
    feedback_examples_used  INTEGER,
    quality_score           REAL,
    quality_feedback        TEXT,            -- JSON: Verbesserungshinweise
    is_sent                 INTEGER NOT NULL DEFAULT 0,  -- Boolean
    sent_at                 TEXT,
    notes                   TEXT,
    created_at              TEXT NOT NULL DEFAULT (datetime('now')),
    is_active               INTEGER NOT NULL DEFAULT 1   -- Boolean
);

-- ─── Analytics ──────────────────────────────────────────────────────────────

CREATE TABLE job_skills (
    job_id      INTEGER NOT NULL REFERENCES jobs(id),
    skill       TEXT NOT NULL,
    skill_type  TEXT,    -- 'required'|'nice_to_have'|'mentioned'
    confidence  REAL,
    PRIMARY KEY (job_id, skill)
);

CREATE TABLE skill_trends (
    skill           TEXT NOT NULL,
    period_start    TEXT NOT NULL,  -- ISO-8601 Wochen-/Monatsanfang
    job_count       INTEGER,
    avg_salary_min  INTEGER,
    source_mix      TEXT,           -- JSON: {stepstone: 5, indeed: 3}
    PRIMARY KEY (skill, period_start)
);

-- ─── Scraping-Log & Klärungsbedarf ──────────────────────────────────────────

CREATE TABLE scrape_runs (
    id              INTEGER PRIMARY KEY,
    started_at      TEXT NOT NULL,
    finished_at     TEXT,
    status          TEXT NOT NULL DEFAULT 'running',  -- 'running'|'finished'|'failed'
    sources_run     TEXT,           -- JSON-Array: ["stepstone", "indeed"]
    stats           TEXT,           -- JSON: {fetched, new, duplicate, skipped, errors}
    error_log       TEXT            -- JSON-Array von Fehlermeldungen
);

CREATE TABLE clarification_queue (
    id              INTEGER PRIMARY KEY,
    entity_type     TEXT NOT NULL,  -- 'job'|'company'
    entity_id       INTEGER NOT NULL,
    issue_type      TEXT NOT NULL,  -- 'address_unknown'|'website_unknown'|'salary_parse'|...
    priority        TEXT NOT NULL DEFAULT 'normal',   -- 'high'|'normal'|'low'
    severity        TEXT NOT NULL DEFAULT 'yellow',   -- 'red'|'yellow'
    attempts        TEXT,           -- JSON-Array: [{stage, tried_at, result}]
    last_attempt_at TEXT,
    resolved        INTEGER NOT NULL DEFAULT 0,  -- Boolean
    resolved_at     TEXT,
    resolved_by     TEXT,           -- 'manual'|'stage4_llm'|'auto'
    resolution_note TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ─── Indizes ────────────────────────────────────────────────────────────────

CREATE INDEX idx_jobs_status       ON jobs(status);
CREATE INDEX idx_jobs_canonical    ON jobs(canonical_id);
CREATE INDEX idx_jobs_company      ON jobs(company_id);
CREATE INDEX idx_jobs_deadline     ON jobs(deadline);
CREATE INDEX idx_eval_score        ON evaluations(stage2_score);
CREATE INDEX idx_eval_strategy     ON evaluations(eval_strategy);
CREATE INDEX idx_eval_profile      ON evaluations(profile_version);
CREATE INDEX idx_feedback_decision ON feedback(decision);
CREATE INDEX idx_feedback_delta    ON feedback(score_delta);
CREATE INDEX idx_clarif_open       ON clarification_queue(resolved, priority);
CREATE INDEX idx_companies_name    ON companies(name_normalized);
CREATE INDEX idx_transit_company   ON transit_cache(company_id, origin_hash);
