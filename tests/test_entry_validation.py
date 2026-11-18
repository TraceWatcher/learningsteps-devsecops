import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[1] / "api"),
)

from models.entry import EntryUpdate  # noqa: E402


def test_valid_partial_update():
    update = EntryUpdate(work="  Kubernetes gelernt  ")

    assert update.model_dump(exclude_unset=True) == {
        "work": "Kubernetes gelernt"
    }


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"work": ""},
        {"work": "ab"},
        {"work": None},
        {"work": "x" * 257},
        {"owner_id": "11111111-1111-4111-8111-111111111111"},
        {"id": "manipulated"},
        {"created_at": "2026-11-18T00:00:00Z"},
    ],
)
def test_invalid_update(payload):
    with pytest.raises(ValidationError):
        EntryUpdate(**payload)
