DO $$
DECLARE
    entry_count integer;
    constraint_count integer;
    index_count integer;
    primary_key_count integer;
BEGIN
    -- Verify restored application data.
    SELECT COUNT(*) INTO entry_count
    FROM public.entries;

    -- Verify expected constraints.
    SELECT COUNT(*) INTO constraint_count
    FROM pg_constraint
    WHERE conrelid = 'public.entries'::regclass
      AND conname IN (
          'entries_owner_required',
          'entries_pkey'
      );

    -- Verify the primary key constraint.
    SELECT COUNT(*) INTO primary_key_count
    FROM pg_constraint
    WHERE conrelid = 'public.entries'::regclass
      AND conname = 'entries_pkey'
      AND contype = 'p'
      AND convalidated = true;

    -- Verify expected application indexes.
    SELECT COUNT(*) INTO index_count
    FROM pg_indexes
    WHERE schemaname = 'public'
      AND tablename = 'entries'
      AND indexname IN (
          'idx_entries_created_at',
          'idx_entries_data_gin',
          'idx_entries_owner_created'
      );

    IF entry_count <> 4
       OR constraint_count <> 2
       OR primary_key_count <> 1
       OR index_count <> 3 THEN

        RAISE EXCEPTION
            'Recovery verification failed: entries=%, constraints=%, primary_keys=%, indexes=%',
            entry_count,
            constraint_count,
            primary_key_count,
            index_count;
    END IF;

    RAISE NOTICE
        'PASS: entries=%, constraints=%, primary_keys=%, indexes=%',
        entry_count,
        constraint_count,
        primary_key_count,
        index_count;
END
$$;
