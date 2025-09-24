"""
Token Calculation Functions
"""
import math
from app.config import CHARS_PER_TOKEN, MIN_OUTPUT_TOKENS, EXTRACT_TOKEN_MULTIPLIER, CLASSIFY_DEFAULT_TOKENS


# ACTION sizing — tuned for potentially long, structured outputs (e.g., Experience/Projects Enhance)
ACTION_TOKEN_BASE = 512
ACTION_TOKEN_MULTIPLIER = EXTRACT_TOKEN_MULTIPLIER * 0.9   # nearly as generous as extract
ACTION_MAX_OUTPUT_TOKENS = 6144                            # higher cap to fit legit long results

def approx_tokens_from_chars(n_chars: int) -> int:
    return max(1, (n_chars + CHARS_PER_TOKEN - 1) // CHARS_PER_TOKEN)

def calculate_max_output_tokens(input_tokens: int, operation: str, provided_tokens: int = None) -> int:
    """
    Output-token budget:

      provided_tokens -> exact (clamped at MIN_OUTPUT_TOKENS)
      classify        -> fixed
      extract         -> proportional (existing)
      action          -> generous scaling + higher base + higher cap
      fallback        -> MIN_OUTPUT_TOKENS
    """
    # Fast-path override
    if provided_tokens:
        t = provided_tokens
    elif operation == "classify":
        t = CLASSIFY_DEFAULT_TOKENS
    elif operation == "extract":
        t = math.ceil(input_tokens * EXTRACT_TOKEN_MULTIPLIER)
    elif operation == "action":
        scaled = math.ceil(input_tokens * ACTION_TOKEN_MULTIPLIER)
        t = min(ACTION_TOKEN_BASE + scaled, ACTION_MAX_OUTPUT_TOKENS)
    else:
        t = MIN_OUTPUT_TOKENS

    # Single clamp (micro-opt)
    return max(MIN_OUTPUT_TOKENS, int(t))

def model_supports_temperature(model: str) -> bool:
    return model.startswith(("gpt-4.1", "gpt-4o"))
