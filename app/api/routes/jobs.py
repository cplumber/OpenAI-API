"""
GET /jobs/{job_id}, /jobs/{job_id}/result Endpoints
"""
from fastapi import APIRouter, HTTPException, status, Path, Request
import json
from app.models.responses import JobStatusResponse, JobResultResponse
from app.database import get_db
from fastapi.responses import JSONResponse

from app.utils.debug_recorder import DebugRequestRecorder
router = APIRouter()

@router.get("/{job_id}", response_model=JobStatusResponse)
async def get_job_status(job_id: str = Path(...), request: Request = None):
    rec = DebugRequestRecorder().start(
        route="/jobs/{job_id}",
        method=(request.method if request else "GET"),
        headers=(dict(request.headers) if request else {}),
        query=(dict(request.query_params) if request else {}),
    )
    with get_db() as conn:
        row = conn.execute(
            "SELECT job_id, status, progress, created_at, completed_at FROM jobs WHERE job_id = ?",
            (job_id,)
        ).fetchone()
        if not row:
            rec.save_response(status.HTTP_404_NOT_FOUND, {"detail": f"Job {job_id} not found"})
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Job {job_id} not found")
        resp = JobStatusResponse(
            job_id=row["job_id"],
            status=row["status"],
            progress=row["progress"],
            created_at=row["created_at"],
            completed_at=row["completed_at"]
        )
        payload = resp.model_dump() if hasattr(resp, "model_dump") else (resp.dict() if hasattr(resp, "dict") else resp)
        rec.save_response(200, payload)
        return resp

def has_openai_auth_error(result: dict) -> bool:
    """
    Inspect result["_execution_errors"] for OpenAI authentication errors.

    Returns True if any error string under that tag mentions
    'error 401' or 'invalid_api_key'.
    """
    if not isinstance(result, dict):
        return False
    errors = result.get("_execution_errors")
    if not isinstance(errors, list):
        return False

    for e in errors:
        if not isinstance(e, dict):
            continue
        err_str = e.get("error")
        if not isinstance(err_str, str):
            continue
        low = err_str.lower()
        if "error 401" in low or "invalid_api_key" in low:
            return True
    return False


@router.get("/{job_id}/result", response_model=JobResultResponse)
async def get_job_result(job_id: str = Path(...), request: Request = None):
    rec = DebugRequestRecorder().start(
        route="/jobs/{job_id}/result",
        method=(request.method if request else "GET"),
        headers=(dict(request.headers) if request else {}),
        query=(dict(request.query_params) if request else {}),
    )
    with get_db() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        if not row:
            rec.save_response(status.HTTP_404_NOT_FOUND, {"detail": f"Job {job_id} not found"})
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Job {job_id} not found")
        if row["status"] not in ["completed", "failed"]:
            rec.save_response(status.HTTP_400_BAD_REQUEST, {"detail": f"Job {job_id} is not yet completed"})
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Job {job_id} is not yet completed")

        result = json.loads(row["result"]) if row["result"] else None
        resp = JobResultResponse(
            job_id=row["job_id"],
            status=row["status"],
            result=result,
            error_message=row["error_message"],
            created_at=row["created_at"],
            completed_at=row["completed_at"]
        )
        payload = resp.model_dump() if hasattr(resp, "model_dump") else (resp.dict() if hasattr(resp, "dict") else resp)

        # --- Use helper function here ---
        if has_openai_auth_error(result):
            rec.save_response(status.HTTP_401_UNAUTHORIZED, payload)
            return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content=payload)
        # --------------------------------

        rec.save_response(200, payload)
        return resp