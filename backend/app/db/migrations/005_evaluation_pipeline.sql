-- Migration 005: Evaluierungs-Pipeline-Erweiterungen
-- Batch-Tracking für Stage 2 (Anthropic Batch API) und Performance-Indizes.

-- ─── Batch-Tracking ─────────────────────────────────────────────────────────
-- Verfolgt asynchrone Stage-2-Batch-Läufe über die Anthropic Batch API.
-- Status-Übergänge: submitted → processing → ended | failed | expired

CREATE TABLE IF NOT EXISTS evaluation_batches (
    id              INTEGER PRIMARY KEY,
    user_id         TEXT NOT NULL REFERENCES users(id),
    batch_api_id    TEXT NOT NULL,
    strategy        TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'submitted',
    -- Erlaubte Status: 'submitted'|'processing'|'ended'|'failed'|'expired'
    job_count       INTEGER NOT NULL,
    completed_count INTEGER DEFAULT 0,
    error_count     INTEGER DEFAULT 0,
    submitted_at    TEXT NOT NULL,
    completed_at    TEXT,
    error_log       TEXT  -- JSON-Array mit Fehlermeldungen
);

CREATE INDEX IF NOT EXISTS idx_eval_batch_status ON evaluation_batches(status);
CREATE INDEX IF NOT EXISTS idx_eval_batch_user ON evaluation_batches(user_id);
CREATE INDEX IF NOT EXISTS idx_eval_batch_api_id ON evaluation_batches(batch_api_id);

-- ─── Performance-Indizes ────────────────────────────────────────────────────
-- Beschleunigen häufige Pipeline-Queries.

-- Stage 1: Finde aktive, neue Jobs die noch nicht evaluiert wurden
CREATE INDEX IF NOT EXISTS idx_jobs_active_new
    ON jobs(is_active, status) WHERE is_active = 1 AND status = 'new';

-- Re-Evaluierung: Finde alle Evaluierungen die nach Profiländerung neu bewertet werden müssen
CREATE INDEX IF NOT EXISTS idx_eval_needs_reeval
    ON evaluations(needs_reevaluation) WHERE needs_reevaluation = 1;

-- Job-Skills: Schneller Lookup aller Skills eines Jobs
CREATE INDEX IF NOT EXISTS idx_job_skills_job ON job_skills(job_id);
