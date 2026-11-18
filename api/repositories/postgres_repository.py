import json
import os
import ssl
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import asyncpg
from dotenv import load_dotenv
from repositories.interface_repository import DatabaseInterface

load_dotenv()

class PostgresDB(DatabaseInterface):
    def __init__(self, pool=None):
        self.pool = pool
        self._owns_pool = False

    @staticmethod
    def datetime_serialize(obj):
        """Convert datetime objects to ISO format for JSON serialization."""
        if isinstance(obj, datetime):
                return obj.isoformat()
        raise TypeError(f"Type {type(obj)} not serializable")

    @staticmethod
    async def create_pool():
        password_file = os.getenv("DB_PASSWORD_FILE")

        if password_file:
            # Azure AKS: Password from Key Vault CSI mount
            password = Path(password_file).read_text().strip()

            return await asyncpg.create_pool(
                host=os.environ["DB_HOST"],
                port=5432,
                user=os.environ["DB_USER"],
                password=password,
                database=os.environ["DB_NAME"],
                ssl=ssl.create_default_context(),
                min_size=0,
                max_size=3,
            )

        # Local Docker Compose
        return await asyncpg.create_pool(
            os.environ["DATABASE_URL"],
            min_size=0,
            max_size=3,
        )

    async def __aenter__(self):
        if self.pool is None:
            self.pool = await self.create_pool()
            self._owns_pool = True

        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        if self._owns_pool and self.pool is not None:
            await self.pool.close()
            self.pool = None
            self._owns_pool = False


    @staticmethod
    def _format_entry(row) -> Dict[str, Any]:
        """Convert a database row into an API entry."""
        data = json.loads(row["data"])

        return {
            "id": row["id"],
            "work": data.get("work", ""),
            "struggle": data.get("struggle", ""),
            "intention": data.get("intention", ""),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    @staticmethod
    def _owner_uuid(owner_id: str) -> uuid.UUID:
        """Validate and convert a user object ID."""
        return uuid.UUID(str(owner_id))

    async def create_entry(
        self, entry_data: Dict[str, Any], owner_id: str
    ) -> Dict[str, Any]:
        owner = self._owner_uuid(owner_id)
        entry_id = entry_data.get("id") or str(uuid.uuid4())
        data_json = json.dumps(
            entry_data, default=self.datetime_serialize
        )

        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO entries
                    (id, owner_id, data, created_at, updated_at)
                VALUES ($1, $2, $3, $4, $5)
                RETURNING *
                """,
                entry_id,
                owner,
                data_json,
                entry_data["created_at"],
                entry_data["updated_at"],
            )

        return self._format_entry(row)

    async def get_all_entries(
        self, owner_id: str
    ) -> List[Dict[str, Any]]:
        owner = self._owner_uuid(owner_id)

        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT *
                FROM entries
                WHERE owner_id = $1
                ORDER BY created_at DESC, id DESC
                """,
                owner,
            )

        return [self._format_entry(row) for row in rows]

    async def get_entry(
        self, entry_id: str, owner_id: str
    ) -> Dict[str, Any] | None:
        owner = self._owner_uuid(owner_id)

        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT *
                FROM entries
                WHERE id = $1 AND owner_id = $2
                """,
                entry_id,
                owner,
            )

        return self._format_entry(row) if row else None

    async def update_entry(
        self,
        entry_id: str,
        updated_data: Dict[str, Any],
        owner_id: str,
    ) -> Dict[str, Any] | None:
        owner = self._owner_uuid(owner_id)
        updated_at = datetime.now(timezone.utc)

        data_json = json.dumps(
            updated_data, default=self.datetime_serialize
        )

        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                UPDATE entries
                SET data = $3, updated_at = $4
                WHERE id = $1 AND owner_id = $2
                RETURNING *
                """,
                entry_id,
                owner,
                data_json,
                updated_at,
            )

        return self._format_entry(row) if row else None

    async def delete_entry(
        self, entry_id: str, owner_id: str
    ) -> bool:
        owner = self._owner_uuid(owner_id)

        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                DELETE FROM entries
                WHERE id = $1 AND owner_id = $2
                RETURNING id
                """,
                entry_id,
                owner,
            )

        return row is not None

    async def delete_all_entries(self, owner_id: str) -> int:
        owner = self._owner_uuid(owner_id)

        async with self.pool.acquire() as conn:
            result = await conn.execute(
                """
                DELETE FROM entries
                WHERE owner_id = $1
                """,
                owner,
            )

        return int(result.rsplit(" ", 1)[-1])

    async def get_entries_for_summary(
        self, owner_id: str, limit: int = 21
    ) -> List[Dict[str, Any]]:
        """Fetch only this user's notes for AI summarization."""
        owner = self._owner_uuid(owner_id)

        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT data
                FROM entries
                WHERE owner_id = $1
                ORDER BY created_at DESC, id DESC
                LIMIT $2
                """,
                owner,
                limit,
            )

        return [json.loads(row["data"]) for row in rows]
