-- Phase 1: dedicated lease + retry columns.
-- Additive. Runtime also applies these via database._ensure_lease_columns().

ALTER TABLE jobs ADD COLUMN lease_expires_at VARCHAR;
ALTER TABLE jobs ADD COLUMN retry_count INTEGER DEFAULT 0;
