"""
Prompt File Loading and Template Processing
"""
from pathlib import Path
from typing import Dict
from app.config import PROMPTS_DIR

PROMPT_TYPE_TO_FILE = {
    "contact": "extract_prompt_contact_about.txt",
    "about": "extract_prompt_contact_about.txt",
    "education": "extract_prompt_education_certifications.txt",
    "certifications": "extract_prompt_education_certifications.txt",
    "experience": "extract_prompt_experience.txt",
    "projects": "extract_prompt_projects.txt",
    "skills": "extract_prompt_skills.txt",
}

def load_prompt_template(prompt_type: str) -> str:
    if prompt_type not in PROMPT_TYPE_TO_FILE:
        raise ValueError(f"Unknown prompt type: {prompt_type}")
    filename = PROMPT_TYPE_TO_FILE[prompt_type]
    prompt_file = Path(PROMPTS_DIR) / filename
    if not prompt_file.exists():
        raise FileNotFoundError(f"Prompt file not found: {prompt_file}")
    return prompt_file.read_text(encoding="utf-8")

def build_prompt(pdf_text: str, prompt_item: Dict[str, str]) -> str:
    if prompt_item.get("prompt"):
        template = prompt_item["prompt"]
    else:
        template = load_prompt_template(prompt_item["prompt_type"])
    return template.replace("{{PDF_TEXT}}", pdf_text)
