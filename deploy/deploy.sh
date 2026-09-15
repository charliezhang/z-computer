#!/usr/bin/env bash
# Sync the repo to the instance and (re)configure it. Safe to re-run.
set -euo pipefail
cd "$(dirname "$0")/.."
source deploy/instance.env
[ -f backend/.env ] || { echo "backend/.env missing: copy backend/.env.example and set ANTHROPIC_API_KEY"; exit 1; }
SSH_OPTS="-o StrictHostKeyChecking=accept-new -o ConnectTimeout=5"
until ssh $SSH_OPTS "ubuntu@$HOST" true 2>/dev/null; do echo "waiting for ssh on $HOST..."; sleep 5; done
rsync -az --delete -e "ssh $SSH_OPTS" \
  --exclude .git --exclude node_modules --exclude .venv --exclude backend/data --exclude frontend/dist --exclude __pycache__ \
  ./ "ubuntu@$HOST:z-computer/"
ssh $SSH_OPTS "ubuntu@$HOST" "SITE=$SITE bash z-computer/deploy/remote-setup.sh"
echo "deployed: https://$SITE"
