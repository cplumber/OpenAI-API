"""
Single/Batch Extraction Logic
"""

import json
from app.core.pdf_processor import extract_pdf_text
from app.core.openai_client import call_openai_api
from app.core.token_calculator import approx_tokens_from_chars, calculate_max_output_tokens
from app.core.parallel_executor import execute_parallel_extraction
from app.utils.prompt_utils import build_prompt
from app.utils.rate_limiter import check_and_increment_rate_limits, decrement_rate_limits
from app.utils.job_manager import update_job_status, create_job

class ExtractionHandler:
    def process_single_extraction(self, job_id: str, request_data, file_content: bytes, filename: str):
        create_job(job_id, request_data.user_id, request_data.openai_api_key)
        update_job_status(job_id, "processing", 10)
        ok, reason = check_and_increment_rate_limits(request_data.user_id, request_data.openai_api_key)
        if not ok:
            update_job_status(job_id, "failed", error_message=f"Rate limit exceeded: {reason}")
            return
        try:
            pdf_text = extract_pdf_text(file_content)
            input_tokens = approx_tokens_from_chars(len(pdf_text))
            update_job_status(job_id, "processing", 40)
            max_output_tokens = calculate_max_output_tokens(input_tokens, "extract", request_data.max_output_tokens)
            prompt_text = build_prompt(pdf_text, {"prompt_type": request_data.prompt_type, "prompt": request_data.prompt})
            response = call_openai_api(request_data.openai_api_key, request_data.model, prompt_text, max_output_tokens, request_data.temperature_zero)
            if response.get("status") != "completed":
                reason = (response.get("incomplete_details") or {}).get("reason", "unknown")
                raise RuntimeError(f"OpenAI API failed: {reason}")
            from app.core.openai_client import extract_text_from_response
            from app.core.json_processor import extract_first_json
            raw = extract_text_from_response(response).strip()
            try:
                result = json.loads(raw)
            except json.JSONDecodeError:
                result = extract_first_json(raw)
            update_job_status(job_id, "completed", 100, result=result)
        except Exception as e:
            update_job_status(job_id, "failed", error_message=str(e))
        finally:
            decrement_rate_limits(request_data.user_id, request_data.openai_api_key)

    def process_batch_extraction(self, job_id: str, request_data, file_content: bytes, filename: str):
        create_job(job_id, request_data.user_id, request_data.openai_api_key)
        update_job_status(job_id, "processing", 10)
        ok, reason = check_and_increment_rate_limits(request_data.user_id, request_data.openai_api_key)
        if not ok:
            update_job_status(job_id, "failed", error_message=f"Rate limit exceeded: {reason}")
            return
        try:
            pdf_text = extract_pdf_text(file_content)
            input_tokens = approx_tokens_from_chars(len(pdf_text))
            update_job_status(job_id, "processing", 40)
            max_output_tokens = calculate_max_output_tokens(input_tokens, "extract", request_data.max_output_tokens)
            prompt_items = [{"prompt_type": p.prompt_type, "prompt": p.prompt} for p in request_data.prompts]
            result = execute_parallel_extraction(pdf_text, prompt_items, request_data.openai_api_key, request_data.model, max_output_tokens, request_data.temperature_zero, call_openai_api, build_prompt)
            update_job_status(job_id, "completed", 100, result=result)
        except Exception as e:
            update_job_status(job_id, "failed", error_message=str(e))
        finally:
            decrement_rate_limits(request_data.user_id, request_data.openai_api_key)
