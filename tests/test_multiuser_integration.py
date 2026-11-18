import asyncio
import os
import sys
from pathlib import Path
from urllib.parse import quote
from uuid import UUID, uuid4

import asyncpg
import pytest
from dotenv import dotenv_values
from fastapi.testclient import TestClient

sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[1] / "api"),
)

from main import app  # noqa: E402
from repositories.postgres_repository import PostgresDB  # noqa: E402
from security.auth import get_current_user  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def local_database_url():
    """Use only the local Docker PostgreSQL instance."""
    values = dotenv_values(PROJECT_ROOT / ".env")

    user = values.get("POSTGRES_USER")
    password = values.get("POSTGRES_PASSWORD")
    database = values.get("POSTGRES_DB")

    if not all([user, password, database]):
        pytest.skip("Local PostgreSQL credentials missing in .env")

    return (
        f"postgresql://{quote(user, safe='')}:"
        f"{quote(password, safe='')}"
        f"@127.0.0.1:5433/{quote(database, safe='')}"
    )


async def cleanup_test_entries(dsn, user_ids):
    conn = await asyncpg.connect(dsn)
    try:
        await conn.execute(
            "DELETE FROM entries WHERE owner_id = ANY($1::uuid[])",
            [UUID(value) for value in user_ids],
        )
    finally:
        await conn.close()


async def check_summary_isolation(dsn, user_a, user_b):
    pool = await asyncpg.create_pool(dsn=dsn)
    try:
        db = PostgresDB(pool=pool)

        notes_a = await db.get_entries_for_summary(user_a)
        notes_b = await db.get_entries_for_summary(user_b)

        return notes_a, notes_b
    finally:
        await pool.close()


@pytest.mark.integration
def test_multiuser_isolation(monkeypatch):
    if os.getenv("RUN_DB_INTEGRATION") != "1":
        pytest.skip(
            "Requires local PostgreSQL; "
            "set RUN_DB_INTEGRATION=1"
    )

    dsn = local_database_url()

    user_a = str(uuid4())
    user_b = str(uuid4())

    # Both identities are simulated only inside this test.
    current_user = {"id": user_a}

    def override_auth():
        return {
            "user_id": current_user["id"],
            "tenant_id": "c0531484-50fa-4ff2-97df-b1f2d4810603",
        }

    monkeypatch.setenv("DATABASE_URL", dsn)
    app.dependency_overrides[get_current_user] = override_auth

    try:
        with TestClient(app) as client:

            # User A creates a note.
            response = client.post(
                "/entries",
                json={
                    "work": "Private learning note A",
                    "struggle": "Terraform networking",
                    "intention": "Improve Azure security",
                },
            )
            assert response.status_code == 200, response.text
            entry_a = response.json()["entry"]["id"]

            # User B creates a different note.
            current_user["id"] = user_b

            response = client.post(
                "/entries",
                json={
                    "work": "Private learning note B",
                    "struggle": "Kubernetes RBAC",
                    "intention": "Improve cluster security",
                },
            )
            assert response.status_code == 200, response.text
            entry_b = response.json()["entry"]["id"]

            # User B can see only their own entry.
            response = client.get("/entries")
            assert response.status_code == 200
            assert response.json()["count"] == 1
            assert response.json()["entries"][0]["id"] == entry_b

            # User B cannot read A's entry.
            assert client.get(
                f"/entries/{entry_a}"
            ).status_code == 404

            # User B cannot update A's entry.
            assert client.patch(
                f"/entries/{entry_a}",
                json={"work": "Unauthorized change"},
            ).status_code == 404

            # User B cannot delete A's entry.
            assert client.delete(
                f"/entries/{entry_a}"
            ).status_code == 404

            # User B deletes only their own entries.
            response = client.delete("/entries")
            assert response.status_code == 200
            assert response.json()["deleted_count"] == 1

            # User A's entry must still exist.
            current_user["id"] = user_a

            response = client.get(f"/entries/{entry_a}")
            assert response.status_code == 200
            assert response.json()["work"] == (
                "Private learning note A"
            )

            # Verify the repository's AI data selection.
            notes_a, notes_b = asyncio.run(
                check_summary_isolation(dsn, user_a, user_b)
            )

            assert len(notes_a) == 1
            assert notes_a[0]["work"] == "Private learning note A"
            assert notes_b == []

            # User A deletes their own entry.
            assert client.delete(
                f"/entries/{entry_a}"
            ).status_code == 200

            assert client.get("/entries").json()["count"] == 0

    finally:
        app.dependency_overrides.pop(get_current_user, None)
        asyncio.run(cleanup_test_entries(dsn, [user_a, user_b]))
