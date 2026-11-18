import logging
import os

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials
from models.entry import Entry, EntryCreate, EntryUpdate
from repositories.postgres_repository import PostgresDB
from security.auth import bearer_scheme, get_current_user
from services.ai_summary_service import AISummaryService
from services.entry_service import EntryService

router = APIRouter()
logger = logging.getLogger("journal")


def get_entry_service(request: Request) -> EntryService:
    db = PostgresDB(pool=request.app.state.db_pool)
    return EntryService(db)


@router.post("/entries/summary", tags=["AI"])
async def summarize_entries(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(
        bearer_scheme
    ),
):
    """Summarize only the authenticated user's notes."""

    # Preserve HTTP 404 when AI is disabled.
    if os.getenv("AI_SUMMARY_ENABLED", "false").lower() != "true":
        raise HTTPException(status_code=404, detail="Not found")

    user = await get_current_user(credentials)
    owner_id = user["user_id"]

    db = PostgresDB(pool=request.app.state.db_pool)
    service = AISummaryService(db)

    try:
        return await service.summarize(owner_id)

    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        ) from exc

    except Exception:
        logger.exception("AI summary generation failed")
        raise HTTPException(
            status_code=502,
            detail="AI summary temporarily unavailable",
        ) from None


@router.post("/entries")
async def create_entry(
    entry_data: EntryCreate,
    entry_service: EntryService = Depends(get_entry_service),
    user: dict = Depends(get_current_user),
):
    """Create a note belonging to the authenticated user."""

    entry = Entry(
        work=entry_data.work,
        struggle=entry_data.struggle,
        intention=entry_data.intention,
    )

    created_entry = await entry_service.create_entry(
        entry.model_dump(),
        user["user_id"],
    )

    return {
        "detail": "Entry created successfully",
        "entry": created_entry,
    }


@router.get("/entries")
async def get_all_entries(
    entry_service: EntryService = Depends(get_entry_service),
    user: dict = Depends(get_current_user),
):
    """Return only the authenticated user's notes."""

    result = await entry_service.get_all_entries(
        user["user_id"]
    )

    return {
        "entries": result,
        "count": len(result),
    }


@router.get("/entries/{entry_id}")
async def get_entry(
    entry_id: str,
    entry_service: EntryService = Depends(get_entry_service),
    user: dict = Depends(get_current_user),
):
    """Return one owned entry."""

    result = await entry_service.get_entry(
        entry_id,
        user["user_id"],
    )

    if result is None:
        raise HTTPException(
            status_code=404,
            detail="Entry not found",
        )

    return result


@router.patch("/entries/{entry_id}")
async def update_entry(
    entry_id: str,
    entry_update: EntryUpdate,
    entry_service: EntryService = Depends(get_entry_service),
    user: dict = Depends(get_current_user),
):
    """Update permitted fields of an owned entry."""

    try:
        result = await entry_service.update_entry(
            entry_id,
            entry_update.model_dump(exclude_unset=True),
            user["user_id"],
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        ) from exc

    if result is None:
        raise HTTPException(
            status_code=404,
            detail="Entry not found",
        )

    return result


@router.delete("/entries/{entry_id}")
async def delete_entry(
    entry_id: str,
    entry_service: EntryService = Depends(get_entry_service),
    user: dict = Depends(get_current_user),
):
    """Delete an entry only if owned by the user."""

    deleted = await entry_service.delete_entry(
        entry_id,
        user["user_id"],
    )

    if not deleted:
        raise HTTPException(
            status_code=404,
            detail="Entry not found",
        )

    return {
        "detail": "Entry deleted successfully",
        "entry_id": entry_id,
    }


@router.delete("/entries")
async def delete_all_entries(
    entry_service: EntryService = Depends(get_entry_service),
    user: dict = Depends(get_current_user),
):
    """Delete only the authenticated user's entries."""

    deleted_count = await entry_service.delete_all_entries(
        user["user_id"]
    )

    return {
        "detail": "Own entries deleted",
        "deleted_count": deleted_count,
    }
