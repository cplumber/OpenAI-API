#!/bin/bash

# Configuration (aligned with test-single.sh)
API_BASE="http://localhost:8000"
#API_BASE="https://www.devfe.flexcoders.net:9443"
PDF_FILE="../../PDF-Tools/sample17.pdf"
USER_ID="test_user_123"
OPENAI_API_KEY=$OPENAI_API_KEY
MODEL="gpt-4.1-mini"

# API key header (now supported in ALL requests)
API_KEY_HEADER="${API_KEY_HEADER:-X-API-Key: ${X_API_KEY_VALUE}}"

echo $OPENAI_API_KEY
echo "=== Resume Analyzer API - BATCH Test ==="

# 1. Health Check (show body on error)
echo "[$(date +'%H:%M:%S')] 1/4 Health Check..."
HC_BODY="$(mktemp)"; trap 'rm -f "$HC_BODY"' EXIT
HC_CODE=$(curl -sS -o "$HC_BODY" -w "%{http_code}" -H "$API_KEY_HEADER" -X GET "$API_BASE/health")
if [ "$HC_CODE" -ge 400 ] || [ ! -s "$HC_BODY" ]; then
  echo "✗ Health check failed (HTTP $HC_CODE):"
  cat "$HC_BODY"
  exit 1
fi
echo "✓ Health check passed"

# 2. Submit Batch Job - ALL 5 TYPES (capture HTTP code + body so errors are visible)
echo "[$(date +'%H:%M:%S')] 2/4 Submitting Batch Job..."

PROMPTS='[
  {"prompt_type":"contact"},
  {"prompt_type":"skills"},
  {"prompt_type":"experience"},
  {"prompt_type":"projects"},
  {"prompt_type":"education"}
]'

SUBMIT_BODY="$(mktemp)"
SUBMIT_CODE=$(curl -sS -o "$SUBMIT_BODY" -w "%{http_code}" -H "$API_KEY_HEADER" -X POST "$API_BASE/extract/batch" \
  -F "file=@$PDF_FILE" \
  -F "user_id=$USER_ID" \
  -F "openai_api_key=$OPENAI_API_KEY" \
  -F "model=$MODEL" \
  -F "prompts=$PROMPTS")

SUBMIT_RESPONSE="$(cat "$SUBMIT_BODY")"; rm -f "$SUBMIT_BODY"

if [ "$SUBMIT_CODE" -ge 400 ] || [ -z "$SUBMIT_RESPONSE" ]; then
  echo "✗ Request failed (HTTP $SUBMIT_CODE):"
  echo "$SUBMIT_RESPONSE"
  exit 1
fi

JOB_ID=$(echo "$SUBMIT_RESPONSE" | grep -o '"job_id":"[^"]*"' | cut -d'"' -f4)

if [ -z "$JOB_ID" ]; then
  echo "✗ Failed to extract job_id from response (HTTP $SUBMIT_CODE):"
  echo "$SUBMIT_RESPONSE"
  exit 1
fi

echo "✓ Batch job submitted: $JOB_ID"
echo "  Processing 5 prompt types in parallel"

# 3. Poll Status (show errors if polling fails)
echo "[$(date +'%H:%M:%S')] 3/4 Polling Status..."

for i in {1..60}; do  # Longer timeout for batch processing
  POLL_BODY="$(mktemp)"
  POLL_CODE=$(curl -sS -o "$POLL_BODY" -w "%{http_code}" -H "$API_KEY_HEADER" "$API_BASE/jobs/$JOB_ID")
  STATUS_RESPONSE="$(cat "$POLL_BODY")"; rm -f "$POLL_BODY"

  if [ "$POLL_CODE" -ge 400 ] || [ -z "$STATUS_RESPONSE" ]; then
    echo ""
    echo "✗ Poll failed (HTTP $POLL_CODE):"
    echo "$STATUS_RESPONSE"
    exit 1
  fi

  STATUS=$(echo "$STATUS_RESPONSE" | grep -o '"status":"[^"]*"' | cut -d'"' -f4)
  PROGRESS=$(echo "$STATUS_RESPONSE" | grep -o '"progress":[0-9]*' | cut -d':' -f2)

  printf "\r  Status: %-12s Progress: %3s%% (Poll #%d)" "${STATUS:-unknown}" "${PROGRESS:-0}" "$i"

  if [[ "$STATUS_RESPONSE" == *'"completed"'* ]]; then
      echo ""
      echo "✓ Batch job completed!"
      break
  elif [[ "$STATUS_RESPONSE" == *'"failed"'* ]]; then
      echo ""
      echo "✗ Batch job failed"
      break
  fi

  sleep 3  # Longer interval for batch jobs
done

# 4. Get Results - FULL OUTPUT (show body on error)
echo "[$(date +'%H:%M:%S')] 4/4 Getting Results..."
echo ""

RES_BODY="$(mktemp)"
RES_CODE=$(curl -sS -o "$RES_BODY" -w "%{http_code}" -H "$API_KEY_HEADER" "$API_BASE/jobs/$JOB_ID/result")
RESULT_JSON="$(cat "$RES_BODY")"; rm -f "$RES_BODY"

if [ "$RES_CODE" -ge 400 ] || [ -z "$RESULT_JSON" ]; then
  echo "✗ Failed to get results (HTTP $RES_CODE):"
  echo "$RESULT_JSON"
  exit 1
fi

echo "=== BATCH RESULTS (All 5 Types) ==="
echo "$RESULT_JSON"
echo ""
echo "=== Test Complete ==="
echo "Batch Job ID: $JOB_ID"
echo "Extracted: contact, skills, experience, projects, education"

# Bonus: Pretty print with jq if available
if command -v jq &> /dev/null; then
  echo ""
  echo "=== PRETTY FORMATTED ==="
  echo "$RESULT_JSON" | jq .

  echo ""
  echo "=== SUMMARY BY TYPE ==="
  RESULT=$(echo "$RESULT_JSON" | jq -r '.result')

  echo "📧 CONTACT:"
  echo "$RESULT" | jq -r '.contact // "Not found"'
  echo ""

  echo "🛠️ SKILLS:"
  echo "$RESULT" | jq -r '.soft_skills // "Not found"'
  echo "$RESULT" | jq -r '.tech_skills // "Not found"'
  echo ""

  echo "💼 EXPERIENCE:"
  echo "$RESULT" | jq -r '.experience // "Not found"'
  echo ""

  echo "🚀 PROJECTS:"
  echo "$RESULT" | jq -r '.projects // "Not found"'
  echo ""

  echo "🎓 EDUCATION:"
  echo "$RESULT" | jq -r '.education // "Not found"'
  echo ""

  if echo "$RESULT" | jq -e '._execution_errors' > /dev/null; then
      echo "⚠️ ERRORS:"
      echo "$RESULT" | jq -r '._execution_errors'
  fi
fi
