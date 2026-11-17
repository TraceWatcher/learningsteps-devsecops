
import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Make application imports available
sys.path.insert(
    0, str(Path(__file__).resolve().parents[1] / "api")
)

# The app requires this variable during import.
# No database connection is made in these tests.
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql://test:test@localhost:5432/test"
)

from main import app
from routers.journal_router import get_entry_service


class FakeEntryService:
    async def get_all_entries(self):
        return []

    async def get_entry(self, entry_id):
        return None


@pytest.fixture
def client():
    async def override_service():
        yield FakeEntryService()

    app.dependency_overrides[get_entry_service] = override_service

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
