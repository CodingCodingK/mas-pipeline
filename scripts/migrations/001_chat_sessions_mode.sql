-- Phase 6.1: add `mode` column to chat_sessions
-- Idempotent: safe to run on a fresh DB or an existing one.
-- Existing rows are backfilled with 'chat' (the previous implicit behavior).

ALTER TABLE chat_sessions
    ADD COLUMN IF NOT EXISTS mode VARCHAR(20) NOT NULL DEFAULT 'chat';

-- Add CHECK constraint if it doesn't exist yet (Postgres < 12 lacks IF NOT EXISTS,
-- so wrap in DO block for portability).
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'chat_sessions_mode_check'
    ) THEN
        ALTER TABLE chat_sessions
            ADD CONSTRAINT chat_sessions_mode_check
            CHECK (mode IN ('chat', 'autonomous'));
    END IF;
END $$;
