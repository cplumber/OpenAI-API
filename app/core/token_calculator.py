"""
Token Calculation Functions
"""
from app.config import CHARS_PER_TOKEN, MIN_OUTPUT_TOKENS, EXTRACT_TOKEN_MULTIPLIER, CLASSIFY_DEFAULT_TOKENS

def approx_tokens_from_chars(n_chars: int) -> int:
    return max(1, (n_chars + CHARS_PER_TOKEN - 1) // CHARS_PER_TOKEN)

def calculate_max_output_tokens(input_tokens: int, operation: str, provided_tokens: int = None) -> int:
    if provided_tokens is not None:
        return max(MIN_OUTPUT_TOKENS, provided_tokens)
    if operation == "extract":
        return max(MIN_OUTPUT_TOKENS, input_tokens * EXTRACT_TOKEN_MULTIPLIER)
    if operation == "classify":
        return CLASSIFY_DEFAULT_TOKENS
    return MIN_OUTPUT_TOKENS

def model_supports_temperature(model: str) -> bool:
    return model.startswith(("gpt-4.1", "gpt-4o"))
