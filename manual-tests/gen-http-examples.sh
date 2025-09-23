#!/usr/bin/env bash
# gen-http-examples.sh — dump full HTTP responses (headers + body) for documentation
# Endpoints (from your test-batch.sh):
#   GET  /health
#   POST /extract/batch
#   GET  /jobs/{job_id}
#   GET  /jobs/{job_id}/result
#
# Cases:
#   Health:
#     H1) 200 OK (with correct X-API-Key)
#     H2) Auth error — missing X-API-Key
#     H3) Auth error — wrong X-API-Key
#   Batch submit:
#     B1) 202 Accepted (valid batch)
#     B2) 422 — empty 'prompts'
#     B3) 422 — missing 'openai_api_key'
#     B4) Auth error — missing X-API-Key
#     B5) Auth error — wrong X-API-Key
#   Job status:
#     S1) 200 OK (valid job_id)
#     S2) Auth error — missing X-API-Key
#     S3) Auth error — wrong X-API-Key
#     S4) Invalid/unknown job_id (observed code)
#   Job result:
#     R1) 200 OK (valid job_id, completed)
#     R2) Auth error — missing X-API-Key
#     R3) Auth error — wrong X-API-Key
#     R4) Invalid/unknown job_id (observed code)
#
# Filenames include the actual HTTP code: <label>.<code>.http

set -euo pipefail

# ---------- Config (override via env) ----------
#API_BASE="${API_BASE:-http://localhost:8000}"
API_BASE="https://www.devfe.flexcoders.net:9443"
PDF_FILE="${PDF_FILE:-../../PDF-Tools/sample17.pdf}"
USER_ID="${USER_ID:-test_user_123}"
MODEL="${MODEL:-gpt-4.1-mini}"

# Example: export OPENAI_API_KEY=sk-...
OPENAI_API_KEY="${OPENAI_API_KEY:-}"
# Keys (match your test-batch.sh style)
X_API_KEY_VALUE="${X_API_KEY_VALUE:-42534256343254365465}"
WRONG_X_API_KEY_VALUE="${WRONG_X_API_KEY_VALUE:-invalid-demo-key}"
API_KEY_HEADER="X-API-Key: ${X_API_KEY_VALUE}"
WRONG_API_KEY_HEADER="X-API-Key: ${WRONG_X_API_KEY_VALUE}"
# Wrong token example (override via env if needed)
WRONG_OPENAI_API_KEY="${WRONG_OPENAI_API_KEY:-sk-wrong-demo-key}"

PROMPTS_JSON='[
  {"prompt_type":"contact"},
  {"prompt_type":"skills"},
  {"prompt_type":"experience"},
  {"prompt_type":"projects"},
  {"prompt_type":"education"}
]'

OUT_DIR="${OUT_DIR:-response-examples}"
mkdir -p "$OUT_DIR"

# ---------- Helpers ----------
need_file() { [ -s "$1" ] || { echo "ERROR: Missing file: $1" >&2; exit 1; }; }

http_dump() {
  # args: <outfile_basename> <curl args...>
  local base="$1"; shift
  local tmp="$(mktemp)"
  local code
  code=$(curl -sS -i -o "$tmp" -w "%{http_code}" "$@") || true
  local out="${OUT_DIR}/${base}.${code}.http"
  mv "$tmp" "$out"
  echo "$out"
}

extract_json_field() {
  # naive JSON field extractor (no jq dependency)
  # usage: extract_json_field "$json" "job_id"
  echo "$1" | grep -o "\"$2\":\"[^\"]*\"" | cut -d'"' -f4
}

poll_until_complete() {
  # args: <job_id> <max_secs>
  local job_id="$1" max_secs="${2:-180}"
  local start=$(date +%s)

  while :; do
    (( $(date +%s) - start > max_secs )) && return 1

    local tmp="$(mktemp)"
    curl -sS -o "$tmp" -H "$API_KEY_HEADER" "$API_BASE/jobs/$job_id" || true
    local body="$(cat "$tmp")"
    rm -f "$tmp"

    # extract "status":"..."
    local status
    status=$(printf '%s' "$body" | grep -o '"status":"[^"]*"' | cut -d'"' -f4)

    # ONLY these two terminal states
    if [ "$status" = "completed" ] || [ "$status" = "failed" ]; then
      return 0
    fi

    sleep 2
  done
}


