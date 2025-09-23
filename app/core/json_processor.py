"""
JSON Parsing and Extraction
"""
import json

def extract_first_json(text: str) -> dict:
    start = text.find("{")
    if start == -1:
        raise ValueError("No JSON object start '{' found")
    depth, end = 0, None
    in_str = False
    esc = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        else:
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
    if end is None:
        raise ValueError("Unbalanced braces; could not find JSON object end '}'")
    return json.loads(text[start:end])
