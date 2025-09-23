"""
POST /classify Endpoint
"""

from fastapi import APIRouter, BackgroundTasks, HTTPException, status, Form, UploadFile, File, Request
from typing import Optional
import uuid
import logging

from app.dependencies import validate_file
from app.models.requests import ClassificationRequest
from app.models.responses import JobResponse
from app.core.classification_handler import ClassificationHandler
from app.utils.debug_recorder import DebugRequestRecorder

logger = logging.getLogger(__name__)

# No prefix here; mount in main as: app.include_router(classify_router, prefix="/classify")
router = APIRouter()

_MIN_TOKENS = 64
_MAX_TOKENS = 8192


@router.post(
    "",
    response_model=JobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Queue a document classification job",
    description=(
        "Uploads a PDF and queues a single classification task. "
        "Returns a job_id immediately; poll your jobs API for status/results."
    ),
    responses={
        202: {"description": "Job queued"},
        400: {"description": "Bad request (file/params)"},
        422: {"description": "Validation error"},
        500: {"description": "Internal server error"},
    },
)
async def classify_document(
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(
        ...,
        description="PDF file to classify. Must be a valid PDF and pass server-side validation.",
    ),
    user_id: str = Form(
        ...,
        description="Internal user identifier used for attribution/auditing.",
        examples=["user_12345"],
    ),
    openai_api_key: str = Form(
        ...,
        description="OpenAI API key to use for this job. Stored/used server-side only; never returned.",
    ),
    model: str = Form(
        ...,
        description=(
            "Model name to use for classification. Must be supported by the server pipeline. "
            "Examples: 'gpt-4o-mini', 'gpt-4.1-turbo'."
        ),
        examples=["gpt-4o-mini"],
    ),
    max_output_tokens: Optional[int] = Form(
        None,
        description=(
            "Maximum number of output tokens allowed for the model response. "
            f"Range: typically {_MIN_TOKENS}–{_MAX_TOKENS} depending on the model. "
            "If omitted, the server applies a default (commonly 512–1024)."
        ),
        examples=[512, 1024, 1500],
    ),
    temperature_zero: bool = Form(
        True,
        description=(
            "Force deterministic decoding by setting model temperature to 0. "
            "Recommended for structured classification outputs. "
            "True = temperature=0, False = use model default."
        ),
        examples=[True, False],
    ),
) -> JobResponse:
    # --- per-request debug logging (classify) ---
    rec = DebugRequestRecorder().start(
        route="/classify",
        method=request.method,
        headers={k: v for k, v in request.headers.items()},
        query=dict(request.query_params),
    )
    rec.save_request_json({
        "user_id": user_id,
        "openai_api_key": "***provided***",
        "model": model,
        "max_output_tokens": max_output_tokens,
        "temperature_zero": temperature_zero,
    })
    try:
        rec.save_uploads([("file", file)])
    except Exception:
        pass
    # --------------------------------------------
    try:
        # Validate file and read content
        content = await validate_file(file)

        # Light-range validation for tokens (keeps Swagger doc truthful)
        if max_output_tokens is not None:
            if not (_MIN_TOKENS <= max_output_tokens <= _MAX_TOKENS):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"max_output_tokens must be between {_MIN_TOKENS} and {_MAX_TOKENS}",
                )

        request_data = ClassificationRequest(
            user_id=user_id,
            openai_api_key=openai_api_key,
            model=model,
            max_output_tokens=max_output_tokens,
            temperature_zero=temperature_zero,
        )

        handler = ClassificationHandler()
        job_id = str(uuid.uuid4())

        # Schedule background processing via FastAPI BackgroundTasks
        background_tasks.add_task(
            handler.process_classification,
            job_id=job_id,
            request_data=request_data,
            file_content=content,
            filename=file.filename,
        )

        resp = JobResponse(job_id=job_id, status="queued", message="Classification job created")
        payload = resp.model_dump() if hasattr(resp, "model_dump") else (resp.dict() if hasattr(resp, "dict") else resp)
        rec.save_response(status.HTTP_202_ACCEPTED, payload)
        return resp
    except HTTPException as e:
        rec.save_response(getattr(e, "status_code", 500), {"detail": getattr(e, "detail", "HTTP error")})
        raise
    except Exception as e:
        logger.exception("Failed to create classification job")
        rec.save_exception(e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create classification job",
        )
