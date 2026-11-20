import asyncio
import logging
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse
from repositories.postgres_repository import PostgresDB
from routers.journal_router import router as journal_router

load_dotenv()

# Configure basic console logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initializing PostgreSQL connection pool")

    app.state.db_pool = await PostgresDB.create_pool()

    logger.info("PostgreSQL connection pool initialized")

    try:
        yield
    finally:
        logger.info("Closing PostgreSQL connection pool")
        await app.state.db_pool.close()

app = FastAPI(
    title="LearningSteps API",
    description="A simple learning journal API for tracking daily work, struggles, and intentions",
    lifespan=lifespan,
)

app.include_router(journal_router)


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/docs")

# Log when the app starts
logger.info("LearningSteps API started successfully")

@app.get("/health/live", tags=["Health"])
async def health_live():
    """Check whether the API process is responding."""
    return {"status": "alive"}


@app.get("/health/version", tags=["Health"])
async def health_version():
    """Expose the deployed application version."""
    return {
        "application": "LearningSteps",
        "version": os.getenv("APP_VERSION", "dev"),
    }


@app.get("/health/ready", tags=["Health"])
async def health_ready():
    """Verify database connectivity using the shared pool."""

    try:
        async def check_database():
            async with app.state.db_pool.acquire() as conn:
                return await conn.fetchval("SELECT 1")

        result = await asyncio.wait_for(
            check_database(),
            timeout=5.0,
        )

        if result != 1:
            raise RuntimeError("Unexpected database response")

    except Exception as exc:
        logger.warning(
            "Database readiness check failed: %s",
            type(exc).__name__,
        )

        raise HTTPException(
            status_code=503,
            detail="Database unavailable",
        ) from None

    return {
        "status": "ready",
        "database": "connected",
    }