# ---------- Preconditions ----------
need_file "$PDF_FILE"
echo "API_BASE=$API_BASE"
echo "PDF_FILE=$PDF_FILE"
echo "MODEL=$MODEL"
echo "USER_ID=$USER_ID"
echo "OPENAI_API_KEY: $([ -n "$OPENAI_API_KEY" ] && echo 'set' || echo 'NOT set')"
echo "X-API-Key (correct): $X_API_KEY_VALUE"
echo "X-API-Key (wrong):   $WRONG_X_API_KEY_VALUE"
echo

# ---------- Health ----------
echo "[Health] H1 200 OK (correct header)"
h1=$(http_dump "health_ok" -H "$API_KEY_HEADER" "$API_BASE/health"); echo "  → $h1"

echo "[Health] H2 missing header"
h2=$(http_dump "health_no_api_key" "$API_BASE/health"); echo "  → $h2"

echo "[Health] H3 wrong header"
h3=$(http_dump "health_wrong_api_key" -H "$WRONG_API_KEY_HEADER" "$API_BASE/health"); echo "  → $h3"

# ---------- Batch submit ----------
echo "[Batch] B1 202 Accepted (valid)"
b1=$(http_dump "batch_submit_valid" \
  -H "$API_KEY_HEADER" -X POST "$API_BASE/extract/batch" \
  -F "file=@$PDF_FILE" -F "user_id=$USER_ID" \
  -F "openai_api_key=$OPENAI_API_KEY" -F "model=$MODEL" \
  -F "prompts=$PROMPTS_JSON"); echo "  → $b1"

B1_BODY="$(cat "$b1")"
JOB_ID="$(extract_json_field "$B1_BODY" job_id || true)"

echo "[Batch] B2 422 — empty 'prompts'"
b2=$(http_dump "batch_empty_prompts" \
  -H "$API_KEY_HEADER" -X POST "$API_BASE/extract/batch" \
  -F "file=@$PDF_FILE" -F "user_id=$USER_ID" \
  -F "openai_api_key=$OPENAI_API_KEY" -F "model=$MODEL" \
  -F "prompts="); echo "  → $b2"

echo "[Batch] B3 422 — missing 'openai_api_key'"
b3=$(http_dump "batch_missing_openai_key" \
  -H "$API_KEY_HEADER" -X POST "$API_BASE/extract/batch" \
  -F "file=@$PDF_FILE" -F "user_id=$USER_ID" \
  -F "model=$MODEL" -F "prompts=$PROMPTS_JSON"); echo "  → $b3"

echo "[Batch] B4 missing X-API-Key"
b4=$(http_dump "batch_no_api_key" \
  -X POST "$API_BASE/extract/batch" \
  -F "file=@$PDF_FILE" -F "user_id=$USER_ID" \
  -F "openai_api_key=$OPENAI_API_KEY" -F "model=$MODEL" \
  -F "prompts=$PROMPTS_JSON"); echo "  → $b4"

echo "[Batch] B5 wrong X-API-Key"
b5=$(http_dump "batch_wrong_api_key" \
  -H "$WRONG_API_KEY_HEADER" -X POST "$API_BASE/extract/batch" \
  -F "file=@$PDF_FILE" -F "user_id=$USER_ID" \
  -F "openai_api_key=$OPENAI_API_KEY" -F "model=$MODEL" \
  -F "prompts=$PROMPTS_JSON"); echo "  → $b5"

