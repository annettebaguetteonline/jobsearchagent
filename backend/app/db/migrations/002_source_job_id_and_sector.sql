-- Migration 002: source_job_id in job_sources, sector in jobs

ALTER TABLE job_sources ADD COLUMN source_job_id TEXT;

CREATE INDEX IF NOT EXISTS idx_job_sources_source_job_id
    ON job_sources(source_name, source_job_id)
    WHERE source_job_id IS NOT NULL;

ALTER TABLE jobs ADD COLUMN sector TEXT;
-- 'public'|'private'|NULL (NULL = unbekannt/nicht zugeordnet)
