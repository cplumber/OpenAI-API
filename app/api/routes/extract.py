"""
POST /extract/single and /extract/batch endpoints.

Mount in main.py like:
    app.include_router(extract_router, prefix="/extract")

Final paths:
    POST /extract/single
    POST /extract/batch
"""

from fastapi import APIRouter, HTTPException, status, Form, UploadFile, File, Request
from typing import Optional, List, Any
import json
import uuid
import threading
import logging

from app.utils.debug_recorder import DebugRequestRecorder
from app.dependencies import validate_file
from app.models.requests import SingleExtractionRequest, BatchExtractionRequest, PromptItem
from app.models.responses import JobResponse
from app.core.extraction_handler import ExtractionHandler
from app.utils.job_manager import create_job

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post(
    "/single",
    response_model=JobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Queue a single extraction job",
    description=(
        "Uploads a single PDF and queues one prompt extraction task. "
        "Returns a job_id immediately; poll your jobs API to get status/results."
    ),
)
async def extract_single(
    request: Request,
    file: UploadFile = File(
        ...,
        description="PDF file to process. Must be a valid PDF and pass server-side validation.",
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
            "Model name to use for inference. "
            "Must be a model supported by the server pipeline. "
            "Examples: 'gpt-4o-mini', 'gpt-4.1-turbo'."
        ),
        examples=["gpt-4o-mini"],
    ),
    prompt_type: str = Form(
        ...,
        description=(
            "Server-recognized prompt type key. "
            "Determines which internal prompt template/logic is used. "
            "Examples: 'contact_about', 'skills', 'projects', 'education'."
        ),
        examples=["skills"],
    ),
    prompt: Optional[str] = Form(
        None,
        description=(
            "Optional custom prompt text to override or augment the default template. "
            "Provide a full instruction string if needed. "
            "Example: 'Extract the top 5 programming languages with years of experience'."
        ),
    ),
    max_output_tokens: Optional[int] = Form(
        None,
        description=(
            "Maximum number of output tokens allowed for the model response. "
            "Range: typically 256–8192 depending on the model. "
            "If omitted, the server applies a default (commonly 1024). "
            "Use lower values for concise answers, higher values for detailed resumes/projects."
        ),
        examples=[512, 1024, 2048],
    ),
    temperature_zero: bool = Form(
        False,
        description=(
            "Force deterministic decoding by setting model temperature to 0. "
            "Recommended for structured extraction tasks. "
            "True = temperature=0, False = use model default. "
            "Example: 'true' ensures reproducible structured JSON output."
        ),
        examples=[True, False],
    ),
) -> JobResponse:
    # --- per-request debug logging (single) ---
    rec = DebugRequestRecorder().start(
        route="/extract/single",
        method=request.method,
        headers={k: v for k, v in request.headers.items()},
        query=dict(request.query_params),
    )
        # try to parse prompt if it’s JSON-like
    logged_prompt = None
    if isinstance(prompt, str):
        try:
            parsed = json.loads(prompt)
            logged_prompt = parsed
        except Exception:
            logged_prompt = prompt[:2000]  # keep truncated raw string
    else:
        logged_prompt = prompt
    rec.save_request_json({
        "user_id": user_id,
        "openai_api_key": "***provided***",
        "model": model,
        "prompt_type": prompt_type,
        "prompt": (prompt[:2000] if isinstance(prompt, str) else None),
        "max_output_tokens": max_output_tokens,
        "temperature_zero": temperature_zero,
    })
    try:
        rec.save_uploads([("file", file)])
    except Exception:
        pass
    # ------------------------------------------

    try:
        content = await validate_file(file)

        request_data = SingleExtractionRequest(
            user_id=user_id,
            openai_api_key=openai_api_key,
            model=model,
            prompt_type=prompt_type,
            prompt=prompt,
            max_output_tokens=max_output_tokens,
            temperature_zero=temperature_zero,
        )

        handler = ExtractionHandler()
        job_id = str(uuid.uuid4())
        create_job(job_id, request_data.user_id, request_data.openai_api_key)

        th = threading.Thread(
            name=f"extract-single-{job_id[:8]}",
            target=handler.process_single_extraction,
            args=(job_id, request_data, content, file.filename),
            daemon=True,
        )
        th.start()

        resp = JobResponse(job_id=job_id, status="queued", message="Single extraction job created")
        payload = resp.model_dump() if hasattr(resp, "model_dump") else (resp.dict() if hasattr(resp, "dict") else resp)
        rec.save_response(status.HTTP_202_ACCEPTED, payload)
        return resp

    except HTTPException as e:
        rec.save_exception(e)
        raise
    except Exception as e:
        logger.exception("Failed to create single extraction job")
        rec.save_exception(e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create extraction job",
        )


