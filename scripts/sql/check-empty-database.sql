\set ON_ERROR_STOP on

DO $$
DECLARE
    relation_count integer;
    routine_count integer;
    type_count integer;
    custom_schema_count integer;
BEGIN
    SELECT COUNT(*) INTO relation_count
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public'
      AND c.relkind IN ('r', 'p', 'v', 'm', 'S', 'f');

    SELECT COUNT(*) INTO routine_count
    FROM pg_proc p
    JOIN pg_namespace n ON n.oid = p.pronamespace
    WHERE n.nspname = 'public';

    SELECT COUNT(*) INTO type_count
    FROM pg_type t
    JOIN pg_namespace n ON n.oid = t.typnamespace
    WHERE n.nspname = 'public'
      AND t.typrelid = 0;

    SELECT COUNT(*) INTO custom_schema_count
    FROM pg_namespace
    WHERE nspname <> 'public'
      AND nspname <> 'information_schema'
      AND nspname NOT LIKE 'pg\_%' ESCAPE '\';

IF relation_count > 0
   OR routine_count > 0
   OR type_count > 0
   OR custom_schema_count > 0 THEN

    RAISE EXCEPTION
        'Restore blocked: relations=%, routines=%, types=%, custom_schemas=%',
        relation_count,
        routine_count,
        type_count,
        custom_schema_count;
END IF;

    RAISE NOTICE 'PASS: No conflicting public schema objects detected';
END
$$;
