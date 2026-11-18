
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List

from repositories.postgres_repository import PostgresDB

logger = logging.getLogger("journal")

ALLOWED_ENTRY_FIELDS = {"work", "struggle", "intention"}


class EntryService:
    def __init__(self, db: PostgresDB):
        self.db = db

    async def create_entry(
        self,
        entry_data: Dict[str, Any],
        owner_id: str,
    ) -> Dict[str, Any]:
        """Create an entry owned by the authenticated user."""
        now = datetime.now(timezone.utc)

        data = {
            key: entry_data[key]
            for key in ALLOWED_ENTRY_FIELDS
            if key in entry_data
        }

        entry = {
            **data,
            "created_at": now,
            "updated_at": now,
        }

        logger.info("Creating entry for authenticated user")
        return await self.db.create_entry(entry, owner_id)

    async def get_all_entries(
        self, owner_id: str
    ) -> List[Dict[str, Any]]:
        """Return only the user's entries."""
        return await self.db.get_all_entries(owner_id)

    async def get_entry(
        self,
        entry_id: str,
        owner_id: str,
    ) -> Dict[str, Any] | None:
        """Return an entry only if owned by the user."""
        return await self.db.get_entry(entry_id, owner_id)

    async def update_entry(
        self,
        entry_id: str,
        updated_data: Dict[str, Any],
        owner_id: str,
    ) -> Dict[str, Any] | None:
        """Update permitted fields of an owned entry."""

        forbidden_fields = set(updated_data) - ALLOWED_ENTRY_FIELDS

        if forbidden_fields:
            raise ValueError(
                "Only work, struggle and intention may be updated"
            )

        existing_entry = await self.db.get_entry(
            entry_id, owner_id
        )

        if existing_entry is None:
            return None

        merged_data = {
            "work": existing_entry["work"],
            "struggle": existing_entry["struggle"],
            "intention": existing_entry["intention"],
            "created_at": existing_entry["created_at"],
            "updated_at": existing_entry["updated_at"],
            **updated_data,
        }

        # The database performs an atomic owner-checked UPDATE.
        return await self.db.update_entry(
            entry_id,
            merged_data,
            owner_id,
        )

    async def delete_entry(
        self,
        entry_id: str,
        owner_id: str,
    ) -> bool:
        """Delete an entry only if owned by the user."""
        return await self.db.delete_entry(
            entry_id, owner_id
        )

    async def delete_all_entries(
        self, owner_id: str
    ) -> int:
        """Delete only entries owned by the user."""
        return await self.db.delete_all_entries(owner_id)
