-- LearningSteps multi-user migration, phase 2
-- Existing ownerless records remain intact.
-- New records must have an owner_id.

BEGIN;

ALTER TABLE public.entries
ADD CONSTRAINT entries_owner_required
CHECK (owner_id IS NOT NULL)
NOT VALID;

COMMIT;
