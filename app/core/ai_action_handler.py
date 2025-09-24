"""
AI Action Logic (single action) — aligned with extract_single flow.

- Keeps same lifecycle: update_job, rate-limit check, progress, model call, JSON extraction.
- Preserves optional PDF support and placeholder substitution.
- Default (no custom prompt): use focused (tab, action) templates and the SAME prompt builder as extraction.
- Custom prompt: used verbatim; placeholders {{PDF_TEXT}} and {{USER_RESUME_JSON}} are replaced.
"""

import json
from typing import Optional, Dict, Tuple

from app.core.pdf_processor import extract_pdf_text
from app.core.openai_client import call_openai_api, extract_text_from_response
from app.core.token_calculator import approx_tokens_from_chars, calculate_max_output_tokens
from app.core.json_processor import extract_first_json
from app.utils.job_manager import update_job_status
from app.utils.rate_limiter import check_and_increment_rate_limits, decrement_rate_limits
from app.utils.debug_recorder import DebugRequestRecorder


def _save_action_artifacts(
    rec: "DebugRequestRecorder",
    *,
    input_filename: str | None,
    input_bytes: bytes | None,
    pdf_text: str | None,
    resume_json_raw: str | None,
    final_prompt: str | None,
    combined_len: int | None,
    pdf_text_len: int | None,
    resume_json_len: int | None,
) -> None:
    """
    Save AIAction artifacts under the handler's PRL folder.
    No-ops if PRL is disabled.
    """
    try:
        # PDF bytes
        if input_bytes:
            name = f"input__{input_filename}" if input_filename else "input.pdf"
            rec.save_bytes(name, input_bytes)
        # PDF text
        if pdf_text:
            rec.save_text("pdf_text.txt", pdf_text)
        # User resume JSON (raw or pretty json if valid)
        if resume_json_raw is not None and resume_json_raw != "":
            try:
                parsed = json.loads(resume_json_raw)
                rec.save_text("user_resume.json", json.dumps(parsed, ensure_ascii=False, indent=2))
            except Exception:
                rec.save_text("user_resume.json", resume_json_raw)
        # Final prompt
        if final_prompt:
            rec.save_text("prompt_action.txt", final_prompt)
        # Quick metrics
        lines = []
        if combined_len is not None:
            lines.append(f"combined_len={combined_len}")
        if pdf_text_len is not None:
            lines.append(f"pdf_text_len={pdf_text_len}")
        if resume_json_len is not None:
            lines.append(f"resume_json_len={resume_json_len}")
        if lines:
            rec.save_text("action_token_inputs.txt", "\n".join(lines))
    except Exception as _e:
        # best-effort only; never break main path on debug write errors
        pass


from app.utils.prompt_utils import build_prompt

# Allowed (tab, action) combinations mirrored from UI (Availability has no defaults)
_ALLOWED_BY_TAB = {
    "Contact": {"AI Suggestions", "Validate"},
    "Soft Skills": {"AI Suggestions", "Validate", "Enhance"},
    "Tech Skills": {"AI Suggestions", "Validate"},
    "About": {"AI Suggestions", "Validate", "Enhance", "Shorten"},
    "Experience": {"AI Suggestions", "Validate", "Enhance"},
    "Projects": {"AI Suggestions", "Validate", "Enhance"},
    "Education": {"AI Suggestions", "Validate"},
    "Certifications": {"AI Suggestions", "Validate"},
    "Availability": set(),  # no defaults
}

