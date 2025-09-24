#!/usr/bin/env bash
set -euo pipefail

# If commit message is passed as first argument, use it.
# Otherwise, generate a timestamped message.
if [ $# -gt 0 ]; then
  COMMIT_MESSAGE="$*"
else
  COMMIT_MESSAGE="autocommit $(date '+%Y-%m-%d %H:%M:%S')"
fi

echo "→ Commit message: $COMMIT_MESSAGE"

git add .
git commit -m "$COMMIT_MESSAGE"
git push -u origin main
