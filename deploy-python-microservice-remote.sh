#!/bin/bash
# deploy-python-microservice-remote.sh — deploy + systemd setup (app → resume-analyzer.service)

set -euo pipefail
#set -x  # uncomment for verbose local command tracing

# --- autonomous dir handling ---
ORIG_PWD="$(pwd)"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
trap 'cd "$ORIG_PWD"' EXIT

# --- CONFIG ---
SERVICE_NAME="app"   # python package import path: app.main:app
SYSTEMD_UNIT_LOCAL="./deploy/resume-analyzer.service"
SYSTEMD_UNIT_NAME="resume-analyzer.service"

REMOTE_USER="dev"
REMOTE_HOST="www.devfe.flexcoders.net"
REMOTE_PORT=22
SSH_KEY="./deploy-access-key/id_ed25519"

REMOTE_BASE="/home/${REMOTE_USER}/openai_api"
APP_LOG="$REMOTE_BASE/logs/${SERVICE_NAME}.log"  # not used by systemd (journal), kept for compatibility

# --- sanity checks ---
[ -f "$SSH_KEY" ] || { echo "SSH key not found: $SSH_KEY"; exit 1; }
[ -f "./requirements.txt" ] || { echo "requirements.txt not found"; exit 1; }
[ -f "./setup-python-env.sh" ] || { echo "setup-python-env.sh not found"; exit 1; }
[ -f "$SYSTEMD_UNIT_LOCAL" ] || { echo "Systemd unit file not found: $SYSTEMD_UNIT_LOCAL"; exit 1; }

# helpers
rsync_to() {
  # $1 = local path, $2 = remote subdir
  local SRC="$1"
  local SUBDIR="$2" # e.g., app / tests / prompts / '' for root files
  local DEST="$REMOTE_USER@$REMOTE_HOST:$REMOTE_BASE/$SUBDIR"
  rsync -avz --progress --delete \
    --exclude '.venv' --exclude '__pycache__' --exclude '.git' \
    -e "ssh -i $SSH_KEY -p $REMOTE_PORT -o StrictHostKeyChecking=accept-new" \
    --rsync-path="mkdir -p '$REMOTE_BASE/$SUBDIR' >/dev/null 2>&1 || true; rsync" \
    "$SRC" "$DEST"
}

# --- sync code (create remote dirs via --rsync-path; no separate ssh mkdir) ---
rsync_to "./app/"     "app/"
rsync_to "./manual-tests/"   "manual-tests/"
rsync_to "./prompts/" "prompts/"
rsync -avz --progress -e "ssh -i $SSH_KEY -p $REMOTE_PORT -o StrictHostKeyChecking=accept-new" \
  ./requirements.txt "$REMOTE_USER@$REMOTE_HOST:$REMOTE_BASE/requirements.txt"
rsync -avz --progress -e "ssh -i $SSH_KEY -p $REMOTE_PORT -o StrictHostKeyChecking=accept-new" \
  ./setup-python-env.sh "$REMOTE_USER@$REMOTE_HOST:$REMOTE_BASE/setup-python-env.sh"

# --- upload systemd unit to a safe temp path ---
rsync -avz --progress -e "ssh -i $SSH_KEY -p $REMOTE_PORT -o StrictHostKeyChecking=accept-new" \
  "$SYSTEMD_UNIT_LOCAL" "$REMOTE_USER@$REMOTE_HOST:/tmp/$SYSTEMD_UNIT_NAME"

# --- single SSH session: venv setup → install systemd unit → enable+restart service ---
ssh -i "$SSH_KEY" -p $REMOTE_PORT -o StrictHostKeyChecking=accept-new "$REMOTE_USER@$REMOTE_HOST" "bash -lc '
  set -e

  REMOTE_BASE=\"$REMOTE_BASE\"
  SERVICE_NAME=\"$SERVICE_NAME\"
  UNIT_NAME=\"$SYSTEMD_UNIT_NAME\"

  mkdir -p \"\$REMOTE_BASE/logs\"
  cd \"\$REMOTE_BASE\"

  # ensure venv/deps are in place
  chmod +x ./setup-python-env.sh
  ./setup-python-env.sh

  # install/refresh systemd unit (requires sudo; assumes dev can sudo without password)
  sudo mv -f /tmp/\$UNIT_NAME /etc/systemd/system/\$UNIT_NAME
  sudo chown root:root /etc/systemd/system/\$UNIT_NAME
  sudo chmod 0644 /etc/systemd/system/\$UNIT_NAME

  # reload, enable at boot, (re)start now
  sudo systemctl daemon-reload
  sudo systemctl enable \$UNIT_NAME
  sudo systemctl restart \$UNIT_NAME

  # quick status line (non-blocking)
  sudo systemctl --no-pager --full status \$UNIT_NAME | head -n 10 || true
'"

echo
echo "✅ Deploy complete."
echo
echo "Service: resume-analyzer.service"
echo "Run status:    sudo systemctl status resume-analyzer.service"
echo "Follow logs:   journalctl -u resume-analyzer.service -f"
echo "Enable on boot: sudo systemctl enable resume-analyzer.service   (already done by script)"
echo
echo "If you still want to tail the legacy file log (not used by systemd):"
echo "ssh -i \"$SSH_KEY\" -p $REMOTE_PORT $REMOTE_USER@$REMOTE_HOST 'tail -n 200 -f $APP_LOG'"
