"""
GET /health Endpoint
"""

from fastapi import APIRouter
from datetime import datetime, timezone
import logging

from app.models.responses import HealthResponse
from app.database import get_db

logger = logging.getLogger(__name__)

# No prefix here; mount as: app.include_router(health_router, prefix="/health")
router = APIRouter()


@router.get(
    "",
    response_model=HealthResponse,
    summary="Health check",
    description=(
        "Performs a basic health check including a database connectivity probe. "
        "Returns 'healthy' when DB is reachable; otherwise 'unhealthy' with error details."
    ),
    responses={
        200: {"description": "Health status payload"},
    },
)
async def health_check() -> HealthResponse:
    """
    Returns a HealthResponse with:
    - status: 'healthy' | 'unhealthy'
    - timestamp: RFC3339 UTC string
    - database: { connected: bool, error?: str }
    - system: { status: 'ok' | 'error' }
    """
    ts = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    try:
        with get_db() as conn:
            conn.execute("SELECT 1").fetchone()
        return HealthResponse(
            status="healthy",
            timestamp=ts,
            database={"connected": True},
            system={"status": "ok"},
        )
    except Exception as e:
        logger.exception("Health check failed")
        return HealthResponse(
            status="unhealthy",
            timestamp=ts,
            database={"connected": False, "error": str(e)},
            system={"status": "error"},
        )