echo "[Batch] B6 wrong 'openai_api_key'"
b6=$(http_dump "batch_wrong_openai_key" \
  -H "$API_KEY_HEADER" -X POST "$API_BASE/extract/batch" \
  -F "file=@$PDF_FILE" \
  -F "user_id=second_user_id" \
  -F "openai_api_key=$WRONG_OPENAI_API_KEY" \
  -F "model=$MODEL" \
  -F "prompts=$PROMPTS_JSON")
echo "  → $b6"

B6_BODY="$(cat "$b6")"
B6_JOB_ID="$(extract_json_field "$B6_BODY" job_id || true)"

if [ -n "${B6_JOB_ID:-}" ]; then
  echo "[Wrong OpenAI Key] Waiting until completed OR failed for $B6_JOB_ID…"
  if poll_until_complete "$B6_JOB_ID" 180; then
    sb6=$(http_dump "jobs_status_wrong_openai_key_${B6_JOB_ID}" \
      -H "$API_KEY_HEADER" "$API_BASE/jobs/$B6_JOB_ID"); echo "  → $sb6"
    rb6=$(http_dump "jobs_result_wrong_openai_key_${B6_JOB_ID}" \
      -H "$API_KEY_HEADER" "$API_BASE/jobs/$B6_JOB_ID/result"); echo "  → $rb6"
  else
    echo "[Wrong OpenAI Key] Timeout."
  fi
else
  echo "[Wrong OpenAI Key] No job_id; skipping."
fi

# ---------- Jobs status ----------
BAD_JOB_ID="${BAD_JOB_ID:-not-a-real-job-id}"

if [ -n "${JOB_ID:-}" ]; then
  echo "[Status] S1 200 OK (valid job_id)"
  s1=$(http_dump "jobs_status_ok_${JOB_ID}" -H "$API_KEY_HEADER" "$API_BASE/jobs/$JOB_ID"); echo "  → $s1"
else
  echo "[Status] S1 skipped (no job_id from B1)"
fi

echo "[Status] S2 missing header"
s2=$(http_dump "jobs_status_no_api_key" "$API_BASE/jobs/${JOB_ID:-$BAD_JOB_ID}"); echo "  → $s2"

echo "[Status] S3 wrong header"
s3=$(http_dump "jobs_status_wrong_api_key" -H "$WRONG_API_KEY_HEADER" "$API_BASE/jobs/${JOB_ID:-$BAD_JOB_ID}"); echo "  → $s3"

echo "[Status] S4 invalid/unknown job_id"
s4=$(http_dump "jobs_status_bad_id_${BAD_JOB_ID}" -H "$API_KEY_HEADER" "$API_BASE/jobs/$BAD_JOB_ID"); echo "  → $s4"

# ---------- Jobs result ----------
if [ -n "${JOB_ID:-}" ]; then
  echo "[Result] ensure completion..."
  if poll_until_complete "$JOB_ID" 180; then
    echo "[Result] R1 200 OK (completed)"
    r1=$(http_dump "jobs_result_ok_${JOB_ID}" -H "$API_KEY_HEADER" "$API_BASE/jobs/$JOB_ID/result"); echo "  → $r1"
  else
    echo "[Result] R1 skipped (job not completed)"
  fi
else
  echo "[Result] R1 skipped (no job_id from B1)"
fi

echo "[Result] R2 missing header"
r2=$(http_dump "jobs_result_no_api_key" "$API_BASE/jobs/${JOB_ID:-$BAD_JOB_ID}/result"); echo "  → $r2"

echo "[Result] R3 wrong header"
r3=$(http_dump "jobs_result_wrong_api_key" -H "$WRONG_API_KEY_HEADER" "$API_BASE/jobs/${JOB_ID:-$BAD_JOB_ID}/result"); echo "  → $r3"

echo "[Result] R4 invalid/unknown job_id"
r4=$(http_dump "jobs_result_bad_id_${BAD_JOB_ID}" -H "$API_KEY_HEADER" "$API_BASE/jobs/$BAD_JOB_ID/result"); echo "  → $r4"

echo
echo "Done. Collected HTTP examples in: $OUT_DIR/"
ls -1 "$OUT_DIR" | sed 's/^/ - /'
