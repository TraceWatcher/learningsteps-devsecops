import logging
import os

from fastapi import APIRouter, Depends, HTTPException, Request
from models.entry import Entry, EntryCreate
from repositories.postgres_repository import PostgresDB
from services.ai_summary_service import AISummaryService
from services.entry_service import EntryService

router = APIRouter()

# TODO: Add authentication middleware
# TODO: Add request validation middleware
# TODO: Add rate limiting middleware
# TODO: Add API versioning
# TODO: Add response caching

def get_entry_service(request: Request) -> EntryService:
    db = PostgresDB(pool=request.app.state.db_pool)
    return EntryService(db)

logger = logging.getLogger("journal")

@router.post("/entries/summary", tags=["AI"])
async def summarize_entries(request: Request):
    """Generate an AI summary of demo notes."""

    if os.getenv("AI_SUMMARY_ENABLED", "false").lower() != "true":
        raise HTTPException(
            status_code=404,
            detail="Not found",
        )

    db = PostgresDB(pool=request.app.state.db_pool)
    service = AISummaryService(db)

    try:
        return await service.summarize()

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
async def create_entry(entry_data: EntryCreate, entry_service: EntryService = Depends(get_entry_service)):
    """Create a new journal entry."""
    try:
        # Create the full entry with auto-generated fields 
        entry = Entry(
            work=entry_data.work,
            struggle=entry_data.struggle, 
            intention=entry_data.intention
        )
        
        # Store the entry in the database
        created_entry = await entry_service.create_entry(entry.model_dump())
        
        # Return success response (FastAPI handles datetime serialization automatically)
        return {
            "detail": "Entry created successfully", 
            "entry": created_entry
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error creating entry: {str(e)}")

# Implements GET /entries endpoint to list all journal entries
# Example response: [{"id": "123", "work": "...", "struggle": "...", "intention": "..."}]
@router.get("/entries")
async def get_all_entries(entry_service: EntryService = Depends(get_entry_service)):
    """Get all journal entries."""
    result = await entry_service.get_all_entries()
    return {"entries": result, "count": len(result)}

@router.get("/entries/{entry_id}")
async def get_entry(request: Request, entry_id: str, entry_service: EntryService = Depends(get_entry_service)):
    """Get a single journal entry by ID."""
    result = await entry_service.get_entry(entry_id)
    if not result:
        raise HTTPException(status_code=404, detail="Entry not found")
    
    return result

@router.patch("/entries/{entry_id}")
async def update_entry(entry_id: str, entry_update: dict, entry_service: EntryService = Depends(get_entry_service)):
    """Update a journal entry"""
    result = await entry_service.update_entry(entry_id, entry_update)
    if not result:
    
        raise HTTPException(status_code=404, detail="Entry not found")
    
    return result

@router.delete("/entries/{entry_id}")
async def delete_entry(entry_id: str, entry_service: EntryService = Depends(get_entry_service)):
    """Delete a specific journal entry."""
    # Check if entry exists first
    existing_entry = await entry_service.get_entry(entry_id)
    if not existing_entry:
        raise HTTPException(status_code=404, detail="Entry not found")
    
    # Delete the entry
    await entry_service.delete_entry(entry_id)
    
    return {"detail": "Entry deleted successfully", "entry_id": entry_id}

@router.delete("/entries")
async def delete_all_entries(entry_service: EntryService = Depends(get_entry_service)):
    """Delete all journal entries"""
    await entry_service.delete_all_entries()
    return {"detail": "All entries deleted"}