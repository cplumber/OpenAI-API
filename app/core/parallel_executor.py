"""
Parallel Execution with 250ms Stagger
"""
import time
import json
from typing import Dict, List, Any, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
from app.config import PARALLEL_STAGGER_DELAY
from app.core.json_processor import extract_first_json
from app.core.openai_client import extract_text_from_response

DESIRED_KEY_ORDER = ["contact", "soft_skills", "tech_skills", "about", "experience", "projects", "education", "certifications"]

def execute_parallel_extraction(pdf_text: str, prompt_items: List[Dict[str, str]], api_key: str, model: str, max_output_tokens: int, temperature_zero: bool, openai_call_func, prompt_builder_func) -> Dict[str, Any]:
    def exec_one(item: Dict[str, str], idx: int) -> Tuple[Dict[str, str], Dict[str, Any]]:
        try:
            if idx > 0:
                time.sleep(PARALLEL_STAGGER_DELAY * idx)
            prompt_text = prompt_builder_func(pdf_text, item)
            response = openai_call_func(api_key=api_key, model=model, prompt=prompt_text, max_output_tokens=max_output_tokens, temperature_zero=temperature_zero)
            if response.get("status") != "completed":
                reason = (response.get("incomplete_details") or {}).get("reason", "unknown")
                raise RuntimeError(f"API call failed: {reason}")
            raw_text = extract_text_from_response(response).strip()
            try:
                data = json.loads(raw_text)
            except json.JSONDecodeError:
                data = extract_first_json(raw_text)
            return item, {"success": True, "data": data}
        except Exception as e:
            return item, {"success": False, "error": str(e)}

    results = {}
    with ThreadPoolExecutor(max_workers=len(prompt_items)) as pool:
        futs = {pool.submit(exec_one, it, i): it for i, it in enumerate(prompt_items)}
        for fut in as_completed(futs):
            item, res = fut.result()
            results[item.get("prompt_type", f"idx_{len(results)}")] = res

    final_result = {}
    failed = []
    for key in DESIRED_KEY_ORDER:
        for _, res in results.items():
            if res.get("success") and isinstance(res.get("data"), dict) and key in res["data"]:
                final_result[key] = res["data"][key]
                break
    for ptype, res in results.items():
        if res.get("success"):
            for k, v in res["data"].items():
                if k not in final_result:
                    final_result[k] = v
        else:
            failed.append({"prompt_type": ptype, "error": res.get("error", "unknown")})
    if failed:
        final_result["_execution_errors"] = failed
    return final_result
