
BEGIN;

DO $$
DECLARE
    rejected BOOLEAN := FALSE;
BEGIN
    BEGIN
        INSERT INTO public.entries (
            id, data, created_at, updated_at
        )
        VALUES (
            'owner-required-negative-test',
            '{"work": "Unauthorized entry"}'::jsonb,
            NOW(),
            NOW()
        );

    EXCEPTION WHEN check_violation THEN
        rejected := TRUE;
        RAISE NOTICE 'PASS: Entry without owner_id rejected';
    END;

    IF NOT rejected THEN
        RAISE EXCEPTION 'FAIL: Entry without owner_id accepted';
    END IF;
END
$$;

ROLLBACK;
