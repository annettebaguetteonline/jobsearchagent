-- Migration 003: Multi-User-Support
-- Neue Tabelle: users (UUID PK)
-- user_id FK in: evaluations, feedback, cover_letters, preference_patterns

-- ─── Users ───────────────────────────────────────────────────────────────────

CREATE TABLE users (
    id              TEXT PRIMARY KEY,   -- UUID
    name            TEXT NOT NULL,
    surname         TEXT,
    profile_json    TEXT,               -- Kernprofil-JSON
    profile_version TEXT,               -- SHA256 des Profils
    folder          TEXT,               -- Pfad zu User-Dokumenten
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Default-User für bestehende Daten
INSERT INTO users (id, name, created_at, updated_at)
VALUES ('00000000-0000-0000-0000-000000000001', 'Default User',
        datetime('now'), datetime('now'));

-- ─── evaluations: Tabelle neu erstellen (UNIQUE-Constraint ändern) ───────────
--
-- SQLite unterstützt kein ALTER TABLE ... ADD UNIQUE oder DROP CONSTRAINT.
-- Lösung: neue Tabelle erstellen, Daten kopieren, alte löschen, umbenennen.

CREATE TABLE evaluations_new (
    id                        INTEGER PRIMARY KEY,
    job_id                    INTEGER NOT NULL REFERENCES jobs(id),
    user_id                   TEXT NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001'
                                  REFERENCES users(id),
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
    needs_reevaluation        INTEGER NOT NULL DEFAULT 0,  -- Boolean
    UNIQUE(job_id, user_id)
);

INSERT INTO evaluations_new
    SELECT id, job_id, '00000000-0000-0000-0000-000000000001',
           eval_strategy, stage1_pass, stage1_reason, stage1_model, stage1_ms,
           stage2_score, stage2_score_breakdown, stage2_recommendation,
           stage2_match_reasons, stage2_missing_skills, stage2_salary_estimate,
           stage2_summary, stage2_application_tips, stage2_model,
           stage2_tokens_used, stage2_ms, location_score,
           location_effective_minutes, evaluated_at, profile_version,
           needs_reevaluation
    FROM evaluations;

DROP TABLE evaluations;
ALTER TABLE evaluations_new RENAME TO evaluations;

-- ─── feedback: user_id ergänzen ──────────────────────────────────────────────

ALTER TABLE feedback ADD COLUMN
    user_id TEXT NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001'
    REFERENCES users(id);

-- ─── cover_letters: user_id ergänzen ─────────────────────────────────────────

ALTER TABLE cover_letters ADD COLUMN
    user_id TEXT NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001'
    REFERENCES users(id);

-- ─── preference_patterns: user_id ergänzen ───────────────────────────────────

ALTER TABLE preference_patterns ADD COLUMN
    user_id TEXT NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001'
    REFERENCES users(id);

-- ─── Indizes ─────────────────────────────────────────────────────────────────

CREATE INDEX idx_users_name    ON users(name);
CREATE INDEX idx_eval_user     ON evaluations(user_id);
CREATE INDEX idx_eval_job_user ON evaluations(job_id, user_id);
CREATE INDEX idx_feedback_user ON feedback(user_id);
CREATE INDEX idx_cover_user    ON cover_letters(user_id);
