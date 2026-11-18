-- LearningSteps: Multi-user database migration
-- Adds Entra ID ownership to journal entries.
-- Existing entries remain unassigned.

BEGIN;

ALTER TABLE public.entries
    ADD COLUMN IF NOT EXISTS owner_id UUID;

CREATE INDEX IF NOT EXISTS idx_entries_owner_created
    ON public.entries (owner_id, created_at DESC);

COMMIT;
