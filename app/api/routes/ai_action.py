"""
POST /ai/action endpoint — validated against UI button matrix.
"""
from fastapi import APIRouter, HTTPException, status, Form, UploadFile, File, Request
from typing import Optional
import uuid
import threading
import logging

from app.utils.debug_recorder import DebugRequestRecorder
from app.models.responses import JobResponse
from app.models.requests import AIActionRequest
from app.core.ai_action_handler import AIActionHandler
from app.dependencies import validate_file

logger = logging.getLogger(__name__)

router = APIRouter()

# Allowed actions per tab (Availability has no defaults)
_ALLOWED_BY_TAB = {
    "Contact": {"AI Suggestions", "Validate"},
    "Soft Skills": {"AI Suggestions", "Validate", "Enhance"},
    "Tech Skills": {"AI Suggestions", "Validate"},
    "About": {"AI Suggestions", "Validate", "Enhance", "Shorten"},
    "Experience": {"AI Suggestions", "Validate", "Enhance"},
    "Projects": {"AI Suggestions", "Validate", "Enhance"},
    "Education": {"AI Suggestions", "Validate"},
    "Certifications": {"AI Suggestions", "Validate"},
    "Availability": set(),
}

@router.post(
    "/action",
    response_model=JobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Queue an AI action job",
    description=(
        "Submit an AI action (AI Suggestions / Validate / Enhance / Shorten) for a given tab. "
        "Resume JSON is required; PDF file is optional."
    ),
)
async def ai_action(
    request: Request,
    user_id: str = Form(..., description="Internal user identifier"),
    openai_api_key: str = Form(..., description="OpenAI API key"),
    model: str = Form(..., description="LLM model to use, e.g. gpt-4o-mini"),
    action_type: str = Form(..., description="AI action: 'AI Suggestions' | 'Validate' | 'Enhance' | 'Shorten'"),
    tab: str = Form(..., description="Target tab label exactly as in UI"),
    resume_json: str = Form(..., description="Current resume JSON (string)"),
    file: Optional[UploadFile] = File(
        None, description="Optional PDF file; used if prompt references {{PDF_TEXT}}"
    ),
    prompt: Optional[str] = Form(
        None, description="Optional custom prompt override (verbatim)"
    ),
    max_output_tokens: Optional[int] = Form(
        None, description="Maximum number of output tokens"
    ),
    temperature_zero: bool = Form(
        True, description="Force deterministic decoding by setting temperature=0"
    ),
) -> JobResponse:
    # --- Debug logging ---
    rec = DebugRequestRecorder().start(
        route="/ai/action",
        method=request.method,
        headers={k: v for k, v in request.headers.items()},
        query=dict(request.query_params),
    )
    rec.save_request_json({
        "user_id": user_id,
        "openai_api_key": "***provided***",
        "model": model,
        "action_type": action_type,
        "tab": tab,
        "resume_json_len": len(resume_json) if isinstance(resume_json, str) else None,
        "max_output_tokens": max_output_tokens,
        "temperature_zero": temperature_zero,
        "custom_prompt": bool(prompt),
    })
    try:
        if file:
            rec.save_uploads([("file", file)])
    except Exception:
        pass
    # ---------------------

    try:
        # Validate default (tab, action) if NO custom prompt
        if not prompt:
            allowed = _ALLOWED_BY_TAB.get(tab, None)
            if allowed is None:
                raise HTTPException(status_code=400, detail=f"Unknown tab: {tab}")
            if action_type not in allowed:
                raise HTTPException(status_code=400, detail=f"Unsupported action '{action_type}' for tab '{tab}'")

        pdf_content = None
        filename = None
        if file:
            pdf_content = await validate_file(file)
            filename = file.filename

        request_data = AIActionRequest(
            user_id=user_id,
            openai_api_key=openai_api_key,
            model=model,
            action_type=action_type,
            tab=tab,
            resume_json=resume_json,
            prompt=prompt,
            max_output_tokens=max_output_tokens,
            temperature_zero=temperature_zero,
        )

        handler = AIActionHandler()
        job_id = str(uuid.uuid4())

        # NOTE: Let the handler own job-creation lifecycle (avoid duplicate create_job here)
        th = threading.Thread(
            name=f"ai-action-{job_id[:8]}",
            target=handler.process_action,
            args=(job_id, request_data, pdf_content, filename),
            daemon=True,
        )
        th.start()

        resp = JobResponse(job_id=job_id, status="queued", message="AI action job created")
        payload = resp.model_dump() if hasattr(resp, "model_dump") else resp.dict()
        rec.save_response(status.HTTP_202_ACCEPTED, payload)
        return resp

    except HTTPException as e:
        rec.save_exception(e)
        raise
    except Exception as e:
        logger.exception("Failed to create AI action job")
        rec.save_exception(e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create AI action job",
        )
