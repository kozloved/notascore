-- Pass 4: account-owned scores.
-- Additive. Safe to run on existing SQLite/Postgres job databases.
-- Runtime also applies these columns via database._ensure_job_ownership_columns().

ALTER TABLE jobs ADD COLUMN user_id VARCHAR;
ALTER TABLE jobs ADD COLUMN title VARCHAR;
ALTER TABLE jobs ADD COLUMN duration_seconds INTEGER;
ALTER TABLE jobs ADD COLUMN claim_token_hash VARCHAR;
ALTER TABLE jobs ADD COLUMN deleted_at VARCHAR;

CREATE INDEX IF NOT EXISTS ix_jobs_user_created ON jobs (user_id, created_at);
CREATE INDEX IF NOT EXISTS ix_jobs_claim_token_hash ON jobs (claim_token_hash);

-- Ownership is enforced in the FastAPI layer from the Supabase JWT `sub`.
-- Job metadata lives in this application database, not Supabase Postgres,
-- so Row Level Security is not applicable here. Do not expose
-- SUPABASE_SERVICE_ROLE_KEY to the browser.
