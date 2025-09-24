"""
AI Action Logic (single action)

Matches extraction handler patterns:
- Uses the same rate limiter utilities
- Uses the same OpenAI client and token calculators
- Stores results/errors via job_manager helpers
"""

import json
from typing import Optional

from app.core.pdf_processor import extract_pdf_text
from app.core.openai_client import call_openai_api
from app.core.token_calculator import approx_tokens_from_chars, calculate_max_output_tokens
from app.utils.job_manager import update_job_status, create_job
from app.utils.rate_limiter import check_and_increment_rate_limits, decrement_rate_limits
from app.utils.debug_recorder import DebugRequestRecorder


class AIActionHandler:
    def process_action(
        self,
        job_id: str,
        request_data,               # AIActionRequest
        file_content: Optional[bytes],
        filename: Optional[str],
    ):
        # Mirror extraction handler lifecycle
        create_job(job_id, request_data.user_id, request_data.openai_api_key)
        update_job_status(job_id, "processing", 10)

        ok, reason = check_and_increment_rate_limits(request_data.user_id, request_data.openai_api_key)
        if not ok:
            update_job_status(job_id, "failed", error_message=f"Rate limit exceeded: {reason}")
            return

        rec = DebugRequestRecorder().start(
            route="AIActionHandler.process_action",
            method="background",
            headers={},
            query={},
        )

        try:
            # Prepare source text
            pdf_text = ""
            if file_content:
                # same PDF path as extraction
                pdf_text = extract_pdf_text(file_content)

            # Estimate tokens from combined inputs (pdf_text + resume_json)
            combined_len = len(pdf_text) + (len(request_data.resume_json) if isinstance(request_data.resume_json, str) else 0)
            input_tokens = approx_tokens_from_chars(combined_len)

            update_job_status(job_id, "processing", 40)

            # Reuse existing token budget logic, use the same "extract" mode for compatibility
            max_output_tokens = calculate_max_output_tokens(input_tokens, "extract", request_data.max_output_tokens)

            # Build prompt strictly from provided prompt, with placeholder substitution only.
            # DO NOT attach standardized context blocks; prompt already contains needed context.
            base_prompt = request_data.prompt or f"Perform action '{request_data.action_type}' on tab '{request_data.tab}' using provided resume JSON and optional PDF text."
            filled_prompt = base_prompt.replace("{{PDF_TEXT}}", pdf_text or "")
            filled_prompt = filled_prompt.replace("{{USER_RESUME_JSON}}", request_data.resume_json)

            # ai_action_handler.py — in process_action(), just before call_openai_api(...)
                  # Debug prints
            print("DEBUG: base_prompt (len={}):\n{}\n".format(len(base_prompt), base_prompt))
            print("DEBUG: filled_prompt (len={}):\n{}\n".format(len(filled_prompt), filled_prompt))
            
            # Call OpenAI (same path as extraction handler) with the filled prompt only
            response = call_openai_api(
                request_data.openai_api_key,
                request_data.model,
                filled_prompt,
                max_output_tokens,
                request_data.temperature_zero,
            )

            if response.get("status") != "completed":
                reason = (response.get("incomplete_details") or {}).get("reason", "unknown")
                raise RuntimeError(f"OpenAI API failed: {reason}")

            # Extract JSON text like extraction handler does
            from app.core.openai_client import extract_text_from_response
            from app.core.json_processor import extract_first_json

            raw = extract_text_from_response(response).strip()
            try:
                result = json.loads(raw)
            except json.JSONDecodeError:
                result = extract_first_json(raw)

            update_job_status(job_id, "completed", 100, result=result)
            rec.save_response(200, {"job_id": job_id, "status": "completed"})

        except Exception as e:
            update_job_status(job_id, "failed", error_message=str(e))
            rec.save_exception(e)
        finally:
            decrement_rate_limits(request_data.user_id, request_data.openai_api_key)
