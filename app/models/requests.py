"""
Pydantic Request Models
"""
from pydantic import BaseModel
from typing import Optional, List

class PromptItem(BaseModel):
    prompt_type: str
    prompt: Optional[str] = None

class SingleExtractionRequest(BaseModel):
    user_id: str
    openai_api_key: str
    model: str
    prompt_type: str
    prompt: Optional[str] = None
    max_output_tokens: Optional[int] = None
    temperature_zero: bool = False

class BatchExtractionRequest(BaseModel):
    user_id: str
    openai_api_key: str
    model: str
    prompts: List[PromptItem]
    max_output_tokens: Optional[int] = None
    temperature_zero: bool = False

class ClassificationRequest(BaseModel):
    user_id: str
    openai_api_key: str
    model: str
    max_output_tokens: Optional[int] = None
    temperature_zero: bool = True

class AIActionRequest(BaseModel):
    user_id: str
    openai_api_key: str
    model: str
    action_type: str   # e.g. "suggest" | "validate" | "enhance" | "shorten"
    tab: str           # e.g. "skills" | "projects" | "education"
    resume_json: str   # current resume JSON (required, raw string)
    prompt: Optional[str] = None
    max_output_tokens: Optional[int] = None
    temperature_zero: bool = True