BEGIN;

INSERT INTO entries (
    id, owner_id, data, created_at, updated_at
)
VALUES
(
    'isolation-test-a',
    '11111111-1111-4111-8111-111111111111',
    '{"work":"Private Notiz von Benutzer A"}'::jsonb,
    NOW(),
    NOW()
),
(
    'isolation-test-b',
    '22222222-2222-4222-8222-222222222222',
    '{"work":"Private Notiz von Benutzer B"}'::jsonb,
    NOW(),
    NOW()
);

-- Benutzer A: Erwartet genau eine eigene Notiz.
SELECT id, data->>'work' AS work
FROM entries
WHERE owner_id = '11111111-1111-4111-8111-111111111111';

-- Benutzer B: Erwartet genau eine andere Notiz.
SELECT id, data->>'work' AS work
FROM entries
WHERE owner_id = '22222222-2222-4222-8222-222222222222';

-- Benutzer A versucht, die Notiz von Benutzer B zu ändern.
-- Erwartet: UPDATE 0.
UPDATE entries
SET data = '{"work":"Manipuliert"}'::jsonb
WHERE id = 'isolation-test-b'
  AND owner_id = '11111111-1111-4111-8111-111111111111';

-- Benutzer A versucht, die Notiz von Benutzer B zu löschen.
-- Erwartet: DELETE 0.
DELETE FROM entries
WHERE id = 'isolation-test-b'
  AND owner_id = '11111111-1111-4111-8111-111111111111';

-- Testdaten werden vollständig zurückgerollt.
ROLLBACK;
