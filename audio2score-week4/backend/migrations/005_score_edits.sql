-- Pass 5: edited score representation.
-- Additive. Original MusicXML/MIDI sidecars are never overwritten.
-- Runtime also applies these columns via database._ensure_score_edit_columns().

ALTER TABLE jobs ADD COLUMN edited_result_storage_key VARCHAR;
ALTER TABLE jobs ADD COLUMN edit_revision INTEGER DEFAULT 0;
