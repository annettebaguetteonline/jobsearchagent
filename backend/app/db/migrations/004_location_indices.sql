-- Migration 004: Zusätzliche Indizes für Location-Pipeline
CREATE INDEX IF NOT EXISTS idx_companies_address_status ON companies(address_status);
CREATE INDEX IF NOT EXISTS idx_jobs_location_status ON jobs(location_status, is_active);
CREATE INDEX IF NOT EXISTS idx_transit_expires ON transit_cache(expires_at);
