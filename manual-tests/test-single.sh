#!/bin/bash

# Configuration
API_BASE="http://localhost:8000"
#API_BASE="https://www.devfe.flexcoders.net:9443"
PDF_FILE="../../PDF-Tools/sample10.pdf"
USER_ID="test_user_123"
OPENAI_API_KEY=$OPENAI_API_KEY
MODEL="gpt-4.1-mini"
API_KEY_HEADER="${API_KEY_HEADER:-X-API-Key: ${X_API_KEY_VALUE}}"

echo "=== Resume Analyzer API Test ==="

# 1. Health Check
echo "[$(date +'%H:%M:%S')] 1/4 Health Check..."
curl -s -f -H "$API_KEY_HEADER" -X GET "$API_BASE/health" \
  && echo "✓ Health check passed"

# 2. Submit Job
echo "[$(date +'%H:%M:%S')] 2/4 Submitting Job..."
SUBMIT_RESPONSE=$(curl -sS --fail-with-body -H "$API_KEY_HEADER" -X POST "$API_BASE/extract/single" \
  -F "file=@$PDF_FILE" \
  -F "user_id=$USER_ID" \
  -F "openai_api_key=$OPENAI_API_KEY" \
  -F "model=$MODEL" \
  -F "prompt_type=contact" 2>&1)   # capture body+errors

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
for i in {1..30}; do
    STATUS_RESPONSE=$(curl -s -H "$API_KEY_HEADER" "$API_BASE/jobs/$JOB_ID")
    STATUS=$(echo "$STATUS_RESPONSE" | grep -o '"status":"[^"]*"' | cut -d'"' -f4)
    PROGRESS=$(echo "$STATUS_RESPONSE" | grep -o '"progress":[0-9]*' | cut -d':' -f2)
    
    printf "\r  Status: %-12s Progress: %3s%% (Poll #%d)" "$STATUS" "${PROGRESS:-0}" "$i"
    
    if [[ "$STATUS_RESPONSE" == *'"completed"'* ]]; then
        echo ""
        echo "✓ Job completed!"
        break
    elif [[ "$STATUS_RESPONSE" == *'"failed"'* ]]; then
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

# Bonus: Pretty print with jq if available
if command -v jq &> /dev/null; then
    echo ""
    echo "=== PRETTY FORMATTED ==="
    echo "$RESULT_JSON" | jq .
fi

