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

    async def create_entry(self, entry_data: Dict[str, Any]) -> Dict[str, Any]:
        async with self.pool.acquire() as conn:
            query = """
            INSERT INTO entries (id, data, created_at, updated_at)
            VALUES ($1, $2, $3, $4)
            RETURNING *
            """
            entry_id = entry_data.get("id") or str(uuid.uuid4())
            data_json = json.dumps(entry_data, default=PostgresDB.datetime_serialize)

            row = await conn.fetchrow(
                query,
                entry_id,
                data_json,
                entry_data["created_at"],
                entry_data["updated_at"]
            )

            # Return a clean entry format without duplication
            if row:
                data = json.loads(row["data"])
                return {
                    "id": row["id"],
                    "work": data.get("work", ""),
                    "struggle": data.get("struggle", ""),
                    "intention": data.get("intention", ""),
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"]
                }
            return {}

    async def get_all_entries(self) -> List[Dict[str, Any]]:
        async with self.pool.acquire() as conn:
            query = "SELECT * FROM entries"
            rows = await conn.fetch(query)
            entries = []
            for row in rows:
                data = json.loads(row["data"])
                entries.append({
                    "id": row["id"],
                    "work": data.get("work", ""),
                    "struggle": data.get("struggle", ""),
                    "intention": data.get("intention", ""),
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"]
                })
            return entries

    async def get_entry(self, entry_id: str) -> Dict[str, Any] | None:
        async with self.pool.acquire() as conn:
            query = "SELECT * FROM entries WHERE id = $1"
            row = await conn.fetchrow(query, entry_id)

            if row:
                data = json.loads(row["data"])
                return {
                    "id": row["id"],
                    "work": data.get("work", ""),
                    "struggle": data.get("struggle", ""),
                    "intention": data.get("intention", ""),
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"]
                }
            return None

    async def update_entry(self, entry_id: str, updated_data: Dict[str, Any]) -> None:
        updated_at = datetime.now(timezone.utc)
        updated_data["id"] = entry_id
        updated_data["updated_at"] = updated_at

        data_json = json.dumps(updated_data, default=PostgresDB.datetime_serialize)

        async with self.pool.acquire() as conn:
            query = """
            UPDATE entries
            SET data = $2, updated_at = $3
            WHERE id = $1
            """
            await conn.execute(query, entry_id, data_json, updated_at)

    async def delete_entry(self, entry_id: str) -> None:
        async with self.pool.acquire() as conn:
            query = "DELETE FROM entries WHERE id = $1"
            await conn.execute(query, entry_id)

    async def delete_all_entries(self) -> None:
        async with self.pool.acquire() as conn:
            query = "DELETE FROM entries"
            await conn.execute(query)

    async def get_entries_for_summary(self, limit: int = 21):
        """Load a bounded set of notes for AI summarization."""

        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT data
                FROM entries
                ORDER BY created_at DESC, id DESC
                LIMIT $1
                """,
                limit,
            )

        return [json.loads(row["data"]) for row in rows]
