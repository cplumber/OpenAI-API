#!/bin/bash

# Configuration
API_BASE="http://127.0.0.1:8000"
# Default
USER_ID="test_user_123"

# Parse CLI args
while [[ $# -gt 0 ]]; do case "$1" in --user-id) USER_ID="$2"; shift 2 ;; *) echo "Unknown parameter: $1"; exit 1 ;; esac; done


OPENAI_API_KEY=$OPENAI_API_KEY   # must be exported in your shell
MODEL="gpt-4.1-mini"
API_KEY_HEADER="${API_KEY_HEADER:-X-API-Key: ${X_API_KEY_VALUE}}"

PROMPT_FILE="../focused-prompts/about.description.txt"
RESUME_JSON_FILE="parsed-resume-samples/results_all_sample19.json"
PDF_FILE="resumes/sample19.pdf"

echo "=== AI About Enhance Test ==="

# 1. Health Check
echo "[$(date +'%H:%M:%S')] 1/4 Health Check..."
curl -s -f -H "$API_KEY_HEADER" -X GET "$API_BASE/health" \
  && echo "✓ Health check passed"

# 2. Submit Job
echo "[$(date +'%H:%M:%S')] 2/4 Submitting AI Action Job..."

# Compact JSON to one line for safety (falls back to cat if jq missing)
if command -v jq >/dev/null 2>&1; then
  RESUME_JSON_MIN=$(jq -c . < "$RESUME_JSON_FILE")
else
  RESUME_JSON_MIN=$(tr -d '\n' < "$RESUME_JSON_FILE")
fi

SUBMIT_RESPONSE=$(curl -sS --fail-with-body -H "$API_KEY_HEADER" -X POST "$API_BASE/ai/action" \
  -F "user_id=$USER_ID" \
  -F "openai_api_key=$OPENAI_API_KEY" \
  -F "model=$MODEL" \
  -F "action_type=enhance" \
  -F "tab=about" \
  --form-string "resume_json=$RESUME_JSON_MIN" \
  --form-string "prompt=$(<"$PROMPT_FILE")" \
  -F "file=@$PDF_FILE;type=application/pdf")

if [ $? -ne 0 ]; then
  echo "✗ Request failed:"
  echo "$SUBMIT_RESPONSE"
  exit 1
fi

JOB_ID=$(echo "$SUBMIT_RESPONSE" | grep -o '"job_id":"[^"]*"' | cut -d'"' -f4)

if [ -z "$JOB_ID" ]; then
    echo "✗ Failed to extract job_id from response:"
    echo "$SUBMIT_RESPONSE"
    exit 1
fi

echo "✓ Job submitted: $JOB_ID"

# 3. Poll Status
echo "[$(date +'%H:%M:%S')] 3/4 Polling Status..."
JOB_DONE=""
for i in {1..30}; do
    STATUS_RESPONSE=$(curl -s -H "$API_KEY_HEADER" "$API_BASE/jobs/$JOB_ID")
    STATUS=$(echo "$STATUS_RESPONSE" | grep -o '"status":"[^"]*"' | cut -d'"' -f4)
    PROGRESS=$(echo "$STATUS_RESPONSE" | grep -o '"progress":[0-9]*' | cut -d':' -f2)

    printf "\r  Status: %-12s Progress: %3s%% (Poll #%d)" "$STATUS" "${PROGRESS:-0}" "$i"

    if [[ "$STATUS_RESPONSE" == *'"completed"'* ]]; then
        JOB_DONE="completed"
        echo ""
        echo "✓ Job completed!"
        break
    elif [[ "$STATUS_RESPONSE" == *'"failed"'* ]]; then
        JOB_DONE="failed"
        echo ""
        echo "✗ Job failed"
        break
    fi

    sleep 2
done

# 4. Get Results - FULL OUTPUT
echo "[$(date +'%H:%M:%S')] 4/4 Getting Results..."
echo ""
RESULT_JSON=$(curl -s -H "$API_KEY_HEADER" "$API_BASE/jobs/$JOB_ID/result")

echo "=== FULL RESULTS ==="
echo "$RESULT_JSON"
echo ""
echo "=== Test Complete ==="
echo "Job ID: $JOB_ID"

# Derive output filename from input resume JSON
# e.g., parsed-resume-samples/results_all_sample18.json
#  -> parsed-resume-samples/results_all_sample18.about.enhance.output.json
INPUT_DIR="$(dirname "$RESUME_JSON_FILE")"
INPUT_BASE="$(basename "$RESUME_JSON_FILE")"
INPUT_STEM="${INPUT_BASE%.*}"
OUT_PATH="${INPUT_DIR}/${INPUT_STEM}.about.enhance.output.json"

# Save only if completed; still allow debugging save on failure if you prefer
if [[ "$JOB_DONE" == "completed" ]]; then
  if command -v jq &> /dev/null; then
      echo "$RESULT_JSON" | jq . > "$OUT_PATH"
  else
      echo "$RESULT_JSON" > "$OUT_PATH"
  fi
  echo "✅ Saved result to: $OUT_PATH"
else
  echo "ℹ️ Job not completed successfully; result not saved."
  # If you want to always save (even on failure), uncomment below:
  # echo "$RESULT_JSON" > "${OUT_PATH%.json}.error.json"
  # echo "📝 Saved error payload to: ${OUT_PATH%.json}.error.json"
fi

# Bonus: Pretty print with jq if available
if command -v jq &> /dev/null; then
    echo ""
    echo "=== PRETTY FORMATTED ==="
    echo "$RESULT_JSON" | jq .
fi
