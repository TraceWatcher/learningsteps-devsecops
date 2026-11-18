
import os
import sys
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[1] / "api"),
)

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql://test:test@localhost:5432/test",
)

from main import app  # noqa: E402
from routers.journal_router import get_entry_service  # noqa: E402
from security.auth import get_current_user  # noqa: E402

TEST_USER_ID = "11111111-1111-4111-8111-111111111111"


class FakeEntryService:
    async def get_all_entries(self, owner_id):
        assert UUID(owner_id) == UUID(TEST_USER_ID)
        return []

    async def get_entry(self, entry_id, owner_id):
        assert UUID(owner_id) == UUID(TEST_USER_ID)
        return None


@pytest.fixture
def client():
    async def override_service():
        yield FakeEntryService()

    async def override_user():
        return {
            "user_id": TEST_USER_ID,
            "tenant_id": "c0531484-50fa-4ff2-97df-b1f2d4810603",
        }

    app.dependency_overrides[get_entry_service] = override_service
    app.dependency_overrides[get_current_user] = override_user

    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()


def test_docs_available(client):
    response = client.get("/docs")

    assert response.status_code == 200
    assert "swagger" in response.text.lower()


def test_get_empty_entries(client):
    response = client.get("/entries")

    assert response.status_code == 200
    assert response.json() == {
        "entries": [],
        "count": 0,
    }


def test_entry_not_found(client):
    response = client.get("/entries/nonexistent-id")

    assert response.status_code == 404
    assert response.json()["detail"] == "Entry not found"


def test_entries_without_authentication():
    app.dependency_overrides.clear()

    try:
        with TestClient(app) as client:
            response = client.get("/entries")

        assert response.status_code == 401
    finally:
        app.dependency_overrides.clear()


def test_entry_by_id_without_authentication():
    app.dependency_overrides.clear()

    try:
        with TestClient(app) as client:
            response = client.get("/entries/some-id")

        assert response.status_code == 401
    finally:
        app.dependency_overrides.clear()