@router.post(
    "/batch",
    response_model=JobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Queue a batch extraction job",
    description=(
        "Uploads a single PDF and queues multiple prompt extractions in one job. "
        "Provide a JSON array of prompt items in the 'prompts' field."
    ),
)
async def extract_batch(
    request: Request,
    file: UploadFile = File(
        ...,
        description="PDF file to process. Must be a valid PDF and pass server-side validation.",
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
            "Model name to use for inference. "
            "Must be a model supported by the server pipeline. "
            "Examples: 'gpt-4o-mini', 'gpt-4.1-turbo'."
        ),
        examples=["gpt-4o-mini"],
    ),
    prompts: str = Form(
        ...,
        description=(
            "JSON array of prompt items. Each item must be an object with:\n"
            " - prompt_type (string, required): key for the extraction template.\n"
            " - prompt (string, optional): custom override text.\n\n"
            "Example:\n"
            "[\n"
            "  {\"prompt_type\":\"skills\"},\n"
            "  {\"prompt_type\":\"projects\", \"prompt\":\"Extract recent projects with roles\"}\n"
            "]"
        ),
    ),
    max_output_tokens: Optional[int] = Form(
        None,
        description=(
            "Maximum number of output tokens allowed for each model response. "
            "Range: typically 256–8192 depending on the model. "
            "If omitted, the server applies a default (commonly 1024). "
            "Choose smaller values for efficiency when running many prompts."
        ),
        examples=[512, 1500, 2048],
    ),
    temperature_zero: bool = Form(
        False,
        description=(
            "Force deterministic decoding by setting model temperature to 0. "
            "Recommended for structured, multi-prompt extraction jobs. "
            "True = temperature=0, False = use model default."
        ),
        examples=[True],
    ),
) -> JobResponse:
    # --- per-request debug logging (batch) ---
    rec = DebugRequestRecorder().start(
        route="/extract/batch",
        method=request.method,
        headers={k: v for k, v in request.headers.items()},
        query=dict(request.query_params),
    )

    # try to parse prompts if it’s JSON-like
    logged_prompts = None
    if isinstance(prompts, str):
        try:
            parsed = json.loads(prompts)
            logged_prompts = parsed
        except Exception:
            logged_prompts = prompts[:2000]  # keep truncated raw string
    else:
        logged_prompts = prompts

    rec.save_request_json({
        "user_id": user_id,
        "openai_api_key": "***provided***",
        "model": model,
        "prompts": logged_prompts,
        "max_output_tokens": max_output_tokens,
        "temperature_zero": temperature_zero,
    })
    try:
        rec.save_uploads([("file", file)])
    except Exception:
        pass
    # -----------------------------------------
    try:
        content = await validate_file(file)

        try:
            parsed: Any = json.loads(prompts)
            if not isinstance(parsed, list):
                raise ValueError("Expected a JSON array for 'prompts'")

            prompt_items: List[PromptItem] = []
            for i, item in enumerate(parsed):
                if not isinstance(item, dict):
                    raise ValueError(f"prompts[{i}] must be an object")
                ptype = item.get("prompt_type")
                if not isinstance(ptype, str) or not ptype.strip():
                    raise ValueError(f"prompts[{i}].prompt_type is required and must be a non-empty string")
                ptext = item.get("prompt")
                if ptext is not None and not isinstance(ptext, str):
                    raise ValueError(f"prompts[{i}].prompt must be a string when provided")
                prompt_items.append(PromptItem(prompt_type=ptype, prompt=ptext))

            if not prompt_items:
                raise ValueError("prompts array must not be empty")

        except (json.JSONDecodeError, ValueError) as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid prompts format: {str(e)}",
            )

        request_data = BatchExtractionRequest(
            user_id=user_id,
            openai_api_key=openai_api_key,
            model=model,
            prompts=prompt_items,
            max_output_tokens=max_output_tokens,
            temperature_zero=temperature_zero,
        )

        handler = ExtractionHandler()
        job_id = str(uuid.uuid4())
        create_job(job_id, request_data.user_id, request_data.openai_api_key)

        th = threading.Thread(
            name=f"extract-batch-{job_id[:8]}",
            target=handler.process_batch_extraction,
            args=(job_id, request_data, content, file.filename),
            daemon=True,
        )
        th.start()

        resp = JobResponse(
            job_id=job_id,
            status="queued",
            message=f"Batch extraction job created with {len(prompt_items)} prompts",
        )
        payload = resp.model_dump() if hasattr(resp, "model_dump") else (resp.dict() if hasattr(resp, "dict") else resp)
        rec.save_response(status.HTTP_202_ACCEPTED, payload)
        return resp

    except HTTPException as e:
        rec.save_exception(e)
        raise
    except Exception as e:
        logger.exception("Failed to create batch extraction job")
        rec.save_exception(e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create extraction job",
        )