# Focused default templates for (tab, action). Minimal, concise, and rely on placeholders.
_FOCUSED_PROMPTS: Dict[Tuple[str, str], str] = {
    ("Contact", "AI Suggestions"): "Using {{PDF_TEXT}} or {{USER_RESUME_JSON}}, suggest missing/ambiguous Contact fixes as strict JSON.",
    ("Contact", "Validate"): "Validate Contact fields found in {{PDF_TEXT}} or {{USER_RESUME_JSON}}; output strict JSON report of issues only.",
    ("Soft Skills", "AI Suggestions"): "From {{PDF_TEXT}} or {{USER_RESUME_JSON}}, suggest relevant soft skills; avoid duplicates; strict JSON.",
    ("Soft Skills", "Validate"): "Validate listed soft skills against evidence in {{PDF_TEXT}} or {{USER_RESUME_JSON}}; strict JSON.",
    ("Soft Skills", "Enhance"): "Enhance soft skills phrasing for clarity and impact using {{PDF_TEXT}} or {{USER_RESUME_JSON}}; strict JSON.",
    ("Tech Skills", "AI Suggestions"): "Suggest technical skills inferred from {{PDF_TEXT}} or {{USER_RESUME_JSON}}; group by area; strict JSON.",
    ("Tech Skills", "Validate"): "Validate technical skills against evidence in {{PDF_TEXT}} or {{USER_RESUME_JSON}}; strict JSON.",
    ("About", "AI Suggestions"): "Draft a concise About section from {{PDF_TEXT}} or {{USER_RESUME_JSON}}; strict JSON.",
    ("About", "Validate"): "Validate About section consistency with {{PDF_TEXT}} or {{USER_RESUME_JSON}}; strict JSON.",
    ("About", "Enhance"): "Enhance About section for clarity and impact using {{PDF_TEXT}} or {{USER_RESUME_JSON}}; strict JSON.",
    ("About", "Shorten"): "Shorten About section to a crisp summary using {{PDF_TEXT}} or {{USER_RESUME_JSON}}; strict JSON.",
    ("Experience", "AI Suggestions"): "From {{PDF_TEXT}} or {{USER_RESUME_JSON}}, infer missing Experience bullets; strict JSON.",
    ("Experience", "Validate"): "Validate Experience items vs {{PDF_TEXT}} or {{USER_RESUME_JSON}}; strict JSON.",
    ("Experience", "Enhance"): "Enhance Experience bullets to be outcome-focused using {{PDF_TEXT}} or {{USER_RESUME_JSON}}; strict JSON.",
    ("Projects", "AI Suggestions"): "Suggest relevant projects from {{PDF_TEXT}} or {{USER_RESUME_JSON}}; strict JSON.",
    ("Projects", "Validate"): "Validate projects against {{PDF_TEXT}} or {{USER_RESUME_JSON}}; strict JSON.",
    ("Projects", "Enhance"): "Enhance project descriptions using {{PDF_TEXT}} or {{USER_RESUME_JSON}}; strict JSON.",
    ("Education", "AI Suggestions"): "Suggest education items from {{PDF_TEXT}} or {{USER_RESUME_JSON}}; strict JSON.",
    ("Education", "Validate"): "Validate education items vs {{PDF_TEXT}} or {{USER_RESUME_JSON}}; strict JSON.",
    ("Certifications", "AI Suggestions"): "Suggest certifications from {{PDF_TEXT}} or {{USER_RESUME_JSON}}; strict JSON.",
    ("Certifications", "Validate"): "Validate certifications vs {{PDF_TEXT}} or {{USER_RESUME_JSON}}; strict JSON.",
    # Availability intentionally omitted (no defaults)
}

class AIActionHandler:
    def _is_allowed_default(self, tab: str, action: str) -> bool:
        allowed = _ALLOWED_BY_TAB.get(tab, set())
        return action in allowed

    def _focused_template_for(self, tab: str, action: str) -> str:
        key = (tab, action)
        if key not in _FOCUSED_PROMPTS:
            raise ValueError(f"No default focused prompt for tab='{tab}' action='{action}'")
        return _FOCUSED_PROMPTS[key]

    def process_action(
        self,
        job_id: str,
        request_data,               # AIActionRequest
        file_content: Optional[bytes],
        filename: Optional[str],
    ):
        # Rate-limit gate (job is created by the route); set processing status
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
                pdf_text = extract_pdf_text(file_content)

            resume_json_text = request_data.resume_json or ""
            # Combine for token budgeting
            combined_len = len(pdf_text) + len(resume_json_text)

            input_tokens = approx_tokens_from_chars(combined_len)

            update_job_status(job_id, "processing", 40)

            # Token budget with distinct mode "action"
            max_output_tokens = calculate_max_output_tokens(
                input_tokens, "action", request_data.max_output_tokens
            )

            # Build final prompt
            if request_data.prompt:
                # Custom prompt verbatim, keep placeholder substitution
                base_prompt = request_data.prompt
                filled_prompt = base_prompt.replace("{{PDF_TEXT}}", pdf_text or "")
                filled_prompt = filled_prompt.replace("{{USER_RESUME_JSON}}", resume_json_text)
            else:
                # Defensive check for allowed default combos
                if not self._is_allowed_default(request_data.tab, request_data.action_type):
                    raise ValueError(f"Unsupported default action for tab='{request_data.tab}': {request_data.action_type}")

                # Focused template + build_prompt
                document_text = pdf_text if pdf_text else resume_json_text
                focused_template = self._focused_template_for(request_data.tab, request_data.action_type)
                prompt_text = build_prompt(document_text, {"prompt_type": request_data.tab, "prompt": focused_template})
                filled_prompt = prompt_text.replace("{{USER_RESUME_JSON}}", resume_json_text)

            # Call OpenAI
            
            # PRL: save action artifacts right before model call
            try:
                combined_len = (len(pdf_text or "") + len(resume_json_text or ""))
                pdf_text_len = len(pdf_text or "")
                resume_json_len = len(resume_json_text or "")
            except Exception:
                combined_len = pdf_text_len = resume_json_len = None

            if rec.enabled and rec.dir:
                _save_action_artifacts(
                    rec,
                    input_filename=filename,
                    input_bytes=file_content,
                    pdf_text=pdf_text,
                    resume_json_raw=resume_json_text,
                    final_prompt=filled_prompt,
                    combined_len=combined_len,
                    pdf_text_len=pdf_text_len,
                    resume_json_len=resume_json_len,
                )

            response = call_openai_api(
                api_key=request_data.openai_api_key,
                model=request_data.model,
                prompt=filled_prompt,
                max_output_tokens=max_output_tokens,
                temperature_zero=request_data.temperature_zero,
            )

            if response.get("status") != "completed":
                reason = (response.get("incomplete_details") or {}).get("reason", "unknown")
                raise RuntimeError(f"OpenAI API failed: {reason}")

            # Extract JSON like extraction handler
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
