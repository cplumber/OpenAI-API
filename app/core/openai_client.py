"""
OpenAI API Communication
"""
import requests
from typing import Dict, Any
from app.config import OPENAI_API_URL, OPENAI_TIMEOUT
from app.core.token_calculator import model_supports_temperature

def call_openai_api(api_key: str, model: str, prompt: str, max_output_tokens: int, temperature_zero: bool) -> Dict[str, Any]:
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {"model": model, "input": prompt, "max_output_tokens": max_output_tokens, "text": {"format": {"type": "json_object"}}}
    if temperature_zero and model_supports_temperature(model):
        payload["temperature"] = 0.0
    resp = requests.post(OPENAI_API_URL, headers=headers, json=payload, timeout=OPENAI_TIMEOUT)
    if resp.status_code != 200:
        raise RuntimeError(f"OpenAI API error {resp.status_code}: {resp.text}")
    return resp.json()

def extract_text_from_response(data: Dict[str, Any]) -> str:
    if isinstance(data.get("output_text"), str):
        return data["output_text"]
    if isinstance(data.get("content"), str):
        return data["content"]
    for item in data.get("output", []):
        content = item.get("content")
        if isinstance(content, list):
            for c in content:
                if isinstance(c, dict) and c.get("type") in ("output_text", "text"):
                    tv = c.get("text")
                    if isinstance(tv, str):
                        return tv
                    if isinstance(tv, dict) and "value" in tv:
                        return str(tv["value"])
        if isinstance(item.get("text"), str):
            return item["text"]
        if isinstance(item.get("text"), dict) and "value" in item["text"]:
            return str(item["text"]["value"])
    raise KeyError("No text found in response payload")
